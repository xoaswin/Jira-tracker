import { useEffect, useState } from "react";
import { CheckCircle2, GitCommit, Send, Sparkles, Undo2 } from "lucide-react";
import {
  useActiveSession,
  useAiStatus,
  useCleanupComment,
  useCompleteSession,
  useDraftWorklog,
} from "../api/hooks";
import type { CompleteResult } from "../api/types";
import { ApiError } from "../api/client";
import { useUi } from "../store/ui";
import { formatDuration, parseDurationToSeconds } from "../lib/time";
import { Banner, Button, Card, Label, Spinner, TextArea, TextInput } from "../components/ui";

export function Finish() {
  const active = useActiveSession();
  const complete = useCompleteSession();
  const cleanup = useCleanupComment();
  const draftWorklog = useDraftWorklog();
  const aiStatus = useAiStatus();
  const { setScreen, reset } = useUi();

  const session = active.data;
  const [durationText, setDurationText] = useState("");
  const [notes, setNotes] = useState("");
  const [transitionDone, setTransitionDone] = useState(false);
  const [result, setResult] = useState<CompleteResult | null>(null);
  // Holds the pre-AI notes so "improve with AI" can be undone.
  const [notesBeforeAi, setNotesBeforeAi] = useState<string | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  // A transient hint under the notes about the commit-draft result.
  const [draftHint, setDraftHint] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      setDurationText(formatDuration(session.elapsed_seconds ?? 0));
      setNotes(session.notes ?? "");
    }
  }, [session]);

  if (active.isLoading) return <Spinner />;
  if (!session && !result) {
    return <Banner tone="info">No session to finish.</Banner>;
  }

  const parsedSeconds = parseDurationToSeconds(durationText);
  const durationValid = parsedSeconds != null;
  const computed = session?.elapsed_seconds ?? 0;
  const durationChanged = durationValid && parsedSeconds !== computed;

  function improveWithAi() {
    if (!notes.trim()) return;
    setAiUnavailable(false);
    const before = notes;
    cleanup.mutate(before, {
      onSuccess: (res) => {
        if (res.used_ai) {
          setNotesBeforeAi(before);
          setNotes(res.text);
        } else {
          // Degraded to raw text (AI off/unreachable): surface a small hint.
          setAiUnavailable(true);
        }
      },
    });
  }

  function undoAi() {
    if (notesBeforeAi != null) {
      setNotes(notesBeforeAi);
      setNotesBeforeAi(null);
    }
  }

  function draftFromCommits() {
    if (!session?.issue_key) return;
    setDraftHint(null);
    setAiUnavailable(false);
    draftWorklog.mutate(
      { issueKey: session.issue_key, since: session.started_at },
      {
        onSuccess: (res) => {
          if (!res.repo_found) {
            setDraftHint(
              "No configured repo has a branch naming this ticket, so there were no commits to draft from.",
            );
            return;
          }
          if (!res.text) {
            setDraftHint(
              "No commits found on that repo since this session started.",
            );
            return;
          }
          // Snapshot current notes so this can be undone; append the draft if
          // notes already exist, else replace.
          setNotesBeforeAi(notes);
          setNotes((prev) => (prev.trim() ? `${prev.trim()}\n\n${res.text}` : res.text));
          setDraftHint(
            res.used_ai
              ? `Drafted from ${res.commit_count} commit${res.commit_count === 1 ? "" : "s"}.`
              : `AI is off; inserted ${res.commit_count} commit message${res.commit_count === 1 ? "" : "s"} as-is.`,
          );
        },
      },
    );
  }

  function confirm() {
    if (!session || parsedSeconds == null) return;
    complete.mutate(
      {
        id: session.id,
        payload: {
          notes,
          adjusted_seconds: durationChanged ? parsedSeconds : undefined,
          transition_to: transitionDone ? "Done" : undefined,
        },
      },
      { onSuccess: (res) => setResult(res) },
    );
  }

  if (result) {
    const ok = result.session.sync_state === "synced";
    return (
      <div className="mx-auto max-w-lg space-y-5">
        <Card className="space-y-4 text-center">
          <CheckCircle2
            className={`mx-auto h-12 w-12 ${ok ? "text-emerald-500" : "text-amber-500"}`}
          />
          <div>
            <h1 className="text-xl font-semibold">
              {ok ? "Logged to Jira" : "Saved locally"}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {formatDuration(result.duration_seconds)}
              {result.session.issue_key ? ` on ${result.session.issue_key}` : ""}
            </p>
          </div>
          {result.warning && <Banner tone="warning">{result.warning}</Banner>}
          {result.session.sync_error && !result.warning && (
            <Banner tone="error">{result.session.sync_error}</Banner>
          )}
          <div className="flex justify-center gap-3">
            <Button
              onClick={() => {
                reset();
                setScreen("start");
              }}
            >
              New session
            </Button>
            <Button variant="secondary" onClick={() => setScreen("dashboard")}>
              View dashboard
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg space-y-5">
      <h1 className="text-2xl font-semibold">Finish session</h1>

      <Card className="space-y-4">
        <div>
          <Label>Duration</Label>
          <TextInput
            value={durationText}
            onChange={(e) => setDurationText(e.target.value)}
          />
          {!durationValid && (
            <p className="mt-1 text-xs text-rose-500">
              Enter something like "1h 30m", "90m", or "45s".
            </p>
          )}
          {durationChanged && durationValid && (
            <p className="mt-1 text-xs text-slate-400">
              Overriding the tracked time of {formatDuration(computed)}.
            </p>
          )}
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between">
            <Label>Notes (pushed as a worklog comment)</Label>
            <div className="flex items-center gap-2">
              {notesBeforeAi != null && (
                <Button variant="ghost" onClick={undoAi}>
                  <Undo2 className="h-3.5 w-3.5" />
                  Undo
                </Button>
              )}
              {session?.issue_key && (
                <Button
                  variant="ghost"
                  onClick={draftFromCommits}
                  loading={draftWorklog.isPending}
                  title="Draft the comment from this repo's commits since you started"
                >
                  <GitCommit className="h-3.5 w-3.5" />
                  Draft from commits
                </Button>
              )}
              <Button
                variant="ghost"
                onClick={improveWithAi}
                loading={cleanup.isPending}
                disabled={!notes.trim()}
                title={
                  aiStatus.data?.available
                    ? "Rewrite the notes with AI"
                    : "AI is not available; will keep your text"
                }
              >
                <Sparkles className="h-3.5 w-3.5" />
                Improve with AI
              </Button>
            </div>
          </div>
          <TextArea
            rows={5}
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              setNotesBeforeAi(null); // manual edits discard the undo snapshot
              setDraftHint(null);
            }}
            placeholder="Rough notes on what you did."
          />
          {aiUnavailable && (
            <p className="mt-1 text-xs text-amber-500">
              AI unavailable, kept your text unchanged.
            </p>
          )}
          {draftHint && (
            <p className="mt-1 text-xs text-slate-400">{draftHint}</p>
          )}
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input
            type="checkbox"
            checked={transitionDone}
            onChange={(e) => setTransitionDone(e.target.checked)}
            className="h-4 w-4"
          />
          Move ticket to Done (skipped silently if no such transition)
        </label>

        {complete.isError && (
          <Banner tone="error">
            {complete.error instanceof ApiError
              ? JSON.stringify(complete.error.detail)
              : String(complete.error)}
          </Banner>
        )}

        <div className="flex gap-3">
          <Button
            onClick={confirm}
            loading={complete.isPending}
            disabled={!durationValid}
          >
            <Send className="h-4 w-4" />
            Confirm and push
          </Button>
          <Button variant="ghost" onClick={() => setScreen("active")}>
            Back
          </Button>
        </div>
      </Card>
    </div>
  );
}
