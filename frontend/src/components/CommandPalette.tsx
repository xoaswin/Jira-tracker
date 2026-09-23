// Command palette (Cmd/Ctrl-K) + global hotkeys, for an app you live in all day.
// Actions are context-aware: pause/resume/finish appear only with an active
// session. Navigation jumps between screens. Fuzzy-ish substring filtering.
//
// Hotkeys (when not typing in an input): p pause/resume, f finish, g then d/m/i/t
// are intentionally avoided to stay simple; single keys only, guarded so they
// never fire while typing.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  LayoutDashboard,
  ListChecks,
  Pause,
  Play,
  Plus,
  Search,
  Settings as SettingsIcon,
  Square,
} from "lucide-react";
import {
  useActiveSession,
  usePauseSession,
  useResumeSession,
} from "../api/hooks";
import { useUi } from "../store/ui";

interface Action {
  id: string;
  label: string;
  hint?: string;
  icon: React.ReactNode;
  run: () => void;
}

function isTypingTarget(el: EventTarget | null): boolean {
  const node = el as HTMLElement | null;
  if (!node) return false;
  const tag = node.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    node.isContentEditable
  );
}

export function CommandPalette() {
  const open = useUi((s) => s.commandOpen);
  const setOpen = (v: boolean) => useUi.getState().setCommandOpen(v);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const active = useActiveSession();
  const pause = usePauseSession();
  const resume = useResumeSession();
  const { setScreen, reset } = useUi();

  const session = active.data;
  const isActive = session?.state === "active";
  const isPaused = session?.state === "paused";

  const actions = useMemo<Action[]>(() => {
    const list: Action[] = [
      {
        id: "start",
        label: "New session",
        hint: "Start screen",
        icon: <Plus className="h-4 w-4" />,
        run: () => {
          reset();
          setScreen("start");
        },
      },
    ];
    if (session) {
      list.push({
        id: "active",
        label: "Go to active session",
        icon: <Play className="h-4 w-4" />,
        run: () => setScreen("active"),
      });
      if (isActive) {
        list.push({
          id: "pause",
          label: "Pause session",
          hint: "P",
          icon: <Pause className="h-4 w-4" />,
          run: () => pause.mutate(session.id),
        });
        list.push({
          id: "finish",
          label: "Finish & log session",
          hint: "F",
          icon: <Square className="h-4 w-4" />,
          run: () => setScreen("finish"),
        });
      }
      if (isPaused) {
        list.push({
          id: "resume",
          label: "Resume session",
          hint: "P",
          icon: <Play className="h-4 w-4" />,
          run: () => resume.mutate(session.id),
        });
      }
    }
    list.push(
      {
        id: "nav-mytickets",
        label: "My Tickets",
        icon: <ListChecks className="h-4 w-4" />,
        run: () => setScreen("mytickets"),
      },
      {
        id: "nav-manage",
        label: "Manage tickets",
        icon: <ListChecks className="h-4 w-4" />,
        run: () => setScreen("manage"),
      },
      {
        id: "nav-dashboard",
        label: "Dashboard",
        icon: <LayoutDashboard className="h-4 w-4" />,
        run: () => setScreen("dashboard"),
      },
      {
        id: "nav-insights",
        label: "Insights",
        icon: <BarChart3 className="h-4 w-4" />,
        run: () => setScreen("insights"),
      },
      {
        id: "nav-settings",
        label: "Settings",
        icon: <SettingsIcon className="h-4 w-4" />,
        run: () => setScreen("settings"),
      },
    );
    return list;
  }, [session, isActive, isPaused, pause, resume, setScreen, reset]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter((a) => a.label.toLowerCase().includes(q));
  }, [actions, query]);

  // Latest mutable actions, read by the once-registered listener without
  // re-subscribing (avoids stale closures and listener churn on every render).
  const hotkeyRef = useRef({ session, isActive, isPaused, pause, resume, setScreen });
  hotkeyRef.current = { session, isActive, isPaused, pause, resume, setScreen };

  // Global key handling, registered ONCE. Browsers reserve Ctrl/Cmd-K (address
  // bar) and Ctrl-J (downloads), so the opener is "/" when not typing in a field
  // (the GitHub/Slack pattern) - a plain key the browser cannot hijack. Reads
  // live open-state from the store so it never goes stale.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const key = e.key;
      const store = useUi.getState();
      const { session: s, isActive: act, isPaused: pau, pause: pz, resume: rz, setScreen: nav } =
        hotkeyRef.current;

      // macOS Cmd-K bonus.
      if (e.metaKey && key.toLowerCase() === "k") {
        e.preventDefault();
        store.setCommandOpen(!store.commandOpen);
        return;
      }
      if (store.commandOpen) return; // palette handles its own keys when open
      if (isTypingTarget(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (key === "/") {
        e.preventDefault();
        store.setCommandOpen(true);
      } else if (key.toLowerCase() === "p" && s) {
        e.preventDefault();
        if (act) pz.mutate(s.id);
        else if (pau) rz.mutate(s.id);
      } else if (key.toLowerCase() === "f" && act) {
        e.preventDefault();
        nav("finish");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Reset + focus when opening.
  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // Focus after paint.
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  if (!open) return null;

  function choose(a: Action) {
    a.run();
    setOpen(false);
  }

  function onInputKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setOpen(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const a = filtered[cursor];
      if (a) choose(a);
    }
  }

  return (
    <div
      className="fixed inset-0 z-30 flex items-start justify-center bg-black/40 p-4 pt-[15vh]"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-3 dark:border-slate-800">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKey}
            placeholder="Type a command..."
            className="w-full bg-transparent py-3 text-sm outline-none placeholder:text-slate-400"
          />
          <span className="flex items-center gap-1 text-[10px] text-slate-400">
            Press <kbd className="rounded border border-slate-300 px-1 dark:border-slate-600">/</kbd> to open
          </span>
        </div>
        <ul className="max-h-80 overflow-y-auto py-1">
          {filtered.length === 0 && (
            <li className="px-4 py-3 text-sm text-slate-400">No matching commands.</li>
          )}
          {filtered.map((a, i) => (
            <li key={a.id}>
              <button
                onMouseEnter={() => setCursor(i)}
                onClick={() => choose(a)}
                className={`flex w-full items-center gap-3 px-4 py-2 text-left text-sm ${
                  i === cursor
                    ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-200"
                    : "text-slate-700 dark:text-slate-200"
                }`}
              >
                <span className="text-slate-400">{a.icon}</span>
                <span className="flex-1">{a.label}</span>
                {a.hint && (
                  <span className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-400 dark:border-slate-700">
                    {a.hint}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
