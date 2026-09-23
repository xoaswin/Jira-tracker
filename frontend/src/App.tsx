import { useEffect, useRef } from "react";
import {
  BarChart3,
  Circle,
  ClipboardList,
  Command as CommandIcon,
  LayoutDashboard,
  ListChecks,
  Play,
  Settings as SettingsIcon,
} from "lucide-react";
import { useActiveSession, useAuthStatus } from "./api/hooks";
import { useUi, type Screen } from "./store/ui";
import { Spinner } from "./components/ui";
import { NudgeBanner } from "./components/NudgeBanner";
import { DailyCompletenessNudge } from "./components/DailyCompletenessNudge";
import { IdlePrompt } from "./components/IdlePrompt";
import { CheckinPrompt } from "./components/CheckinPrompt";
import { Settings } from "./screens/Settings";
import { Start } from "./screens/Start";
import { Match } from "./screens/Match";
import { ActiveSession } from "./screens/ActiveSession";
import { Finish } from "./screens/Finish";
import { Dashboard } from "./screens/Dashboard";
import { MyTickets } from "./screens/MyTickets";
import { Manage } from "./screens/Manage";
import { Insights } from "./screens/Insights";
import { CommandPalette } from "./components/CommandPalette";

function NavButton({
  active,
  onClick,
  icon,
  label,
  title,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors ${
        active
          ? "bg-indigo-600 text-white shadow-sm"
          : "text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      }`}
    >
      {icon}
      {/* Labels collapse to icon-only below lg so the bar never wraps. */}
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}

export default function App() {
  const auth = useAuthStatus();
  const active = useActiveSession();
  const { screen, setScreen, currentSessionId, setCurrentSession } = useUi();
  const autoRouted = useRef(false);

  const connected = auth.data?.connected ?? false;

  // Force the settings screen until connected.
  useEffect(() => {
    if (auth.isSuccess && !connected) setScreen("settings");
  }, [auth.isSuccess, connected, setScreen]);

  // On first load, resume an in-flight session.
  useEffect(() => {
    if (autoRouted.current) return;
    if (connected && active.isSuccess) {
      autoRouted.current = true;
      if (active.data) {
        setCurrentSession(active.data.id);
        if (screen === "start") setScreen("active");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, active.isSuccess]);

  if (auth.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const nav: { key: Screen; label: string; icon: React.ReactNode }[] = [
    { key: "start", label: "Start", icon: <Play className="h-4 w-4" /> },
    {
      key: "mytickets",
      label: "My Tickets",
      icon: <ClipboardList className="h-4 w-4" />,
    },
    {
      key: "manage",
      label: "Manage",
      icon: <ListChecks className="h-4 w-4" />,
    },
    {
      key: "dashboard",
      label: "Dashboard",
      icon: <LayoutDashboard className="h-4 w-4" />,
    },
    {
      key: "insights",
      label: "Insights",
      icon: <BarChart3 className="h-4 w-4" />,
    },
    {
      key: "settings",
      label: "Settings",
      icon: <SettingsIcon className="h-4 w-4" />,
    },
  ];

  function render() {
    if (!connected) return <Settings />;
    switch (screen) {
      case "start":
        return <Start />;
      case "match":
        return <Match />;
      case "active":
        return <ActiveSession />;
      case "finish":
        return <Finish />;
      case "dashboard":
        return <Dashboard />;
      case "mytickets":
        return <MyTickets />;
      case "manage":
        return <Manage />;
      case "insights":
        return <Insights />;
      case "settings":
        return <Settings />;
      default:
        return <Start />;
    }
  }

  const hasActive = !!active.data || currentSessionId != null;

  return (
    <div className="min-h-full">
      {connected && <NudgeBanner />}
      {connected && <DailyCompletenessNudge />}
      {connected && <IdlePrompt />}
      {connected && <CheckinPrompt />}
      {connected && <CommandPalette />}
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-2.5">
          <div className="flex shrink-0 items-center gap-2">
            <span
              className={`inline-flex h-2 w-2 shrink-0 rounded-full ${
                connected ? "bg-emerald-500" : "bg-rose-500"
              }`}
              title={connected ? "Connected to Jira" : "Not connected"}
            />
            <span className="whitespace-nowrap text-sm font-semibold tracking-tight">
              Work Session Tracker
            </span>
          </div>
          <nav className="flex flex-1 items-center justify-end gap-0.5">
            {hasActive && connected && (
              <button
                onClick={() => setScreen("active")}
                title="Active session"
                className={`mr-1 inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors ${
                  screen === "active"
                    ? "bg-emerald-600 text-white shadow-sm"
                    : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:bg-emerald-950/60 dark:text-emerald-300 dark:hover:bg-emerald-900/60"
                }`}
              >
                <Circle className="h-2 w-2 animate-pulse fill-current" />
                Active
              </button>
            )}
            {nav.map((n) => (
              <NavButton
                key={n.key}
                active={screen === n.key}
                onClick={() => setScreen(n.key)}
                icon={n.icon}
                label={n.label}
                title={n.label}
              />
            ))}
            {connected && (
              <button
                onClick={() => useUi.getState().setCommandOpen(true)}
                title="Command palette (press / )"
                className="ml-1 inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:border-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              >
                <CommandIcon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">/</span>
              </button>
            )}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-8">{render()}</main>
    </div>
  );
}
