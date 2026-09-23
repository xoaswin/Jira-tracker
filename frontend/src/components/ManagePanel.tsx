// Shared ticket-management panel: drive a ticket's workflow (auto-walk),
// edit its date fields (start / due / actual start / actual end, whatever is
// editable per editmeta), and complete its subtasks (parent Done is blocked
// until every subtask is Done).
//
// Consumers supply their own identity chrome (the Active Session timer card,
// or a collapsible card header on the Manage screen), so this renders only the
// management controls plus the ticket summary + status line.

import { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  Copy as CopyIcon,
  Flag,
  Plus,
  Save,
  User,
} from "lucide-react";
import {
  useAddWorklog,
  useAssignableUsers,
  useCreateSubtask,
  useEditDates,
  useManageView,
  useMarkDone,
  usePriorities,
  useSetAssignee,
  useSetPriority,
  useTransitionIssue,
  useTransitionSubtask,
  useWorklogs,
} from "../api/hooks";
import { ApiError } from "../api/client";
import type { DateField, ManageView, Subtask } from "../api/types";
import { formatDuration } from "../lib/time";
import { Banner, Button, Label, Spinner, TextArea, TextInput } from "./ui";

export function categoryTone(cat: string | null): string {
  if (cat === "Done") return "text-emerald-500";
  if (cat === "In Progress") return "text-sky-500";
  return "text-slate-400";
}

