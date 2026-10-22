# Changelog

## Unreleased

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
