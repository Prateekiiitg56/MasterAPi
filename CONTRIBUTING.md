# Contributing

## Setup

```bash
git clone https://github.com/Prateekiiitg56/MasterAPi
cd MasterAPi
pip install -e ".[dev]"
python -m pytest
ruff check .
```

Tests never touch your real vault or keyring: the `vault` fixture uses a temp
folder and a throwaway `MASTERAPI_KEY`, and upstream providers are mocked with
`httpx.MockTransport`.

## Add a provider

If the provider has an OpenAI-compatible API, it is one entry in
`masterapi/providers/__init__.py`:

```python
"newprovider": Provider("https://api.newprovider.com/v1", capabilities=(CHAT, EMBEDDINGS)),
```

Set `auth=` if the key is not sent as a Bearer token, and `adapter="http"` with
`capabilities=()` for APIs that only make sense as raw passthrough.

A provider with its own request format needs an adapter in
`masterapi/adapters/`. Adapters do no I/O: they map an OpenAI-format body to the
provider's request, and its response (and stream events) back. See
`adapters/anthropic.py` and `tests/test_anthropic.py`.

## Code Mode

The sandbox API lives in two places that must match: `masterapi/codemode/runner.ts`
(the `masterapi` object agents call) and `Bindings` in `masterapi/codemode/__init__.py`
(the host side). The TypeScript declaration shown to agents is in `masterapi/mcp_server.py`.
Code Mode tests skip when Deno is not installed.

## Pull requests

- One change per PR, with a test.
- Never log, print or return a full key or token.
- Update `CHANGELOG.md` under "Unreleased".
