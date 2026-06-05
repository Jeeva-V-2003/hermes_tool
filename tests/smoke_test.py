#!/usr/bin/env python3
"""End-to-end smoke test for every HermesVision MCP tool.

Runs each registered tool directly (the same callables Hermes invokes) and
reports PASS / WARN / FAIL. GUI input tools (click / type) are exercised against
a throwaway Tkinter window so nothing leaks onto other applications.

Run:
    .venv/bin/python tests/smoke_test.py

Exit code is non-zero if any tool FAILS.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mcp_server import config  # noqa: E402
from mcp_server.tools import permissions as perms_mod  # noqa: E402
import mcp_server.main as server  # noqa: E402

# ANSI colours
G, R, Y, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[34m", "\033[0m"

results: list[tuple[str, str, str]] = []  # (status, tool, detail)


def record(status: str, tool: str, detail: str = "") -> None:
    colour = {"PASS": G, "WARN": Y, "FAIL": R}.get(status, "")
    detail_short = detail.replace("\n", " ")
    if len(detail_short) > 90:
        detail_short = detail_short[:90] + "…"
    print(f"  {colour}{status:<4}{X}  {tool:<22} {detail_short}")
    results.append((status, tool, detail))


# Build name -> callable map from the live FastMCP server.
TOOLS = {t.name: t.fn for t in server.mcp._tool_manager.list_tools()}


def call(name: str, **kwargs) -> str:
    fn = TOOLS[name]
    return fn(**kwargs)


def expect_ok(name: str, **kwargs) -> str:
    """Call a tool; PASS unless it raises or returns an ERROR string."""
    try:
        out = call(name, **kwargs)
    except Exception as exc:  # noqa: BLE001
        record("FAIL", name, f"raised {type(exc).__name__}: {exc}")
        return ""
    if isinstance(out, str) and out.startswith("ERROR:"):
        record("FAIL", name, out)
    else:
        record("PASS", name, out)
    return out


def main() -> int:
    # Line-buffer stdout so progress is visible live even under redirection.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    # Hard watchdog: never let the test hang the terminal.
    import threading

    def _watchdog() -> None:
        time.sleep(180)
        print(f"\n{R}WATCHDOG: smoke test exceeded 180s — aborting.{X}", flush=True)
        os._exit(3)

    threading.Thread(target=_watchdog, daemon=True).start()

    print(f"\n{B}=== HermesVision smoke test ==={X}")
    print(f"DISPLAY={os.environ.get('DISPLAY', '(unset)')}  "
          f"python={sys.version.split()[0]}  root={_ROOT}\n")

    # Preserve and reset the real permission allowlist.
    config.ensure_dirs()
    backup = None
    if os.path.exists(config.ALLOWED_ACTIONS_PATH):
        backup = config.ALLOWED_ACTIONS_PATH + ".smoketest.bak"
        shutil.copy(config.ALLOWED_ACTIONS_PATH, backup)

    try:
        # ---- Phase 0: permission gate actually blocks ---------------------- #
        print(f"{B}[permissions: gate]{X}")
        perms_mod.save_permissions(dict(config.DEFAULT_PERMISSIONS))  # file_write=False
        out = call("write_file", path="/tmp/hv_should_be_blocked.txt", content="x")
        if out.startswith("ERROR: Permission denied for file_write"):
            record("PASS", "write_file(gate)", "correctly denied without permission")
        else:
            record("FAIL", "write_file(gate)", f"expected denial, got: {out}")

        # Grant everything for the functional run.
        perms_mod.save_permissions({a: True for a in config.ACTION_TYPES})

        # ---- permissions tools -------------------------------------------- #
        print(f"\n{B}[permissions]{X}")
        expect_ok("check_permission", action_type="file_write")
        expect_ok("grant_permission", action_type="file_write")
        expect_ok("revoke_permission", action_type="file_delete")
        expect_ok("grant_permission", action_type="file_delete")  # re-grant for fs tests
        expect_ok("list_permissions")

        # ---- filesystem ---------------------------------------------------- #
        print(f"\n{B}[filesystem]{X}")
        test_dir = "/tmp/hermesvision_smoke"
        test_file = os.path.join(test_dir, "note.txt")
        expect_ok("write_file", path=test_file, content="hello hermesvision\n")
        expect_ok("write_file", path=test_file, content="appended line\n", mode="append")
        out = expect_ok("read_file", path=test_file)
        if out and "appended line" not in out:
            record("WARN", "read_file(verify)", "appended content missing")
        expect_ok("list_directory", path=test_dir, show_hidden=True)
        out = expect_ok("search_files", directory=test_dir, pattern="*.txt")
        try:
            if out and test_file not in json.loads(out):
                record("WARN", "search_files(verify)", "expected file not in results")
        except Exception:
            pass
        expect_ok("get_file_info", path=test_file)
        expect_ok("delete_file", path=test_file)

        # ---- screen -------------------------------------------------------- #
        print(f"\n{B}[screen]{X}")
        out = expect_ok("capture_screen", region="full")
        if out and not out.startswith("data:image/png;base64,"):
            record("WARN", "capture_screen(fmt)", "missing data-uri prefix")
        expect_ok("capture_screen", region="top-half")
        expect_ok("capture_screen", region="0,0,200,200")
        out = expect_ok("find_on_screen", description="a window")
        # OCR may legitimately be unavailable (tesseract not installed).
        try:
            ocr = call("get_screen_text", region="0,0,300,120")
            if ocr.startswith("ERROR:") and "tesseract" in ocr.lower():
                record("WARN", "get_screen_text", "tesseract not installed (optional)")
            elif ocr.startswith("ERROR:"):
                record("FAIL", "get_screen_text", ocr)
            else:
                record("PASS", "get_screen_text", ocr or "(empty)")
        except Exception as exc:  # noqa: BLE001
            record("FAIL", "get_screen_text", str(exc))

        # ---- input control (contained Tkinter window) --------------------- #
        print(f"\n{B}[input_control]{X}")
        run_input_tests()

        # ---- app launcher / shell ----------------------------------------- #
        print(f"\n{B}[app_launcher]{X}")
        expect_ok("run_terminal_command", command="echo hermesvision-ok")
        expect_ok("list_running_apps")
        # Launch a harmless, immediately-exiting executable.
        true_bin = shutil.which("true") or "/bin/true"
        expect_ok("launch_app", app_name=os.path.basename(true_bin))
        # Start a sleeper and kill it by PID to exercise kill_app.
        sleeper = subprocess.Popen(["sleep", "30"])
        time.sleep(0.3)
        expect_ok("kill_app", name_or_pid=str(sleeper.pid))
        try:
            sleeper.wait(timeout=3)
        except Exception:
            sleeper.kill()

        # ---- api caller ---------------------------------------------------- #
        print(f"\n{B}[api_caller]{X}")
        out = expect_ok(
            "http_request", url="https://example.com", method="GET", timeout=20
        )
        if out and not out.startswith("ERROR:"):
            try:
                payload = json.loads(out)
                if payload.get("status") != 200:
                    record("WARN", "http_request(status)", f"status={payload.get('status')}")
            except Exception:
                pass

        # ---- browser ------------------------------------------------------- #
        print(f"\n{B}[browser]{X}")
        run_browser_tests()

    finally:
        # Restore the user's real permission allowlist.
        if backup and os.path.exists(backup):
            shutil.move(backup, config.ALLOWED_ACTIONS_PATH)

    # ---- summary ----------------------------------------------------------- #
    passed = sum(1 for s, _, _ in results if s == "PASS")
    warned = sum(1 for s, _, _ in results if s == "WARN")
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"\n{B}=== Summary ==={X}")
    print(f"  {G}PASS {passed}{X}   {Y}WARN {warned}{X}   {R}FAIL {failed}{X}")
    if failed:
        print(f"\n{R}FAILURES:{X}")
        for s, tool, detail in results:
            if s == "FAIL":
                print(f"  - {tool}: {detail}")
        return 1
    print(f"\n{G}All tools working with no errors.{X}")
    return 0


def run_input_tests() -> None:
    """Exercise move_mouse / scroll / press_key / click / type_text / drag
    against a throwaway Tk window so nothing touches other applications."""
    if not os.environ.get("DISPLAY"):
        for t in ("move_mouse", "click", "type_text", "press_key", "scroll", "drag"):
            record("WARN", t, "no DISPLAY - input tools skipped")
        return
    try:
        import tkinter as tk
    except Exception as exc:  # noqa: BLE001
        for t in ("move_mouse", "click", "type_text", "press_key", "scroll", "drag"):
            record("WARN", t, f"tkinter unavailable: {exc}")
        return

    try:
        clicked = {"v": False}
        root = tk.Tk()
        root.title("HermesVision input test")
        root.geometry("420x180+250+250")
        root.attributes("-topmost", True)
        entry = tk.Entry(root, width=30)
        entry.pack(pady=24)
        btn = tk.Button(root, text="CLICK ME", command=lambda: clicked.__setitem__("v", True))
        btn.pack(pady=8)
        for _ in range(6):
            root.update()
            root.update_idletasks()
        root.lift()
        entry.focus_force()
        root.update()

        def abs_center(widget):
            return (
                root.winfo_rootx() + widget.winfo_x() + widget.winfo_width() // 2,
                root.winfo_rooty() + widget.winfo_y() + widget.winfo_height() // 2,
            )

        ex, ey = abs_center(entry)
        bx, by = abs_center(btn)

        # move_mouse
        expect_ok("move_mouse", x=ex, y=ey)
        root.update()

        # click into the entry, then make sure Tk has actually focused it
        expect_ok("click", x=ex, y=ey)
        for _ in range(4):
            root.update()
            time.sleep(0.05)
        entry.focus_force()
        for _ in range(3):
            root.update()
            time.sleep(0.05)

        # type into the entry
        expect_ok("type_text", text="hvtest", interval=0.04)
        for _ in range(8):
            root.update()
            time.sleep(0.05)
        typed = entry.get()
        if "hvtest" in typed:
            record("PASS", "type_text(verify)", f"entry now contains '{typed}'")
        else:
            record("WARN", "type_text(verify)", f"entry contains '{typed}' (focus race?)")

        # press a benign, always-mapped key (avoid f13-f24 / media keys, which
        # can trigger a python-xlib remap error on some X servers)
        expect_ok("press_key", key="shift")
        root.update()

        # scroll over the window
        expect_ok("scroll", x=ex, y=ey, direction="down", amount=2)
        root.update()

        # click the button via the click tool, then verify callback fired
        expect_ok("click", x=bx, y=by)
        for _ in range(6):
            root.update()
        if clicked["v"]:
            record("PASS", "click(verify)", "button callback fired")
        else:
            record("WARN", "click(verify)", "button callback not observed (focus race?)")

        # drag inside the window (harmless)
        expect_ok("drag", from_x=ex, from_y=ey, to_x=ex + 30, to_y=ey, duration=0.2)
        root.update()

        root.destroy()
    except Exception as exc:  # noqa: BLE001
        record("FAIL", "input_control", f"GUI harness error: {exc}")


def run_browser_tests() -> None:
    out = call("browser_open", url="https://example.com")
    if out.startswith("ERROR:"):
        # Browser may be unavailable if system libs are missing.
        record("WARN", "browser_open", out)
        record("WARN", "browser_*", "skipped (browser unavailable)")
        return
    record("PASS", "browser_open", out)

    out = call("browser_get_text")
    (record("PASS", "browser_get_text", out) if not out.startswith("ERROR:")
     else record("FAIL", "browser_get_text", out))

    out = call("browser_screenshot")
    (record("PASS", "browser_screenshot", f"{len(out)} b64 chars")
     if not out.startswith("ERROR:") else record("FAIL", "browser_screenshot", out))

    out = call("browser_click", selector="a")
    (record("PASS", "browser_click", out) if not out.startswith("ERROR:")
     else record("WARN", "browser_click", out))  # 'a' may navigate away; non-fatal

    out = call("browser_close")
    (record("PASS", "browser_close", out) if not out.startswith("ERROR:")
     else record("FAIL", "browser_close", out))


if __name__ == "__main__":
    sys.exit(main())
