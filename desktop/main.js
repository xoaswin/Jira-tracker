// Electron shell for the desktop build. It:
//   * spawns the PyInstaller-packaged backend as a child process,
//   * shows the full app in a normal window (hidden to the tray on close),
//   * keeps an always-on-top floating status pill (widget.html) alive,
//   * fires an hourly "still on this?" check-in in a small pop-up (nudge.html)
//     within your work hours, whether or not a timer is running,
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

const WIDGET_W = 240;
const WIDGET_H = 52;

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

function localDate(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// The status snapshot the widget and nudge render from.
async function composeStatus() {
  const auth = await apiGet("/api/auth/status");
  const connected = !!(auth && auth.connected);
  const date = localDate();
  if (!connected) return { connected, session: null, intention: null, date };
  const [session, intention] = await Promise.all([
    apiGet("/api/sessions/active"),
    apiGet(`/api/plan/intention?date=${date}`),
  ]);
  return { connected, session: session || null, intention: intention || null, date };
}

async function appendNote(text) {
  const date = localDate();
  const existing = await apiGet(`/api/plan/intention?date=${date}`);
  const note = existing && existing.note ? `${existing.note}\n${text}` : text;
  const ticket_keys = existing && existing.ticket_keys ? existing.ticket_keys : [];
  return apiPost("/api/plan/intention", { plan_date: date, note, ticket_keys });
}

// ---------------------------------------------------------------------------
// Work-window helpers (local clock, mirroring the web app's lib/idle)
// ---------------------------------------------------------------------------

function parseHM(hm) {
  if (!hm || !/^\d{1,2}:\d{2}$/.test(hm)) return null;
  const [h, m] = hm.split(":").map(Number);
  return h * 60 + m;
}

function nowMinutes() {
  const d = new Date();
  return d.getHours() * 60 + d.getMinutes();
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
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  widgetWindow.setAlwaysOnTop(true, "screen-saver");
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
  nudgeWindow = new BrowserWindow({
    width: 400,
    height: 330,
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
  nudgeWindow.setAlwaysOnTop(true, "screen-saver");
  nudgeWindow.loadFile(path.join(__dirname, "renderer", "nudge.html"));
  nudgeWindow.once("ready-to-show", () => {
    nudgeWindow.show();
    nudgeWindow.focus();
  });
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

  if (nudgeWindow) return; // one at a time
  if (Date.now() < snoozeUntil) return;
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
    apiPost("/api/plan/intention", payload),
  );
  ipcMain.handle("intention:append-note", (_e, text) => appendNote(text));

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

app.whenReady().then(async () => {
  registerIpc();
  spawnBackend();
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
