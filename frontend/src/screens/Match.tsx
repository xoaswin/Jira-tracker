import { useEffect, useRef } from "react";
import { ArrowLeft, PlusCircle, RefreshCw, Sparkles } from "lucide-react";
import {
  useCreateSession,
  useIssues,
  useMatch,
  useRefreshIssues,
  useUpdateSession,
} from "../api/hooks";
import type { Issue, MatchCandidate } from "../api/types";
import { useUi } from "../store/ui";
import { Banner, Button, Card, Spinner } from "../components/ui";
import { CandidateCard } from "../components/CandidateCard";
import { CreateIssuePanel } from "../components/CreateIssuePanel";
import { IssueList } from "../components/IssueList";

export function Match() {
  const {
    selectedBoardId,
    matchBoardIds,
    draftDescription,
    branchKey,
    createIntent,
    setScreen,
    setCurrentSession,
  } = useUi();

  // The set to search: the resolved match set (pinned or single) if present,
  // else fall back to the selected board.
  const boardsToSearch =
    matchBoardIds.length > 0
      ? matchBoardIds
      : selectedBoardId != null
        ? [selectedBoardId]
        : [];
  const multiBoard = boardsToSearch.length > 1;

  // The full-issue-list fallback below shows one board; use the first searched
  // board (or the selected one) for that.
  const listBoardId = boardsToSearch[0] ?? selectedBoardId;
  const issues = useIssues(listBoardId);
  const refreshIssues = useRefreshIssues(listBoardId);
  const createSession = useCreateSession();
  const updateSession = useUpdateSession();
  const match = useMatch();

  // Auto-fetch issues from Jira if this board has nothing cached yet, so the
  // matcher has something to rank. Without this, a never-refreshed board shows
  // "no matches" and the user has to know to click Refresh (a common gotcha).
  const autoFetched = useRef<number | null>(null);
  useEffect(() => {
    if (
      listBoardId != null &&
      issues.isSuccess &&
      (issues.data?.length ?? 0) === 0 &&
      autoFetched.current !== listBoardId &&
      !refreshIssues.isPending
    ) {
      autoFetched.current = listBoardId;
      refreshIssues.mutate(undefined, {
        // Re-run the matcher once fresh issues land.
        onSuccess: () => {
          if (boardsToSearch.length > 0 && draftDescription.trim()) {
            match.mutate({
              boards: boardsToSearch,
              text: draftDescription.trim(),
              branch_key: branchKey,
            });
          }
        },
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listBoardId, issues.isSuccess, issues.data]);

  // Run the matcher once when the screen opens (and when the set changes).
  // Matching is local and cheap; it never blocks on Jira (section 6).
  const boardsKey = boardsToSearch.join(",");
  useEffect(() => {
    if (boardsToSearch.length > 0 && draftDescription.trim()) {
      match.mutate({
        boards: boardsToSearch,
        text: draftDescription.trim(),
        branch_key: branchKey,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boardsKey, draftDescription, branchKey]);

  const busy = createSession.isPending || updateSession.isPending;
  const result = match.data;
  const topKey = result?.candidates[0]?.issue_key;

  function startSession(
    issueKey: string,
    origin: "matched" | "manual" | "created",
  ) {
    // Start the timer immediately on selection (section 11).
    createSession.mutate(
      { description: draftDescription.trim(), board_id: listBoardId ?? null },
      {
        onSuccess: (session) => {
          updateSession.mutate(
            { id: session.id, patch: { issue_key: issueKey, issue_origin: origin } },
            {
              onSuccess: () => {
                setCurrentSession(session.id);
                setScreen("active");
              },
            },
          );
        },
      },
    );
  }

  function pickCandidate(c: MatchCandidate) {
    startSession(c.issue_key, "matched");
  }

  function pickIssue(issue: Issue) {
    startSession(issue.issue_key, "manual");
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="flex items-center gap-3">
        <Button variant="ghost" onClick={() => setScreen("start")}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold">Pick a ticket</h1>
          <p className="truncate text-sm text-slate-500">"{draftDescription}"</p>
        </div>
      </div>

      {/* Ranked candidates (section 6). */}
      <Card className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
            <Sparkles className="h-4 w-4 text-indigo-500" />
            Best matches
            {multiBoard && (
              <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                across {boardsToSearch.length} boards
              </span>
            )}
          </h2>
          {result && (
            <span className="text-[11px] text-slate-400">
              {result.used_embeddings ? "keyword + semantic" : "keyword ranking"}
            </span>
          )}
        </div>

        {match.isPending ? (
          <Spinner />
        ) : match.isError ? (
          <Banner tone="error">{String(match.error)}</Banner>
        ) : result && result.candidates.length > 0 ? (
          <>
            {result.lead_with_create && (
              <Banner tone="info">
                No strong match. Consider creating a new issue below, or pick one
                of these.
              </Banner>
            )}
            <div className="space-y-2">
              {result.candidates.map((c) => (
                <CandidateCard
                  key={c.issue_key}
                  candidate={c}
                  onSelect={pickCandidate}
                  highlight={result.preselect_top && c.issue_key === topKey}
                />
              ))}
            </div>
          </>
        ) : (
          <Banner tone="info">
            No candidates yet. Use the full list below to pick manually.
          </Banner>
        )}
      </Card>

      {/* Create a new issue (Phase 4). Always available: you may want a brand
          new ticket even when matches exist (section 11). In multi-board search
          the new issue is created on the first searched board. */}
      {listBoardId != null && (
        <Card
          className={`space-y-3 ${
            result?.lead_with_create || createIntent
              ? "border-indigo-300 dark:border-indigo-800"
              : ""
          }`}
        >
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
            <PlusCircle className="h-4 w-4 text-emerald-500" />
            Create a new issue
            {multiBoard && (
              <span className="text-xs font-normal text-slate-400">
                (on the first searched board)
              </span>
            )}
          </h2>
          <CreateIssuePanel
            boardId={listBoardId}
            text={draftDescription.trim()}
            autoStart={createIntent}
            onCreated={(issueKey) => startSession(issueKey, "created")}
            onUseExisting={(issueKey) => startSession(issueKey, "matched")}
          />
        </Card>
      )}

      {/* Manual search over the full cached list (always available). */}
      <Card className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
            All your open issues on this board
          </h2>
          <Button
            variant="ghost"
            loading={refreshIssues.isPending}
            onClick={() => refreshIssues.mutate()}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </div>

        {issues.isLoading ? (
          <Spinner />
        ) : issues.data ? (
          <IssueList issues={issues.data} onSelect={pickIssue} selectedKey={topKey} />
        ) : (
          <Banner tone="info">Refresh to load issues for this board.</Banner>
        )}
      </Card>

      {busy && <p className="text-sm text-slate-400">Starting timer...</p>}
      {(createSession.isError || updateSession.isError) && (
        <Banner tone="error">
          {String(createSession.error ?? updateSession.error)}
        </Banner>
      )}
    </div>
  );
}
