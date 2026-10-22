"""`masterapi` command line: manage named keys and tokens, test aliases, run the server."""

import argparse
import getpass
import logging
import sys
from pathlib import Path

from . import __version__
from .client import MasterAPI, MasterAPIError
from .keypool import mask
from .providers import CHAT, EMBEDDINGS, IMAGES, OPERATIONS, PROVIDERS, provider_for
from .vault import Vault, VaultError


def _read_keys(keys_file: str | None) -> list[str]:
    """Keys come from a file (one per line), piped stdin, or a hidden prompt.
    Never from argv, which ends up in shell history."""
    if keys_file:
        text = Path(keys_file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        keys = []
        while key := getpass.getpass("Paste API key (blank line to finish): ").strip():
            keys.append(key)
        return keys
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _models(a) -> dict:
    return {CHAT: a.model, EMBEDDINGS: a.embed_model, IMAGES: a.image_model}


def _overrides(a) -> dict:
    caps = None if a.cap is None else [c.strip() for c in a.cap.split(",") if c.strip()]
    headers = None
    if a.header:
        headers = {}
        for item in a.header:
            k, sep, v = item.partition("=")
            if not sep:
                raise ValueError(f"--header must be NAME=VALUE, got '{item}'")
            headers[k.strip()] = v.strip()
    return {"base_url": a.base_url, "adapter": a.adapter, "auth": a.auth, "capabilities": caps, "headers": headers}


def cmd_add(vault: Vault, a) -> None:
    overrides = _overrides(a)
    draft = {"provider": a.provider, **{k: v for k, v in overrides.items() if v}}
    keys = _read_keys(a.keys_file) if provider_for(draft).needs_key else []
    vault.add(a.name, a.provider, keys, models=_models(a), force=a.force, **overrides)
    print(f"saved '{a.name}' ({a.provider}, {len(keys)} key(s))")


def cmd_set(vault: Vault, a) -> None:
    vault.update(a.name, models=_models(a), **_overrides(a))
    print(f"updated '{a.name}'")


def cmd_add_keys(vault: Vault, a) -> None:
    added = vault.add_keys(a.name, _read_keys(a.keys_file))
    print(f"added {added} new key(s) to '{a.name}' ({len(vault.get(a.name)['keys'])} total)")


def cmd_remove_key(vault: Vault, a) -> None:
    print(f"removed {vault.remove_key(a.name, ending=a.ending)} key(s) from '{a.name}'")


def cmd_list(vault: Vault, a) -> None:
    aliases = vault.aliases()
    if not aliases:
        print("no aliases yet; add one with `masterapi add NAME -p PROVIDER`")
    for name, al in sorted(aliases.items()):
        try:
            caps = ",".join(provider_for(al).capabilities) or "raw"
        except ValueError as e:
            caps = f"invalid: {e}"
        models = " ".join(f"{op}={m}" for op, m in al.get("models", {}).items()) or "-"
        keys = ", ".join(mask(k) for k in al["keys"]) or "-"
        print(f"{name:18} {al['provider']:11} [{caps}]  {models}  keys[{len(al['keys'])}]: {keys}")


def cmd_remove(vault: Vault, a) -> None:
    vault.remove(a.name)
    print(f"removed '{a.name}'")


def cmd_providers(vault: Vault, a) -> None:
    for name, p in PROVIDERS.items():
        caps = ",".join(p.capabilities) or "raw"
        print(f"{name:11} {p.adapter:9} {p.auth:32} [{caps}]  {p.base_url}")
    print("custom      any HTTP API: --provider custom --base-url URL [--adapter openai|anthropic|http] [--auth ...]")


def cmd_test(vault: Vault, a) -> None:
    api = MasterAPI(vault)
    if a.op == CHAT:
        print(api.chat(a.target, a.prompt or "Say hi in five words."))
    elif a.op == EMBEDDINGS:
        vectors = api.embed(a.target, a.prompt or "hello world")
        print(f"{len(vectors)} vector(s), {len(vectors[0])} dimensions")
    else:
        for item in api.image(a.target, a.prompt or "a small red fox, watercolor"):
            print(item.get("url") or f"base64 image, {len(item.get('b64_json', ''))} chars")


def cmd_token(vault: Vault, a) -> None:
    if a.token_command == "create":
        token = vault.create_token(a.name, a.alias, a.admin)
        print(f"token '{a.name}' (shown once, store it safely):\n{token}")
    elif a.token_command == "list":
        for t in vault.list_tokens():
            scope = ",".join(t["aliases"]) if t["aliases"] else "all aliases"
            print(f"{t['name']:18} {'admin' if t['admin'] else 'client':6} {scope:30} created {t['created']}")
    else:
        vault.revoke_token(a.name)
        print(f"revoked '{a.name}'")


def cmd_keygen(vault: Vault, a) -> None:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())


