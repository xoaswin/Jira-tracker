// Quick-access assistant: a slide-over drawer wrapping the shared AssistantChat.
// The conversation is shared with the full Assistant tab via the UI store, so
// switching between them is seamless.

import { useEffect } from "react";
import { Maximize2, Sparkles, Trash2, X } from "lucide-react";
import { useUi } from "../store/ui";
import { AssistantChat } from "./AssistantChat";

export function AssistantPanel() {
  const {
    assistantOpen: open,
    setAssistantOpen: setOpen,
    setAssistantMessages,
    setScreen,
  } = useUi();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="relative flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-white/10 dark:bg-[#0b0b12]">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-white/10">
          <div className="flex items-center gap-2.5">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 text-white shadow-md shadow-indigo-900/30 ring-1 ring-inset ring-white/20">
              <Sparkles className="h-4 w-4" />
            </span>
            <div>
              <div className="text-sm font-semibold">Assistant</div>
              <div className="text-[11px] text-slate-400">Grounded in your day</div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setAssistantMessages([])}
              title="New chat"
              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white/5"
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <button
              onClick={() => {
                setOpen(false);
                setScreen("assistant");
              }}
              title="Open full assistant"
              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white/5"
            >
              <Maximize2 className="h-4 w-4" />
            </button>
            <button
              onClick={() => setOpen(false)}
              title="Close (Esc)"
              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white/5"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1">
          <AssistantChat autoFocus />
        </div>
      </div>
    </div>
  );
}
