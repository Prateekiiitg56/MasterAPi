"""Register the MasterAPI MCP server with coding agents in one step.

Each agent keeps its MCP servers in its own place: Claude Code through its CLI,
Cursor / Claude Desktop / Windsurf in a JSON file, Codex in a TOML file. Existing
entries for other servers are left untouched; an existing `masterapi` entry is replaced.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

NAME = "masterapi"


def server_command() -> list[str]:
    """How agents should start the server: the installed `masterapi` command, else this Python."""
    exe = shutil.which("masterapi")
    return [str(Path(exe).resolve())] if exe else [sys.executable, "-m", "masterapi"]


def _appdata() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


@dataclass
class Agent:
    key: str
    label: str
    kind: str  # "claude-cli" | "json" | "toml"
    path: Path | None = None

    @property
    def detected(self) -> bool:
        if self.kind == "claude-cli":
            return shutil.which("claude") is not None
        return self.path.parent.exists()


def agents() -> list[Agent]:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return [
        Agent("claude", "Claude Code", "claude-cli"),
        Agent("cursor", "Cursor", "json", Path.home() / ".cursor" / "mcp.json"),
        Agent("codex", "Codex", "toml", codex_home / "config.toml"),
        Agent("claude-desktop", "Claude Desktop", "json", _appdata() / "Claude" / "claude_desktop_config.json"),
        Agent("windsurf", "Windsurf", "json", Path.home() / ".codeium" / "windsurf" / "mcp_config.json"),
    ]


def write_json_config(path: Path, command: list[str], args: list[str]) -> None:
    data = {}
    if path.exists() and path.read_text(encoding="utf-8").strip():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ValueError(f"{path} is not valid JSON ({e}); fix it or add masterapi by hand") from None
    data.setdefault("mcpServers", {})[NAME] = {"command": command[0], "args": [*command[1:], *args]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_toml_config(path: Path, command: list[str], args: list[str]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    # Drop an existing [mcp_servers.masterapi] table (up to the next table header).
    text = re.sub(r"(?ms)^\[mcp_servers\.masterapi\]\s*$.*?(?=^\[|\Z)", "", text).rstrip()
    # JSON string and array syntax is valid TOML for these values.
    block = (f"[mcp_servers.{NAME}]\ncommand = {json.dumps(command[0])}\n"
             f"args = {json.dumps([*command[1:], *args])}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((text + "\n\n" if text else "") + block, encoding="utf-8")


def connect(agent: Agent, args: list[str], command: list[str] | None = None) -> str:
    """Register with one agent; returns a short description of what changed."""
    command = command or server_command()
    if agent.kind == "claude-cli":
        claude = shutil.which("claude")
        subprocess.run([claude, "mcp", "remove", NAME, "-s", "user"], capture_output=True)
        r = subprocess.run([claude, "mcp", "add", "--scope", "user", NAME, "--", *command, *args],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip() or "claude mcp add failed")
        return "added to user config (all projects)"
    if agent.kind == "json":
        write_json_config(agent.path, command, args)
    else:
        write_toml_config(agent.path, command, args)
    return f"updated {agent.path}"
