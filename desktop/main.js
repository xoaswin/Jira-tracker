// Electron shell for the desktop build. It:
//   * spawns the PyInstaller-packaged backend as a child process,
//   * shows the full app in a normal window (hidden to the tray on close),
//   * runs as a single instance (a second launch just focuses the first),
//   * shows an always-on-top floating button (widget.html) only while the main
//     window is NOT in front of you (hidden when it's focused on screen),
//   * fires an hourly "still on this?" check-in in a small corner card
//     (nudge.html) within your work hours, whether or not a timer is running,
//   * asks for your start-of-day plan (plan.html) and stores it via the backend
//     so the check-in can nudge you against it and it survives with no timer.
//
// The backend only allows CORS from the Vite dev origin, so the small windows
// never fetch it directly: every backend call is proxied here over IPC.
// See PROJECT_CONTEXT.md and backend/packaging/build_backend.ps1.

const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  nativeImage,
  shell,
  ipcMain,
  screen,
} = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");

const BACKEND_PORT = 8756;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const HEALTH_TIMEOUT_MS = 30_000;
const HEALTH_POLL_MS = 400;

// How often to re-evaluate whether a check-in is due (a minute is precise
// enough for an hourly cadence and cheap). The interval itself comes from the
// backend's checkin_interval_minutes; 0 (disabled in the web app) falls back to
// hourly here, since the desktop user explicitly wants the nudge.
const SCHEDULER_TICK_MS = 60_000;
const DEFAULT_INTERVAL_MIN = 60;
const SNOOZE_MS = 10 * 60_000;
const SETTINGS_REFRESH_MS = 5 * 60_000;

// Small square window holding a single round floating button.
const WIDGET_W = 44;
const WIDGET_H = 44;

// Check-in card: compact by default (status line + quick buttons), grows only
// when the user starts chatting with the assistant.
const NUDGE_W = 360;
const NUDGE_H = 196;
const NUDGE_CHAT_H = 460;
const CORNER_MARGIN = 16;

// Must match build.appId in package.json, or packaged Windows toast
// notifications can be mis-branded/unreliable.
app.setAppUserModelId("com.avasoft.jiratracker");

let backendProcess = null;
let mainWindow = null;
let widgetWindow = null;
let nudgeWindow = null;
let planWindow = null;
let tray = null;
let schedulerTimer = null;
let settingsTimer = null;
let quitting = false;

// Scheduler state (wall-clock ms).
let lastNudgeAt = Date.now();
let snoozeUntil = 0;
let settingsCache = null;
let lastPlanPromptDate = null;
// Window position when a manual widget drag began (renderer sends screen deltas).
let widgetDragOrigin = null;

// ---------------------------------------------------------------------------
// Backend process
// ---------------------------------------------------------------------------

function backendExePath() {
  // Packaged: electron-builder's extraResources puts the PyInstaller onedir
  // output under resources/backend/. Dev: fall back to the local PyInstaller
  // output so the packaged backend can be exercised without a full build.
  const packaged = path.join(process.resourcesPath, "backend", "jira-tracker-backend.exe");
  if (app.isPackaged) return packaged;
  return path.join(
    __dirname,
    "..",
    "backend",
    "packaging",
    "dist",
    "jira-tracker-backend",
    "jira-tracker-backend.exe",
  );
}

