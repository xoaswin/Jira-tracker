// A filterable list of cached issues (Phase 1: plain manual selection, no ranking).

import { useMemo, useState } from "react";
import { CircleDot, GitBranch, Layers } from "lucide-react";
import type { Issue } from "../api/types";
import { TextInput } from "./ui";

function typeIcon(issueType: string | null) {
  if (issueType === "Sub-task") return <GitBranch className="h-4 w-4 text-sky-500" />;
  if (issueType === "Bug") return <CircleDot className="h-4 w-4 text-rose-500" />;
  return <Layers className="h-4 w-4 text-indigo-500" />;
}

export function IssueList({
  issues,
  onSelect,
  selectedKey,
}: {
  issues: Issue[];
  onSelect: (issue: Issue) => void;
  selectedKey?: string | null;
}) {
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return issues;
    return issues.filter(
      (i) =>
        i.issue_key.toLowerCase().includes(q) ||
        i.summary.toLowerCase().includes(q) ||
        (i.description_text ?? "").toLowerCase().includes(q),
    );
  }, [issues, filter]);

  return (
    <div className="space-y-3">
      <TextInput
        placeholder="Filter by key or summary..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {filtered.length === 0 && (
        <p className="py-6 text-center text-sm text-slate-400">
          No matching issues. Try refreshing this board.
        </p>
      )}
      <ul className="space-y-2">
        {filtered.map((issue) => (
          <li key={issue.id}>
            <button
              onClick={() => onSelect(issue)}
              className={`flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
                selectedKey === issue.issue_key
                  ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950"
                  : "border-slate-200 hover:border-indigo-300 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800"
              }`}
            >
              <span className="mt-0.5">{typeIcon(issue.issue_type)}</span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
                    {issue.issue_key}
                  </span>
                  {issue.status && (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500 dark:bg-slate-800">
                      {issue.status}
                    </span>
                  )}
                  {issue.sprint_name && (
                    <span className="text-[10px] text-slate-400">
                      {issue.sprint_name}
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block truncate text-sm text-slate-800 dark:text-slate-200">
                  {issue.summary}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
