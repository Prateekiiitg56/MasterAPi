"""MCP server: lets coding agents (Claude Code, Cursor, Codex, ...) use your aliases.

Two shapes, picked by `mode`:
- "code" (Code Mode): one `run_code` tool. The agent writes TypeScript against a
  typed `masterapi` API; it runs in the Deno sandbox (see masterapi.codemode).
  Many calls, loops and Promise.all fan-out happen in one tool call.
- "tools": classic one-call-per-tool (chat, embed, generate_image, request).
"auto" uses Code Mode when Deno is installed.

Agents only ever see alias names. Keys, the vault and admin actions are not exposed.
"""

import json

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .client import MasterAPI, MasterAPIError
from .codemode import Bindings, CodeRunner, find_deno, format_run

INSTRUCTIONS = """MasterAPI gives you the user's AI models and APIs by alias name (for example
"gemini" or "openai"); the API keys stay hidden. Use it to get a second opinion from
another model, delegate bulk work to a cheaper model, create embeddings or generate
images. Call list_models first to see which aliases exist and what each supports."""


def _ts_api(aliases: list[str] | None) -> str:
    """TypeScript declaration of the sandbox API, shown to the agent in the tool description."""
    alias_type = " | ".join(f'"{a}"' for a in aliases) if aliases else "string"
    return f"""type Alias = {alias_type};
type Target = Alias | `${{Alias}}:${{string}}`;   // "alias" uses its default model; "alias:model-id" picks one
type Message = {{ role: "system" | "user" | "assistant" | "tool"; content: string | unknown[] }};

declare const masterapi: {{
  /** Aliases you may call, what each supports ("chat" | "embeddings" | "images"), default models. */
  models(): Promise<{{ name: Alias; provider: string; capabilities: string[]; models: Record<string, string> }}[]>;

  /** Prompt (or messages) in, reply text out. Options: system, temperature, max_tokens, any OpenAI field. */
  chat(
    model: Target,
    prompt: string | Message[],
    options?: {{ system?: string; temperature?: number; max_tokens?: number; [k: string]: unknown }},
  ): Promise<string>;

  /** Full OpenAI-format chat completion (tools, response_format, ...). Works for every provider. */
  chatCompletion(model: Target, body: {{ messages: Message[]; [k: string]: unknown }}): Promise<any>;

  /** One vector per input, in input order. */
  embed(model: Target, input: string | string[], options?: {{ dimensions?: number }}): Promise<number[][]>;

  /** Generate images. Base64 results are saved to files; you get {{ url }} or {{ path }}. */
  image(
    model: Target,
    prompt: string,
    options?: {{ size?: string; n?: number; [k: string]: unknown }},
  ): Promise<{{ url?: string; path?: string; revised_prompt?: string }}[]>;

  /** Raw HTTP call to any API stored under `alias`; the key is added. Binary bodies are saved to `path`. */
  request(
    alias: Alias,
    method: string,
    path: string,
    options?: {{ json?: unknown; body?: string; query?: Record<string, string>; headers?: Record<string, string> }},
  ): Promise<{{ status: number; contentType: string; body?: unknown; path?: string; bytes?: number }}>;
}};"""


def _code_doc(aliases: list[str] | None, timeout: float, max_calls: int) -> str:
    return f"""Run a short TypeScript program that uses the user's AI models through `masterapi`.

Write the BODY of an async function: use `await`, then `return` a JSON-serializable value.
`console.log` output is returned too. Run independent calls in parallel with Promise.all.
The sandbox has no network, files, env or `import`; `masterapi` is the only way out.
Limits: {timeout:.0f}s, {max_calls} masterapi calls, 4 in flight at once. Return summaries, not huge data.

```ts
{_ts_api(aliases)}
```

Example:
```ts
const [a, b] = await Promise.all([
  masterapi.chat("gemini", "Review this function for bugs: ..."),
  masterapi.chat("openai", "Review this function for bugs: ..."),
]);
return {{ gemini: a, openai: b }};
```"""


