// A ranked match candidate card with a visible confidence percentage (section 6,
// section 11). Colour of the confidence pill tracks the preselect / create-lead
// thresholds so the user can see at a glance how sure the matcher is.

import { CircleDot, GitBranch, Layers, User, UserCheck } from "lucide-react";
import type { MatchCandidate } from "../api/types";

function typeIcon(issueType: string | null) {
  if (issueType === "Sub-task") return <GitBranch className="h-4 w-4 text-sky-500" />;
  if (issueType === "Bug") return <CircleDot className="h-4 w-4 text-rose-500" />;
  return <Layers className="h-4 w-4 text-indigo-500" />;
}

function confidenceTone(pct: number): string {
  if (pct >= 75) return "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300";
  if (pct >= 45) return "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300";
  return "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400";
}

// Who owns this ticket. "Mine" is called out distinctly (green) because the
// board scope can include everyone's tickets, and telling yours apart is the
// whole point; someone else's shows their name; unassigned is muted.
function AssigneeTag({ candidate }: { candidate: MatchCandidate }) {
  if (candidate.is_mine) {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
        <UserCheck className="h-3 w-3" />
        Mine
      </span>
    );
  }
  if (candidate.assignee_name) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-slate-400">
        <User className="h-3 w-3" />
        {candidate.assignee_name}
      </span>
    );
  }
  return <span className="text-[10px] italic text-slate-400">Unassigned</span>;
}

export function CandidateCard({
  candidate,
  onSelect,
  highlight = false,
}: {
  candidate: MatchCandidate;
  onSelect: (c: MatchCandidate) => void;
  highlight?: boolean;
}) {
  return (
    <button
      onClick={() => onSelect(candidate)}
      className={`flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
        highlight
          ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950"
          : "border-slate-200 hover:border-indigo-300 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800"
      }`}
    >
      <span className="mt-0.5">{typeIcon(candidate.issue_type)}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
            {candidate.issue_key}
          </span>
          {candidate.status && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500 dark:bg-slate-800">
              {candidate.status}
            </span>
          )}
          {candidate.sprint_name && (
            <span className="text-[10px] text-slate-400">{candidate.sprint_name}</span>
          )}
          <AssigneeTag candidate={candidate} />
        </span>
        <span className="mt-0.5 block truncate text-sm text-slate-800 dark:text-slate-200">
          {candidate.summary}
        </span>
        <span className="mt-1 block text-[11px] text-slate-400">{candidate.reason}</span>
      </span>
      <span
        className={`shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${confidenceTone(
          candidate.confidence_pct,
        )}`}
        title={`bm25 ${candidate.bm25} · embedding ${candidate.embedding} · recency ${candidate.recency}`}
      >
        {candidate.confidence_pct}%
      </span>
    </button>
  );
}
