# Changelog

## Unreleased

- Security hardening: stored keys are masked out of upstream errors, logs and
  proxied error bodies; raw passthrough paths can't leave the base URL; keys are
  refused over plain HTTP to non-local hosts; atomic, owner-only vault writes;
  50 MB request body limit; no-store and other security headers on every API
  response; `/docs`, `/redoc` and `/openapi.json` removed (Swagger loads CDN
  scripts); sanitised request IDs. SECURITY.md gains a privacy section.

- One-line install scripts (`install.ps1`, `install.sh`), `masterapi setup` wizard and
  `masterapi connect` to register the MCP server with Claude Code, Cursor, Codex,
  Claude Desktop and Windsurf.
- MCP server for coding agents: `masterapi mcp` (stdio) and `/mcp` on the gateway.
- Code Mode: one `run_code` tool; agents write TypeScript against a typed `masterapi`
  API, run in a permission-less Deno sandbox. Images and binary output saved to files.
- Dashboard redesign: overview page, deep links, sidebar and mobile tab bar, dialogs with
  typed confirmation for deletes, inline validation, live key health, sortable usage,
  light/dark/system theme, keyboard shortcut `/` for search.
- `GET /admin/me` returns the signed-in token's name and role.
- `GET /admin/stats`: uptime, success rate, median and p95 response time, tokens and
  requests per minute for the last hour. `/admin/usage` rows gain `avg_ms`.
- Dashboard restyle: soft cool-gray, dusty blue, sage and blush palette with deep brown
  and blue-gray for contrast, serif headings, compact buttons; overview band with key
  health and a traffic chart, KPI ledger, per-alias key pips, favicon.

## 0.2.0

- Embeddings (`/v1/embeddings`, `embed()`) and image generation
  (`/v1/images/generations`, `image()`).
- Native Anthropic adapter with tools, images and streaming.
- Any API with a key: custom auth styles (`header:`, `query:`, `none`) and raw
  passthrough (`/proxy/{alias}/...`, `request()`).
- More providers: together, xai, fireworks, cohere, perplexity, ollama,
  elevenlabs, replicate, stability, deepgram.
- Key pool with cooldowns from `Retry-After`, rest period for rejected keys, health stats.
- Per-project tokens, stored hashed, optionally limited to some aliases; admin tokens.
- FastAPI server with request IDs, usage counters, admin API and web dashboard.
- Docker image, CI, `masterapi keygen`.
- Vaults from 0.1 are upgraded automatically.

## 0.1.0

- Encrypted vault, named aliases with several keys, OpenAI-compatible chat, local server.
