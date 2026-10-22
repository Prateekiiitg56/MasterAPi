# Security

MasterAPI holds API keys that cost money, so this file says exactly how they are
protected and where the limits are.

## How secrets are stored

- **Provider keys** live in `vault.enc` (in `MASTERAPI_HOME`, default `~/.masterapi`),
  encrypted with Fernet (AES-128-CBC + HMAC-SHA256).
- **The vault encryption key** lives in the OS keyring (Windows Credential Manager,
  macOS Keychain, Secret Service on Linux). Where no keyring exists, it comes from
  the `MASTERAPI_KEY` environment variable. Anyone with this key and the vault
  file can read every provider key.
- **Client tokens** are stored only as SHA-256 hashes. The plaintext is shown once
  when created.
- If the keyring entry disappears while a vault exists, MasterAPI refuses to start
  rather than create a new key and overwrite the vault.

## What the server does

- Listens on `127.0.0.1` by default. Binding elsewhere logs a warning.
- Every endpoint except `/health` needs a token. Admin endpoints and the dashboard
  need an admin token. Tokens can be limited to some aliases.
- Client `Authorization`, `x-api-key`, `api-key` and `Cookie` headers are removed
  before a request is forwarded; the alias's own key is added instead.
- The admin API returns keys only as `...last4` plus a fingerprint, never in full.
- Logs record alias, key fingerprint and status. They never contain keys or tokens.
- The dashboard is served with a strict Content-Security-Policy, builds its DOM
  without `innerHTML`, and keeps the admin token in `sessionStorage` only.

## Code Mode sandbox

Agent-written code (`run_code`) is untrusted. It runs in a separate Deno process:

- No Deno permissions: network, file system, env, subprocesses and FFI are denied.
- `--no-remote --no-npm --no-config`: no remote or npm modules.
- V8 `--disallow-code-generation-from-strings`: no `eval` or `Function`, so `import`
  can't be built at runtime; source containing `import` is rejected (Deno lets
  dynamic `import()` read local JSON and JS files even without read permission).
- `Deno`, `Worker`, `WebSocket` and `fetch` are removed before the code runs.
- The process gets an empty working directory and no secrets in its environment.
- Its only channel is the `masterapi` binding (JSON over stdio). The host checks the
  alias scope on every call and enforces time, call and output limits.

Keys stay in the host process. The worst a malicious program can do is spend calls
on the aliases it is allowed to use, within the limits.

## Your responsibilities

- Put TLS in front of the server (a reverse proxy such as Caddy or nginx) before
  exposing it beyond localhost. The server itself speaks plain HTTP.
- Back up `MASTERAPI_KEY` if you use it. A lost key means a lost vault.
- `masterapi serve` prints a new admin token once on first start. In Docker this
  ends up in container logs; revoke it and create another if logs are shared.
- Give each project its own token so you can revoke one without touching others.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting
("Security" tab, "Report a vulnerability") on this repository. Expect a reply
within a week.
