import json

import httpx
import pytest
from cryptography.fernet import Fernet

from masterapi import MasterAPI, Vault


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTERAPI_KEY", Fernet.generate_key().decode())
    return Vault(tmp_path / "vault.enc")


class Upstream:
    """Mock provider. `status[key]` picks the reply status per key (default 200);
    every request is recorded in `seen`."""

    def __init__(self):
        self.status: dict[str, object] = {}
        self.seen: list[httpx.Request] = []
        self.reply = None  # optional callable(request) -> httpx.Response

    def key_of(self, request: httpx.Request) -> str:
        auth = request.headers.get("authorization", "")
        return (auth.removeprefix("Bearer ") or request.headers.get("x-api-key")
                or request.url.params.get("key") or "")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        status = self.status.get(self.key_of(request), 200)
        if status == "gemini-bad-key":
            return httpx.Response(400, json=[{"error": {"message": "Please pass a valid API key"}}])
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}}, headers={"retry-after": "7"})
        if self.reply:
            return self.reply(request)
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        if path.endswith("/embeddings"):
            vectors = [{"index": 1, "embedding": [0.3]}, {"index": 0, "embedding": [0.1]}]
            return httpx.Response(200, json={"data": vectors})
        if path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "https://img/1.png"}]})
        if body.get("stream"):
            return httpx.Response(200, content=b'data: {"x":1}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": f"hi from {self.key_of(request)}"}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 4}})

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.seen]


@pytest.fixture
def upstream():
    return Upstream()


@pytest.fixture
def api(vault, upstream):
    return MasterAPI(vault, http=httpx.Client(transport=httpx.MockTransport(upstream)), retries=0)
