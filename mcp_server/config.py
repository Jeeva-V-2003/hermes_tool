"""Shared configuration for HermesVision.

This module is intentionally dependency-light (standard library only at import
time) so that BOTH the MCP server process and the dashboard process can import
it without pulling in heavy GUI / web dependencies.

All paths use ``os.path.expanduser`` so ``~`` is always expanded before use.
"""

from __future__ import annotations

import logging
import os
import sys

# --------------------------------------------------------------------------- #
# Project / config directories
# --------------------------------------------------------------------------- #

# Absolute path to the project root (the directory containing this package).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Per-user HermesVision config directory: ~/.hermesvision
CONFIG_DIR = os.path.expanduser("~/.hermesvision")
ALLOWED_ACTIONS_PATH = os.path.join(CONFIG_DIR, "allowed_actions.json")
LOG_PATH = os.path.join(CONFIG_DIR, "mcp_server.log")

# --------------------------------------------------------------------------- #
# Shared runtime files (read/written by BOTH processes)
#
# The MCP server and the dashboard are separate OS processes. They communicate
# only through these files:
#   * STATE_PATH       - latest screenshot + system info (JSON object)
#   * EVENTS_PATH       - append-only JSON-lines stream of tool events
#   * SCREENSHOT_PATH   - last captured PNG on disk
# --------------------------------------------------------------------------- #

STATE_PATH = "/tmp/hermesvision_state.json"
EVENTS_PATH = "/tmp/hermesvision_events.jsonl"
SCREENSHOT_PATH = "/tmp/hermesvision_screen.png"

# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

DASHBOARD_HOST = os.environ.get("HERMESVISION_DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.environ.get("HERMESVISION_DASHBOARD_PORT", "7860"))

# --------------------------------------------------------------------------- #
# Permission action types
# --------------------------------------------------------------------------- #

ACTION_TYPES = [
    "mouse_click",
    "keyboard_type",
    "file_write",
    "file_delete",
    "run_command",
    "launch_app",
    "browser_navigate",
]

# Sensible defaults: read-only-ish / low-risk actions default to allowed,
# anything that mutates the machine defaults to denied until the user grants it.
DEFAULT_PERMISSIONS = {
    "mouse_click": False,
    "keyboard_type": False,
    "file_write": False,
    "file_delete": False,
    "run_command": False,
    "launch_app": True,
    "browser_navigate": True,
}


def ensure_dirs() -> None:
    """Create the HermesVision config directory if it does not yet exist."""
    os.makedirs(CONFIG_DIR, exist_ok=True)


_logging_configured = False


def setup_logging() -> logging.Logger:
    """Configure logging to a file and to stderr.

    IMPORTANT: the MCP server speaks the protocol over **stdout**, so nothing
    must ever be printed there. All diagnostics go to the log file and stderr.
    """
    global _logging_configured
    logger = logging.getLogger("hermesvision")
    if _logging_configured:
        return logger

    ensure_dirs()
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    try:
        file_handler = logging.FileHandler(LOG_PATH)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception:  # pragma: no cover - logging must never crash the server
        pass

    # Stream handler -> stderr (NEVER stdout).
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    logger.propagate = False
    _logging_configured = True
    return logger


def get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary screen.

    Tries ``mss`` first, then ``pyautogui``, then falls back to a sane default.
    Never raises.
    """
    # Try mss (does not require an X connection to import).
    try:
        import mss  # type: ignore

        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            return int(mon["width"]), int(mon["height"])
    except Exception:
        pass

    try:
        import pyautogui  # type: ignore

        size = pyautogui.size()
        return int(size[0]), int(size[1])
    except Exception:
        pass

    return 1920, 1080
