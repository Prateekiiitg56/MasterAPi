"""Call any stored alias by name: chat, embeddings, images, or raw HTTP."""

import logging
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from .adapters import ADAPTERS
from .keypool import INVALID, RATE_LIMITED, TRANSIENT, KeyPool, fingerprint
from .providers import CHAT, EMBEDDINGS, IMAGES, Auth, Provider, provider_for
from .vault import UnknownAlias, Vault

log = logging.getLogger("masterapi")

TRANSIENT_STATUSES = {408, 500, 502, 503, 504, 529}


class MasterAPIError(Exception):
    def __init__(self, message: str, status: int = 502, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def classify(r: httpx.Response) -> str | None:
    """Why a response failed, as far as key selection cares. None = not the key's fault."""
    if r.status_code == 429:
        return RATE_LIMITED
    if r.status_code in (401, 402, 403):
        return INVALID
    # Gemini reports an invalid key as 400 "API key not valid".
    if r.status_code == 400 and "api key" in r.text.lower():
        return INVALID
    if r.status_code in TRANSIENT_STATUSES:
        return TRANSIENT
    return None


def _retry_after(r: httpx.Response) -> float | None:
    try:
        return float(r.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        raise MasterAPIError(f"upstream returned non-JSON ({r.status_code})") from None


@dataclass(frozen=True)
class Route:
    name: str
    provider: Provider
    model: str | None
    keys: list[str]

    @property
    def adapter(self):
        return ADAPTERS[self.provider.adapter]


class MasterAPI:
    def __init__(self, vault: Vault | None = None, http: httpx.Client | None = None,
                 timeout: float | None = None, retries: int | None = None):
        self.vault = vault or Vault()
        if timeout is None:
            timeout = float(os.environ.get("MASTERAPI_TIMEOUT", 120))
        self.http = http or httpx.Client(timeout=httpx.Timeout(timeout, connect=10))
        self.retries = retries if retries is not None else int(os.environ.get("MASTERAPI_RETRIES", 1))
        self.pool = KeyPool()

    def route(self, target: str, op: str | None = None) -> Route:
        """`target` is "alias" or "alias:model" (model may itself contain ':' or '/')."""
        name, _, model = target.partition(":")
        try:
            alias = self.vault.get(name)
        except UnknownAlias as e:
            raise MasterAPIError(str(e), 404) from None
        try:
            provider = provider_for(alias)
        except ValueError as e:
            raise MasterAPIError(f"alias '{name}': {e}", 400) from None

        if op:
            if op not in provider.capabilities:
                supported = ", ".join(provider.capabilities) or "raw requests only"
                raise MasterAPIError(f"alias '{name}' ({alias['provider']}) does not support {op}; "
                                     f"supported: {supported}", 400)
            model = model or (alias.get("models") or {}).get(op)
            if not model:
                raise MasterAPIError(f"alias '{name}' has no default {op} model; call it as '{name}:<model>'", 400)

        keys = alias.get("keys") or ([] if provider.needs_key else [""])
        if not keys:
            raise MasterAPIError(f"alias '{name}' has no keys", 400)
        return Route(name, provider, model or None, keys)

    def _send(self, route: Route, method: str, path: str, *, json=None, content=None,
              headers=None, params=None, stream: bool = False, passthrough: bool = False) -> httpx.Response:
        """Try the alias's keys in pool order until one is accepted.

        Key failures (429, 401/402/403, invalid key) move on to the next key. Other
        4xx errors are the caller's fault: raised, or returned when `passthrough`.
        A whole extra pass only happens when every failure was transient (5xx/network).
        """
        auth = Auth.parse(route.provider.auth)
        error = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(min(0.5 * 2 ** (attempt - 1), 4))
            transient_only = True
            for key in self.pool.order(route.name, route.keys):
                h = {**route.provider.headers, **(headers or {})}
                q = httpx.QueryParams(params or {})
                if auth.kind == "header":
                    h[auth.name] = auth.value(key)
                elif auth.kind == "query":
                    q = q.set(auth.name, auth.value(key))
                request = self.http.build_request(method, route.provider.base_url + path,
                                                  json=json, content=content, headers=h, params=q)
                try:
                    r = self.http.send(request, stream=stream)
                except httpx.HTTPError as e:
                    error = MasterAPIError(f"network error calling '{route.name}': {type(e).__name__}")
                    self.pool.failure(route.name, key, TRANSIENT, str(error))
                    log.warning("alias=%s key=%s network error: %s", route.name, fingerprint(key), e)
                    continue

                if r.status_code < 400:
                    self.pool.success(route.name, key)
                    return r
                if stream:
                    r.read()
                kind = classify(r)
                if kind is None:
                    self.pool.success(route.name, key)  # key was accepted; the request was not
                    if passthrough:
                        return r
                    r.close()
                    raise MasterAPIError(f"'{route.name}' upstream returned {r.status_code}: {r.text[:1000]}",
                                         r.status_code)
                r.close()
                error = MasterAPIError(f"'{route.name}' upstream returned {r.status_code}: {r.text[:1000]}",
                                       r.status_code, _retry_after(r))
                cooldown = self.pool.failure(route.name, key, kind, f"HTTP {r.status_code}", _retry_after(r))
                log.warning("alias=%s key=%s status=%s %s cooldown=%.0fs",
                            route.name, fingerprint(key), r.status_code, kind, cooldown)
                if kind != TRANSIENT:
                    transient_only = False
            if not transient_only:
                break
        raise error

    def _typed(self, op: str, target: str, body: dict, stream: bool = False) -> tuple[Route, httpx.Response]:
        route = self.route(target, op)
        try:
            path, payload = route.adapter.request(op, body, route.model)
        except (ValueError, KeyError, TypeError) as e:
            raise MasterAPIError(f"invalid request: {e}", 400) from None
        return route, self._send(route, "POST", path, json=payload, stream=stream)

    # OpenAI-format operations: request bodies and responses use the OpenAI schema
    # whatever the provider.

    def chat_completion(self, target: str, body: dict) -> dict:
        route, r = self._typed(CHAT, target, {k: v for k, v in body.items() if k != "stream"})
        return route.adapter.response(CHAT, _json(r))

    def chat_stream(self, target: str, body: dict) -> Iterator[bytes]:
        """Returns an iterator of SSE bytes. Errors before the first byte raise here."""
        route, r = self._typed(CHAT, target, {**body, "stream": True}, stream=True)
        translator = route.adapter.stream_translator()

        def chunks():
            try:
                if translator is None:
                    yield from r.iter_bytes()
                else:
                    for line in r.iter_lines():
                        for event in translator.feed(line):
                            yield event.encode()
            except httpx.HTTPError as e:
                raise MasterAPIError(f"stream interrupted: {type(e).__name__}") from e
            finally:
                r.close()

        return chunks()

    def embeddings(self, target: str, body: dict) -> dict:
        route, r = self._typed(EMBEDDINGS, target, body)
        return route.adapter.response(EMBEDDINGS, _json(r))

    def images(self, target: str, body: dict) -> dict:
        route, r = self._typed(IMAGES, target, body)
        return route.adapter.response(IMAGES, _json(r))

    def request(self, alias: str, method: str, path: str, *, json=None, content=None,
                headers=None, params=None, stream: bool = False) -> httpx.Response:
        """Raw call to any API stored under `alias`; the key is injected for you.
        Non-key errors (e.g. 404) come back as the response, not an exception."""
        route = self.route(alias)
        return self._send(route, method.upper(), "/" + path.lstrip("/"), json=json, content=content,
                          headers=headers, params=params, stream=stream, passthrough=True)

    # Short helpers

    def chat(self, target: str, prompt: str | list[dict], *, system: str | None = None, **params) -> str:
        messages = prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}]
        if system:
            messages = [{"role": "system", "content": system}, *messages]
        data = self.chat_completion(target, {"messages": messages, **params})
        return data["choices"][0]["message"]["content"]

    def embed(self, target: str, input: str | list[str], **params) -> list[list[float]]:
        data = self.embeddings(target, {"input": input, **params})
        return [d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))]

    def image(self, target: str, prompt: str, **params) -> list[dict]:
        """Returns the `data` list: items with `url` or `b64_json`."""
        return self.images(target, {"prompt": prompt, **params})["data"]


_default: MasterAPI | None = None
_default_lock = threading.Lock()


def default() -> MasterAPI:
    global _default
    with _default_lock:
        if _default is None:
            _default = MasterAPI()
        return _default


def chat(target: str, prompt: str | list[dict], **kwargs) -> str:
    """`from masterapi import chat; chat("my-gemini", "hello")`"""
    return default().chat(target, prompt, **kwargs)


def embed(target: str, input: str | list[str], **kwargs) -> list[list[float]]:
    return default().embed(target, input, **kwargs)


def image(target: str, prompt: str, **kwargs) -> list[dict]:
    return default().image(target, prompt, **kwargs)


def request(alias: str, method: str, path: str, **kwargs) -> httpx.Response:
    return default().request(alias, method, path, **kwargs)
