import json

import pytest

from masterapi.connect import write_json_config, write_toml_config

CMD = ["C:\\Tools\\masterapi.exe"]


def test_json_config_keeps_other_servers_and_replaces_ours(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}, "masterapi": {"command": "old"}},
                                "theme": "dark"}))
    write_json_config(path, CMD, ["mcp", "--alias", "gemini"])
    data = json.loads(path.read_text())
    assert data["theme"] == "dark"
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["masterapi"] == {"command": CMD[0], "args": ["mcp", "--alias", "gemini"]}


def test_json_config_created_and_invalid_json_untouched(tmp_path):
    fresh = tmp_path / "new" / "mcp.json"
    write_json_config(fresh, ["python", "-m", "masterapi"], ["mcp"])
    assert json.loads(fresh.read_text())["mcpServers"]["masterapi"]["args"] == ["-m", "masterapi", "mcp"]

    broken = tmp_path / "broken.json"
    broken.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        write_json_config(broken, CMD, ["mcp"])
    assert broken.read_text() == "{ not json"


def test_toml_config_replaces_only_our_table(tmp_path):
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+

    path = tmp_path / "config.toml"
    path.write_text('model = "o3"\n\n[mcp_servers.masterapi]\ncommand = "old"\nargs = []\n\n'
                    '[mcp_servers.other]\ncommand = "x"\n')
    write_toml_config(path, CMD, ["mcp"])
    write_toml_config(path, CMD, ["mcp"])  # idempotent
    data = tomllib.loads(path.read_text())
    assert data["model"] == "o3"
    assert data["mcp_servers"]["other"] == {"command": "x"}
    assert data["mcp_servers"]["masterapi"] == {"command": CMD[0], "args": ["mcp"]}
    assert path.read_text().count("[mcp_servers.masterapi]") == 1
