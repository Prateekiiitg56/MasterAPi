import httpx
import pytest
from fastapi.testclient import TestClient

from masterapi.server import create_app, ensure_admin_token


@pytest.fixture
def setup(api, vault):
    vault.add("gem", "gemini", ["sk-gemini-0001"], models={"chat": "gemini-2.5-flash", "embeddings": "e1"})
    vault.add("el", "elevenlabs", ["sk-eleven-0001"])
    admin = ensure_admin_token(api)
    project = vault.create_token("proj", aliases=["gem"])
    client = TestClient(create_app(api))
    return client, {"Authorization": f"Bearer {admin}"}, {"Authorization": f"Bearer {project}"}


def test_auth_and_scope(setup):
    client, admin, project = setup
    assert client.get("/health").json()["ok"] is True
    r = client.post("/v1/chat/completions", json={"model": "gem", "messages": []},
                    headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == 401
    assert client.get("/proxy/el/v1/voices", headers=project).status_code == 403
    assert client.get("/admin/aliases", headers=project).status_code == 403
    assert [m["id"] for m in client.get("/v1/models", headers=project).json()["data"]] == ["gem"]


def test_openai_endpoints(setup, upstream):
    client, _, project = setup
    messages = [{"role": "user", "content": "hi"}]
    r = client.post("/v1/chat/completions", headers=project, json={"model": "gem", "messages": messages})
    assert r.json()["choices"][0]["message"]["content"] == "hi from sk-gemini-0001"
    assert r.headers["x-request-id"]

    r = client.post("/v1/embeddings", headers=project, json={"model": "gem", "input": "hi"})
    assert r.json()["data"][0]["embedding"] == [0.3]

    r = client.post("/v1/images/generations", headers=project, json={"model": "gem", "prompt": "fox"})
    assert r.status_code == 400 and "no default images model" in r.json()["error"]["message"]

    with client.stream("POST", "/v1/chat/completions", headers=project,
                       json={"model": "gem", "messages": [], "stream": True}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.read().endswith(b"data: [DONE]\n\n")

    r = client.post("/v1/chat/completions", headers=project, json={"model": "gem:unknown", "messages": []})
    assert r.status_code == 200
    assert upstream.bodies()[-1]["model"] == "unknown"


def test_rate_limit_surfaces_retry_after(setup, upstream):
    client, _, project = setup
    upstream.status = {"sk-gemini-0001": 429}
    r = client.post("/v1/chat/completions", headers=project, json={"model": "gem", "messages": []})
    assert r.status_code == 429 and r.headers["retry-after"] == "7"


def test_proxy_injects_key_and_strips_client_auth(setup, upstream):
    client, admin, _ = setup
    upstream.reply = lambda req: httpx.Response(201, content=b"audio-bytes", headers={"content-type": "audio/mpeg"})
    r = client.post("/proxy/el/v1/text-to-speech/abc?optimize=1", headers={**admin, "x-api-key": "client-secret"},
                    content=b'{"text":"hi"}')
    assert r.status_code == 201 and r.content == b"audio-bytes"
    sent = upstream.seen[-1]
    assert sent.headers["xi-api-key"] == "sk-eleven-0001"
    assert "x-api-key" not in sent.headers and "authorization" not in sent.headers
    assert str(sent.url) == "https://api.elevenlabs.io/v1/text-to-speech/abc?optimize=1"


def test_admin_api_never_returns_plaintext_keys(setup):
    client, admin, _ = setup
    r = client.post("/admin/aliases", headers=admin, json={
        "name": "oa", "provider": "openai", "keys": ["sk-openai-secret-0001"], "models": {"chat": "gpt-4o-mini"}})
    assert r.status_code == 201
    r = client.post("/admin/aliases/oa/keys", headers=admin, json={"keys": ["sk-openai-secret-0002"]})
    assert r.json() == {"added": 1}
    listing = client.get("/admin/aliases", headers=admin)
    assert "secret" not in listing.text
    oa = next(a for a in listing.json() if a["name"] == "oa")
    assert [k["key"] for k in oa["keys"]] == ["...0001", "...0002"]

    fp = oa["keys"][0]["fingerprint"]
    assert client.delete(f"/admin/aliases/oa/keys/{fp}", headers=admin).json() == {"removed": 1}
    r = client.patch("/admin/aliases/oa", headers=admin, json={"models": {"chat": "gpt-5"}})
    assert r.json()["models"]["chat"] == "gpt-5"
    bad = {"name": "x", "provider": "nope", "keys": ["k"]}
    assert client.post("/admin/aliases", headers=admin, json=bad).status_code == 400
    assert client.delete("/admin/aliases/oa", headers=admin).status_code == 204
    assert client.delete("/admin/aliases/oa", headers=admin).status_code == 404


def test_admin_tokens_and_usage(setup):
    client, admin, project = setup
    r = client.post("/admin/tokens", headers=admin, json={"name": "app2", "aliases": ["gem"]})
    token = r.json()["token"]
    assert client.get("/v1/models", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert "hash" not in client.get("/admin/tokens", headers=admin).text
    assert client.delete("/admin/tokens/app2", headers=admin).status_code == 204
    assert client.get("/v1/models", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    client.post("/v1/chat/completions", headers=project, json={"model": "gem", "messages": []})
    usage = client.get("/admin/usage", headers=admin).json()
    assert usage == [{"token": "proj", "alias": "gem", "op": "chat", "requests": 1, "errors": 0,
                      "prompt_tokens": 3, "completion_tokens": 4}]


def test_dashboard_served_with_csp(setup):
    client, _, _ = setup
    r = client.get("/dashboard/")
    assert r.status_code == 200 and "MasterAPI" in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/dashboard/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/dashboard/../vault.enc").status_code == 404
