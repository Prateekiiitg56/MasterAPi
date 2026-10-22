# MasterAPI

Self-hosted gateway for your AI API keys. Store keys once under a name like
`gemini` or `router`, then call any model by that name from any project: chat,
embeddings, image generation, or any other HTTP API that takes a key.

```python
from masterapi import chat, embed, image

chat("gemini", "Explain recursion in one line")
embed("openai", ["first text", "second text"])
image("openai", "a lighthouse at dawn, watercolor")
```

```python
# Any language, any OpenAI SDK
client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="<project token>")
client.chat.completions.create(model="router", messages=[...])
```

## Why

- **Keys in one place.** No more `.env` files with copies of the same keys in every repo.
- **Bulk keys.** One name can hold many keys. Calls rotate across them; a key that
  hits a rate limit rests for its `Retry-After`, a rejected key rests 10 minutes,
  and the call moves on to the next key.
- **One request format.** OpenAI's format works for every provider. Anthropic's
  native API is translated, including tools, images and streaming.
- **Any API.** Non-LLM services (ElevenLabs, Replicate, Deepgram, your own) work
  through a raw passthrough that injects the key.
- **Per-project tokens.** Each project gets its own revocable token, optionally
  limited to some aliases. Projects never see the real keys.
- **Dashboard.** Add keys, watch key health and usage, manage tokens.
- **Coding agents.** An MCP server with Code Mode: agents write TypeScript against
  your aliases and it runs in a locked-down Deno sandbox.

## Install

