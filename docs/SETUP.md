# Setup guide

Everything from first install to running MasterAPI as an always-on service.
For a quick start, the [README](../README.md#install) is enough.

- [1. Install](#1-install)
- [2. First run](#2-first-run)
- [3. Add keys](#3-add-keys)
- [4. Use from your code](#4-use-from-your-code)
- [5. Connect coding agents](#5-connect-coding-agents)
- [6. Run the server and dashboard](#6-run-the-server-and-dashboard)
- [7. Run it in Docker](#7-run-it-in-docker)
- [8. Start automatically](#8-start-automatically)
- [9. Configuration](#9-configuration)
- [10. Update and uninstall](#10-update-and-uninstall)
- [11. Troubleshooting](#11-troubleshooting)

## 1. Install

### One line (recommended)

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/Prateekiiitg56/MasterAPi/main/install.ps1 | iex
```

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/Prateekiiitg56/MasterAPi/main/install.sh | sh
```

The script:

1. installs [uv](https://docs.astral.sh/uv/) if you don't have it (it manages Python for you),
2. installs MasterAPI as a uv tool, so the `masterapi` command is on your PATH,
3. installs [Deno](https://deno.com), the sandbox used by Code Mode,
4. runs `masterapi setup`.

Skip parts with environment variables: `MASTERAPI_NO_DENO=1` (no Deno; agents get
plain tools instead of Code Mode) and `MASTERAPI_NO_SETUP=1` (install only).

```powershell
$env:MASTERAPI_NO_DENO = 1; irm https://raw.githubusercontent.com/Prateekiiitg56/MasterAPi/main/install.ps1 | iex
```

Prefer to read the script first? It is short: [install.ps1](../install.ps1), [install.sh](../install.sh).

### With uv or pip

```bash
uv tool install git+https://github.com/Prateekiiitg56/MasterAPi
pip install git+https://github.com/Prateekiiitg56/MasterAPi
```

Then run `masterapi setup`. Install Deno separately if you want Code Mode
(`winget install DenoLand.Deno`, `brew install deno`, or see [deno.com](https://deno.com)).

### From source

```bash
git clone https://github.com/Prateekiiitg56/MasterAPi
cd MasterAPi
pip install -e ".[dev]"
```

Requirements: Python 3.10 or newer (uv installs one for you), Windows, macOS or Linux.

## 2. First run

```bash
masterapi setup
```

The setup:

1. shows where your vault is and whether Code Mode is ready,
2. adds a key: pick a provider, a name, a default model, then paste one or more keys
   (input is hidden),
3. sends a test message through it,
4. finds your coding agents and offers to connect them.

Run it again any time. It never deletes anything.

The vault is created at `~/.masterapi/vault.enc` (`%USERPROFILE%\.masterapi` on
Windows). Its encryption key is stored in your OS keychain under the service name
`masterapi`.

## 3. Add keys

```bash
masterapi providers                       # built-in providers and what they support
masterapi add gemini -p gemini -m gemini-2.5-flash --embed-model gemini-embedding-001
masterapi add openai -p openai -m gpt-4o-mini --embed-model text-embedding-3-small --image-model gpt-image-1
masterapi add claude -p anthropic -m claude-sonnet-4-5
masterapi add local  -p ollama -m llama3.2  # no key needed
```

`-m` sets the default chat model, `--embed-model` and `--image-model` the defaults for
embeddings and images. Callers can always pick another model with `"alias:model-id"`.

### Many keys under one name

```bash
masterapi add router -p openrouter -m openai/gpt-4o-mini -f openrouter_keys.txt
masterapi add-keys router -f more_keys.txt
```

The file has one key per line; blank lines and lines starting with `#` are ignored.
Delete the file once the keys are imported.

Calls start at the next key each time. A key that returns `429` rests for the time in
its `Retry-After` header (or a growing backoff). A key that returns `401`, `402`,
`403` or "API key not valid" rests 10 minutes. Server errors move on to the next key
and retry once.

### Any other API

```bash
# Any OpenAI-compatible server (vLLM, LM Studio, a company gateway)
masterapi add vllm -p custom --base-url http://gpu-box:8000/v1 -m qwen2.5 --cap chat,embeddings

# A non-LLM API with the key in a custom header (raw requests only)
masterapi add weather -p custom --base-url https://api.weather.example --adapter http --auth header:X-Api-Key

# Key in the query string
masterapi add maps -p custom --base-url https://maps.example/api --adapter http --auth query:key
```

| `--auth` | Key is sent as |
|---|---|
| `bearer` (default) | `Authorization: Bearer KEY` |
| `header:NAME` | `NAME: KEY` |
| `header:NAME=TEMPLATE` | e.g. `header:Authorization=Token {key}` |
| `query:NAME` | `?NAME=KEY` |
| `none` | no key |

Built-in providers accept the same flags to override their defaults, for example
`masterapi set gemini --base-url https://my-proxy.example/v1beta/openai`.

### Managing keys

```bash
masterapi list                       # names, models, keys (last 4 characters only)
masterapi set gemini -m gemini-2.5-pro
masterapi remove-key router a1b2     # remove the key ending in a1b2
masterapi remove router              # delete the alias and its keys
masterapi test gemini "hello"        # also: --op embeddings, --op images
```

Everything here is also available in the [dashboard](#6-run-the-server-and-dashboard).

## 4. Use from your code

### Python, same machine

```python
from masterapi import chat, embed, image, request, MasterAPI

chat("gemini", "hello")
chat("router:meta-llama/llama-3.3-70b-instruct:free", "hello", temperature=0.2)
embed("openai", ["a", "b"])
image("openai", "a red fox")
request("elevenlabs", "GET", "/v1/voices").json()   # any API, key added for you

api = MasterAPI()
api.chat_completion("claude", {"messages": [...], "tools": [...]})   # full OpenAI-format response
for chunk in api.chat_stream("gemini", {"messages": [...]}):          # streaming (SSE bytes)
    ...
```

Errors raise `masterapi.MasterAPIError` with `.status` (and `.retry_after` for 429).

### Any language, through the server

Start the server ([section 6](#6-run-the-server-and-dashboard)), create a token for the project:

```bash
masterapi token create my-app                         # all aliases
masterapi token create scraper --alias router         # only "router"
```

Use any OpenAI SDK with `base_url = http://127.0.0.1:8787/v1`, `api_key = <token>`,
and the alias as `model`. Examples for Python, Node and curl are in [examples/](../examples/).

| Endpoint | What it does |
|---|---|
| `POST /v1/chat/completions` | chat; `"stream": true` supported |
| `POST /v1/embeddings` | embeddings |
| `POST /v1/images/generations` | image generation |
| `GET /v1/models` | aliases this token may use |
| `ANY /proxy/{alias}/{path}` | any other endpoint (audio, image edits, other APIs); the key is added |
| `/mcp` | MCP server for remote coding agents |
| `/dashboard/` | web dashboard |
| `/docs` | interactive API docs |

Errors use OpenAI's format: `{"error": {"message", "type", "code"}}`. When every key
of an alias is rate limited, the response is `429` with a `Retry-After` header.

## 5. Connect coding agents

```bash
masterapi connect --list                 # supported agents and which are installed
masterapi connect                        # connect every agent found
masterapi connect claude cursor          # or only these
masterapi connect --alias gemini         # agents may only use "gemini"
```

Supported: Claude Code, Cursor, Codex, Claude Desktop and Windsurf. `connect`
replaces only its own `masterapi` entry and leaves your other MCP servers alone.
Restart the agent (or start a new session) afterwards.

### By hand

**Claude Code**

```bash
claude mcp add --scope user masterapi -- masterapi mcp
```

**Cursor** (`~/.cursor/mcp.json`), **Claude Desktop** (`claude_desktop_config.json`), **Windsurf** (`~/.codeium/windsurf/mcp_config.json`)

```json
{ "mcpServers": { "masterapi": { "command": "masterapi", "args": ["mcp"] } } }
```

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.masterapi]
command = "masterapi"
args = ["mcp"]
```

If an agent can't find `masterapi`, use the full path from `where masterapi`
(Windows) or `which masterapi` (macOS/Linux).

### What the agent gets

| Mode | Tools | When |
|---|---|---|
| Code Mode | `list_models`, `run_code` | Deno installed (default) |
| Tools | `list_models`, `chat`, `embed`, `generate_image`, `request` | no Deno, or `masterapi mcp --mode tools` |

In Code Mode the agent writes TypeScript against a typed `masterapi` API (`chat`,
`chatCompletion`, `embed`, `image`, `request`, `models`) and it runs in a Deno
sandbox with no permissions. Each run gets 60 seconds, 100 calls and 4 calls in
flight. Images and binary responses are saved to `./masterapi-outputs/` in the
agent's working folder and returned as file paths; add that folder to your
project's `.gitignore`.

Options for `masterapi mcp`: `--alias` (repeatable), `--mode auto|code|tools`,
`--timeout SECONDS`, `--output-dir PATH`.

### Remote agents (over HTTP)

`masterapi serve` also serves MCP at `/mcp`. The token's alias limits apply.

```bash
claude mcp add --transport http masterapi http://127.0.0.1:8787/mcp --header "Authorization: Bearer <token>"
```

## 6. Run the server and dashboard

```bash
masterapi serve                    # http://127.0.0.1:8787
masterapi serve --port 8790        # if 8787 is taken
```

On first start it prints an **admin token** once. Open
`http://127.0.0.1:8787/dashboard/` and sign in with it. Lost it? Create another:

```bash
masterapi token create admin2 --admin
masterapi token list
masterapi token revoke admin
```

The server listens on `127.0.0.1` only. To reach it from other machines, use
`--host 0.0.0.0` behind a reverse proxy with TLS (Caddy, nginx) and give each client
its own token. Read [SECURITY.md](../SECURITY.md) first.

## 7. Run it in Docker

Containers have no OS keychain, so you provide the vault key yourself:

```bash
masterapi keygen > masterapi.key                     # keep this file safe and backed up
docker build -t masterapi https://github.com/Prateekiiitg56/MasterAPi.git
docker run -d --name masterapi -p 127.0.0.1:8787:8787 \
  -v masterapi-data:/data -e MASTERAPI_KEY="$(cat masterapi.key)" masterapi
docker logs masterapi                                # admin token, shown once
```

Add keys inside the container (input stays hidden):

```bash
docker exec -it masterapi masterapi add gemini -p gemini -m gemini-2.5-flash
```

The image includes Deno, so `/mcp` uses Code Mode.

## 8. Start automatically

**Windows**: start with your login (PowerShell):

```powershell
$exe = (Get-Command masterapi).Source
Register-ScheduledTask -TaskName "MasterAPI" -Trigger (New-ScheduledTaskTrigger -AtLogOn) `
  -Action (New-ScheduledTaskAction -Execute $exe -Argument "serve")
```

Remove it with `Unregister-ScheduledTask -TaskName MasterAPI`.

**Linux**: a systemd user service:

```ini
# ~/.config/systemd/user/masterapi.service
[Unit]
Description=MasterAPI gateway

[Service]
ExecStart=%h/.local/bin/masterapi serve
EnvironmentFile=%h/.masterapi/env
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
masterapi keygen | sed 's/^/MASTERAPI_KEY=/' > ~/.masterapi/env && chmod 600 ~/.masterapi/env
systemctl --user enable --now masterapi
```

The `env` file is needed only when no desktop keyring is running (servers). If you
created the vault with the keyring, keep using the keyring and drop the
`EnvironmentFile` line; a new `MASTERAPI_KEY` can't open a vault made with another key.

**macOS**: a LaunchAgent at `~/Library/LaunchAgents/dev.masterapi.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.masterapi</string>
  <key>ProgramArguments</key><array><string>/Users/YOU/.local/bin/masterapi</string><string>serve</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/dev.masterapi.plist
```

## 9. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MASTERAPI_HOME` | `~/.masterapi` | folder for the vault and server outputs |
| `MASTERAPI_KEY` | OS keychain | vault encryption key (Docker, CI, headless servers) |
| `MASTERAPI_TIMEOUT` | `120` | provider timeout in seconds |
| `MASTERAPI_RETRIES` | `1` | extra passes over the keys after server or network errors |
| `MASTERAPI_DENO` | auto-detected | path to the Deno binary for Code Mode |

## 10. Update and uninstall

**Update**: run the install line again, or:

```bash
uv tool install --force git+https://github.com/Prateekiiitg56/MasterAPi
```

Your vault, tokens and agent connections are kept.

**Uninstall**

```bash
uv tool uninstall masterapi            # or: pip uninstall masterapi
claude mcp remove masterapi -s user    # and remove the "masterapi" entry from other agents' configs
```

To also delete your stored keys (this can't be undone):

```bash
rm -r ~/.masterapi
python -c "import keyring; keyring.delete_password('masterapi', 'vault-key')"
```

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `masterapi: command not found` right after installing | Open a new terminal so PATH updates, or run `uv tool update-shell`. |
| `address already in use` / port taken | `masterapi serve --port 8790` |
| `no usable OS keyring` | Headless machine or container: set `MASTERAPI_KEY` (from `masterapi keygen`). |
| `vault exists but its encryption key is missing` | The keychain entry is gone. Set `MASTERAPI_KEY` to the original key. MasterAPI refuses to start rather than overwrite the vault. |
| `cannot decrypt vault` | `MASTERAPI_KEY` doesn't match the key the vault was made with. |
| The agent doesn't show MasterAPI tools | Restart the agent. Check `claude mcp get masterapi`. Run `masterapi mcp` yourself: it should wait silently (Ctrl+C to stop). |
| Agent gets `chat`/`embed` tools instead of `run_code` | Deno isn't found. Install it, or set `MASTERAPI_DENO` to its path. `masterapi setup` shows the status. |
| `429` with `Retry-After` from the server | Every key of that alias is rate limited. Add keys (`masterapi add-keys`) or wait. |
| A key shows "Rejected" in the dashboard | The provider refused it (invalid, expired or out of credit). Replace it with `remove-key` and `add-keys`. |
| `does not support images` (or embeddings) | That provider can't do it, or the alias needs `--cap`. See `masterapi providers`. |
| `has no default chat model` | Set one with `masterapi set NAME -m MODEL`, or call `"name:model-id"`. |

Still stuck? [Open an issue](https://github.com/Prateekiiitg56/MasterAPi/issues) with
the command you ran and the error. Never paste keys or tokens.
