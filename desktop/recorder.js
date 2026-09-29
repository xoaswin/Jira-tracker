// Activity recorder: which app/window is in front, and whether you're away.
//
// A single hidden PowerShell process prints the foreground window (process
// name + title) every few seconds via user32 (no native Node modules, so the
// hand-repacked app.asar stays pure JS). Electron's powerMonitor supplies idle
// time and lock/suspend events. Samples are folded into segments and posted
// to the backend (/api/activity/segments), which stores them locally, infers
// the Jira ticket, and replies with a zero-click tracking suggestion.
//
// Away handling: locking the screen, suspending, or going idle past the idle
// threshold pauses the running timer; coming back resumes it (only if it was
// the recorder that paused it; see backend services/activity.set_away).

const { spawn } = require("child_process");
const { powerMonitor } = require("electron");

const SAMPLE_SECONDS = 5;
const FLUSH_MS = 30_000;
// A segment counts as "idle" after this long without input (for the timeline);
// pausing the timer uses the user's idle threshold setting instead.
const IDLE_SEGMENT_SECONDS = 5 * 60;
const MAX_PENDING = 600;

const SAMPLER_PS = `
$ErrorActionPreference = 'SilentlyContinue'
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class JtFg {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
}
"@
$sb = New-Object System.Text.StringBuilder 512
while ($true) {
  $h = [JtFg]::GetForegroundWindow()
  $null = $sb.Clear()
  $null = [JtFg]::GetWindowText($h, $sb, 512)
  $procId = [uint32]0
  $null = [JtFg]::GetWindowThreadProcessId($h, [ref]$procId)
  $name = ''
  if ($procId -ne 0) { $p = Get-Process -Id $procId -ErrorAction SilentlyContinue; if ($p) { $name = $p.ProcessName } }
  $line = @{ app = $name; title = $sb.ToString() } | ConvertTo-Json -Compress
  try { [Console]::Out.WriteLine($line); [Console]::Out.Flush() } catch { exit }
  Start-Sleep -Seconds ${SAMPLE_SECONDS}
}
`;

function createRecorder({ apiPost, getSettings, onSuggestion, onAway, log = console.log }) {
  let proc = null;
  let buffer = "";
  let current = null; // { start: Date, app, title, kind }
  let pending = [];
  let flushTimer = null;
  let locked = false;
  let away = null; // null | "idle" | "locked" | "suspend"
  let stopped = false;

  function idleThresholdSeconds() {
    const s = getSettings() || {};
    return Math.max(1, s.idle_threshold_minutes || 15) * 60;
  }

  async function setAway(reason) {
    if (reason === away) return;
    const wasAway = away !== null;
    away = reason;
    if (reason !== null && !wasAway) {
      await apiPost("/api/activity/away", { away: true });
      onAway && onAway(true, reason);
    } else if (reason === null && wasAway) {
      await apiPost("/api/activity/away", { away: false });
      onAway && onAway(false, null);
    }
  }

  function close(at) {
    if (!current) return;
    if (at - current.start >= 1000) {
      pending.push({
        start: current.start.toISOString(),
        end: at.toISOString(),
        app: current.app,
        title: current.title,
        kind: current.kind,
      });
      if (pending.length > MAX_PENDING) pending = pending.slice(-MAX_PENDING);
    }
    current = null;
  }

  function onSample(sample) {
    const now = new Date();
    const idle = powerMonitor.getSystemIdleTime();
    let kind = "active";
    if (locked) kind = "locked";
    else if (idle >= IDLE_SEGMENT_SECONDS) kind = "idle";
    // Don't record what's on screen while away.
    const app = kind === "active" ? sample.app || "" : "";
    const title = kind === "active" ? sample.title || "" : "";
    if (!current || current.app !== app || current.title !== title || current.kind !== kind) {
      close(now);
      current = { start: now, app, title, kind };
    }

    if (locked) setAway("locked");
    else if (idle >= idleThresholdSeconds()) setAway("idle");
    else if (away === "idle" && idle < SAMPLE_SECONDS * 2) setAway(null);
  }

  async function flush() {
    if (current) {
      // Close at "now" and continue the same window; the backend merges
      // contiguous identical segments back together.
      const now = new Date();
      const cont = { ...current, start: now };
      close(now);
      current = cont;
    }
    if (!pending.length) return;
    const batch = pending;
    pending = [];
    const res = await apiPost("/api/activity/segments", { segments: batch });
    if (!res) {
      pending = batch.concat(pending).slice(-MAX_PENDING); // backend down: retry later
      return;
    }
    if (res.suggestion && onSuggestion) onSuggestion(res.suggestion);
  }

  function startSampler() {
    if (stopped) return;
    const encoded = Buffer.from(SAMPLER_PS, "utf16le").toString("base64");
    proc = spawn(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
      { windowsHide: true, stdio: ["ignore", "pipe", "ignore"] },
    );
    proc.stdout.setEncoding("utf8");
    proc.stdout.on("data", (chunk) => {
      buffer += chunk;
      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line.startsWith("{")) continue;
        try {
          onSample(JSON.parse(line));
        } catch {
          /* partial/garbled line; skip */
        }
      }
    });
    proc.on("error", (err) => log(`[recorder] sampler failed: ${err.message}`));
    proc.on("exit", () => {
      proc = null;
      // Restart if it died unexpectedly (e.g. killed by AV); back off a bit.
      if (!stopped) setTimeout(startSampler, 15_000);
    });
  }

  const onLock = () => {
    locked = true;
    setAway("locked");
  };
  const onUnlock = () => {
    locked = false;
    setAway(null);
  };
  const onSuspend = () => setAway("suspend");
  const onResume = () => setAway(locked ? "locked" : null);

  return {
    start() {
      stopped = false;
      powerMonitor.on("lock-screen", onLock);
      powerMonitor.on("unlock-screen", onUnlock);
      powerMonitor.on("suspend", onSuspend);
      powerMonitor.on("resume", onResume);
      startSampler();
      flushTimer = setInterval(() => flush().catch(() => {}), FLUSH_MS);
      log("[recorder] started");
    },
    async stop() {
      stopped = true;
      if (flushTimer) clearInterval(flushTimer);
      powerMonitor.removeListener("lock-screen", onLock);
      powerMonitor.removeListener("unlock-screen", onUnlock);
      powerMonitor.removeListener("suspend", onSuspend);
      powerMonitor.removeListener("resume", onResume);
      if (proc) proc.kill();
      close(new Date());
      if (pending.length) await apiPost("/api/activity/segments", { segments: pending }).catch(() => null);
    },
  };
}

module.exports = { createRecorder };
