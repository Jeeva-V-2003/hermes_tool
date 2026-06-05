# 🧠 HermesVision

A **sidecar MCP server + live web dashboard** that bolts extra "computer use"
super-powers onto an already-installed [Hermes](https://github.com/hrishi0102/hermes)
desktop AI agent — **without changing a single line of Hermes source code**.

When Hermes starts, it auto-discovers HermesVision through its MCP config and the
new tools (screen capture, mouse/keyboard control, file ops, a headless browser,
app launching, HTTP calls) appear alongside Hermes's built-in tools. A separate
dashboard on `http://localhost:7860` lets you watch the live screen, follow every
tool call, and flip permission switches in real time.

---

## ✨ What you get

| Group | Tools |
|-------|-------|
| **Screen / vision** | `capture_screen`, `get_screen_text` (OCR), `find_on_screen` |
| **Mouse / keyboard** | `move_mouse`, `click`, `type_text`, `press_key`, `scroll`, `drag` |
| **Filesystem** | `read_file`, `write_file`, `list_directory`, `search_files`, `delete_file`, `get_file_info` |
| **Browser (Playwright)** | `browser_open`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_close` |
| **Apps / shell** | `launch_app`, `run_terminal_command`, `list_running_apps`, `kill_app` |
| **HTTP** | `http_request` |
| **Permissions** | `check_permission`, `grant_permission`, `revoke_permission`, `list_permissions` |

**30 tools total.** Every sensitive tool is gated by a permission allowlist so
the agent can't silently click, type, write, delete, run shell commands or
launch apps until you allow it.

---

## ✅ Prerequisites

- **Linux** with a graphical session (X11 recommended; Wayland works via a
  `scrot` fallback for screen capture).
- **Python 3.11+** (tested on 3.12, Ubuntu 24.04).
- An **installed Hermes agent** (this project plugs into it; it does not install
  Hermes for you).
- `sudo` access for the one-time system package install (tesseract, scrot, …).

> **Ubuntu 24.04 note:** the system Python is "externally managed" (PEP 668),
> so HermesVision installs everything into its **own virtual environment**
> (`.venv/`). Nothing is installed into your system Python.

---

## 🚀 Installation

```bash
git clone https://github.com/Jeeva-V-2003/hermes_tool.git
cd hermes_tool
bash setup.sh
```

`setup.sh` will:

1. Install system deps (`tesseract-ocr`, `scrot`, `xdotool`, `python3-tk`, plus
   the shared libs Chromium needs) — *sudo may prompt*.
2. Create a `.venv/` and install all Python dependencies into it.
3. Download the Playwright Chromium build.
4. Create `~/.hermesvision/` and a default permission allowlist.
5. **Register HermesVision into your Hermes config** (see next section).
6. Install a user `systemd` service for the dashboard and start it.

When it finishes:

- Dashboard → **http://localhost:7860**
- Start Hermes **normally** — the HermesVision tools are already registered.

---

## 🔌 How HermesVision launches inside Hermes

HermesVision is a **stdio MCP server**: Hermes spawns it as a subprocess and
talks to it over stdin/stdout. You register it by adding an `mcp_servers` entry
to your Hermes config. **`setup.sh` does this for you**, but here is exactly what
it adds so you can verify or do it by hand.

### Modern Hermes (`~/.hermes/config.yaml`) — the common case

Add (or merge) this block into `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  hermesvision:
    command: "/ABSOLUTE/PATH/TO/hermes_tool/.venv/bin/python"
    args:
      - "/ABSOLUTE/PATH/TO/hermes_tool/mcp_server/main.py"
    env:
      DISPLAY: ":0"                       # use your real display, e.g. ":0" or ":1"
      HERMESVISION_DASHBOARD_PORT: "7860"
    timeout: 120
    connect_timeout: 60
```

> ⚠️ Two things that matter:
> - **`command` must be the venv Python** (`.venv/bin/python`), not bare
>   `python3` — only the venv has the dependencies.
> - **`DISPLAY` must be set** to your actual X display. Hermes only forwards the
>   env vars you list here, so without it the GUI tools can't reach the screen.
>   Find yours with `echo $DISPLAY` (often `:0`, sometimes `:1`).

### Legacy / generic MCP clients (`mcp_config.json`)

If your client uses a JSON `mcp_config.json` with an `mcpServers` object instead,
the installer writes the equivalent JSON entry:

```json
{
  "mcpServers": {
    "hermesvision": {
      "command": "/ABSOLUTE/PATH/TO/hermes_tool/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/hermes_tool/mcp_server/main.py"],
      "env": { "DISPLAY": ":0", "HERMESVISION_DASHBOARD_PORT": "7860" }
    }
  }
}
```

### Register it (or re-register) manually

```bash
# from the project directory, using the venv so PyYAML is available
DISPLAY="$DISPLAY" .venv/bin/python installer/inject_mcp_config.py
```

The injector searches `~/.hermes/config.yaml`, `~/.config/hermes/config.yaml`,
then the legacy `mcp_config.json` locations, then a depth-4 scan of your home
directory. It **backs up** any file before editing it and verifies the result
still parses. If nothing is found it writes a starter `~/.hermes/config.yaml`.

### Confirm Hermes sees it

Start Hermes normally. The HermesVision tools (e.g. `capture_screen`,
`click`, `http_request`) should now be listed among its tools. In hermes_cli you
can check the MCP/tool listing, e.g.:

```bash
hermes tools          # browse configured toolsets / MCP servers
```

If you change `config.yaml` while Hermes is running, restart Hermes (or use its
MCP reload) so it re-spawns the server.

---

## 🖥️ The dashboard

Open **http://localhost:7860**. Four panels:

```
┌─────────────────────────────────────────────────────────────┐
│  🧠 HermesVision Dashboard                       [ LIVE ]    │
├───────────────────────────┬─────────────────────────────────┤
│   📺 LIVE SCREEN          │   🔧 TOOL LOG                   │
│   latest capture,         │   scrolling list of every tool  │
│   refreshed every ~2s     │   call: time, name, params,     │
│                           │   result (green/red/yellow)     │
├───────────────────────────┼─────────────────────────────────┤
│   🔒 PERMISSIONS          │   ℹ️ SYSTEM INFO                │
│   toggle each action      │   screen size, OS, display,     │
│   (calls REST instantly)  │   uptime, last tool called      │
└───────────────────────────┴─────────────────────────────────┘
```

Run the dashboard manually (if you don't use the systemd service):

```bash
.venv/bin/python dashboard/app.py
```

---

## 🏗️ How it works (architecture)

```
                     ┌──────────────────────────────────────────┐
                     │                Hermes agent              │
                     │   (unchanged; reads ~/.hermes/config.yaml)│
                     └───────────────┬──────────────────────────┘
                                     │ spawns as stdio subprocess
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │            HermesVision MCP server (mcp_server/)          │
        │  FastMCP · 30 tools · permission gate · clean stdout      │
        └───────┬───────────────────────────────┬──────────────────┘
                │ append events                  │ write latest screen
                ▼                                ▼
   /tmp/hermesvision_events.jsonl     /tmp/hermesvision_state.json
                │                                │
                │  (polled / read)               │
                ▼                                ▼
        ┌──────────────────────────────────────────────────────────┐
        │           Dashboard process (dashboard/app.py)           │
        │   FastAPI + WebSocket · serves UI on :7860               │
        └──────────────────────────────────────────────────────────┘
                                     ▲
                                     │ WebSocket (screen + tool log)
                              your web browser