function spawnBackend() {
  const userData = app.getPath("userData");
  // SQLAlchemy's sqlite:/// URL parsing wants forward slashes even on Windows.
  const dbPath = path.join(userData, "data", "tracker.db").replace(/\\/g, "/");
  const logDir = path.join(userData, "logs");

  backendProcess = spawn(backendExePath(), [], {
    env: {
      ...process.env,
      DATABASE_URL: `sqlite:///${dbPath}`,
      LOG_DIR: logDir,
      SECRET_BACKEND: "auto",
    },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  backendProcess.stdout.on("data", (d) => console.log(`[backend] ${d}`));
  backendProcess.stderr.on("data", (d) => console.error(`[backend] ${d}`));
  // A missing/unspawnable exe (e.g. a dev run before the PyInstaller build)
  // emits 'error'; without a handler Node would throw and crash the shell.
  // Degrade instead: the UI comes up and simply shows "backend not up".
  backendProcess.on("error", (err) => {
    console.error(`[backend] failed to start: ${err.message}`);
    backendProcess = null;
  });
  backendProcess.on("exit", (code) => {
    console.error(`[backend] exited with code ${code}`);
    backendProcess = null;
  });
}

async function waitForHealth() {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/health`);
      if (res.ok) return;
    } catch {
      // backend not up yet, keep polling
    }
    await new Promise((r) => setTimeout(r, HEALTH_POLL_MS));
  }
  throw new Error("backend did not become healthy in time");
}

// ---------------------------------------------------------------------------
// Backend HTTP helpers (main process only; renderers go through IPC)
// ---------------------------------------------------------------------------

async function apiGet(pathname) {
  try {
    const res = await fetch(`${BACKEND_URL}${pathname}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function apiPost(pathname, body) {
  try {
    const res = await fetch(`${BACKEND_URL}${pathname}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function apiPatch(pathname, body) {
  try {
    const res = await fetch(`${BACKEND_URL}${pathname}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// The workday follows settings.timezone (IST by default), never the machine
// clock: the laptop may be set to another zone while Jira work is tracked in IST.
const DEFAULT_TZ = "Asia/Kolkata";

function appTz() {
  const tz = settingsCache && settingsCache.timezone;
  try {
    if (tz) {
      new Intl.DateTimeFormat("en-US", { timeZone: tz });
      return tz;
    }
  } catch {
    /* invalid zone: fall through */
  }
  return DEFAULT_TZ;
}

function zonedParts(ms = Date.now()) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: appTz(),
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const out = {};
  for (const p of fmt.formatToParts(new Date(ms))) {
    if (p.type !== "literal") out[p.type] = Number(p.value);
  }
  return out;
}

function localDate(ms = Date.now()) {
  const p = zonedParts(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

// The status snapshot the widget and nudge render from.
async function composeStatus() {
  const auth = await apiGet("/api/auth/status");
  const connected = !!(auth && auth.connected);
  const date = localDate();
  const hour = zonedParts().hour;
  if (!connected) return { connected, session: null, intention: null, date, hour };
  const [session, intention] = await Promise.all([
    apiGet("/api/sessions/active"),
    apiGet(`/api/plan/intention?date=${date}`),
  ]);
  return { connected, session: session || null, intention: intention || null, date, hour };
}

async function appendNote(text) {
  const date = localDate();
  const existing = await apiGet(`/api/plan/intention?date=${date}`);
  const note = existing && existing.note ? `${existing.note}\n${text}` : text;
  const ticket_keys = existing && existing.ticket_keys ? existing.ticket_keys : [];
  return apiPost("/api/plan/intention", { plan_date: date, note, ticket_keys });
}

// Start of today in the app timezone, as instants for the assistant.
function dayBounds() {
  const now = Date.now();
  const p = zonedParts(now);
  const sinceMidnightMs = ((p.hour * 60 + p.minute) * 60 + p.second) * 1000 + (now % 1000);
  return {
    day_start: new Date(now - sinceMidnightMs).toISOString(),
    day_end: new Date(now).toISOString(),
  };
}

// Proxy the contextual assistant for the conversational nudge. Returns the
// backend's {reply, used_ai, action} (or a safe fallback shape on error).
async function assistantChat(messages) {
  const b = dayBounds();
  const res = await apiPost("/api/assistant/chat", {
    messages,
    day_start: b.day_start,
    day_end: b.day_end,
    local_date: localDate(),
  });
  return res || { reply: "", used_ai: false, action: null };
}

// Execute a confirmed assistant action via the centralized backend endpoint
// (handles every action type + name->id resolution). Returns a result string.
async function assistantAct(action) {
  if (!action) return "Nothing to do.";
  const res = await apiPost("/api/assistant/act", {
    type: action.type,
    args: action.args || {},
    local_date: localDate(),
  });
  if (res && res.ok) {
    if (action.type === "start_session") showMainWindow();
    return res.message || "Done.";
  }
  return (res && res.message) || "Could not complete that.";
}

// ---------------------------------------------------------------------------
// Work-window helpers (app timezone, mirroring the web app's lib/idle)
// ---------------------------------------------------------------------------

function parseHM(hm) {
  if (!hm || !/^\d{1,2}:\d{2}$/.test(hm)) return null;
  const [h, m] = hm.split(":").map(Number);
  return h * 60 + m;
}

function nowMinutes() {
  const p = zonedParts();
  return p.hour * 60 + p.minute;
}

function isWithinWorkWindow(start, end) {
  const s = parseHM(start);
  const e = parseHM(end);
  if (s == null || e == null) return true; // unset -> always in-window
  const cur = nowMinutes();
  if (s <= e) return cur >= s && cur < e;
  return cur >= s || cur < e; // overnight window
}

function checkinIntervalMin() {
  const v = settingsCache && settingsCache.checkin_interval_minutes;
  return v && v > 0 ? v : DEFAULT_INTERVAL_MIN;
}

// ---------------------------------------------------------------------------
// Windows
// ---------------------------------------------------------------------------

function widgetStatePath() {
  return path.join(app.getPath("userData"), "widget-state.json");
}

function loadWidgetPosition() {
  try {
    const raw = fs.readFileSync(widgetStatePath(), "utf8");
    const { x, y } = JSON.parse(raw);
    if (Number.isFinite(x) && Number.isFinite(y)) return { x, y };
  } catch {
    /* no saved position yet */
  }
  const wa = screen.getPrimaryDisplay().workArea;
  return { x: wa.x + wa.width - WIDGET_W - 16, y: wa.y + wa.height - WIDGET_H - 16 };
}

function saveWidgetPosition() {
  if (!widgetWindow) return;
  const [x, y] = widgetWindow.getPosition();
  try {
    fs.writeFileSync(widgetStatePath(), JSON.stringify({ x, y }));
  } catch {
    /* best-effort */
  }
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 820,
    show: false,
    icon: path.join(__dirname, "assets", "icon.ico"),
  });
  // Tag the user agent so the in-page CheckinPrompt can suppress itself: the
  // native nudge window owns check-ins in the desktop build, avoiding a double
  // prompt (the web build keeps its in-page modal).
  const ua = `${mainWindow.webContents.getUserAgent()} JiraTrackerDesktop`;
  mainWindow.loadURL(BACKEND_URL, { userAgent: ua });
  mainWindow.once("ready-to-show", () => mainWindow.show());

  // Electron denies window.open/target=_blank by default; the app links out to
  // Jira issues, which should open in the OS browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  // The floating button is a shortcut back to the app, so it's pointless (and
  // cluttering) while the app itself is in front of you.
  for (const ev of ["show", "hide", "minimize", "restore", "focus"]) {
    mainWindow.on(ev, syncWidgetVisibility);
  }
  // Debounced: blur fires before the next window takes focus.
  mainWindow.on("blur", () => setTimeout(syncWidgetVisibility, 150));
}

function mainWindowInFront() {
  return (
    !!mainWindow &&
    !mainWindow.isDestroyed() &&
    mainWindow.isVisible() &&
    !mainWindow.isMinimized() &&
    mainWindow.isFocused()
  );
}

function syncWidgetVisibility() {
  if (!widgetWindow || widgetWindow.isDestroyed()) return;
  if (mainWindowInFront()) {
    if (widgetWindow.isVisible()) widgetWindow.hide();
  } else if (!widgetWindow.isVisible()) {
    widgetWindow.showInactive();
  }
}

function showMainWindow() {
  if (!mainWindow) return createMainWindow();
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function createWidgetWindow() {
  const { x, y } = loadWidgetPosition();
  widgetWindow = new BrowserWindow({
    width: WIDGET_W,
    height: WIDGET_H,
    x,
    y,
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    movable: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  widgetWindow.setAlwaysOnTop(true, "screen-saver");
  widgetWindow.once("ready-to-show", syncWidgetVisibility);
  widgetWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  widgetWindow.loadFile(path.join(__dirname, "renderer", "widget.html"));
  widgetWindow.on("moved", saveWidgetPosition);
  widgetWindow.on("closed", () => {
    widgetWindow = null;
  });
}

function openNudgeWindow() {
  if (nudgeWindow) {
    nudgeWindow.show();
    nudgeWindow.focus();
    return;
  }
  const wa = screen.getPrimaryDisplay().workArea;
  nudgeWindow = new BrowserWindow({
    width: NUDGE_W,
    height: NUDGE_H,
    // Bottom-right corner, like a notification, not the middle of the screen.
    x: wa.x + wa.width - NUDGE_W - CORNER_MARGIN,
    y: wa.y + wa.height - NUDGE_H - CORNER_MARGIN,
    frame: false,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    show: false,
    icon: path.join(__dirname, "assets", "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  nudgeWindow.setAlwaysOnTop(true, "screen-saver");
  nudgeWindow.loadFile(path.join(__dirname, "renderer", "nudge.html"));
  // showInactive: don't steal focus from whatever you're typing in.
  nudgeWindow.once("ready-to-show", () => nudgeWindow.showInactive());
  nudgeWindow.on("closed", () => {
    nudgeWindow = null;
    // Any dismissal (answer/snooze/OS close) restarts the interval clock, so an
    // ignored nudge re-fires after the interval rather than immediately.
    lastNudgeAt = Date.now();
  });
}

function openPlanWindow() {
  if (planWindow) {
    planWindow.show();
    planWindow.focus();
    return;
  }
  planWindow = new BrowserWindow({
    width: 480,
    height: 470,
    frame: false,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: false,
    alwaysOnTop: true,
    show: false,
    icon: path.join(__dirname, "assets", "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  planWindow.setAlwaysOnTop(true, "screen-saver");
  planWindow.loadFile(path.join(__dirname, "renderer", "plan.html"));
  planWindow.once("ready-to-show", () => {
    planWindow.show();
    planWindow.focus();
  });
  planWindow.on("closed", () => {
    planWindow = null;
  });
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "assets", "tray-icon.ico"));
  tray = new Tray(icon);
  tray.setToolTip("Jira Tracker");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open Jira Tracker", click: showMainWindow },
      { label: "Check in now", click: openNudgeWindow },
      { label: "Plan my day", click: openPlanWindow },
      { type: "separator" },
      {
        label: "Quit",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", showMainWindow);
}

// ---------------------------------------------------------------------------
// Scheduler
// ---------------------------------------------------------------------------

async function refreshSettings() {
  const s = await apiGet("/api/settings");
  if (s) settingsCache = s;
}

// Prompt for the day's plan once per local date: only when connected, no plan
// exists yet, and it's past the configured work start (so it doesn't fire at
// 6am before the workday).
async function maybePromptPlan() {
  const date = localDate();
  if (lastPlanPromptDate === date) return;
  const auth = await apiGet("/api/auth/status");
  if (!auth || !auth.connected) return; // don't nag before Jira is set up
  const start = settingsCache && settingsCache.work_start_time;
  const startMin = parseHM(start);
  if (startMin != null && nowMinutes() < startMin) return; // too early
  const existing = await apiGet(`/api/plan/intention?date=${date}`);
  lastPlanPromptDate = date; // mark handled regardless, to prompt at most once
  if (existing) return;
  openPlanWindow();
}

async function schedulerTick() {
  await maybePromptPlan();

  if (nudgeWindow || planWindow) return; // one pop-up at a time
  if (Date.now() < snoozeUntil) return;
  // You're looking at the app (and its timer) already; ask once you leave it.
  if (mainWindowInFront()) return;
  const s = settingsCache || {};
  if (!isWithinWorkWindow(s.work_start_time, s.work_end_time)) return;
  if ((Date.now() - lastNudgeAt) / 60000 < checkinIntervalMin()) return;

  const auth = await apiGet("/api/auth/status");
  if (!auth || !auth.connected) return; // nothing useful to ask before setup
  openNudgeWindow();
}

// ---------------------------------------------------------------------------
// IPC (the renderers' only backend/window access)
// ---------------------------------------------------------------------------

function registerIpc() {
  ipcMain.handle("status:get", () => composeStatus());
  ipcMain.handle("intention:get", (_e, date) =>
    apiGet(`/api/plan/intention?date=${date || localDate()}`),
  );
  ipcMain.handle("intention:save", (_e, payload) =>
    apiPost("/api/plan/intention", { ...payload, plan_date: (payload && payload.plan_date) || localDate() }),
  );
  ipcMain.handle("intention:append-note", (_e, text) => appendNote(text));
  ipcMain.handle("assistant:chat", (_e, messages) => assistantChat(messages || []));
  ipcMain.handle("assistant:act", (_e, action) => assistantAct(action));

  // Manual drag for the round widget (renderer distinguishes drag from click).
  ipcMain.handle("widget:drag-start", () => {
    if (widgetWindow) widgetDragOrigin = widgetWindow.getPosition();
  });
  ipcMain.handle("widget:drag-move", (_e, dx, dy) => {
    if (widgetWindow && widgetDragOrigin) {
      widgetWindow.setPosition(
        widgetDragOrigin[0] + Math.round(dx),
        widgetDragOrigin[1] + Math.round(dy),
      );
    }
  });
  ipcMain.handle("widget:drag-end", () => {
    widgetDragOrigin = null;
    saveWidgetPosition();
  });

  ipcMain.handle("app:open", () => {
    showMainWindow();
  });
  ipcMain.handle("nudge:trigger", () => {
    snoozeUntil = 0;
    openNudgeWindow();
  });
  ipcMain.handle("checkin:answer", () => {
    lastNudgeAt = Date.now();
    snoozeUntil = 0;
    if (nudgeWindow) nudgeWindow.close();
  });
  ipcMain.handle("nudge:expand", () => {
    if (!nudgeWindow) return;
    const [x, y] = nudgeWindow.getPosition();
    const [, h] = nudgeWindow.getSize();
    if (h >= NUDGE_CHAT_H) return;
    // Grow upward so the card stays anchored to the bottom corner.
    nudgeWindow.setBounds({ x, y: y - (NUDGE_CHAT_H - h), width: NUDGE_W, height: NUDGE_CHAT_H });
    nudgeWindow.focus();
  });
  ipcMain.handle("nudge:dismiss", () => {
    if (nudgeWindow) nudgeWindow.close();
  });
  ipcMain.handle("nudge:snooze", () => {
    snoozeUntil = Date.now() + SNOOZE_MS;
    if (nudgeWindow) nudgeWindow.close();
  });
  ipcMain.handle("plan:close", () => {
    if (planWindow) planWindow.close();
  });
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

async function isBackendHealthy() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// One instance only: a second launch (Start menu, shortcut, auto-start) would
// otherwise add a second floating button, tray icon and backend.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => showMainWindow());
}

app.whenReady().then(async () => {
  if (!gotLock) return;
  registerIpc();
  // In dev (unpackaged), if a backend is already serving 8756 (e.g. `make dev`
  // in WSL, reachable from Windows via localhost forwarding), reuse it instead
  // of spawning the bundled PyInstaller exe. That exe can be stale between
  // rebuilds, and reusing the live dev backend means code changes show up in the
  // desktop app immediately with no re-freeze. Packaged builds always spawn
  // their bundled backend (nothing else is running).
  const external = !app.isPackaged && (await isBackendHealthy());
  if (external) {
    console.log("[backend] reusing already-running backend on", BACKEND_URL);
  } else {
    spawnBackend();
  }
  try {
    await waitForHealth();
  } catch (err) {
    console.error(err);
  }
  await refreshSettings();
  createMainWindow();
  createWidgetWindow();
  createTray();

  // Kick the start-of-day prompt shortly after launch, then let the scheduler
  // own both the plan check and the hourly nudge.
  setTimeout(() => maybePromptPlan(), 1500);
  schedulerTimer = setInterval(schedulerTick, SCHEDULER_TICK_MS);
  settingsTimer = setInterval(refreshSettings, SETTINGS_REFRESH_MS);
});

// Windows-only target: the tray + floating widget keep the app alive; never
// quit just because every window closed.
app.on("window-all-closed", () => {});

app.on("before-quit", () => {
  quitting = true;
  if (schedulerTimer) clearInterval(schedulerTimer);
  if (settingsTimer) clearInterval(settingsTimer);
  if (backendProcess && !backendProcess.killed) backendProcess.kill();
});