def cmd_serve(vault: Vault, a) -> None:
    from .server import serve
    serve(a.host, a.port, MasterAPI(vault), a.log_level)


def cmd_mcp(vault: Vault, a) -> None:
    from .mcp_server import build_mcp
    # stdout carries the MCP protocol; everything else goes to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    mcp = build_mcp(MasterAPI(vault), aliases=a.alias, mode=a.mode, output_dir=a.output_dir, timeout=a.timeout)
    mcp.run("stdio")


def _mcp_args(a) -> list[str]:
    args = ["mcp"]
    for alias in a.alias or []:
        args += ["--alias", alias]
    if getattr(a, "mode", "auto") != "auto":
        args += ["--mode", a.mode]
    return args


def _connect_agents(chosen, args: list[str]) -> None:
    from .connect import connect
    for agent in chosen:
        try:
            print(f"  ok      {agent.label}: {connect(agent, args)}")
        except (OSError, RuntimeError, ValueError) as e:
            print(f"  failed  {agent.label}: {e}")


def cmd_connect(vault: Vault, a) -> None:
    from .connect import agents
    known = {agent.key: agent for agent in agents()}
    if a.list:
        for agent in known.values():
            print(f"{agent.key:15} {agent.label:15} {'found' if agent.detected else 'not found'}")
        return
    unknown = set(a.agents) - set(known)
    if unknown:
        raise ValueError(f"unknown agent {sorted(unknown)}; choose from {', '.join(known)}")
    chosen = [known[k] for k in a.agents] if a.agents else [ag for ag in known.values() if ag.detected]
    if not chosen:
        print(f"No supported agent found. Name one explicitly: {', '.join(known)}")
        return
    _connect_agents(chosen, _mcp_args(a))
    print("Restart the agent (or start a new session) to load MasterAPI.")


# Suggested default chat models for the setup wizard; any model id works.
SUGGESTED_MODELS = {
    "openai": "gpt-4o-mini", "gemini": "gemini-2.5-flash", "anthropic": "claude-sonnet-4-5",
    "openrouter": "openai/gpt-4o-mini", "groq": "llama-3.3-70b-versatile", "mistral": "mistral-small-latest",
    "deepseek": "deepseek-chat", "ollama": "llama3.2",
}


def _ask(question: str, default: bool) -> bool:
    try:
        answer = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer.startswith("y")


