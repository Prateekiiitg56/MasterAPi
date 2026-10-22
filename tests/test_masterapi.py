import httpx
import pytest
from cryptography.fernet import Fernet

from masterapi import MasterAPIError, Vault, VaultError
from masterapi.keypool import KeyPool
from masterapi.vault import _hash

# Vault

def test_vault_is_encrypted_and_round_trips(vault):
    vault.add("gem", "gemini", ["sk-secret-1", "sk-secret-2", "sk-secret-1"], models={"chat": "gemini-2.5-flash"})
    assert b"sk-secret" not in vault.path.read_bytes()
    alias = Vault(vault.path).get("gem")
    assert alias["keys"] == ["sk-secret-1", "sk-secret-2"]
    assert alias["models"] == {"chat": "gemini-2.5-flash"}


def test_vault_validates(vault):
    vault.add("a", "openai", ["k1"])
    with pytest.raises(VaultError, match="exists"):
        vault.add("a", "openai", ["k2"])
    with pytest.raises(VaultError, match="invalid name"):
        vault.add("bad:name", "openai", ["k"])
    with pytest.raises(VaultError, match="unknown provider"):
        vault.add("b", "nope", ["k"])
    with pytest.raises(VaultError, match="base-url"):
        vault.add("b", "custom", ["k"])
    with pytest.raises(VaultError, match="at least one"):
        vault.add("b", "openai", [])
    vault.add("local", "ollama", [], models={"chat": "llama3.2"})  # auth none: no key needed


def test_vault_keys_and_failed_edit_changes_nothing(vault):
    vault.add("a", "openai", ["sk-test-0001", "sk-test-0002"])
    assert vault.add_keys("a", ["sk-test-0002", "sk-test-0003"]) == 1
    assert vault.remove_key("a", ending="0002") == 1
    assert vault.get("a")["keys"] == ["sk-test-0001", "sk-test-0003"]
    with pytest.raises(VaultError):
        vault.update("a", adapter="bogus")
    assert "adapter" not in vault.get("a")


def test_wrong_encryption_key_fails_loudly(vault, monkeypatch):
    vault.add("a", "openai", ["k1"])
    monkeypatch.setenv("MASTERAPI_KEY", Fernet.generate_key().decode())
    with pytest.raises(VaultError, match="decrypt"):
        Vault(vault.path).aliases()


def test_tokens_are_hashed_and_scoped(vault):
    token = vault.create_token("proj", aliases=["gem"])
    assert token.encode() not in vault.path.read_bytes()
    assert vault.verify_token(token) == {"name": "proj", "aliases": ["gem"], "admin": False}
    assert vault.verify_token("mapi-wrong") is None
    vault.revoke_token("proj")
    assert vault.verify_token(token) is None


def test_v01_vault_migrates(vault):
    vault._save({"aliases": {"g": {"provider": "gemini", "model": "m1", "base_url": None, "keys": ["k"]}},
                 "token": "mapi-old"})
    fresh = Vault(vault.path)
    assert fresh.get("g")["models"] == {"chat": "m1"}
    assert fresh.verify_token("mapi-old")["name"] == "default"
    assert _hash("mapi-old") == fresh._load()["tokens"]["default"]["hash"]


# Routing and operations

