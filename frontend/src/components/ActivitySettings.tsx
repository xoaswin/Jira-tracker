// Zero-click tracking + activity recording + code folders.
//
// Code folders let the app read git branches/commits (the packaged desktop
// app has no .env). Auto-track starts/switches the timer after ~5 minutes on a
// ticket (window title or branch), with an undo toast.

import { useEffect, useState } from "react";
import { Activity, Save } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSettings, useUpdateSettings } from "../api/hooks";
import { Banner, Button, Card, Label, TextArea } from "./ui";

const VSCODE_TITLE =
  '"window.title": "${activeRepositoryBranchName} — ${rootName}${separator}${activeEditorShort}"';

export function ActivitySettings() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const qc = useQueryClient();
  const [autoTrack, setAutoTrack] = useState(true);
  const [folders, setFolders] = useState("");
  const [saved, setSaved] = useState(false);
  const [cleared, setCleared] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    const s = settings.data;
    if (s) {
      setAutoTrack(s.auto_track ?? true);
      setFolders((s.git_repo_paths ?? []).join("\n"));
    }
  }, [settings.data]);

  function save() {
    update.mutate(
      {
        auto_track: autoTrack,
        git_repo_paths: folders
          .split("\n")
          .map((l) => l.trim())
          .filter(Boolean),
      },
      {
        onSuccess: () => {
          setSaved(true);
          window.setTimeout(() => setSaved(false), 2500);
        },
      },
    );
  }

  async function clear() {
    const res = await api.clearActivity();
    setConfirmClear(false);
    setCleared(`Deleted ${res.deleted} activity records.`);
    qc.invalidateQueries({ queryKey: ["activity-day"] });
    qc.invalidateQueries({ queryKey: ["activity-focus"] });
  }

  return (
    <Card className="space-y-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
        <Activity className="h-4 w-4" />
        Activity and auto-tracking
      </h2>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        The desktop app notes which app and window is in front every few seconds. It stays on
        this computer (kept 45 days) and powers the Timeline and Focus radar. Locking your screen
        or going idle pauses the running timer.
      </p>

      <label className="flex items-start gap-2 text-sm text-slate-600 dark:text-slate-300">
        <input
          type="checkbox"
          checked={autoTrack}
          onChange={(e) => setAutoTrack(e.target.checked)}
          className="mt-0.5 h-4 w-4"
        />
        <span>
          Start and switch the timer automatically
          <span className="mt-0.5 block text-xs text-slate-400">
            After about 5 minutes on one ticket (a Jira tab, or your editor on that ticket's
            branch) during work hours. A toast lets you undo.
          </span>
        </span>
      </label>

      <div>
        <Label>Code folders (one per line)</Label>
        <TextArea
          rows={3}
          placeholder={"C:\\Users\\you\\code\\payments-api\n\\\\wsl.localhost\\Ubuntu\\home\\you\\repo"}
          value={folders}
          onChange={(e) => setFolders(e.target.value)}
          className="font-mono text-xs"
        />
        <p className="mt-1 text-xs text-slate-400">
          Git repos to read branches and commits from (auto-tracking, the Timeline, worklog
          drafts). WSL repos work via <span className="font-mono">\\wsl.localhost\...</span>.
        </p>
      </div>

      <details className="text-xs text-slate-500 dark:text-slate-400">
        <summary className="cursor-pointer">Tip: show the branch in VS Code's title</summary>
        <p className="mt-1">
          Add this to VS Code's settings.json so the ticket in your branch name is visible to
          auto-tracking even without Code folders:
        </p>
        <pre className="mt-1 overflow-x-auto rounded bg-slate-100 px-2 py-1.5 font-mono text-[11px] dark:bg-slate-800">
          {VSCODE_TITLE}
        </pre>
      </details>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={save} loading={update.isPending}>
          <Save className="h-4 w-4" />
          Save
        </Button>
        {saved && <span className="text-sm font-medium text-emerald-500">Saved</span>}
        <span className="flex-1" />
        {confirmClear ? (
          <>
            <span className="text-xs text-slate-500">Delete all recorded activity?</span>
            <Button variant="danger" onClick={clear}>
              Delete
            </Button>
            <Button variant="ghost" onClick={() => setConfirmClear(false)}>
              Keep
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={() => setConfirmClear(true)}>
            Clear activity history
          </Button>
        )}
      </div>
      {cleared && <p className="text-xs text-slate-500">{cleared}</p>}
      {update.isError && <Banner tone="error">{String(update.error)}</Banner>}
    </Card>
  );
}
