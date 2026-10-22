"""HTTP gateway: OpenAI-compatible API, raw proxy, admin API and web dashboard.

Any project, in any language, points an OpenAI SDK at http://127.0.0.1:8787/v1
and uses an alias name as the model.
"""

import json
import logging
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from . import __version__
from .client import MasterAPI, MasterAPIError
from .keypool import fingerprint, mask
from .mcp_server import build_mcp, http_endpoint
from .providers import EMBEDDINGS, IMAGES, PROVIDERS, provider_for
from .vault import UnknownAlias, VaultError, home

log = logging.getLogger("masterapi.server")

HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
               "trailers", "transfer-encoding", "upgrade", "host", "content-length"}
# Client-side credentials never reach the provider; the alias's key is injected instead.
CLIENT_AUTH_HEADERS = {"authorization", "x-masterapi-token", "x-api-key", "api-key", "cookie"}
DASHBOARD_FILES = {"index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css"}
DASHBOARD_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                 "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Usage:
    """In-memory request and token counters per (client token, alias, operation)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, str], dict] = {}

    def record(self, token: str, alias: str, op: str, ok: bool, usage: dict | None = None) -> None:
        with self._lock:
            row = self._rows.setdefault((token, alias, op), {"requests": 0, "errors": 0,
                                                            "prompt_tokens": 0, "completion_tokens": 0})
            row["requests"] += 1
            row["errors"] += not ok
            for k in ("prompt_tokens", "completion_tokens"):
                row[k] += (usage or {}).get(k) or 0

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [{"token": t, "alias": a, "op": o, **row} for (t, a, o), row in sorted(self._rows.items())]


def _error(status: int, message: str, retry_after: float | None = None) -> JSONResponse:
    headers = {"Retry-After": str(int(retry_after))} if retry_after else None
    return JSONResponse({"error": {"message": message, "type": "masterapi_error", "code": status}},
                        status, headers=headers)


def _public_alias(name: str, alias: dict) -> dict:
    """Alias as shown to admins: keys masked, never plaintext."""
    try:
        caps = list(provider_for(alias).capabilities)
    except ValueError:
        caps = []
    return {"name": name, **{k: v for k, v in alias.items() if k != "keys"}, "resolved_capabilities": caps,
            "keys": [{"key": mask(k), "fingerprint": fingerprint(k)} for k in alias["keys"]]}


def create_app(api: MasterAPI | None = None) -> FastAPI:
    api = api or MasterAPI()
    usage = Usage()
    # MCP for coding agents at /mcp (Code Mode when Deno is installed); the token's
    # alias scope applies there too.
    mcp = build_mcp(api, http=True, output_dir=str(home() / "outputs"))
    mcp_app = http_endpoint(mcp, api.vault)

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="MasterAPI", version=__version__, lifespan=lifespan)
    app.router.routes.append(Route("/mcp", endpoint=mcp_app, methods=["GET", "POST", "DELETE"]))

    @app.exception_handler(MasterAPIError)
    async def _api_error(request, e: MasterAPIError):
        return _error(e.status, str(e), e.retry_after)

    @app.exception_handler(VaultError)
    async def _vault_error(request, e: VaultError):
        return _error(404 if isinstance(e, UnknownAlias) else 400, str(e))

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info("%s %s %s %s %.0fms token=%s", rid, request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000, getattr(request.state, "token", "-"))
        return response

    def caller(request: Request) -> dict:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
        else:
            token = request.headers.get("x-masterapi-token", "")
        record = api.vault.verify_token(token)
        if record is None:
            raise MasterAPIError("missing or invalid token; create one with `masterapi token create NAME`", 401)
        request.state.token = record["name"]
        return record

    def admin(record: dict = Depends(caller)) -> dict:
        if not record["admin"]:
            raise MasterAPIError("this endpoint needs an admin token", 403)
        return record

    def allow(record: dict, alias: str) -> None:
        if record["aliases"] and alias not in record["aliases"]:
            raise MasterAPIError(f"token '{record['name']}' may not use alias '{alias}'", 403)

    def target_of(body: dict, record: dict) -> str:
        target = body.pop("model", None)
        if not isinstance(target, str) or not target:
            raise MasterAPIError("'model' must be an alias name or 'alias:model'", 400)
        allow(record, target.partition(":")[0])
        return target

    def tracked(record: dict, target: str, op: str, call):
        alias = target.partition(":")[0]
        try:
            result = call()
        except MasterAPIError:
            usage.record(record["name"], alias, op, ok=False)
            raise
        tokens = result.get("usage") if isinstance(result, dict) else None
        usage.record(record["name"], alias, op, ok=True, usage=tokens)
        return result

    def sse_guard(chunks):
        try:
            yield from chunks
        except MasterAPIError as e:
            yield f"data: {json.dumps({'error': {'message': str(e)}})}\n\n".encode()

    # OpenAI-compatible API

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/v1/models")
    def list_models(record: dict = Depends(caller)):
        data = []
        for name, alias in api.vault.aliases().items():
            if record["aliases"] and name not in record["aliases"]:
                continue
            public = _public_alias(name, alias)
            data.append({"id": name, "object": "model", "owned_by": alias["provider"],
                         "capabilities": public["resolved_capabilities"], "models": alias.get("models", {})})
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    def chat_completions(body: dict = Body(...), record: dict = Depends(caller)):
        target = target_of(body, record)
        if body.get("stream"):
            chunks = tracked(record, target, "chat", lambda: api.chat_stream(target, body))
            return StreamingResponse(sse_guard(chunks), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache"})
        return tracked(record, target, "chat", lambda: api.chat_completion(target, body))

    @app.post("/v1/embeddings")
    def embeddings(body: dict = Body(...), record: dict = Depends(caller)):
        target = target_of(body, record)
        return tracked(record, target, EMBEDDINGS, lambda: api.embeddings(target, body))

    @app.post("/v1/images/generations")
    def images(body: dict = Body(...), record: dict = Depends(caller)):
        target = target_of(body, record)
        return tracked(record, target, IMAGES, lambda: api.images(target, body))

    # Raw passthrough for any API (audio, image edits, non-LLM services)

    @app.api_route("/proxy/{alias}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(alias: str, path: str, request: Request, record: dict = Depends(caller)):
        allow(record, alias)
        skip = HOP_HEADERS | CLIENT_AUTH_HEADERS | {"accept-encoding"}
        headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}
        content = await request.body()

        def send():
            return tracked(record, alias, "proxy", lambda: api.request(
                alias, request.method, path, content=content or None, headers=headers,
                params=list(request.query_params.multi_items()), stream=True))

        r = await run_in_threadpool(send)

        def body_iter():
            try:
                yield from r.iter_bytes()
            finally:
                r.close()

        # httpx already decoded the body, so the original encoding/length no longer apply.
        out = {k: v for k, v in r.headers.items() if k.lower() not in HOP_HEADERS | {"content-encoding"}}
        return StreamingResponse(body_iter(), status_code=r.status_code, headers=out)

    # Admin API (used by the dashboard)

    @app.get("/admin/aliases")
    def admin_aliases(_: dict = Depends(admin)):
        return [_public_alias(n, a) for n, a in sorted(api.vault.aliases().items())]

    @app.post("/admin/aliases", status_code=201)
    def admin_add_alias(body: dict = Body(...), _: dict = Depends(admin)):
        fields = {k: body.get(k) for k in ("base_url", "adapter", "auth", "capabilities", "headers")}
        api.vault.add(str(body.get("name", "")), str(body.get("provider", "")), list(body.get("keys") or []),
                      models=body.get("models"), force=bool(body.get("force")), **fields)
        return _public_alias(body["name"], api.vault.get(body["name"]))

    @app.patch("/admin/aliases/{name}")
    def admin_update_alias(name: str, body: dict = Body(...), _: dict = Depends(admin)):
        fields = {k: body.get(k) for k in ("base_url", "adapter", "auth", "capabilities", "headers")}
        api.vault.update(name, models=body.get("models"), **fields)
        return _public_alias(name, api.vault.get(name))

    @app.delete("/admin/aliases/{name}", status_code=204)
    def admin_remove_alias(name: str, _: dict = Depends(admin)):
        api.vault.remove(name)
        return Response(status_code=204)

    @app.post("/admin/aliases/{name}/keys")
    def admin_add_keys(name: str, body: dict = Body(...), _: dict = Depends(admin)):
        return {"added": api.vault.add_keys(name, list(body.get("keys") or []))}

    @app.delete("/admin/aliases/{name}/keys/{key_fingerprint}")
    def admin_remove_key(name: str, key_fingerprint: str, _: dict = Depends(admin)):
        return {"removed": api.vault.remove_key(name, fingerprint=key_fingerprint)}

    @app.get("/admin/me")
    def admin_me(record: dict = Depends(admin)):
        return record

    @app.get("/admin/providers")
    def admin_providers(_: dict = Depends(admin)):
        return {name: {"base_url": p.base_url, "adapter": p.adapter, "auth": p.auth,
                       "capabilities": list(p.capabilities)} for name, p in PROVIDERS.items()}

    @app.get("/admin/keys")
    def admin_keys(_: dict = Depends(admin)):
        return api.pool.snapshot()

    @app.get("/admin/usage")
    def admin_usage(_: dict = Depends(admin)):
        return usage.snapshot()

    @app.get("/admin/tokens")
    def admin_tokens(_: dict = Depends(admin)):
        return api.vault.list_tokens()

    @app.post("/admin/tokens", status_code=201)
    def admin_create_token(body: dict = Body(...), _: dict = Depends(admin)):
        token = api.vault.create_token(str(body.get("name", "")), body.get("aliases") or None,
                                       bool(body.get("admin")))
        return {"name": body["name"], "token": token}

    @app.delete("/admin/tokens/{name}", status_code=204)
    def admin_revoke_token(name: str, record: dict = Depends(admin)):
        if name == record["name"]:
            raise MasterAPIError("refusing to revoke the token making this request", 400)
        api.vault.revoke_token(name)
        return Response(status_code=204)

    # Dashboard (static files; all data comes from the admin API)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/dashboard/")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard_redirect():
        return RedirectResponse("/dashboard/")

    @app.get("/dashboard/{file:path}", include_in_schema=False)
    def dashboard(file: str):
        file = file or "index.html"
        if file not in DASHBOARD_FILES:
            return _error(404, "not found")
        content = resources.files("masterapi.dashboard").joinpath(file).read_bytes()
        return Response(content, media_type=DASHBOARD_FILES[file],
                        headers={"Content-Security-Policy": DASHBOARD_CSP, "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "Cache-Control": "no-cache"})

    return app


def ensure_admin_token(api: MasterAPI) -> str | None:
    """Create an admin token on first start; return it so it can be shown once."""
    tokens = api.vault.list_tokens()
    if any(t["admin"] for t in tokens):
        return None
    names = {t["name"] for t in tokens}
    name = "admin" if "admin" not in names else f"admin-{secrets.token_hex(2)}"
    return api.vault.create_token(name, admin=True)


def serve(host: str = "127.0.0.1", port: int = 8787, api: MasterAPI | None = None,
          log_level: str = "info") -> None:
    import uvicorn

    logging.basicConfig(level=log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    api = api or MasterAPI()
    if token := ensure_admin_token(api):
        print(f"Created admin token (shown once, store it safely):\n  {token}\n")
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("listening on %s: anyone who reaches this port with a valid token can spend your keys; "
                    "put TLS (a reverse proxy) in front of it", host)
    print(f"MasterAPI {__version__}: http://{host}:{port}/v1  dashboard: http://{host}:{port}/dashboard/")
    uvicorn.run(create_app(api), host=host, port=port, log_level=log_level, access_log=False)
