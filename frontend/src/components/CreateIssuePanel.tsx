// Create-new-issue flow (Phase 4). Two steps:
//
//   1. Draft: POST /api/issues/draft returns a suggested type, summary,
//      description, any required custom fields, and a duplicate warning.
//   2. Confirm: the user edits every field, then one explicit click creates the
//      issue (section 15 rule 1: never write to Jira without a confirmation).
//
// The duplicate guard (section 7) surfaces a blocking warning when an existing
// issue is >=0.8 similar, offering to log against it instead.

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Plus, Sparkles } from "lucide-react";
import { useCreateIssue, useDraftIssue } from "../api/hooks";
import type { DraftResponse, RequiredField } from "../api/types";
import { Banner, Button, Label, TextArea, TextInput } from "./ui";

export function CreateIssuePanel({
  boardId,
  text,
  parentKey,
  autoStart = false,
  onCreated,
  onUseExisting,
}: {
  boardId: number;
  text: string;
  parentKey?: string | null;
  // When true, kick off the AI draft immediately (the user chose "Create new
  // ticket" up front rather than browsing matches first).
  autoStart?: boolean;
  onCreated: (issueKey: string) => void;
  onUseExisting: (issueKey: string) => void;
}) {
  const draft = useDraftIssue();
  const create = useCreateIssue();

  // Editable draft state, populated once the draft returns.
  const [form, setForm] = useState<DraftResponse | null>(null);
  const [extra, setExtra] = useState<Record<string, string>>({});
  const autoStarted = useRef(false);

  function startDraft() {
    draft.mutate(
      { board_id: boardId, text, parent_key: parentKey },
      { onSuccess: (d) => setForm(d) },
    );
  }

  // Auto-open the draft once if requested (create-first flow).
  useEffect(() => {
    if (autoStart && !autoStarted.current && text.trim() && !form && !draft.isPending) {
      autoStarted.current = true;
      startDraft();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, text]);

  function submit() {
    if (!form) return;
    const fields = buildExtraFields(form.required_fields, extra);
    create.mutate(
      {
        board_id: boardId,
        project_key: form.project_key,
        type: form.issue_type,
        summary: form.summary,
        description: form.description,
        parent_key: form.parent_key,
        fields,
      },
      { onSuccess: (res) => onCreated(res.issue_key) },
    );
  }

  // Step 0: nothing drafted yet.
  if (!form) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-slate-500">
          No suitable ticket? Draft a new one from your description.
        </p>
        <Button onClick={startDraft} loading={draft.isPending} variant="secondary">
          <Sparkles className="h-4 w-4" />
          Draft a new issue
        </Button>
        {draft.isError && <Banner tone="error">{String(draft.error)}</Banner>}
      </div>
    );
  }

  const missingRequired = form.required_fields.filter(
    (f) => !((extra[f.field_id] ?? "").trim()),
  );

  // Step 1: confirmation form with every field editable.
  return (
    <div className="space-y-4">
      {form.duplicate && (
        <Banner tone="warning">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="space-y-2">
              <p>
                This looks very similar to{" "}
                <span className="font-mono font-semibold">
                  {form.duplicate.issue_key}
                </span>
                : {form.duplicate.summary} ({Math.round(form.duplicate.similarity * 100)}%
                match). Log against that instead?
              </p>
              <Button
                variant="secondary"
                onClick={() => onUseExisting(form.duplicate!.issue_key)}
              >
                Use {form.duplicate.issue_key}
              </Button>
            </div>
          </div>
        </Banner>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label>Type</Label>
          <select
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            value={form.issue_type}
            onChange={(e) => setForm({ ...form, issue_type: e.target.value })}
          >
            <option value="Story">Story</option>
            <option value="Task">Task</option>
            <option value="Bug">Bug</option>
            <option value="Sub-task">Sub-task</option>
          </select>
        </div>
        <div>
          <Label>Project</Label>
          <TextInput value={form.project_key} disabled />
        </div>
      </div>

      {(form.issue_type === "Sub-task" || form.parent_key) && (
        <div>
          <Label>Parent issue key</Label>
          <TextInput
            placeholder="e.g. PAY-431"
            value={form.parent_key ?? ""}
            onChange={(e) => setForm({ ...form, parent_key: e.target.value || null })}
          />
        </div>
      )}

      <div>
        <Label>Summary</Label>
        <TextInput
          value={form.summary}
          onChange={(e) => setForm({ ...form, summary: e.target.value })}
        />
      </div>

      <div>
        <Label>Description</Label>
        <TextArea
          rows={5}
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
      </div>

      {form.required_fields.map((f) => (
        <RequiredFieldInput
          key={f.field_id}
          field={f}
          value={extra[f.field_id] ?? ""}
          onChange={(v) => setExtra({ ...extra, [f.field_id]: v })}
        />
      ))}

      <div className="flex items-center gap-3">
        <Button
          onClick={submit}
          loading={create.isPending}
          disabled={
            !form.summary.trim() ||
            missingRequired.length > 0 ||
            (form.issue_type === "Sub-task" && !form.parent_key)
          }
        >
          <Plus className="h-4 w-4" />
          Create {form.issue_type}
        </Button>
        <Button variant="ghost" onClick={() => setForm(null)}>
          Cancel
        </Button>
      </div>

      {create.isError && <Banner tone="error">{String(create.error)}</Banner>}
    </div>
  );
}

// A single required custom field. Renders a select for option types with known
// allowed values, otherwise a text input.
function RequiredFieldInput({
  field,
  value,
  onChange,
}: {
  field: RequiredField;
  value: string;
  onChange: (v: string) => void;
}) {
  const hasOptions = field.allowed_values.length > 0;
  return (
    <div>
      <Label>
        {field.name} <span className="text-rose-500">*</span>
      </Label>
      {hasOptions ? (
        <select
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Select...</option>
          {field.allowed_values.map((av) => {
            const label = av.value ?? av.name ?? av.id ?? "";
            const key = av.id ?? label;
            return (
              <option key={key} value={label}>
                {label}
              </option>
            );
          })}
        </select>
      ) : (
        <TextInput value={value} onChange={(e) => onChange(e.target.value)} />
      )}
    </div>
  );
}

// Shape the user's required-field answers into the Jira fields payload. Option
// types take {value: ...}; everything else is sent as a plain string.
function buildExtraFields(
  required: RequiredField[],
  answers: Record<string, string>,
): Record<string, unknown> | null {
  const out: Record<string, unknown> = {};
  for (const f of required) {
    const v = (answers[f.field_id] ?? "").trim();
    if (!v) continue;
    out[f.field_id] =
      f.schema_type === "option" || f.allowed_values.length > 0 ? { value: v } : v;
  }
  return Object.keys(out).length > 0 ? out : null;
}