One line. It installs [uv](https://docs.astral.sh/uv/) if needed, MasterAPI, and
[Deno](https://deno.com) (the Code Mode sandbox), then starts a short setup that
stores your first key and connects your coding agents.

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/Prateekiiitg56/MasterAPi/main/install.ps1 | iex
```

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/Prateekiiitg56/MasterAPi/main/install.sh | sh
```

Already have uv or pip?

```bash
uv tool install git+https://github.com/Prateekiiitg56/MasterAPi && masterapi setup
pip install git+https://github.com/Prateekiiitg56/MasterAPi && masterapi setup
```

`masterapi setup` can be run again at any time. Requires Python 3.10+ (uv brings
its own). Update with `uv tool upgrade masterapi`.

## Store keys

```bash
masterapi providers
masterapi add gemini -p gemini -m gemini-2.5-flash --embed-model gemini-embedding-001
masterapi add openai -p openai -m gpt-4o-mini --embed-model text-embedding-3-small --image-model gpt-image-1
masterapi add router -p openrouter -m openai/gpt-4o-mini -f openrouter_keys.txt
masterapi add claude -p anthropic -m claude-sonnet-4-5
masterapi add local  -p ollama -m llama3.2
masterapi list
masterapi test gemini "hello"
masterapi test openai --op images "a red fox"
```

`add` asks for keys with hidden input. `-f` reads a file with one key per line
for bulk import. Keys are never accepted as arguments, so they stay out of shell
history. Delete the keys file after importing it.

More: `add-keys NAME -f FILE`, `remove-key NAME LAST4`, `set NAME -m MODEL`, `remove NAME`.

### Built-in providers

| Provider | Supports | Key sent as |
|---|---|---|
| openai, gemini, together | chat, embeddings, images | Bearer |
| xai | chat, images | Bearer |
| mistral, fireworks, cohere | chat, embeddings | Bearer |
| openrouter, groq, deepseek, perplexity | chat | Bearer |
| anthropic | chat (native API, translated) | `x-api-key` |
| ollama | chat, embeddings | no key |
| elevenlabs, replicate, stability, deepgram | raw requests | provider's own header |

### Any other API

```bash
# OpenAI-compatible endpoint
masterapi add vllm -p custom --base-url http://gpu-box:8000/v1 -m qwen2.5 --cap chat,embeddings
# Key in a custom header, raw requests only
masterapi add weather -p custom --base-url https://api.weather.example --adapter http --auth header:X-Api-Key
# Key in the query string
masterapi add maps -p custom --base-url https://maps.example/api --adapter http --auth query:key
```

`--auth` accepts `bearer`, `none`, `header:NAME`, `header:NAME=TEMPLATE`
(e.g. `header:Authorization=Token {key}`) and `query:NAME`. Built-in providers
take the same flags to override their defaults.

## Call by name

A target is `name` (uses the alias's default model for that operation) or
`name:model`, e.g. `router:meta-llama/llama-3.3-70b-instruct:free`.

### Python

```python
from masterapi import MasterAPI

api = MasterAPI()
api.chat_completion("claude", {"messages": [...], "tools": [...]})   # full OpenAI-format response
for chunk in api.chat_stream("gemini", {"messages": [...]}):          # SSE bytes
    ...
api.embeddings("openai", {"input": ["a", "b"], "dimensions": 256})
api.images("openai", {"prompt": "a fox", "size": "1024x1024"})
api.request("elevenlabs", "POST", "/v1/text-to-speech/VOICE_ID", json={"text": "hi"})  # raw httpx.Response
```

### Server (any language)

```bash
masterapi serve                       # http://127.0.0.1:8787, prints an admin token on first start
masterapi token create my-app --alias gemini --alias router
```

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat/completions` | chat, `stream: true` supported |
| `POST /v1/embeddings` | embeddings |
| `POST /v1/images/generations` | image generation |
| `GET /v1/models` | aliases this token may use |
| `ANY /proxy/{alias}/{path}` | raw passthrough; key injected, client auth headers stripped |
| `/dashboard/` | web dashboard (admin token) |
| `/admin/*` | admin API used by the dashboard |
| `/mcp` | MCP server for coding agents (token scope applies) |
| `/docs` | OpenAPI docs |

Errors use OpenAI's shape `{"error": {"message", "type", "code"}}`. When every key
is rate limited the response is `429` with `Retry-After`.

See [examples/](examples/) for Python, OpenAI SDK, Node and curl.

### Coding agents (MCP + Code Mode)

`masterapi mcp` is an MCP server, so Claude Code, Cursor, Codex, Cline and other
agents can use your aliases. They see alias names only, never keys, and they get no
admin actions.

```bash
masterapi connect                  # every agent found: Claude Code, Cursor, Codex, Claude Desktop, Windsurf
masterapi connect claude cursor    # or just these
masterapi connect --alias gemini   # limit what agents may use
masterapi connect --list           # which agents are installed
```

Restart the agent afterwards. Prefer doing it by hand? Claude Code:
`claude mcp add --scope user masterapi -- masterapi mcp`. Cursor (`~/.cursor/mcp.json`)
and Codex (`~/.codex/config.toml`):

```json
{ "mcpServers": { "masterapi": { "command": "masterapi", "args": ["mcp"] } } }
```

```toml
[mcp_servers.masterapi]
command = "masterapi"
args = ["mcp"]
```

#### Code Mode

With [Deno](https://deno.com) installed, the server offers one `run_code` tool
instead of a tool per action (the idea behind Cloudflare's Code Mode, without
Cloudflare). The agent gets a typed TypeScript API in the tool description and
writes a short program:

```ts
const files = ["auth.py", "db.py", "api.py"];
const reviews = await Promise.all(files.map((f) =>
  masterapi.chat("gemini", `List bugs in ${f}: ...`)));
return reviews;
```

One tool call can loop, fan out in parallel and combine results, instead of
dozens of round trips through the agent's context.

The program runs in a Deno process with **no permissions**: no network, files,
env or subprocesses. Code generation from strings and `import` are blocked, and
`Deno`, `fetch` and `Worker` are removed. Its only way out is the `masterapi`
binding, which the Python host serves over stdio, so keys never enter the sandbox.
Limits: 60 s, 100 calls, 4 in flight per run, output capped at 40,000 characters.
Generated images and binary responses are saved to `./masterapi-outputs/` and
returned as file paths.

`--mode tools` gives classic tools instead (`chat`, `embed`, `generate_image`,
`request`). Without Deno, `auto` (the default) falls back to that mode.

#### Over HTTP

`masterapi serve` also serves MCP at `/mcp`. The project token's alias limits apply.

```bash
claude mcp add --transport http masterapi http://127.0.0.1:8787/mcp --header "Authorization: Bearer <token>"
```

### Docker

```bash
docker build -t masterapi .
docker run -d -p 127.0.0.1:8787:8787 -v masterapi-data:/data -e MASTERAPI_KEY=$(masterapi keygen) masterapi
docker logs <container>      # admin token, shown once
```

Save that `MASTERAPI_KEY`: it decrypts the vault.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MASTERAPI_HOME` | `~/.masterapi` | vault folder |
| `MASTERAPI_KEY` | OS keyring | vault encryption key (Docker, CI, servers without a keyring) |
| `MASTERAPI_TIMEOUT` | `120` | upstream timeout in seconds |
| `MASTERAPI_RETRIES` | `1` | extra passes over the keys after 5xx or network errors |

## Architecture

```
project ─► masterapi.chat/embed/image/request ─┐
any SDK ─► FastAPI server /v1, /proxy ─────────┤
                                               ▼
                         MasterAPI client: resolve "alias[:model]"
                                               │
                 provider registry (+ alias overrides): URL, auth style, capabilities
                                               │
                 adapter: OpenAI-compatible │ Anthropic native │ raw HTTP
                                               │
                 key pool: round robin, cooldowns, health ─► httpx ─► provider
```

| File | Role |
|---|---|
| `masterapi/vault.py` | encrypted storage of aliases and hashed tokens |
| `masterapi/providers/` | provider registry, auth styles |
| `masterapi/adapters/` | request/response translation (no I/O) |
| `masterapi/keypool.py` | key order, cooldowns, health |
| `masterapi/client.py` | Python API, retries |
| `masterapi/server.py` | HTTP gateway, admin API, dashboard, `/mcp` |
| `masterapi/mcp_server.py` | MCP tools for coding agents |
| `masterapi/codemode/` | Code Mode: Deno sandbox runner and host bindings |

## Security

Read [SECURITY.md](SECURITY.md). In short: the vault is encrypted with a key held
in your OS keyring, tokens are stored hashed, the server listens on localhost by
default, and the admin API never returns plaintext keys. Put a TLS reverse proxy
in front before exposing it to a network.

## Limits

- Anthropic has no embeddings or image API. OpenAI options it lacks (`n`,
  `response_format`) are dropped when translating.
- Image edits, audio and other endpoints go through `/proxy` or `request()`.
- Key health and usage counters live in memory and reset on restart.
- Two processes writing the vault at the same moment can lose one change.
- Code Mode needs Deno. The sandbox runs one program at a time per tool call and
  starts a fresh Deno process each run (about 0.1 s).

## Development

```bash
pip install -e ".[dev]"
python -m pytest
ruff check .
```

MIT licensed.