export function ManagePanel({ data }: { data: ManageView }) {
  const key = data.issue_key;
  const editDates = useEditDates(key);
  const transition = useTransitionIssue(key);
  const markDone = useMarkDone(key);

  // Local editable copy of date values.
  const [dates, setDates] = useState<Record<string, string>>(() =>
    Object.fromEntries(data.date_fields.map((f) => [f.field_id, f.value ?? ""])),
  );
  const [savedDates, setSavedDates] = useState(false);

  const allSubtasksDone = data.subtasks.every((s) => s.is_done);
  const doneBlocked = data.subtasks.length > 0 && !allSubtasksDone;

  function saveDates() {
    editDates.mutate(dates, {
      onSuccess: () => {
        setSavedDates(true);
        window.setTimeout(() => setSavedDates(false), 2500);
      },
    });
  }

  return (
    <div className="space-y-5">
      {/* Ticket summary + current status. */}
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-slate-700 dark:text-slate-200">{data.summary}</p>
        <span
          className={`shrink-0 text-xs font-semibold ${categoryTone(data.status_category)}`}
        >
          {data.status ?? "unknown"}
        </span>
      </div>

      {/* Assignee + priority */}
      <AssigneeAndPriority data={data} />

      {/* Workflow transitions */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
          Status
        </h2>
        <div className="flex flex-wrap gap-2">
          {data.available_transitions.length === 0 && (
            <span className="text-sm text-slate-400">
              No transitions available from {data.status}.
            </span>
          )}
          {data.available_transitions.map((t) => (
            <Button
              key={t.id}
              variant="secondary"
              loading={transition.isPending}
              onClick={() => transition.mutate(t.to || t.name || "")}
            >
              <ArrowRight className="h-4 w-4" />
              {t.name}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-3 pt-1">
          <Button
            onClick={() => markDone.mutate()}
            loading={markDone.isPending}
            disabled={doneBlocked || data.status_category === "Done"}
            title={
              doneBlocked
                ? "Finish all subtasks first"
                : "Auto-walk this ticket to Done"
            }
          >
            <CheckCircle2 className="h-4 w-4" />
            Mark Done
          </Button>
          {doneBlocked && (
            <span className="text-xs text-amber-500">
              Blocked: {data.subtasks.filter((s) => !s.is_done).length} subtask(s)
              not Done.
            </span>
          )}
          {transition.data && transition.data.applied.length > 0 && (
            <span className="text-xs text-slate-400">
              Applied: {transition.data.applied.join(" -> ")}
            </span>
          )}
        </div>
        {(transition.isError || markDone.isError) && (
          <Banner tone="error">
            {String(transition.error ?? markDone.error)}
          </Banner>
        )}
      </div>

      {/* Editable dates */}
      {data.date_fields.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
            Dates
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {data.date_fields.map((f: DateField) => (
              <div key={f.field_id}>
                <Label>{f.name}</Label>
                <TextInput
                  type={f.schema_type === "datetime" ? "datetime-local" : "date"}
                  value={dates[f.field_id] ?? ""}
                  onChange={(e) =>
                    setDates({ ...dates, [f.field_id]: e.target.value })
                  }
                />
              </div>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <Button onClick={saveDates} loading={editDates.isPending}>
              <Save className="h-4 w-4" />
              Save dates
            </Button>
            {savedDates && (
              <span className="text-sm font-medium text-emerald-500">Saved</span>
            )}
          </div>
          {editDates.isError && (
            <Banner tone="error">{String(editDates.error)}</Banner>
          )}
        </div>
      )}

      {/* Log work */}
      <LogWork issueKey={key} />

      {/* Subtasks. Shown for any non-subtask issue so the FIRST subtask can be
          added too (a sub-task itself cannot have children, so hide it there). */}
      {(data.issue_type ?? "").toLowerCase().replace(" ", "-") !== "sub-task" && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
            Subtasks ({data.subtasks.filter((s) => s.is_done).length}/
            {data.subtasks.length} done)
          </h2>
          {data.subtasks.length > 0 && (
            <ul className="space-y-2">
              {data.subtasks.map((s) => (
                <SubtaskRow
                  key={s.issue_key}
                  parentKey={key}
                  subtask={s}
                  parentDates={data.date_fields}
                />
              ))}
            </ul>
          )}
          <AddSubtask parentKey={key} />
        </div>
      )}
    </div>
  );
}

// Reassign the ticket and change its priority, the two most common edits after
// dates/status. Assignee uses Jira's assignable-user type-ahead (only people
// who can actually be assigned this issue); priority is the instance's list.
function AssigneeAndPriority({ data }: { data: ManageView }) {
  const key = data.issue_key;
  const [pickingAssignee, setPickingAssignee] = useState(false);
  const [query, setQuery] = useState("");

  const priorities = usePriorities(key, true);
  const assignable = useAssignableUsers(key, query, pickingAssignee);
  const setAssignee = useSetAssignee(key);
  const setPriority = useSetPriority(key);

  function assign(accountId: string | null) {
    setAssignee.mutate(accountId, {
      onSuccess: () => {
        setPickingAssignee(false);
        setQuery("");
      },
    });
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {/* Assignee */}
      <div>
        <Label>Assignee</Label>
        {pickingAssignee ? (
          <div className="space-y-1">
            <TextInput
              autoFocus
              placeholder="Search people..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="max-h-40 overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-800">
              <button
                onClick={() => assign(null)}
                className="block w-full px-3 py-1.5 text-left text-xs text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-800"
              >
                Unassign
              </button>
              {assignable.isLoading && (
                <div className="px-3 py-1.5">
                  <Spinner />
                </div>
              )}
              {assignable.data?.map((u) => (
                <button
                  key={u.account_id ?? u.display_name}
                  onClick={() => assign(u.account_id)}
                  className="block w-full px-3 py-1.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
                >
                  {u.display_name}
                  {u.email && (
                    <span className="ml-1 text-xs text-slate-400">{u.email}</span>
                  )}
                </button>
              ))}
              {assignable.data && assignable.data.length === 0 && !assignable.isLoading && (
                <p className="px-3 py-1.5 text-xs text-slate-400">No matches.</p>
              )}
            </div>
            <button
              onClick={() => setPickingAssignee(false)}
              className="text-xs text-slate-400 hover:underline"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setPickingAssignee(true)}
            disabled={setAssignee.isPending}
            className="flex w-full items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-left text-sm hover:border-indigo-300 disabled:opacity-50 dark:border-slate-700"
          >
            <User className="h-4 w-4 text-slate-400" />
            {setAssignee.isPending
              ? "Saving..."
              : (data.assignee_name ?? "Unassigned")}
          </button>
        )}
        {setAssignee.isError && (
          <Banner tone="error">{String(setAssignee.error)}</Banner>
        )}
      </div>

      {/* Priority */}
      <div>
        <Label>Priority</Label>
        <div className="relative">
          <Flag className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <select
            className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm dark:border-slate-700 dark:bg-slate-950 disabled:opacity-50"
            value={data.priority_id ?? ""}
            disabled={setPriority.isPending || !priorities.data}
            onChange={(e) => e.target.value && setPriority.mutate(e.target.value)}
          >
            {!data.priority_id && <option value="">Not set</option>}
            {priorities.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        {setPriority.isError && (
          <Banner tone="error">{String(setPriority.error)}</Banner>
        )}
      </div>
    </div>
  );
}

// Log time against this ticket directly (outside a timed session), plus a list
// of recent worklogs so you can see what has already been logged. Posts a real
// Jira worklog via the same machinery the timer's finish flow uses.
function LogWork({ issueKey }: { issueKey: string }) {
  const [hours, setHours] = useState("");
  const [minutes, setMinutes] = useState("");
  const [started, setStarted] = useState(""); // datetime-local; empty = now
  const [comment, setComment] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const worklogs = useWorklogs(issueKey);
  const add = useAddWorklog(issueKey);

  const h = parseInt(hours, 10) || 0;
  const m = parseInt(minutes, 10) || 0;
  const hasTime = h > 0 || m > 0;

  function submit() {
    // Guard against double-submit: ignore clicks while a request is in flight.
    // (The server also dedupes identical worklogs, but this avoids the round
    // trip and any flicker.)
    if (add.isPending || !hasTime) return;
    setNote(null);
    add.mutate(
      {
        hours: h,
        minutes: m,
        started: started ? started : null,
        comment: comment.trim() || null,
      },
      {
        onSuccess: (res) => {
          setHours("");
          setMinutes("");
          setStarted("");
          setComment("");
          setNote(
            res.rounded_up
              ? "Logged (rounded up to Jira's 1-minute minimum)."
              : "Logged.",
          );
          window.setTimeout(() => setNote(null), 3000);
        },
      },
    );
  }

  return (
    <div className="space-y-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
        <Clock className="h-4 w-4" />
        Log work
      </h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label>Hours</Label>
          <TextInput
            type="number"
            min={0}
            placeholder="0"
            value={hours}
            onChange={(e) => setHours(e.target.value)}
          />
        </div>
        <div>
          <Label>Minutes</Label>
          <TextInput
            type="number"
            min={0}
            max={59}
            placeholder="0"
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          />
        </div>
        <div>
          <Label>Started (optional)</Label>
          <TextInput
            type="datetime-local"
            value={started}
            onChange={(e) => setStarted(e.target.value)}
          />
        </div>
      </div>
      <div>
        <Label>Comment (optional)</Label>
        <TextArea
          rows={2}
          placeholder="What did you work on?"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={submit} loading={add.isPending} disabled={!hasTime}>
          <Plus className="h-4 w-4" />
          Log work
        </Button>
        {note && <span className="text-sm font-medium text-emerald-500">{note}</span>}
        {!hasTime && (
          <span className="text-xs text-slate-400">Enter hours or minutes.</span>
        )}
      </div>
      {add.isError && (
        <Banner tone="error">
          {add.error instanceof ApiError
            ? JSON.stringify(add.error.detail)
            : String(add.error)}
        </Banner>
      )}

      {/* Recent worklogs */}
      {worklogs.data && worklogs.data.length > 0 && (
        <ul className="space-y-1 border-t border-slate-100 pt-2 dark:border-slate-800">
          {worklogs.data.slice(0, 5).map((w) => (
            <li
              key={w.id}
              className="flex items-start justify-between gap-3 text-xs text-slate-500"
            >
              <span className="min-w-0">
                <span className="font-mono font-semibold text-slate-600 dark:text-slate-300">
                  {formatDuration(w.time_spent_seconds)}
                </span>
                {w.comment && <span className="ml-2 truncate">{w.comment}</span>}
              </span>
              <span className="shrink-0 whitespace-nowrap text-slate-400">
                {w.started ? new Date(w.started).toLocaleDateString() : ""}
                {w.author ? ` · ${w.author}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Inline "add a subtask" under the current story/task/bug. Creates a Sub-task
// with the parent set (the backend resolves the project's actual sub-task type),
// then the parent view refreshes to show it.
function AddSubtask({ parentKey }: { parentKey: string }) {
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState("");
  const create = useCreateSubtask(parentKey);

  function submit() {
    if (!summary.trim() || create.isPending) return;
    create.mutate(summary.trim(), {
      onSuccess: () => {
        setSummary("");
        setOpen(false);
      },
    });
  }

  if (!open) {
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" />
        Add subtask
      </Button>
    );
  }

  return (
    <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <Label>New subtask</Label>
      <TextInput
        autoFocus
        placeholder="What needs doing?"
        value={summary}
        onChange={(e) => setSummary(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      <div className="flex items-center gap-2">
        <Button onClick={submit} loading={create.isPending} disabled={!summary.trim()}>
          <Plus className="h-4 w-4" />
          Create
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            setOpen(false);
            setSummary("");
          }}
        >
          Cancel
        </Button>
      </div>
      {create.isError && (
        <Banner tone="error">
          {create.error instanceof ApiError
            ? JSON.stringify(create.error.detail)
            : String(create.error)}
        </Banner>
      )}
    </div>
  );
}

// One subtask: shows status + Mark Done, and expands to edit ITS OWN dates.
// Needed because a subtask's "Done" transition can have validators requiring
// fields like Actual start / Actual end to be filled first.
function SubtaskRow({
  parentKey,
  subtask,
  parentDates,
}: {
  parentKey: string;
  subtask: Subtask;
  parentDates: DateField[];
}) {
  const [editing, setEditing] = useState(false);
  // Load the subtask's own manageable view (its editable date fields) only when
  // expanded, to avoid a fetch per subtask up front.
  const sub = useManageView(editing ? subtask.issue_key : null);
  const editDates = useEditDates(subtask.issue_key);
  const subtaskT = useTransitionSubtask(parentKey);
  const [dates, setDates] = useState<Record<string, string>>({});
  const [savedDates, setSavedDates] = useState(false);

  // Seed the date inputs from the subtask's own editable fields once loaded.
  useEffect(() => {
    if (sub.data?.issue_key === subtask.issue_key) {
      setDates(
        Object.fromEntries(
          sub.data.date_fields.map((f) => [f.field_id, f.value ?? ""]),
        ),
      );
    }
  }, [sub.data, subtask.issue_key]);

  function saveDates() {
    editDates.mutate(dates, {
      onSuccess: () => {
        setSavedDates(true);
        window.setTimeout(() => setSavedDates(false), 2500);
      },
    });
  }

  // Copy the parent's date values into this subtask's inputs, matching by field
  // id (custom-field ids are stable within a project). Only fills fields the
  // subtask actually has and the parent has a value for; leaves the rest.
  const parentByField = new Map(parentDates.map((f) => [f.field_id, f.value]));
  const copyableFields = (sub.data?.date_fields ?? []).filter(
    (f) => parentByField.get(f.field_id),
  );
  function copyFromParent() {
    const next = { ...dates };
    for (const f of copyableFields) {
      next[f.field_id] = parentByField.get(f.field_id) ?? "";
    }
    setDates(next);
  }

  return (
    <li className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="mr-2 font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
            {subtask.issue_key}
          </span>
          <span className="text-sm">{subtask.summary}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`text-xs ${categoryTone(subtask.status_category)}`}>
            {subtask.status}
          </span>
          <Button variant="ghost" onClick={() => setEditing((v) => !v)}>
            {editing ? "Hide" : "Dates"}
          </Button>
          {subtask.is_done ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : (
            <Button
              variant="ghost"
              loading={subtaskT.isPending}
              onClick={() =>
                subtaskT.mutate({ subtaskKey: subtask.issue_key, target: "Done" })
              }
            >
              Mark Done
            </Button>
          )}
        </div>
      </div>

      {editing && (
        <div className="mt-3 space-y-3 border-t border-slate-100 pt-3 dark:border-slate-800">
          {sub.isLoading && <Spinner />}
          {sub.data && sub.data.date_fields.length === 0 && (
            <p className="text-xs text-slate-400">No editable date fields on this subtask.</p>
          )}
          {sub.data && sub.data.date_fields.length > 0 && (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                {sub.data.date_fields.map((f) => (
                  <div key={f.field_id}>
                    <Label>{f.name}</Label>
                    <TextInput
                      type={f.schema_type === "datetime" ? "datetime-local" : "date"}
                      value={dates[f.field_id] ?? ""}
                      onChange={(e) =>
                        setDates({ ...dates, [f.field_id]: e.target.value })
                      }
                    />
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={saveDates} loading={editDates.isPending}>
                  <Save className="h-4 w-4" />
                  Save dates
                </Button>
                <Button
                  variant="secondary"
                  onClick={copyFromParent}
                  disabled={copyableFields.length === 0}
                  title={
                    copyableFields.length === 0
                      ? `${parentKey} has no dates set to copy`
                      : `Copy matching dates from ${parentKey}`
                  }
                >
                  <CopyIcon className="h-4 w-4" />
                  Same as parent
                </Button>
                {savedDates && (
                  <span className="text-sm font-medium text-emerald-500">Saved</span>
                )}
              </div>
              <p className="text-xs text-slate-400">
                {copyableFields.length > 0
                  ? `Fills matching date fields from ${parentKey}; review, then Save.`
                  : `${parentKey} has no date values set yet, so there's nothing to copy.`}
              </p>
            </>
          )}
          {editDates.isError && <Banner tone="error">{String(editDates.error)}</Banner>}
        </div>
      )}

      {subtaskT.isError && (
        <div className="mt-2">
          <Banner tone="error">{String(subtaskT.error)}</Banner>
        </div>
      )}
    </li>
  );
}
