import json

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from masterapi.codemode import Bindings, CodeRunner, find_deno, format_run
from masterapi.mcp_server import build_mcp
from masterapi.server import create_app

needs_deno = pytest.mark.skipif(find_deno() is None, reason="Deno is not installed")


@pytest.fixture
def aliases(vault):
    vault.add("gem", "gemini", ["sk-gemini-0001"], models={"chat": "m", "embeddings": "e"})
    vault.add("oa", "openai", ["sk-openai-0001"], models={"chat": "m", "images": "img"})


@pytest.fixture
def runner(api, aliases, tmp_path):
    return CodeRunner(Bindings(api, output_dir=tmp_path), timeout=10)


# Sandbox

@needs_deno
def test_parallel_calls_and_console(runner, upstream):
    out = runner.run("""
        const names = (await masterapi.models()).map((m) => m.name);
        console.log("aliases", names);
        const replies = await Promise.all(["gem", "oa"].map((m) => masterapi.chat(m, "hi")));
        const vectors = await masterapi.embed("gem", ["a", "b"]);
        return { names, replies, count: vectors.length };
    """)
    assert out["ok"], out
    assert out["result"] == {"names": ["gem", "oa"], "replies": ["hi from sk-gemini-0001", "hi from sk-openai-0001"],
                             "count": 2}
    assert out["calls"] == 4
    assert out["logs"][0].startswith("[log] aliases")


@needs_deno
@pytest.mark.parametrize("code, error", [
    ('return await fetch("https://example.com")', "Network access is disabled"),
    ('return Deno.env.get("PATH")', "Deno is not defined"),
    ('return eval("1 + 1")', "Code generation from strings disallowed"),
    ('return await (async () => {}).constructor("return 1")()', "Code generation from strings disallowed"),
    ('return await import("file:///etc/passwd")', "`import` is not available"),
    ('return new Worker("file:///x.ts")', "Worker is not defined"),
])
def test_sandbox_blocks_escapes(runner, code, error):
    out = runner.run(code)
    assert not out["ok"] and error in out["error"]


@needs_deno
def test_scope_errors_and_limits(api, aliases, tmp_path):
    scoped = CodeRunner(Bindings(api, aliases=["gem"], output_dir=tmp_path), timeout=3, max_calls=2)
    out = scoped.run('return await masterapi.chat("oa", "hi")')
    assert "not available here (HTTP 403)" in out["error"]
    out = scoped.run('for (let i = 0; i < 3; i++) await masterapi.models(); return 1')
    assert "call limit reached" in out["error"]
    assert "timed out" in scoped.run("while (true) {}")["error"]


@needs_deno
def test_images_and_binary_are_saved_to_files(api, aliases, upstream, tmp_path):
    def reply(request):
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"b64_json": "iVBORw0KGgo="}]})
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})
    upstream.reply = reply
    out_dir = tmp_path / "out"
    runner = CodeRunner(Bindings(api, output_dir=out_dir), timeout=10)
    out = runner.run("""
        const [img] = await masterapi.image("oa", "a fox");
        const tts = await masterapi.request("oa", "POST", "/audio/speech", { json: { input: "hi" } });
        return { img, tts };
    """)
    assert out["ok"], out
    assert out["result"]["img"]["path"].endswith(".png")
    assert out["result"]["tts"]["bytes"] == 8 and out["result"]["tts"]["path"].endswith(".mp3")
    assert sorted(p.suffix for p in out_dir.iterdir()) == [".mp3", ".png"]


def test_output_is_capped():
    text = format_run({"ok": True, "result": "x" * 100_000, "logs": [], "calls": 0, "seconds": 0})
    assert len(text) < 41_000 and "truncated" in text


# MCP

def call_tool(mcp, name, args):
    async def go():
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = [t.name for t in (await client.list_tools()).tools]
            result = await client.call_tool(name, args)
            return tools, result
    return anyio.run(go)


@needs_deno
def test_mcp_code_mode(api, aliases, tmp_path):
    mcp = build_mcp(api, mode="code", output_dir=str(tmp_path))
    tools, result = call_tool(mcp, "run_code", {"code": 'return await masterapi.chat("gem", "hi")'})
    assert tools == ["list_models", "run_code"]
    assert '"hi from sk-gemini-0001"' in result.content[0].text
    description = next(t for t in anyio.run(lambda: mcp.list_tools()) if t.name == "run_code").description
    assert 'type Alias = "gem" | "oa"' in description


def test_mcp_tools_mode_and_scope(api, aliases, tmp_path):
    mcp = build_mcp(api, mode="tools", aliases=["gem"], output_dir=str(tmp_path))
    tools, result = call_tool(mcp, "chat", {"model": "gem", "prompt": "hi"})
    assert tools == ["list_models", "chat", "embed", "generate_image", "request"]
    assert result.content[0].text == "hi from sk-gemini-0001"
    _, result = call_tool(mcp, "chat", {"model": "oa", "prompt": "hi"})
    assert result.isError and "not available here" in result.content[0].text
    _, result = call_tool(mcp, "list_models", {})
    assert [m["name"] for m in json.loads(result.content[0].text)] == ["gem"]


def test_mcp_over_http_uses_token_scope(api, vault, aliases):
    token = vault.create_token("agent", aliases=["gem"])
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_models", "arguments": {}}}
    with TestClient(create_app(api)) as client:
        assert client.post("/mcp", json=rpc, headers={"Accept": headers["Accept"]}).status_code == 401
        r = client.post("/mcp", json=rpc, headers=headers)
        assert r.status_code == 200, r.text
        listed = json.loads(r.json()["result"]["content"][0]["text"])
        assert [m["name"] for m in listed] == ["gem"]
