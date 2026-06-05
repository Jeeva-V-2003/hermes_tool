#!/usr/bin/env python3
"""Register the HermesVision MCP server into an installed Hermes.

This handles BOTH shapes of Hermes configuration:

  * Modern hermes-agent / hermes_cli: a YAML ``config.yaml`` with a top-level
    ``mcp_servers:`` mapping (e.g. ``~/.hermes/config.yaml``). This is what the
    current Hermes uses. We inject our entry while preserving the rest of the
    file (and always write a timestamped backup first).

  * Legacy / generic MCP clients: a JSON ``mcp_config.json`` with an
    ``mcpServers`` object. We add our entry there.

If no config is found at all, we create a starter ``~/.hermes/config.yaml`` with
just our entry plus instructions.

The MCP server is launched with the project's venv interpreter so it always has
its dependencies, and DISPLAY is captured so GUI tools work under Hermes.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_NAME = "hermesvision"


def _venv_python() -> str:
    candidate = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    return candidate if os.path.exists(candidate) else "python3"


def _main_py() -> str:
    return os.path.join(PROJECT_ROOT, "mcp_server", "main.py")


def _display() -> str:
    return os.environ.get("DISPLAY") or ":0"


def _port() -> str:
    return os.environ.get("HERMESVISION_DASHBOARD_PORT", "7860")


def _entry_dict() -> dict:
    return {
        "command": _venv_python(),
        "args": [_main_py()],
        "env": {
            "DISPLAY": _display(),
            "HERMESVISION_DASHBOARD_PORT": _port(),
        },
        "timeout": 120,
        "connect_timeout": 60,
    }


# --------------------------------------------------------------------------- #
# YAML config.yaml (modern Hermes)
# --------------------------------------------------------------------------- #


def _yaml_block(indent: int) -> str:
    """Render the hermesvision entry as YAML text, indented under mcp_servers."""
    pad = " " * indent
    e = _entry_dict()
    lines = [
        f"{pad}{SERVER_NAME}:",
        f'{pad}  command: "{e["command"]}"',
        f"{pad}  args:",
        f'{pad}    - "{e["args"][0]}"',
        f"{pad}  env:",
        f'{pad}    DISPLAY: "{e["env"]["DISPLAY"]}"',
        f'{pad}    HERMESVISION_DASHBOARD_PORT: "{e["env"]["HERMESVISION_DASHBOARD_PORT"]}"',
        f"{pad}  timeout: {e['timeout']}",
        f"{pad}  connect_timeout: {e['connect_timeout']}",
    ]
    return "\n".join(lines) + "\n"


def _already_present_yaml(text: str) -> bool:
    """Best-effort check whether our server is already configured."""
    try:
        import yaml

        data = yaml.safe_load(text) or {}
        servers = data.get("mcp_servers") or {}
        return isinstance(servers, dict) and SERVER_NAME in servers
    except Exception:
        # Fall back to a crude text search.
        return f"\n  {SERVER_NAME}:" in text and "mcp_servers:" in text


def _backup(path: str) -> str:
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{path}.hermesvision.bak.{stamp}"
    with open(path, "r", encoding="utf-8") as src, open(backup, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    return backup


def inject_yaml(path: str) -> bool:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    if _already_present_yaml(text):
        print(f"✓ '{SERVER_NAME}' is already registered in {path} - nothing to do.")
        return True

    backup = _backup(path)

    lines = text.splitlines(keepends=True)
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        # Insert immediately after a top-level `mcp_servers:` line.
        if not inserted and line.lstrip().startswith("mcp_servers:") and not line.startswith(" "):
            out.append(_yaml_block(indent=2))
            inserted = True

    if not inserted:
        # No mcp_servers key yet: append a fresh top-level block.
        tail = "" if text.endswith("\n") else "\n"
        block = (
            f"{tail}\n"
            "# Added by HermesVision installer\n"
            "mcp_servers:\n"
            f"{_yaml_block(indent=2)}"
        )
        out.append(block)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(out))

    # Validate the result still parses as YAML; restore backup if not.
    try:
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            yaml.safe_load(fh.read())
    except Exception as exc:  # noqa: BLE001
        with open(backup, "r", encoding="utf-8") as src, open(path, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        print(f"ERROR: injection produced invalid YAML ({exc}); restored backup.")
        return False

    print(f"✓ Registered '{SERVER_NAME}' in {path}")
    print(f"  (backup saved to {backup})")
    return True


# --------------------------------------------------------------------------- #
# JSON mcp_config.json (legacy / generic)
# --------------------------------------------------------------------------- #


def inject_json(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    servers = data.setdefault("mcpServers", {})
    if SERVER_NAME in servers:
        print(f"✓ '{SERVER_NAME}' already present in {path} - updating it.")
    servers[SERVER_NAME] = _entry_dict()

    _backup(path) if os.path.exists(path) else None
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(f"✓ Registered '{SERVER_NAME}' in {path}")
    return True


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def find_yaml_config() -> str | None:
    for candidate in (
        os.path.expanduser("~/.hermes/config.yaml"),
        os.path.expanduser("~/.config/hermes/config.yaml"),
        os.path.expanduser("~/hermes/config.yaml"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def find_json_config() -> str | None:
    for candidate in (
        os.path.expanduser("~/.hermes/mcp_config.json"),
        os.path.expanduser("~/hermes/mcp_config.json"),
        os.path.expanduser("~/.config/hermes/mcp_config.json"),
    ):
        if os.path.isfile(candidate):
            return candidate

    # Recursive search of the home directory, max depth 4.
    home = os.path.expanduser("~")
    base_depth = home.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(home):
        depth = root.count(os.sep) - base_depth
        if depth >= 4:
            dirs[:] = []
            continue
        # Skip noisy / irrelevant trees.
        dirs[:] = [d for d in dirs if d not in (".cache", "node_modules", ".git", ".venv")]
        if "mcp_config.json" in files:
            return os.path.join(root, "mcp_config.json")
    return None


def create_starter() -> bool:
    path = os.path.expanduser("~/.hermes/config.yaml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = (
        "# Created by the HermesVision installer.\n"
        "# No existing Hermes config was found, so this starter was created.\n"
        "# If your Hermes uses a different config file, copy the 'mcp_servers'\n"
        "# block below into it.\n\n"
        "mcp_servers:\n"
        f"{_yaml_block(indent=2)}"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"⚠ No existing Hermes config found.")
    print(f"✓ Created starter config at {path}")
    print("  If your Hermes reads a different file, copy the mcp_servers block into it.")
    return True


def main() -> int:
    print("=== HermesVision: registering MCP server into Hermes ===")
    print(f"  project root : {PROJECT_ROOT}")
    print(f"  interpreter  : {_venv_python()}")
    print(f"  server script: {_main_py()}")
    print(f"  DISPLAY      : {_display()}")
    print()

    yaml_path = find_yaml_config()
    if yaml_path:
        return 0 if inject_yaml(yaml_path) else 1

    json_path = find_json_config()
    if json_path:
        return 0 if inject_json(json_path) else 1

    return 0 if create_starter() else 1


if __name__ == "__main__":
    sys.exit(main())
