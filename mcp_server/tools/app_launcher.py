"""Launch Linux apps, run shell commands, and inspect/kill processes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional

from mcp_server.tools.permissions import permission_gate
from dashboard.websocket_manager import emit_tool_call

# Obvious footguns we refuse outright regardless of permission state.
_BLOCKED_SUBSTRINGS = ["rm -rf /", "mkfs"]


def register(mcp) -> None:
    @mcp.tool()
    def launch_app(app_name: str, args: Optional[list[str]] = None) -> str:
        """Launch a Linux application by name, detached (non-blocking).

        e.g. launch_app("gedit"), launch_app("firefox", ["https://example.com"]).
        Requires the 'launch_app' permission. Returns "Launched: <app_name>" or
        an ERROR if the executable is not on PATH.
        """
        args = args or []
        params = {"app_name": app_name, "args": args}
        denied = permission_gate("launch_app")
        if denied:
            return emit_tool_call("launch_app", params, denied)

        exe = shutil.which(app_name)
        if not exe:
            return emit_tool_call(
                "launch_app", params, f"ERROR: app not found on PATH: {app_name}"
            )
        try:
            env = dict(os.environ)
            env.setdefault("DISPLAY", os.environ.get("DISPLAY", ":0"))
            subprocess.Popen(
                [exe, *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # fully detach from our process
                env=env,
            )
            return emit_tool_call("launch_app", params, f"Launched: {app_name}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("launch_app", params, f"ERROR: {exc}")

    @mcp.tool()
    def run_terminal_command(command: str, timeout: int = 30) -> str:
        """Run a shell command and return combined stdout + stderr.

        timeout: max seconds to wait. Requires the 'run_command' permission.
        For safety, commands containing "rm -rf /" or "mkfs" are refused.
        """
        params = {"command": command, "timeout": timeout}
        denied = permission_gate("run_command")
        if denied:
            return emit_tool_call("run_terminal_command", params, denied)

        lowered = command.lower()
        for bad in _BLOCKED_SUBSTRINGS:
            if bad in lowered:
                return emit_tool_call(
                    "run_terminal_command",
                    params,
                    f"ERROR: refused - command contains blocked pattern '{bad}'",
                )
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            out = out.strip() or f"(no output; exit code {proc.returncode})"
            return emit_tool_call("run_terminal_command", params, out)
        except subprocess.TimeoutExpired:
            return emit_tool_call(
                "run_terminal_command", params, f"ERROR: command timed out after {timeout}s"
            )
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("run_terminal_command", params, f"ERROR: {exc}")

    @mcp.tool()
    def list_running_apps() -> str:
        """List currently running processes as JSON: [{pid, name, cpu, mem}, ...].

        Sorted by CPU usage (highest first), top 50 entries.
        """
        try:
            # Put the variable-width command name LAST so a name containing
            # spaces never shifts the numeric columns.
            proc = subprocess.run(
                ["ps", "-eo", "pid,%cpu,%mem,comm", "--sort=-%cpu"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            lines = proc.stdout.strip().splitlines()[1:]  # drop header
            apps = []
            for line in lines[:50]:
                parts = line.split(None, 3)
                if len(parts) < 4:
                    continue
                pid, cpu, mem, name = parts
                try:
                    apps.append(
                        {
                            "pid": int(pid),
                            "name": name,
                            "cpu": float(cpu),
                            "mem": float(mem),
                        }
                    )
                except ValueError:
                    continue  # skip any malformed row defensively
            return emit_tool_call("list_running_apps", {}, json.dumps(apps))
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("list_running_apps", {}, f"ERROR: {exc}")

    @mcp.tool()
    def kill_app(name_or_pid: str) -> str:
        """Kill a process by numeric PID or by process name.

        Requires the 'run_command' permission. Returns "Killed: <name_or_pid>".
        """
        params = {"name_or_pid": name_or_pid}
        denied = permission_gate("run_command")
        if denied:
            return emit_tool_call("kill_app", params, denied)
        try:
            if name_or_pid.isdigit():
                os.kill(int(name_or_pid), 15)  # SIGTERM
                return emit_tool_call("kill_app", params, f"Killed: {name_or_pid}")
            # By name -> pkill
            proc = subprocess.run(
                ["pkill", "-f", name_or_pid], capture_output=True, text=True, timeout=10
            )
            if proc.returncode in (0, 1):  # 1 = no processes matched
                if proc.returncode == 1:
                    return emit_tool_call(
                        "kill_app", params, f"ERROR: no process matched: {name_or_pid}"
                    )
                return emit_tool_call("kill_app", params, f"Killed: {name_or_pid}")
            return emit_tool_call(
                "kill_app", params, f"ERROR: pkill failed: {proc.stderr.strip()}"
            )
        except ProcessLookupError:
            return emit_tool_call("kill_app", params, f"ERROR: no such PID: {name_or_pid}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("kill_app", params, f"ERROR: {exc}")