def build_mcp(api: MasterAPI | None = None, *, aliases: list[str] | None = None, mode: str = "auto",
              http: bool = False, output_dir: str = "masterapi-outputs", timeout: float = 60,
              max_calls: int = 100) -> FastMCP:
    """Create the MCP server.

    aliases: limit to these aliases (stdio). Over HTTP the caller's token decides instead.
    """
    api = api or MasterAPI()
    deno = find_deno()
    if mode == "auto":
        mode = "code" if deno else "tools"
    if mode == "code" and not deno:
        raise MasterAPIError("Code Mode needs Deno (https://deno.com); install it or use --mode tools", 400)

    # Every /mcp request must carry a MasterAPI token (TokenAuthASGI), which already
    # defeats DNS-rebinding; the SDK's Host check would only break Docker and proxies.
    mcp = FastMCP("masterapi", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
                  streamable_http_path="/",
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    def scope(ctx: Context | None) -> list[str] | None:
        """Aliases this caller may use: the token's scope over HTTP, `aliases` over stdio."""
        try:
            request = ctx.request_context.request if ctx else None
        except (ValueError, AttributeError, LookupError):  # no request (stdio or direct call)
            request = None
        record = getattr(getattr(request, "state", None), "masterapi_token", None)
        if record is not None:
            return record["aliases"]
        return aliases

    def bindings(ctx: Context | None) -> Bindings:
        return Bindings(api, aliases=scope(ctx), output_dir=output_dir)

    async def blocking(fn, *args):
        """Run sync work off the event loop; turn API errors into readable tool errors."""
        try:
            return await anyio.to_thread.run_sync(fn, *args)
        except MasterAPIError as e:
            raise ValueError(f"{e} (HTTP {e.status})") from None

    shown_aliases = None if http else (aliases or sorted(api.vault.aliases()))
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    calls_out = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)

    async def list_models(ctx: Context) -> str:
        """List the aliases you can call, what each supports and their default models."""
        return json.dumps(await blocking(bindings(ctx).models), indent=2)

    mcp.add_tool(list_models, annotations=read_only)

    if mode == "code":
        async def run_code(code: str, ctx: Context) -> str:
            runner = CodeRunner(bindings(ctx), timeout=timeout, max_calls=max_calls, deno=deno)
            return format_run(await blocking(runner.run, code))

        mcp.add_tool(run_code, description=_code_doc(shown_aliases, timeout, max_calls), annotations=calls_out)
        return mcp

    async def chat(model: str, prompt: str, ctx: Context, system: str | None = None,
                   temperature: float | None = None, max_tokens: int | None = None) -> str:
        """Ask a model. `model` is an alias ("gemini") or "alias:model-id". Returns the reply text."""
        options = {k: v for k, v in {"system": system, "temperature": temperature, "max_tokens": max_tokens}.items()
                   if v is not None}
        return await blocking(lambda: bindings(ctx).chat(model, prompt, options))

    async def embed(model: str, texts: list[str], ctx: Context) -> str:
        """Create embeddings for `texts`. Returns one vector per text as JSON."""
        return json.dumps(await blocking(lambda: bindings(ctx).embed(model, texts)))

    async def generate_image(model: str, prompt: str, ctx: Context, size: str | None = None) -> str:
        """Generate an image. Returns URLs, or paths of saved files."""
        options = {"size": size} if size else {}
        return json.dumps(await blocking(lambda: bindings(ctx).image(model, prompt, options)), indent=2)

    async def request(alias: str, method: str, path: str, ctx: Context, json_body: dict | None = None,
                      query: dict[str, str] | None = None) -> str:
        """Raw HTTP call to any API stored under `alias` (the key is added). Binary responses are saved to a file."""
        options = {"json": json_body, "query": query}
        return json.dumps(await blocking(lambda: bindings(ctx).request(alias, method, path, options)), indent=2)

    mcp.add_tool(chat, annotations=calls_out)
    mcp.add_tool(embed, annotations=calls_out)
    mcp.add_tool(generate_image, annotations=calls_out)
    mcp.add_tool(request, annotations=calls_out)
    return mcp


def http_endpoint(mcp: FastMCP, vault) -> "TokenAuthASGI":
    """ASGI app serving MCP over streamable HTTP. The caller must run mcp.session_manager.run()."""
    mcp.streamable_http_app()  # creates the session manager
    return TokenAuthASGI(StreamableHTTPASGIApp(mcp.session_manager), vault)


class TokenAuthASGI:
    """Guards the /mcp endpoint with MasterAPI tokens and passes the token's scope to tools."""

    def __init__(self, app, vault):
        self.app = app
        self.vault = vault

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else headers.get("x-masterapi-token", "")
        record = await anyio.to_thread.run_sync(self.vault.verify_token, token)
        if record is None:
            body = json.dumps({"error": {"message": "missing or invalid token", "type": "masterapi_error",
                                         "code": 401}}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
            return await send({"type": "http.response.body", "body": body})
        scope.setdefault("state", {})["masterapi_token"] = record
        await self.app(scope, receive, send)