```

The MCP server and the dashboard are **separate processes**. They never share
Python objects — they communicate only through two files in `/tmp`
(`websocket_manager.py` is the shared bus used by both). This keeps the MCP
server's stdout clean (it must speak only MCP protocol) and lets the dashboard
restart independently.

```
hermes_tool/
├── setup.sh                     # one-command installer (venv-based)
├── requirements.txt
├── mcp_server/
│   ├── main.py                  # FastMCP entry point (stdio)
│   ├── config.py                # shared paths / settings
│   └── tools/                   # screen, input_control, filesystem,
│                                # browser, app_launcher, api_caller, permissions
├── dashboard/
│   ├── app.py                   # FastAPI + WebSocket on :7860
│   ├── websocket_manager.py     # shared cross-process event/state bus
│   └── static/                  # index.html, style.css, app.js
├── installer/
│   └── inject_mcp_config.py     # registers the server into Hermes
└── tests/
    └── smoke_test.py            # exercises every tool end-to-end
```

---

## 🔒 Permissions

A small allowlist lives at `~/.hermesvision/allowed_actions.json`:

```json
{
  "mouse_click": false,
  "keyboard_type": false,
  "file_write": false,
  "file_delete": false,
  "run_command": false,
  "launch_app": true,
  "browser_navigate": true
}
```

A sensitive tool returns
`ERROR: Permission denied for <action>. Use grant_permission tool to allow.`
until the matching action is allowed. You can change permissions three ways:

- **Dashboard:** flip the toggles in the 🔒 Permissions panel (applies instantly).
- **Ask the agent:** "grant the file_write permission" → it calls
  `grant_permission` / `revoke_permission`.
- **Edit the file** directly and restart nothing — it's read on each call.

| Action type | Gates |
|-------------|-------|
| `mouse_click` | `click`, `drag` |
| `keyboard_type` | `type_text` |
| `file_write` | `write_file` |
| `file_delete` | `delete_file` |
| `run_command` | `run_terminal_command`, `kill_app` |
| `launch_app` | `launch_app` |
| `browser_navigate` | `browser_open` |

---

## 🧰 Tool reference

<details>
<summary><b>Screen / vision</b></summary>

- **`capture_screen(region="full")`** — capture the screen; returns a
  `data:image/png;base64,…` string. `region` = `full` / `top-half` /
  `bottom-half` / `left-half` / `right-half`, or `"x,y,width,height"`. Also saved
  to `/tmp/hermesvision_screen.png` and pushed to the dashboard.
- **`get_screen_text(region="full")`** — OCR the screen (tesseract) and return
  the text.
- **`find_on_screen(description)`** — return `{image, screen_width,
  screen_height, description}` so a vision model can compute coordinates.
</details>

<details>
<summary><b>Mouse / keyboard</b></summary>

- **`move_mouse(x, y)`**, **`click(x, y, button="left", clicks=1)`**,
  **`type_text(text, interval=0.05)`**, **`press_key(key)`** (e.g. `"enter"`,
  `"ctrl+c"`, `"alt+tab"`), **`scroll(x, y, direction="down", amount=3)`**,
  **`drag(from_x, from_y, to_x, to_y, duration=0.5)`**.
- Failsafe: slam the real mouse into the **top-left corner** to abort an action.
</details>

<details>
<summary><b>Filesystem</b></summary>

- **`read_file(path)`** (≤100KB, binary-safe), **`write_file(path, content,
  mode="overwrite"|"append")`**, **`list_directory(path="~",
  show_hidden=False)`**, **`search_files(directory, pattern, max_results=20)`**,
  **`delete_file(path)`** (files or empty dirs), **`get_file_info(path)`**.
</details>

<details>
<summary><b>Browser (headless Chromium)</b></summary>

- **`browser_open(url)`**, **`browser_screenshot()`**,
  **`browser_click(selector)`** (CSS or `text=…`), **`browser_type(selector,
  text)`**, **`browser_get_text()`** (≤10000 chars), **`browser_close()`**.
- One browser instance is reused across calls.
</details>

<details>
<summary><b>Apps / shell / HTTP</b></summary>

- **`launch_app(app_name, args=[])`** (detached), **`run_terminal_command(command,
  timeout=30)`** (blocks `rm -rf /` and `mkfs`), **`list_running_apps()`**,
  **`kill_app(name_or_pid)`**, **`http_request(url, method="GET", headers="{}",
  body="", timeout=30)`**.
</details>

---

## 🧪 Verify the install

Run the bundled smoke test — it exercises **every** tool (input tools run
against a throwaway window so nothing leaks onto your other apps):

```bash
.venv/bin/python tests/smoke_test.py
```

You should see a `PASS`/`WARN`/`FAIL` table ending in
`All tools working with no errors.` (`WARN` is expected for OCR if you skipped
the tesseract install).

---

## 🩺 Troubleshooting (Linux display issues)

| Symptom | Fix |
|---------|-----|
| Tools return `ERROR: no DISPLAY is set` | Add `DISPLAY` to the `env:` block in your Hermes `mcp_servers` entry. Find it with `echo $DISPLAY` (often `:0` or `:1`). |
| `capture_screen` fails on **Wayland** | Install `scrot` (`sudo apt-get install scrot`) — HermesVision falls back to it automatically. Or log in to an **Xorg** session. |
| `get_screen_text` → `tesseract is not installed` | `sudo apt-get install -y tesseract-ocr`. |
| `press_key` with `f13`–`f24` or media keys errors | Those aren't mapped on some X servers (a python-xlib quirk). Use standard keys / combos. |
| `browser_open` → missing library errors | `sudo apt-get install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libgbm1 libasound2t64`, or run `.venv/bin/python -m playwright install-deps chromium`. |
| Dashboard not reachable on :7860 | `systemctl --user status hermesvision-dashboard`, or run it manually: `.venv/bin/python dashboard/app.py`. Change the port with `HERMESVISION_DASHBOARD_PORT`. |
| Hermes doesn't show the new tools | Confirm the `mcp_servers` entry points at `.venv/bin/python` and the absolute `main.py` path, then restart Hermes. Check the MCP server log at `~/.hermesvision/mcp_server.log`. |
| Permission denied errors from tools | Expected until you allow the action — toggle it on the dashboard or ask the agent to `grant_permission`. |

Logs: `~/.hermesvision/mcp_server.log` (server) and the dashboard's stdout.

---

## 🗑️ Uninstall

```bash
systemctl --user disable --now hermesvision-dashboard 2>/dev/null || true
rm -f ~/.config/systemd/user/hermesvision-dashboard.service
# remove the 'hermesvision' entry from ~/.hermes/config.yaml
# (a timestamped backup was saved next to it during install)
rm -rf ~/.hermesvision
```

---

## 📝 Notes

- HermesVision **never modifies Hermes source code**. It only adds one
  `mcp_servers` entry and runs its own processes.
- The MCP server writes nothing to stdout except MCP protocol frames — all logs
  go to `~/.hermesvision/mcp_server.log` and stderr.
- `requirements.txt` adds `python-xlib` (needed by pyautogui on Linux/X11) and
  `PyYAML` (used by the installer to edit `config.yaml`) on top of the core deps.
