// Preload for the small desktop windows (widget / nudge / plan).
//
// These windows render local HTML with contextIsolation on and no Node access.
// The backend only allows CORS from the Vite dev origin, so a renderer can't
// fetch 127.0.0.1 directly; instead every backend call is proxied through the
// main process over IPC. This bridge is the entire surface the renderers get.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  // Read-only snapshot the widget/nudge render from: connection state, the
  // active session (or null), today's intention (or null), and the local date.
  getStatus: () => ipcRenderer.invoke("status:get"),

  // Start-of-day plan (backed by /api/plan/intention, one row per local date).
  getIntention: (date) => ipcRenderer.invoke("intention:get", date),
  saveIntention: (payload) => ipcRenderer.invoke("intention:save", payload),
  // Append a free-text line to today's intention note, so untracked work still
  // gets captured as reusable context even when no timer is running.
  appendNote: (text) => ipcRenderer.invoke("intention:append-note", text),

  // Window actions.
  openApp: () => ipcRenderer.invoke("app:open"),
  triggerNudge: () => ipcRenderer.invoke("nudge:trigger"),
  // Records that the check-in was answered (resets the hourly interval) and
  // closes the nudge window.
  answerCheckin: () => ipcRenderer.invoke("checkin:answer"),
  snoozeNudge: () => ipcRenderer.invoke("nudge:snooze"),
  closePlan: () => ipcRenderer.invoke("plan:close"),
});
