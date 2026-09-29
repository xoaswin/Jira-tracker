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

  // Contextual assistant: chat (returns {reply, used_ai, action}) and execute a
  // confirmed action, for the conversational nudge.
  assistantChat: (messages) => ipcRenderer.invoke("assistant:chat", messages),
  assistantAct: (action) => ipcRenderer.invoke("assistant:act", action),

  // Window actions.
  openApp: () => ipcRenderer.invoke("app:open"),
  triggerNudge: () => ipcRenderer.invoke("nudge:trigger"),

  // Manual drag of the round floating widget.
  widgetDragStart: () => ipcRenderer.invoke("widget:drag-start"),
  widgetDragMove: (dx, dy) => ipcRenderer.invoke("widget:drag-move", dx, dy),
  widgetDragEnd: () => ipcRenderer.invoke("widget:drag-end"),
  // Records that the check-in was answered (resets the hourly interval) and
  // closes the nudge window.
  answerCheckin: () => ipcRenderer.invoke("checkin:answer"),
  snoozeNudge: () => ipcRenderer.invoke("nudge:snooze"),
  // Close the check-in without answering (it re-asks after the interval).
  dismissNudge: () => ipcRenderer.invoke("nudge:dismiss"),
  // Grow the compact check-in card into a chat once the user types.
  expandNudge: () => ipcRenderer.invoke("nudge:expand"),
  closePlan: () => ipcRenderer.invoke("plan:close"),

  // End-of-day wrap-up: today's sessions, a drafted comment per session, and
  // logging the reviewed sessions to Jira.
  wrapupGet: () => ipcRenderer.invoke("wrapup:get"),
  wrapupDraft: (sessionId) => ipcRenderer.invoke("wrapup:draft", sessionId),
  wrapupLog: (items) => ipcRenderer.invoke("wrapup:log", items),
  closeWrapup: () => ipcRenderer.invoke("wrapup:close"),

  // Voice check-in: send a recorded clip (ArrayBuffer) for transcription;
  // resolves {text} or {error}. onVoiceToggle fires on the global hotkey.
  transcribe: (bytes, mime) => ipcRenderer.invoke("voice:transcribe", bytes, mime),
  onVoiceToggle: (fn) => ipcRenderer.on("voice:toggle", () => fn()),

  // Zero-click tracking toast ("Tracking PPVM-123 automatically · Undo").
  toastGet: () => ipcRenderer.invoke("toast:get"),
  toastUndo: () => ipcRenderer.invoke("toast:undo"),
  toastClose: () => ipcRenderer.invoke("toast:close"),
  onToastUpdate: (fn) => ipcRenderer.on("toast:update", () => fn()),
});
