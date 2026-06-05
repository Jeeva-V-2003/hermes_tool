/* HermesVision dashboard front-end.
 * Connects to /ws, renders the live screen feed, tool log, permission toggles
 * and system info. Permission toggles hit the REST API immediately. */

(function () {
  "use strict";

  const MAX_LOG = 50;
  const ACTIONS = [
    "mouse_click",
    "keyboard_type",
    "file_write",
    "file_delete",
    "run_command",
    "launch_app",
    "browser_navigate",
  ];

  const $ = (id) => document.getElementById(id);
  const els = {
    statusBox: $("status"),
    statusText: $("status-text"),
    screen: $("screen"),
    screenEmpty: $("screen-empty"),
    screenMeta: $("screen-meta"),
    log: $("log"),
    perms: $("perms"),
    clearLog: $("clear-log"),
    iScreen: $("i-screen"),
    iOs: $("i-os"),
    iDisplay: $("i-display"),
    iPython: $("i-python"),
    iUptime: $("i-uptime"),
    iLastTool: $("i-lasttool"),
  };

  let ws = null;
  let reconnectTimer = null;

  // ----------------------------- screen ----------------------------------- //
  function setScreen(b64) {
    if (!b64) return;
    els.screen.src = "data:image/png;base64," + b64;
    els.screen.style.display = "block";
    els.screenEmpty.style.display = "none";
    const now = new Date().toLocaleTimeString();
    els.screenMeta.textContent = "updated " + now;
  }

  // ------------------------------ log ------------------------------------- //
  function classify(ev) {
    if (ev.type === "permission_request" || ev.type === "permission_changed")
      return "warn";
    if (ev.tool === "check_permission") return "warn";
    if (ev.error) return "err";
    if (typeof ev.result === "string" && ev.result.indexOf("ERROR:") === 0)
      return "err";
    return "ok";
  }

  function fmtTime(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    return d.toLocaleTimeString();
  }

  function addLog(ev) {
    const li = document.createElement("li");
    li.className = classify(ev);

    let title = ev.tool || ev.type || "event";
    let params = "";
    let result = "";

    if (ev.type === "permission_request") {
      title = "permission_request";
      params = "action: " + ev.action_type;
    } else if (ev.type === "permission_changed") {
      title = "permission_changed";
      params = ev.action_type + " -> " + (ev.allowed ? "ALLOWED" : "DENIED");
    } else {
      if (ev.params && Object.keys(ev.params).length)
        params = JSON.stringify(ev.params);
      if (ev.result != null) result = String(ev.result);
    }

    const row = document.createElement("div");
    row.className = "row";
    const tool = document.createElement("span");
    tool.className = "tool";
    tool.textContent = title;
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = fmtTime(ev.ts);
    row.appendChild(tool);
    row.appendChild(time);
    li.appendChild(row);

    if (params) {
      const p = document.createElement("div");
      p.className = "params";
      p.textContent = params;
      li.appendChild(p);
    }
    if (result) {
      const r = document.createElement("div");
      r.className = "result";
      r.textContent = result.length > 240 ? result.slice(0, 240) + "…" : result;
      li.appendChild(r);
    }

    els.log.insertBefore(li, els.log.firstChild);
    while (els.log.children.length > MAX_LOG)
      els.log.removeChild(els.log.lastChild);
  }

  // -------------------------- permissions --------------------------------- //
  function renderPerms(perms) {
    els.perms.innerHTML = "";
    ACTIONS.forEach((action) => {
      const row = document.createElement("div");
      row.className = "perm-row";

      const name = document.createElement("span");
      name.className = "perm-name";
      name.textContent = action;

      const label = document.createElement("label");
      label.className = "switch";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!perms[action];
      input.addEventListener("change", () => togglePerm(action, input));
      const slider = document.createElement("span");
      slider.className = "slider";
      label.appendChild(input);
      label.appendChild(slider);

      row.appendChild(name);
      row.appendChild(label);
      els.perms.appendChild(row);
    });
  }

  function togglePerm(action, input) {
    const verb = input.checked ? "grant" : "revoke";
    fetch("/api/perms/" + action + "/" + verb, { method: "POST" })
      .then((r) => r.json())
      .then((perms) => renderPerms(perms))
      .catch(() => {
        input.checked = !input.checked; // revert on failure
      });
  }

  // -------------------------- system info --------------------------------- //
  function fmtUptime(s) {
    s = s || 0;
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return (h ? h + "h " : "") + (m ? m + "m " : "") + sec + "s";
  }

  function renderInfo(info) {
    if (!info) return;
    els.iScreen.textContent = info.screen_width + " × " + info.screen_height;
    els.iOs.textContent = info.os || "—";
    els.iDisplay.textContent = info.display || "—";
    els.iPython.textContent = info.python || "—";
    els.iUptime.textContent = fmtUptime(info.uptime_seconds);
    els.iLastTool.textContent = info.last_tool || "(none yet)";
  }

  // ------------------------- connection ----------------------------------- //
  function setStatus(live) {
    els.statusBox.className = "status " + (live ? "live" : "dead");
    els.statusText.textContent = live ? "LIVE" : "DISCONNECTED";
  }

  function handle(ev) {
    switch (ev.type) {
      case "init":
        (ev.events || []).forEach(addLog);
        renderPerms(ev.perms || {});
        renderInfo(ev.sysinfo);
        if (ev.screen) setScreen(ev.screen);
        break;
      case "screen_update":
        setScreen(ev.image);
        break;
      case "sysinfo":
        renderInfo(ev.sysinfo);
        break;
      case "tool_called":
      case "permission_request":
      case "permission_changed":
        addLog(ev);
        break;
      default:
        break;
    }
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(proto + "://" + location.host + "/ws");

    ws.onopen = () => setStatus(true);
    ws.onmessage = (m) => {
      try {
        handle(JSON.parse(m.data));
      } catch (e) {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => {
      setStatus(false);
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
  }

  els.clearLog.addEventListener("click", () => (els.log.innerHTML = ""));

  // Initial REST fetches so the page is populated even before the first WS tick.
  fetch("/api/perms").then((r) => r.json()).then(renderPerms).catch(() => {});
  fetch("/api/sysinfo").then((r) => r.json()).then(renderInfo).catch(() => {});
  connect();
})();
