#!/bin/bash
# =============================================================================
# HermesVision setup script
#
# Installs the HermesVision sidecar:
#   - system deps (tesseract, scrot, xdotool, tk)   [needs sudo]
#   - a self-contained Python venv with all deps     (Ubuntu 24.04 is PEP 668)
#   - Playwright Chromium
#   - default permission allowlist
#   - registers the MCP server into Hermes's config
#   - a user systemd service for the dashboard (best effort)
#
# Re-running is safe (idempotent).
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PROJECT_DIR/.venv"
PY="$VENV/bin/python"
DISPLAY_VALUE="${DISPLAY:-:0}"
DASH_PORT="${HERMESVISION_DASHBOARD_PORT:-7860}"

echo "=== HermesVision Setup ==="
echo "  project : $PROJECT_DIR"
echo "  display : $DISPLAY_VALUE"
echo "  dashboard port: $DASH_PORT"
echo ""

# 1. System dependencies -------------------------------------------------------
echo "[1/7] Installing system dependencies (sudo may prompt)…"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq || true
  sudo apt-get install -y \
    python3-venv python3-dev python3-tk \
    tesseract-ocr scrot xdotool \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2t64 libpango-1.0-0 libcairo2 \
    || echo "  (some apt packages could not be installed; continuing)"
else
  echo "  apt-get not found; please install tesseract-ocr, scrot, xdotool manually."
fi

# 2. Python virtual environment ------------------------------------------------
echo "[2/7] Creating Python virtual environment…"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$PY" -m pip install --upgrade pip -q

# 3. Python dependencies -------------------------------------------------------
echo "[3/7] Installing Python dependencies into the venv…"
"$PY" -m pip install -r "$PROJECT_DIR/requirements.txt"

# 4. Playwright browser --------------------------------------------------------
echo "[4/7] Installing Playwright Chromium…"
"$PY" -m playwright install chromium || echo "  (playwright chromium install failed; browser tools will be unavailable)"

# 5. Config dir + default permissions -----------------------------------------
echo "[5/7] Creating config directory and default permissions…"
mkdir -p "$HOME/.hermesvision"
"$PY" - <<'PYEOF'
import json, os
path = os.path.expanduser('~/.hermesvision/allowed_actions.json')
if not os.path.exists(path):
    defaults = {
        'mouse_click': False,
        'keyboard_type': False,
        'file_write': False,
        'file_delete': False,
        'run_command': False,
        'launch_app': True,
        'browser_navigate': True,
    }
    with open(path, 'w') as fh:
        json.dump(defaults, fh, indent=2)
    print('  created default permissions at', path)
else:
    print('  permissions already exist at', path)
PYEOF

# 6. Register MCP server into Hermes ------------------------------------------
echo "[6/7] Registering HermesVision into Hermes config…"
DISPLAY="$DISPLAY_VALUE" HERMESVISION_DASHBOARD_PORT="$DASH_PORT" \
  "$PY" "$PROJECT_DIR/installer/inject_mcp_config.py"

# 7. Dashboard systemd service (best effort) ----------------------------------
echo "[7/7] Installing dashboard service (user systemd, best effort)…"
if command -v systemctl >/dev/null 2>&1; then
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/hermesvision-dashboard.service" <<EOF
[Unit]
Description=HermesVision Dashboard
After=network.target

[Service]
Environment=DISPLAY=$DISPLAY_VALUE
Environment=HERMESVISION_DASHBOARD_PORT=$DASH_PORT
ExecStart=$PY $PROJECT_DIR/dashboard/app.py
WorkingDirectory=$PROJECT_DIR
Restart=always

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload || true
  systemctl --user enable hermesvision-dashboard || true
  systemctl --user restart hermesvision-dashboard || true
  echo "  dashboard service installed and started."
else
  echo "  systemd not available; start the dashboard manually:"
  echo "    $PY $PROJECT_DIR/dashboard/app.py"
fi

echo ""
echo "✅ HermesVision installed successfully!"
echo "📺 Dashboard : http://localhost:$DASH_PORT"
echo "🚀 Start Hermes normally — the HermesVision tools are now registered."
echo ""
echo "If the dashboard service didn't start, run it manually with:"
echo "    $PY $PROJECT_DIR/dashboard/app.py"
