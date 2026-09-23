// Manual time entry (log past work without a live timer). Creates a completed
// session with an explicit duration and pushes it through the outbox.

import { useState } from "react";
import { Check, Clock } from "lucide-react";
import { useManualSession } from "../api/hooks";
import { parseDurationToSeconds } from "../lib/time";
import { Banner, Button, Card, Label, TextArea, TextInput } from "./ui";

export function ManualEntry() {
  const manual = useManualSession();
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState("");
  const [issueKey, setIssueKey] = useState("");
  const [durationText, setDurationText] = useState("");
  const [notes, setNotes] = useState("");
  const [when, setWhen] = useState(""); // datetime-local, optional
  const [justLogged, setJustLogged] = useState(false);

  const seconds = parseDurationToSeconds(durationText);
  const valid = description.trim().length > 0 && seconds != null && seconds > 0;

  function submit() {
    if (!valid || seconds == null) return;
    manual.mutate(
      {
        description: description.trim(),
        duration_seconds: seconds,
        issue_key: issueKey.trim() || null,
        notes: notes.trim() || null,
        // datetime-local has no timezone; send as-is and let the server treat it
        // as the start instant. Omit if not provided.
        started_at: when ? new Date(when).toISOString() : null,
      },
      {
        onSuccess: () => {
          setJustLogged(true);
          setDescription("");
          setIssueKey("");
          setDurationText("");
          setNotes("");
          setWhen("");
          window.setTimeout(() => setJustLogged(false), 3000);
        },
      },
    );
  }

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <Clock className="h-4 w-4" />
        Log time manually
      </Button>
    );
  }

  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
          <Clock className="h-4 w-4 text-indigo-500" />
          Log time manually
        </h2>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>

      <div>
        <Label>What did you work on?</Label>
        <TextInput
          placeholder="e.g. reviewed the migration runbook"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label>Ticket (optional)</Label>
          <TextInput
            placeholder="e.g. PAY-431"
            value={issueKey}
            onChange={(e) => setIssueKey(e.target.value.toUpperCase())}
          />
        </div>
        <div>
          <Label>Duration</Label>
          <TextInput
            placeholder='e.g. "1h 30m" or "90m"'
            value={durationText}
            onChange={(e) => setDurationText(e.target.value)}
          />
          {durationText && seconds == null && (
            <p className="mt-1 text-xs text-rose-500">
              Try "1h 30m", "90m", or "45s".
            </p>
          )}
        </div>
      </div>

      <div>
        <Label>When did it start? (optional)</Label>
        <TextInput
          type="datetime-local"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
        />
      </div>

      <div>
        <Label>Notes (pushed as a worklog comment, optional)</Label>
        <TextArea
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={submit} loading={manual.isPending} disabled={!valid}>
          <Check className="h-4 w-4" />
          Log it
        </Button>
        {justLogged && (
          <span className="text-sm font-medium text-emerald-500">Logged</span>
        )}
      </div>

      {!issueKey.trim() && (
        <p className="text-xs text-slate-400">
          No ticket: this is tracked locally but nothing is pushed to Jira.
        </p>
      )}
      {manual.isError && <Banner tone="error">{String(manual.error)}</Banner>}
    </Card>
  );
}