def test_chat_uses_provider_url_and_default_model(api, vault, upstream):
    vault.add("gem", "gemini", ["g1"], models={"chat": "gemini-2.5-flash"})
    assert api.chat("gem", "hello") == "hi from g1"
    r = upstream.seen[0]
    assert str(r.url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert upstream.bodies()[0]["model"] == "gemini-2.5-flash"


def test_model_override_keeps_colons(api, vault, upstream):
    vault.add("or", "openrouter", ["o1"], models={"chat": "openai/gpt-4o-mini"})
    api.chat("or:meta-llama/llama-3.3-70b-instruct:free", "x")
    assert upstream.bodies()[0]["model"] == "meta-llama/llama-3.3-70b-instruct:free"


def test_embeddings_and_images(api, vault, upstream):
    vault.add("oa", "openai", ["k"], models={"embeddings": "text-embedding-3-small", "images": "gpt-image-1"})
    assert api.embed("oa", ["a", "b"]) == [[0.1], [0.3]]  # sorted by index
    assert api.image("oa", "a fox") == [{"url": "https://img/1.png"}]
    assert [r.url.path for r in upstream.seen] == ["/v1/embeddings", "/v1/images/generations"]
    assert upstream.bodies()[1] == {"prompt": "a fox", "model": "gpt-image-1"}


def test_capability_and_model_errors(api, vault):
    vault.add("groq", "groq", ["k"], models={"chat": "llama"})
    with pytest.raises(MasterAPIError, match="does not support images") as e:
        api.image("groq", "x")
    assert e.value.status == 400
    with pytest.raises(MasterAPIError, match="no default embeddings model"):
        vault.update("groq", capabilities=["chat", "embeddings"])
        api.embed("groq", "x")
    with pytest.raises(MasterAPIError) as e:
        api.chat("ghost", "x")
    assert e.value.status == 404


def test_auth_styles(api, vault, upstream):
    vault.add("ant", "anthropic", ["ak"], models={"chat": "claude-x"})
    vault.add("q", "custom", ["qk"], base_url="https://q.example/v1", auth="query:key", models={"chat": "m"})
    vault.add("dg", "deepgram", ["dk"])
    vault.add("local", "ollama", [], models={"chat": "llama3.2"})
    upstream.reply = lambda r: httpx.Response(200, json={
        "id": "1", "model": "m", "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
        "usage": {}, "choices": [{"message": {"content": "ok"}}]})
    api.chat("ant", "x")
    api.chat("q", "x")
    api.request("dg", "GET", "/v1/projects")
    api.chat("local", "x")
    ant, q, dg, local = upstream.seen
    assert ant.headers["x-api-key"] == "ak" and ant.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in ant.headers
    assert q.url.params["key"] == "qk"
    assert dg.headers["authorization"] == "Token dk" and str(dg.url) == "https://api.deepgram.com/v1/projects"
    assert "authorization" not in local.headers


# Key rotation

def test_rotates_past_rate_limited_and_dead_keys(api, vault, upstream):
    vault.add("bulk", "openai", ["sk-test-0001", "sk-test-0002", "sk-test-0003"], models={"chat": "m"})
    upstream.status = {"sk-test-0001": 429, "sk-test-0002": 401}
    assert api.chat("bulk", "x") == "hi from sk-test-0003"
    health = {s["key"]: s for s in api.pool.snapshot()}
    assert health["...0001"]["cooldown_seconds"] == 7  # from Retry-After
    assert health["...0002"]["cooldown_seconds"] == 600
    assert [health[k]["status"] for k in ("...0001", "...0002", "...0003")] == ["rate_limited", "invalid", "ready"]


def test_gemini_invalid_key_400_rotates(api, vault, upstream):
    vault.add("gem", "gemini", ["bad", "good"], models={"chat": "m"})
    upstream.status = {"bad": "gemini-bad-key"}
    assert api.chat("gem", "x") == "hi from good"


def test_bad_request_does_not_burn_other_keys(api, vault, upstream):
    vault.add("bulk", "openai", ["k1", "k2"], models={"chat": "m"})
    upstream.status = {"k1": 404}
    with pytest.raises(MasterAPIError) as e:
        api.chat("bulk", "x")
    assert e.value.status == 404 and len(upstream.seen) == 1


def test_all_keys_rate_limited_returns_429_with_retry_after(api, vault, upstream):
    vault.add("bulk", "openai", ["k1", "k2"], models={"chat": "m"})
    upstream.status = {"k1": 429, "k2": 429}
    with pytest.raises(MasterAPIError) as e:
        api.chat("bulk", "x")
    assert e.value.status == 429 and e.value.retry_after == 7


def test_pool_round_robin_and_cooling_keys_go_last():
    now = [0.0]
    pool = KeyPool(clock=lambda: now[0])
    keys = ["a", "b", "c"]
    assert pool.order("x", keys) == ["a", "b", "c"]
    assert pool.order("x", keys) == ["b", "c", "a"]
    pool.failure("x", "c", "rate_limited", "429", retry_after=10)
    assert pool.order("x", keys) == ["a", "b", "c"]
    now[0] = 11
    assert pool.order("x", keys) == ["a", "b", "c"]


def test_transient_errors_retry_whole_pass(vault, upstream):
    from masterapi import MasterAPI

    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else upstream(request)

    api = MasterAPI(vault, http=httpx.Client(transport=httpx.MockTransport(flaky)), retries=1)
    vault.add("one", "openai", ["k"], models={"chat": "m"})
    assert api.chat("one", "x") == "hi from k"
    assert len(calls) == 2


def test_raw_request_passes_errors_through(api, vault, upstream):
    vault.add("el", "elevenlabs", ["ek"])
    upstream.reply = lambda r: httpx.Response(404, json={"detail": "voice not found"})
    r = api.request("el", "GET", "v1/voices/xyz")
    assert r.status_code == 404
    assert upstream.seen[0].headers["xi-api-key"] == "ek"
