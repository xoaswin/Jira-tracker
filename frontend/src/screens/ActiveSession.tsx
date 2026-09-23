import { useEffect, useRef, useState } from "react";
import { ExternalLink, Pause, Play, Square, Trash2 } from "lucide-react";
import {
  useAbandonSession,
  useActiveSession,
  useAuthStatus,
  useManageView,
  usePauseSession,
  useResumeSession,
  useUpdateSession,
} from "../api/hooks";
import { useUi } from "../store/ui";
import { Banner, Button, Card, Spinner, TextArea } from "../components/ui";
import { ManagePanel } from "../components/ManagePanel";
import { EstimateBudget } from "../components/EstimateBudget";
import { ApiError } from "../api/client";
import { Timer } from "../components/Timer";

export function ActiveSession() {
  const active = useActiveSession();
  const auth = useAuthStatus();
  const pause = usePauseSession();
  const resume = useResumeSession();
  const updateSession = useUpdateSession();
  const abandon = useAbandonSession();
  const { setScreen, reset } = useUi();

  const session = active.data;
  // Manage the attached ticket (status / dates / subtasks) inline. Only fetch
  // once a ticket is actually attached to the session.
  const manage = useManageView(session?.issue_key ?? null);
  const [notes, setNotes] = useState("");
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const loadedFor = useRef<number | null>(null);

  // Load notes from the session once (not on every refetch, to avoid clobbering typing).
  useEffect(() => {
    if (session && loadedFor.current !== session.id) {
      setNotes(session.notes ?? "");
      loadedFor.current = session.id;
    }
  }, [session]);

  // Autosave notes a couple of seconds after typing stops (section 11).
  useEffect(() => {
    if (!session) return;
    if (notes === (session.notes ?? "")) return;
    const id = setTimeout(() => {
      updateSession.mutate(
        { id: session.id, patch: { notes } },
        { onSuccess: () => setSavedAt(Date.now()) },
      );
    }, 1500);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes]);

  if (active.isLoading) return <Spinner />;
  if (!session) {
    return (
      <Banner tone="info">
        No active session. Start one from the Start screen.
      </Banner>
    );
  }

  const jiraUrl =
    session.issue_key && auth.data?.base_url
      ? `${auth.data.base_url}/browse/${session.issue_key}`
      : null;

  function discard() {
    // Leave the session without tracking anything: mark it abandoned (nothing
    // is pushed to Jira) and go back to Start. For accidental picks.
    abandon.mutate(session!.id, {
      onSuccess: () => {
        reset();
        setScreen("start");
      },
    });
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Card className="space-y-6 py-8">
        <Timer session={session} />

        {/* Mid-session budget vs learned estimate for this ticket's type. */}
        <EstimateBudget session={session} issueType={manage.data?.issue_type ?? null} />

        <div className="text-center">
          {session.issue_key ? (
            <a
              href={jiraUrl ?? "#"}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 font-mono text-sm font-semibold text-indigo-600 hover:underline dark:text-indigo-400"
            >
              {session.issue_key}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : (
            <span className="text-sm text-amber-600">No ticket attached yet</span>
          )}
          <p className="mt-1 text-sm text-slate-500">{session.description}</p>
        </div>

        <div className="flex justify-center gap-3">
          {session.state === "active" ? (
            <Button
              variant="secondary"
              loading={pause.isPending}
              onClick={() => pause.mutate(session.id)}
            >
              <Pause className="h-4 w-4" />
              Pause
            </Button>
          ) : (
            <Button
              variant="secondary"
              loading={resume.isPending}
              onClick={() => resume.mutate(session.id)}
            >
              <Play className="h-4 w-4" />
              Resume
            </Button>
          )}
          <Button onClick={() => setScreen("finish")}>
            <Square className="h-4 w-4" />
            Finish
          </Button>
        </div>

        {/* Discard: leave an accidentally-started session without tracking or
            pushing anything to Jira. */}
        <div className="text-center">
          {confirmDiscard ? (
            <div className="inline-flex items-center gap-3 text-sm">
              <span className="text-slate-500">Discard this session? Nothing is logged.</span>
              <Button
                variant="danger"
                loading={abandon.isPending}
                onClick={discard}
              >
                <Trash2 className="h-4 w-4" />
                Discard
              </Button>
              <Button variant="ghost" onClick={() => setConfirmDiscard(false)}>
                Keep
              </Button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmDiscard(true)}
              className="text-xs text-slate-400 hover:text-rose-500 hover:underline"
            >
              Discard session
            </button>
          )}
        </div>
      </Card>

      <Card className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
            Notes
          </h2>
          {savedAt && (
            <span className="text-xs text-slate-400">Autosaved</span>
          )}
        </div>
        <TextArea
          rows={5}
          placeholder="Jot down what you are doing as you go..."
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </Card>

      {/* Manage the attached ticket without leaving the timer: set start / due /
          actual dates, move it through the workflow, complete subtasks. */}
      {session.issue_key && (
        <Card className="space-y-4">
          <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
            Manage {session.issue_key}
          </h2>
          {manage.isLoading && <Spinner />}
          {manage.isError && (
            <Banner tone="error">
              {manage.error instanceof ApiError
                ? JSON.stringify(manage.error.detail)
                : String(manage.error)}
            </Banner>
          )}
          {manage.data && (
            <ManagePanel key={manage.data.issue_key} data={manage.data} />
          )}
        </Card>
      )}
    </div>
  );
}
