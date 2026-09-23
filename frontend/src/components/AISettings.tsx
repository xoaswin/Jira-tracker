// AI provider + behaviour settings (Phase 5, section 8/16).
//
// Ollama is the default and is fully local. Gemini and Groq are opt-in and send
// internal text to a third party, so selecting them shows a clear warning and
// asks for an API key (stored in the keychain, never returned).

import { useEffect, useState } from "react";
import { AlertTriangle, Bell, Save } from "lucide-react";
import { useAiStatus, useSettings, useUpdateSettings } from "../api/hooks";
import {
  notificationPermission,
  notificationsSupported,
  requestNotificationPermission,
} from "../lib/notify";
import { Banner, Button, Card, Label, TextInput } from "./ui";

const THIRD_PARTY = new Set(["gemini", "groq"]);

export function AISettings() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const aiStatus = useAiStatus();

  const [provider, setProvider] = useState("ollama");
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [ollamaModel, setOllamaModel] = useState("");
  const [nudgeTime, setNudgeTime] = useState("18:00");
  const [idle, setIdle] = useState(15);
  const [usesTempo, setUsesTempo] = useState(false);
  const [issueScope, setIssueScope] = useState("open_on_board");
  const [workStart, setWorkStart] = useState("");
  const [workEnd, setWorkEnd] = useState("");
  const [dailyTarget, setDailyTarget] = useState(0);
  const [checkinInterval, setCheckinInterval] = useState(0);
  const [autoActualDates, setAutoActualDates] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [justSaved, setJustSaved] = useState(false);
  const [notifyPerm, setNotifyPerm] = useState(notificationPermission());

  async function enableNotifications() {
    const result = await requestNotificationPermission();
    setNotifyPerm(result);
  }

  useEffect(() => {
    const s = settings.data;
    if (s) {
      setProvider(s.ai_provider);
      setOllamaUrl(s.ollama_url ?? "http://localhost:11434");
      setOllamaModel(s.ollama_model ?? "llama3.1:8b");
      setNudgeTime(s.nudge_time ?? "18:00");
      setIdle(s.idle_threshold_minutes);
      setUsesTempo(s.uses_tempo);
      setIssueScope(s.issue_scope);
      setWorkStart(s.work_start_time ?? "");
      setWorkEnd(s.work_end_time ?? "");
      setDailyTarget(s.daily_target_hours ?? 0);
      setCheckinInterval(s.checkin_interval_minutes ?? 0);
      setAutoActualDates(s.auto_actual_dates ?? false);
    }
  }, [settings.data]);

  if (settings.isLoading) return null;

  const isThirdParty = THIRD_PARTY.has(provider);
  const keyAlreadySet =
    (provider === "gemini" && settings.data?.has_gemini_key) ||
    (provider === "groq" && settings.data?.has_groq_key);

  function save() {
    const patch: Parameters<typeof update.mutate>[0] = {
      ai_provider: provider,
      ollama_url: ollamaUrl,
      ollama_model: ollamaModel,
      nudge_time: nudgeTime,
      idle_threshold_minutes: idle,
      uses_tempo: usesTempo,
      issue_scope: issueScope,
      work_start_time: workStart || null,
      work_end_time: workEnd || null,
      daily_target_hours: dailyTarget,
      checkin_interval_minutes: checkinInterval,
      auto_actual_dates: autoActualDates,
    };
    if (apiKey.trim()) {
      if (provider === "gemini") patch.gemini_api_key = apiKey.trim();
      if (provider === "groq") patch.groq_api_key = apiKey.trim();
    }
    update.mutate(patch, {
      onSuccess: () => {
        setApiKey("");
        setJustSaved(true);
        window.setTimeout(() => setJustSaved(false), 2500);
      },
    });
  }

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
          AI and behaviour
        </h2>
        {aiStatus.data && (
          <span
            className={`text-xs ${
              aiStatus.data.available ? "text-emerald-500" : "text-slate-400"
            }`}
          >
            {aiStatus.data.provider === "none"
              ? "AI off"
              : aiStatus.data.available
                ? `${aiStatus.data.provider} ready`
                : `${aiStatus.data.provider} unavailable`}
          </span>
        )}
      </div>

      <div>
        <Label>Which tickets to search on a board</Label>
        <select
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
          value={issueScope}
          onChange={(e) => setIssueScope(e.target.value)}
        >
          <option value="open_on_board">All open tickets on the board (any assignee)</option>
          <option value="assigned_to_me">Only my open tickets</option>
          <option value="mine_all_status">My tickets, including Done</option>
          <option value="all_on_board">Everything on the board (any status)</option>
        </select>
        <p className="mt-1 text-xs text-slate-400">
          Applies on the next board refresh. Covers all issue types (story, bug,
          task, sub-task).
        </p>
      </div>

      <div>
        <Label>AI provider</Label>
        <select
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        >
          <option value="ollama">Ollama (local, recommended)</option>
          <option value="gemini">Google Gemini (cloud)</option>
          <option value="groq">Groq (cloud)</option>
          <option value="none">Off</option>
        </select>
      </div>

      {isThirdParty && (
        <Banner tone="warning">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              This sends your work descriptions and ticket text to a third party.
              For internal company information, prefer Ollama, which stays on this
              machine.
            </span>
          </div>
        </Banner>
      )}

      {provider === "ollama" && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Ollama URL</Label>
            <TextInput
              value={ollamaUrl}
              onChange={(e) => setOllamaUrl(e.target.value)}
            />
          </div>
          <div>
            <Label>Model</Label>
            <TextInput
              value={ollamaModel}
              onChange={(e) => setOllamaModel(e.target.value)}
            />
          </div>
        </div>
      )}

      {isThirdParty && (
        <div>
          <Label>
            API key{" "}
            {keyAlreadySet && (
              <span className="text-xs font-normal text-emerald-500">(saved)</span>
            )}
          </Label>
          <TextInput
            type="password"
            placeholder={keyAlreadySet ? "Leave blank to keep current key" : "Paste your API key"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <p className="mt-1 text-xs text-slate-400">
            Stored in your OS keychain, never in the database.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label>Idle threshold (minutes)</Label>
          <TextInput
            type="number"
            min={1}
            value={String(idle)}
            onChange={(e) => setIdle(Math.max(0, Number(e.target.value) || 0))}
          />
        </div>
        <div>
          <Label>End-of-day nudge time</Label>
          <TextInput
            type="time"
            value={nudgeTime}
            onChange={(e) => setNudgeTime(e.target.value)}
          />
        </div>
      </div>

      {/* Work day + accountability: drives the daily-completeness nudge and the
          recurring "what are you working on?" check-in. All local-clock. */}
      <div className="space-y-3 border-t border-slate-100 pt-4 dark:border-slate-800">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Work day and accountability
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Work start</Label>
            <TextInput
              type="time"
              value={workStart}
              onChange={(e) => setWorkStart(e.target.value)}
            />
          </div>
          <div>
            <Label>Work end</Label>
            <TextInput
              type="time"
              value={workEnd}
              onChange={(e) => setWorkEnd(e.target.value)}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Daily target (hours)</Label>
            <TextInput
              type="number"
              min={0}
              step={0.5}
              placeholder="e.g. 7.5"
              value={dailyTarget ? String(dailyTarget) : ""}
              onChange={(e) => setDailyTarget(Math.max(0, Number(e.target.value) || 0))}
            />
            <p className="mt-1 text-xs text-slate-400">
              Nudges you after work end if the day's tracked time is short. 0 = off.
            </p>
          </div>
          <div>
            <Label>Check-in every (minutes)</Label>
            <TextInput
              type="number"
              min={0}
              step={15}
              placeholder="e.g. 60"
              value={checkinInterval ? String(checkinInterval) : ""}
              onChange={(e) =>
                setCheckinInterval(Math.max(0, Number(e.target.value) || 0))
              }
            />
            <p className="mt-1 text-xs text-slate-400">
              During work hours, asks what you're working on (or confirms you're
              still on the current ticket if a timer is running). 0 = off.
            </p>
          </div>
        </div>

        {checkinInterval > 0 && notificationsSupported() && notifyPerm !== "granted" && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-800 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-200">
            <span className="flex items-center gap-2">
              <Bell className="h-4 w-4 shrink-0" />
              {notifyPerm === "denied"
                ? "Desktop notifications are blocked. Allow them for this site in your browser to get a Windows popup for check-ins."
                : "Check-ins only show as an in-app modal on this tab. Enable desktop notifications to get a Windows popup even when the tab isn't focused."}
            </span>
            {notifyPerm !== "denied" && (
              <Button
                type="button"
                variant="secondary"
                className="shrink-0"
                onClick={enableNotifications}
              >
                Enable
              </Button>
            )}
          </div>
        )}
        {checkinInterval > 0 && notificationsSupported() && notifyPerm === "granted" && (
          <p className="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
            <Bell className="h-4 w-4" />
            Desktop notifications are on for check-ins.
          </p>
        )}

        <label className="flex items-start gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input
            type="checkbox"
            checked={autoActualDates}
            onChange={(e) => setAutoActualDates(e.target.checked)}
            className="mt-0.5 h-4 w-4"
          />
          <span>
            Auto-set actual dates from my work
            <span className="mt-0.5 block text-xs text-slate-400">
              When I finish a session, stamp the ticket's actual start (first
              time only) and actual end from the session, so I don't edit them by
              hand.
            </span>
          </span>
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
        <input
          type="checkbox"
          checked={usesTempo}
          onChange={(e) => setUsesTempo(e.target.checked)}
          className="h-4 w-4"
        />
        My organisation uses Tempo Timesheets
      </label>
      {usesTempo && (
        <Banner tone="info">
          Worklogs written through the standard Jira API may not appear in Tempo
          reports, because Tempo maintains its own worklog store.
        </Banner>
      )}

      <div className="flex items-center gap-3">
        <Button onClick={save} loading={update.isPending}>
          <Save className="h-4 w-4" />
          Save settings
        </Button>
        {justSaved && (
          <span className="text-sm font-medium text-emerald-500">Saved</span>
        )}
      </div>
      {update.isError && <Banner tone="error">{String(update.error)}</Banner>}
    </Card>
  );
}
