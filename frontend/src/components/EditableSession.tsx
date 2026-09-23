// Edit a completed session and re-sync it to Jira. For fixing a wrong ticket,
// notes, or duration after the fact. Re-push updates the existing worklog in
// place when already synced (no duplicate), else enqueues a fresh push.

import { useState } from "react";
import { Pencil, Save } from "lucide-react";
import { useRepushSession, useUpdateSession } from "../api/hooks";
import type { WorkSession } from "../api/types";
import { formatDuration, parseDurationToSeconds } from "../lib/time";
import { Banner, Button, Label, TextArea, TextInput } from "./ui";

export function EditableSession({ session }: { session: WorkSession }) {
  const update = useUpdateSession();
  const repush = useRepushSession();
  const [editing, setEditing] = useState(false);

  const [issueKey, setIssueKey] = useState(session.issue_key ?? "");
  const [notes, setNotes] = useState(session.notes ?? "");
  const [durationText, setDurationText] = useState(
    formatDuration(session.elapsed_seconds ?? 0),
  );

  const seconds = parseDurationToSeconds(durationText);
  const durationValid = seconds != null;

  async function saveAndResync() {
    if (!durationValid) return;
    // Persist the edits first, then re-push.
    await update.mutateAsync({
      id: session.id,
      patch: {
        issue_key: issueKey.trim() || undefined,
        notes,
        adjusted_seconds: seconds ?? undefined,
      },
    });
    await repush.mutateAsync(session.id);
    setEditing(false);
  }

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-indigo-500"
        title="Fix the ticket, notes, or duration and re-sync"
      >
        <Pencil className="h-3.5 w-3.5" />
        Edit
      </button>
    );
  }

  const busy = update.isPending || repush.isPending;

  return (
    <div className="mt-2 space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label>Ticket</Label>
          <TextInput
            value={issueKey}
            placeholder="e.g. PAY-431"
            onChange={(e) => setIssueKey(e.target.value.toUpperCase())}
          />
        </div>
        <div>
          <Label>Duration</Label>
          <TextInput
            value={durationText}
            onChange={(e) => setDurationText(e.target.value)}
          />
          {!durationValid && (
            <p className="mt-1 text-xs text-rose-500">Try "1h 30m" or "90m".</p>
          )}
        </div>
      </div>
      <div>
        <Label>Notes</Label>
        <TextArea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      <div className="flex items-center gap-2">
        <Button onClick={saveAndResync} loading={busy} disabled={!durationValid}>
          <Save className="h-4 w-4" />
          Save and re-sync
        </Button>
        <Button variant="ghost" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
      {repush.data && (
        <Banner tone={repush.data.sync_state === "synced" ? "success" : "warning"}>
          {repush.data.sync_state === "synced"
            ? "Re-synced to Jira."
            : `Status: ${repush.data.sync_state}. ${repush.data.sync_error ?? ""}`}
        </Banner>
      )}
      {(update.isError || repush.isError) && (
        <Banner tone="error">{String(update.error ?? repush.error)}</Banner>
      )}
    </div>
  );
}
