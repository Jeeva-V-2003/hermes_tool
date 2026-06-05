"""File read/write/list/search tools."""

from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import shutil
import stat

from mcp_server.tools.permissions import permission_gate
from dashboard.websocket_manager import emit_tool_call

_MAX_BYTES = 100 * 1024  # 100 KB


def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{num}B"


def register(mcp) -> None:
    @mcp.tool()
    def read_file(path: str) -> str:
        """Read and return a text file's contents.

        Binary files return "BINARY FILE - cannot display as text". Files larger
        than 100KB return the first 100KB with a truncation warning appended.
        """
        params = {"path": path}
        try:
            full = _expand(path)
            if not os.path.exists(full):
                return emit_tool_call("read_file", params, f"ERROR: file not found: {full}")
            if os.path.isdir(full):
                return emit_tool_call("read_file", params, f"ERROR: path is a directory: {full}")

            size = os.path.getsize(full)
            with open(full, "rb") as fh:
                raw = fh.read(_MAX_BYTES)

            if b"\x00" in raw:
                return emit_tool_call("read_file", params, "BINARY FILE - cannot display as text")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return emit_tool_call("read_file", params, "BINARY FILE - cannot display as text")

            if size > _MAX_BYTES:
                text += (
                    f"\n\n[WARNING: file is {_human_size(size)}; showing first "
                    f"{_human_size(_MAX_BYTES)} only]"
                )
            return emit_tool_call("read_file", params, text)
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("read_file", params, f"ERROR: {exc}")

    @mcp.tool()
    def write_file(path: str, content: str, mode: str = "overwrite") -> str:
        """Write content to a file. mode: "overwrite" | "append".

        Parent directories are created as needed. Requires the 'file_write'
        permission.
        """
        params = {"path": path, "mode": mode, "bytes": len(content)}
        denied = permission_gate("file_write")
        if denied:
            return emit_tool_call("write_file", params, denied)
        try:
            full = _expand(path)
            parent = os.path.dirname(full)
            if parent:
                os.makedirs(parent, exist_ok=True)
            file_mode = "a" if mode == "append" else "w"
            with open(full, file_mode, encoding="utf-8") as fh:
                fh.write(content)
            return emit_tool_call("write_file", params, f"Written to {full}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("write_file", params, f"ERROR: {exc}")

    @mcp.tool()
    def list_directory(path: str = "~", show_hidden: bool = False) -> str:
        """List a directory's contents with file sizes and types.

        Returns one entry per line. Set show_hidden to include dotfiles.
        """
        params = {"path": path, "show_hidden": show_hidden}
        try:
            full = _expand(path)
            if not os.path.isdir(full):
                return emit_tool_call("list_directory", params, f"ERROR: not a directory: {full}")
            entries = sorted(os.listdir(full))
            lines = [f"Contents of {full}:"]
            count = 0
            for name in entries:
                if not show_hidden and name.startswith("."):
                    continue
                child = os.path.join(full, name)
                try:
                    if os.path.isdir(child):
                        lines.append(f"  [DIR]  {name}/")
                    else:
                        size = os.path.getsize(child)
                        lines.append(f"  [FILE] {name}  ({_human_size(size)})")
                    count += 1
                except OSError:
                    lines.append(f"  [????] {name}")
            lines.append(f"({count} item(s))")
            return emit_tool_call("list_directory", params, "\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("list_directory", params, f"ERROR: {exc}")

    @mcp.tool()
    def search_files(directory: str, pattern: str, max_results: int = 20) -> str:
        """Recursively glob for files under a directory matching a pattern.

        pattern uses shell glob syntax (e.g. "*.py", "report*"). Returns a JSON
        array of matching absolute paths (up to max_results).
        """
        params = {"directory": directory, "pattern": pattern, "max_results": max_results}
        try:
            base = _expand(directory)
            if not os.path.isdir(base):
                return emit_tool_call("search_files", params, f"ERROR: not a directory: {base}")
            matches = glob.glob(os.path.join(base, "**", pattern), recursive=True)
            matches = matches[: max(0, max_results)]
            return emit_tool_call("search_files", params, json.dumps(matches))
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("search_files", params, f"ERROR: {exc}")

    @mcp.tool()
    def delete_file(path: str) -> str:
        """Delete a file or an EMPTY directory.

        Requires the 'file_delete' permission. Non-empty directories are
        refused for safety.
        """
        params = {"path": path}
        denied = permission_gate("file_delete")
        if denied:
            return emit_tool_call("delete_file", params, denied)
        try:
            full = _expand(path)
            if not os.path.exists(full):
                return emit_tool_call("delete_file", params, f"ERROR: not found: {full}")
            if os.path.isdir(full):
                if os.listdir(full):
                    return emit_tool_call(
                        "delete_file", params, f"ERROR: directory not empty: {full}"
                    )
                os.rmdir(full)
            else:
                os.remove(full)
            return emit_tool_call("delete_file", params, f"Deleted: {full}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("delete_file", params, f"ERROR: {exc}")

    @mcp.tool()
    def get_file_info(path: str) -> str:
        """Return JSON metadata for a path: size, created, modified, permissions, type."""
        params = {"path": path}
        try:
            full = _expand(path)
            if not os.path.exists(full):
                return emit_tool_call("get_file_info", params, f"ERROR: not found: {full}")
            st = os.stat(full)
            if os.path.isdir(full):
                ftype = "directory"
            elif os.path.islink(full):
                ftype = "symlink"
            elif os.path.isfile(full):
                ftype = "file"
            else:
                ftype = "other"
            info = {
                "path": full,
                "type": ftype,
                "size": st.st_size,
                "size_human": _human_size(st.st_size),
                "created": _dt.datetime.fromtimestamp(st.st_ctime).isoformat(),
                "modified": _dt.datetime.fromtimestamp(st.st_mtime).isoformat(),
                "permissions": stat.filemode(st.st_mode),
                "permissions_octal": oct(st.st_mode & 0o777),
            }
            return emit_tool_call("get_file_info", params, json.dumps(info, indent=2))
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("get_file_info", params, f"ERROR: {exc}")
