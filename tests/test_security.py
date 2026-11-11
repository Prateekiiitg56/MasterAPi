"""Keys never leave the process except toward the provider; local data stays private."""

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from masterapi import MasterAPIError, VaultError
from masterapi.server import create_app, ensure_admin_token

KEY = "sk-secret-abcdef123456"


def test_upstream_errors_never_echo_the_key(api, vault, upstream):
    vault.add("o", "openai", [KEY], models={"chat": "m"})
    upstream.reply = lambda r: httpx.Response(400, text=f"bad request for key {KEY}")
    with pytest.raises(MasterAPIError) as e:
        api.chat("o", "x")
    assert KEY not in str(e.value) and "...3456" in str(e.value)

    upstream.reply = None
    upstream.status = {KEY: 401}
    with pytest.raises(MasterAPIError) as e:
        api.chat("o", "x")
    assert KEY not in str(e.value)


def test_passthrough_error_bodies_are_redacted(api, vault, upstream):
    vault.add("dg", "deepgram", [KEY])
    upstream.reply = lambda r: httpx.Response(404, text=f"no route {r.url} key={KEY}")
    r = api.request("dg", "GET", "/v1/nothing")
    assert r.status_code == 404 and KEY not in r.text and "...3456" in r.text


@pytest.mark.parametrize("path", ["../v2/x", "/a/../../b", "a/./b", "x?key=other", "x#frag", "a\\b", "a\nb"])
def test_raw_paths_stay_under_the_base_url(api, vault, upstream, path):
    vault.add("dg", "deepgram", [KEY])
    with pytest.raises(MasterAPIError) as e:
        api.request("dg", "GET", path)
    assert e.value.status == 400 and not upstream.seen


@pytest.mark.parametrize("url", ["http://api.example.com/v1", "ftp://x/v1", "https://user:pw@x/v1", "not a url"])
def test_keys_only_travel_over_https(vault, url):
    with pytest.raises(VaultError):
        vault.add("c", "custom", [KEY], base_url=url)


@pytest.mark.parametrize("url", ["http://localhost:8080/v1", "http://127.0.0.1:9/v1", "http://192.168.1.5/v1",
                                 "http://ollama:11434/v1", "http://[::1]:9/v1"])
def test_plain_http_allowed_on_this_machine_or_private_network(vault, url):
    vault.add("c", "custom", [KEY], base_url=url)


def test_vault_file_is_encrypted_and_private(vault):
    vault.add("o", "openai", [KEY])
    raw = vault.path.read_bytes()
    assert KEY.encode() not in raw and b"openai" not in raw
    assert not list(vault.path.parent.glob("*.tmp"))
    if os.name == "posix":
        assert vault.path.stat().st_mode & 0o077 == 0


@pytest.fixture
def client(api, vault):
    vault.add("gem", "gemini", [KEY], models={"chat": "m"})
    admin = ensure_admin_token(api)
    return TestClient(create_app(api)), {"Authorization": f"Bearer {admin}"}


def test_admin_api_never_returns_keys(client, upstream):
    c, admin = client
    for path in ("/admin/aliases", "/admin/keys", "/admin/usage", "/admin/tokens", "/admin/stats"):
        r = c.get(path, headers=admin)
        assert r.status_code == 200 and KEY not in r.text, path


def test_security_headers_and_no_caching(client):
    c, admin = client
    r = c.get("/admin/aliases", headers=admin)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert c.get("/dashboard/").headers["content-security-policy"].startswith("default-src 'none'")


def test_no_api_docs_that_load_third_party_scripts(client):
    c, _ = client
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404


def test_request_ids_are_sanitised(client):
    c, _ = client
    assert c.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"
    assert c.get("/health", headers={"X-Request-ID": "bad id\tinjected"}).headers["x-request-id"] != "bad id\tinjected"


def test_oversized_bodies_rejected(api, vault, monkeypatch):
    monkeypatch.setenv("MASTERAPI_MAX_BODY_MB", "0.001")  # ~1 KB
    ensure_admin_token(api)
    token = vault.create_token("p")
    c = TestClient(create_app(api))
    r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {token}"},
               json={"model": "x", "messages": [{"role": "user", "content": "a" * 5000}]})
    assert r.status_code == 413

    def chunks():
        for _ in range(10):
            yield b"a" * 500

    r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {token}"}, content=chunks())
    assert r.status_code == 413