def _prompt(question: str, default: str = "") -> str:
    try:
        answer = input(f"{question}{f' [{default}]' if default else ''}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def _add_interactive(vault: Vault) -> str | None:
    names = [*PROVIDERS, "custom"]
    print("Providers: " + ", ".join(names))
    provider = _prompt("Provider", "gemini").lower()
    if provider not in names:
        print(f"  unknown provider '{provider}'")
        return None
    name = _prompt("Name your projects will use", provider)
    base_url = _prompt("Base URL of the API") if provider == "custom" else None
    if provider == "custom" and not base_url:
        print("  a custom provider needs a base URL")
        return None
    spec = provider_for({"provider": provider, "base_url": base_url})
    model = _prompt("Default chat model", SUGGESTED_MODELS.get(provider, "")) if CHAT in spec.capabilities else ""
    keys = []
    if spec.needs_key:
        print("Paste one key per prompt (input is hidden). Several keys spread the load.")
        while key := getpass.getpass("API key (blank to finish): ").strip():
            keys.append(key)
    try:
        vault.add(name, provider, keys, models={CHAT: model}, base_url=base_url)
    except VaultError as e:
        print(f"  not saved: {e}")
        return None
    print(f"  saved '{name}' with {len(keys)} key(s)")
    return name


def cmd_setup(vault: Vault, a) -> None:
    from .codemode import find_deno
    from .connect import agents

    print(f"MasterAPI {__version__} setup")
    print()
    aliases = vault.aliases()
    print(f"Vault:     {vault.path} ({len(aliases)} aliases)")
    print("Code Mode: " + ("ready (Deno found)" if find_deno() else
                           "off, Deno not found. Agents get plain tools until you install it: https://deno.com"))
    print()

    added = None
    if _ask("Add an API key now?", default=not aliases):
        while True:
            added = _add_interactive(vault) or added
            if not _ask("Add another?", default=False):
                break
    if added and _ask(f"Send a test message through '{added}'?", default=True):
        try:
            print("  reply:", MasterAPI(vault).chat(added, "Say hi in five words."))
        except MasterAPIError as e:
            print(f"  failed: {e}")

    found = [agent for agent in agents() if agent.detected]
    print()
    if found and _ask(f"Connect MasterAPI to {', '.join(ag.label for ag in found)}?", default=True):
        _connect_agents(found, ["mcp"])
    elif not found:
        print("No coding agent found. Later: masterapi connect claude|cursor|codex")

    print()
    print("Done. Next:")
    print("  masterapi add NAME -p PROVIDER   add more keys (masterapi providers lists them)")
    print("  masterapi serve                  dashboard and OpenAI-compatible API")
    print("  Restart your coding agent and ask it to use masterapi.")


def _alias_options(s: argparse.ArgumentParser) -> None:
    s.add_argument("-m", "--model", help="default chat model")
    s.add_argument("--embed-model", help="default embeddings model")
    s.add_argument("--image-model", help="default image model")
    s.add_argument("--base-url", help="API endpoint (required for --provider custom)")
    s.add_argument("--adapter", help="request format: openai, anthropic or http (raw only)")
    s.add_argument("--auth", help="bearer | none | header:NAME[=TEMPLATE] | query:NAME")
    s.add_argument("--cap", help=f"comma list of {','.join(OPERATIONS)}")
    s.add_argument("--header", action="append", help="extra header NAME=VALUE (repeatable)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="masterapi", description="Store named API keys and call any model by name.")
    p.add_argument("--version", action="version", version=f"masterapi {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("add", help="create a named alias with one or more keys")
    s.add_argument("name")
    s.add_argument("-p", "--provider", required=True, help="see `masterapi providers`, or 'custom'")
    _alias_options(s)
    s.add_argument("-f", "--keys-file", help="file with one key per line (bulk import)")
    s.add_argument("--force", action="store_true", help="replace an existing alias")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("set", help="change an alias's models or settings ('' clears a field)")
    s.add_argument("name")
    _alias_options(s)
    s.set_defaults(func=cmd_set)

    s = sub.add_parser("add-keys", help="append more keys to an alias")
    s.add_argument("name")
    s.add_argument("-f", "--keys-file")
    s.set_defaults(func=cmd_add_keys)

    s = sub.add_parser("remove-key", help="remove keys ending with the given characters")
    s.add_argument("name")
    s.add_argument("ending", help="last 4+ characters of the key, as shown by `list`")
    s.set_defaults(func=cmd_remove_key)

    sub.add_parser("list", help="show aliases (keys masked)").set_defaults(func=cmd_list)

    s = sub.add_parser("remove", help="delete an alias and its keys")
    s.add_argument("name")
    s.set_defaults(func=cmd_remove)

    sub.add_parser("providers", help="list built-in providers").set_defaults(func=cmd_providers)

    s = sub.add_parser("test", help="send a test request through an alias")
    s.add_argument("target", help="alias or alias:model")
    s.add_argument("prompt", nargs="?")
    s.add_argument("--op", choices=OPERATIONS, default=CHAT)
    s.set_defaults(func=cmd_test)

    s = sub.add_parser("token", help="manage server access tokens")
    tsub = s.add_subparsers(dest="token_command", required=True)
    t = tsub.add_parser("create", help="create a token (one per project is a good habit)")
    t.add_argument("name")
    t.add_argument("--alias", action="append", help="limit the token to this alias (repeatable)")
    t.add_argument("--admin", action="store_true", help="allow the admin API and dashboard")
    tsub.add_parser("list")
    t = tsub.add_parser("revoke")
    t.add_argument("name")
    s.set_defaults(func=cmd_token)

    s = sub.add_parser("setup", help="guided first run: add keys, connect coding agents")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("connect", help="register the MCP server with coding agents")
    s.add_argument("agents", nargs="*", help="claude, cursor, codex, claude-desktop, windsurf (default: all found)")
    s.add_argument("--alias", action="append", help="only expose this alias (repeatable)")
    s.add_argument("--mode", choices=["auto", "code", "tools"], default="auto")
    s.add_argument("--list", action="store_true", help="show supported agents and which are installed")
    s.set_defaults(func=cmd_connect)

    s = sub.add_parser("mcp", help="run an MCP server (stdio) for coding agents")
    s.add_argument("--alias", action="append", help="only expose this alias (repeatable)")
    s.add_argument("--mode", choices=["auto", "code", "tools"], default="auto",
                   help="code: one run_code tool in a Deno sandbox; tools: one tool per action; "
                        "auto: code when Deno is installed")
    s.add_argument("--output-dir", default="masterapi-outputs", help="where generated images and files are saved")
    s.add_argument("--timeout", type=float, default=60, help="seconds per run_code call")
    s.set_defaults(func=cmd_mcp)

    sub.add_parser("keygen", help="print a new vault encryption key for MASTERAPI_KEY").set_defaults(func=cmd_keygen)

    s = sub.add_parser("serve", help="run the gateway server and dashboard")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    s.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command not in ("serve", "mcp"):
        # Per-key rotation warnings are for server logs; CLI errors already say what failed.
        logging.getLogger("masterapi").setLevel(logging.ERROR)
    try:
        args.func(Vault(), args)
    except (VaultError, MasterAPIError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
