import { useMemo, useState } from "react";
import { Clock, GitBranch, Plus, RefreshCw, Search, Star, Timer as TimerIcon } from "lucide-react";
import {
  useBoards,
  useCreateSession,
  useGitContext,
  useRefreshBoards,
  useSessions,
  useToggleFavourite,
  useUpdateSession,
} from "../api/hooks";
import { useUi } from "../store/ui";
import { Banner, Button, Card, Spinner, TextArea, TextInput } from "../components/ui";

export function Start() {
  const boards = useBoards();
  const refreshBoards = useRefreshBoards();
  const toggleFav = useToggleFavourite();
  const createSession = useCreateSession();
  const updateSession = useUpdateSession();
  const git = useGitContext();

  const {
    selectedBoardId,
    setSelectedBoard,
    draftDescription,
    setDraftDescription,
    setScreen,
    setCurrentSession,
    setBranchKey,
    searchPinned,
    setSearchPinned,
    setMatchBoardIds,
    setCreateIntent,
  } = useUi();

  const sessions = useSessions();
  const [boardFilter, setBoardFilter] = useState("");

  const allBoards = boards.data ?? [];
  const pinned = allBoards.filter((b) => b.is_favourite);

  // Recent tickets: distinct issue keys from past sessions, most recent first,
  // so common tickets are one click away without typing or searching.
  const recentTickets = useMemo(() => {
    const seen = new Set<string>();
    const out: { issue_key: string; board_id: number | null }[] = [];
    for (const s of sessions.data ?? []) {
      if (s.issue_key && !seen.has(s.issue_key)) {
        seen.add(s.issue_key);
        out.push({ issue_key: s.issue_key, board_id: s.board_id });
      }
      if (out.length >= 6) break;
    }
    return out;
  }, [sessions.data]);

  // Boards to show in the picker: filtered by the search box, pinned first.
  const visibleBoards = useMemo(() => {
    const q = boardFilter.trim().toLowerCase();
    const matched = q
      ? allBoards.filter(
          (b) =>
            b.name.toLowerCase().includes(q) ||
            (b.project_key ?? "").toLowerCase().includes(q),
        )
      : allBoards;
    return [...matched].sort((a, b) => {
      if (a.is_favourite !== b.is_favourite) return a.is_favourite ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [allBoards, boardFilter]);

  // In pinned-search mode we need at least one pinned board; otherwise a single
  // selected board.
  const canProceed =
    draftDescription.trim().length > 0 &&
    (searchPinned ? pinned.length > 0 : selectedBoardId != null);

  function applyGitContext() {
    // Insert the git-derived text into the description and remember the branch
    // key so Match can preselect it (section 9).
    if (!git.data?.detected) return;
    const suggestion = git.data.suggested_text;
    if (suggestion) {
      setDraftDescription(
        draftDescription.trim().length > 0
          ? `${draftDescription.trim()} ${suggestion}`
          : suggestion,
      );
    }
    setBranchKey(git.data.issue_key);
  }

  function resolveBoardIds() {
    return searchPinned
      ? pinned.map((b) => b.id)
      : selectedBoardId != null
        ? [selectedBoardId]
        : [];
  }

  function findTicket() {
    if (!canProceed) return;
    // Carry any git-detected key forward even if the chip was not clicked.
    if (git.data?.detected) setBranchKey(git.data.issue_key);
    setMatchBoardIds(resolveBoardIds());
    setCreateIntent(false);
    setScreen("match");
  }

  function createTicket() {
    // Skip matching and go straight to drafting a new issue. Requires a board
    // (single-select) so we know where to create it; in pinned mode the first
    // pinned board is used.
    if (draftDescription.trim().length === 0) return;
    if (git.data?.detected) setBranchKey(git.data.issue_key);
    setMatchBoardIds(resolveBoardIds());
    setCreateIntent(true);
    setScreen("match");
  }

  function startWithoutTicket() {
    if (draftDescription.trim().length === 0) return;
    createSession.mutate(
      { description: draftDescription.trim(), board_id: selectedBoardId },
      {
        onSuccess: (session) => {
          setCurrentSession(session.id);
          setScreen("active");
        },
      },
    );
  }

  function startWithRecent(issueKey: string, boardId: number | null) {
    // One-click start against a recently-used ticket. Uses the typed
    // description if present, else the ticket key as a placeholder.
    const desc = draftDescription.trim() || `Work on ${issueKey}`;
    createSession.mutate(
      { description: desc, board_id: boardId },
      {
        onSuccess: (session) => {
          updateSession.mutate(
            { id: session.id, patch: { issue_key: issueKey, issue_origin: "manual" } },
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

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">What are you working on?</h1>
        <p className="mt-1 text-sm text-slate-500">
          Describe it in plain language, pick a board, and find the ticket.
        </p>
      </div>

      <TextArea
        rows={3}
        autoFocus
        placeholder="e.g. fixing the retry logic on the payment webhook"
        value={draftDescription}
        onChange={(e) => setDraftDescription(e.target.value)}
      />

      {git.data?.detected && git.data.branch && (
        <button
          onClick={applyGitContext}
          title="Click to insert into the description"
          className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left text-sm hover:border-indigo-300 hover:bg-slate-100 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800"
        >
          <GitBranch className="h-4 w-4 shrink-0 text-sky-500" />
          <span className="min-w-0 flex-1 truncate">
            On branch{" "}
            <span className="font-mono text-xs font-semibold text-slate-700 dark:text-slate-200">
              {git.data.branch}
            </span>
            {git.data.issue_key && (
              <span className="ml-2 rounded bg-indigo-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                {git.data.issue_key}
              </span>
            )}
          </span>
          <span className="shrink-0 text-xs text-slate-400">Insert</span>
        </button>
      )}

      {/* Recent tickets: one-click start against a recently-used ticket. */}
      {recentTickets.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 text-xs text-slate-400">
            <Clock className="h-3.5 w-3.5" />
            Recent:
          </span>
          {recentTickets.map((t) => (
            <button
              key={t.issue_key}
              onClick={() => startWithRecent(t.issue_key, t.board_id)}
              disabled={createSession.isPending || updateSession.isPending}
              title="Start a session on this ticket"
              className="rounded-full border border-slate-200 px-2.5 py-1 font-mono text-xs font-semibold text-indigo-600 hover:border-indigo-300 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-800 dark:text-indigo-400 dark:hover:bg-slate-800"
            >
              {t.issue_key}
            </button>
          ))}
        </div>
      )}

      <Card className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
            Board
          </h2>
          <Button
            variant="ghost"
            loading={refreshBoards.isPending}
            onClick={() => refreshBoards.mutate()}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </div>

        {/* Search boards by name or project key. */}
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <TextInput
            className="pl-9"
            placeholder="Search boards by name or project key..."
            value={boardFilter}
            onChange={(e) => setBoardFilter(e.target.value)}
          />
        </div>

        {/* Search-across-pinned toggle. Pin boards with the star to build the set. */}
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input
            type="checkbox"
            checked={searchPinned}
            onChange={(e) => setSearchPinned(e.target.checked)}
            className="h-4 w-4"
            disabled={pinned.length === 0}
          />
          Search across pinned boards
          {pinned.length > 0 && (
            <span className="text-xs text-slate-400">
              ({pinned.length} pinned: {pinned.map((b) => b.project_key ?? b.name).join(", ")})
            </span>
          )}
          {pinned.length === 0 && (
            <span className="text-xs text-slate-400">
              (star boards below to build a set)
            </span>
          )}
        </label>

        {boards.isLoading ? (
          <Spinner />
        ) : visibleBoards.length > 0 ? (
          <ul className="grid max-h-72 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
            {visibleBoards.map((board) => {
              // In pinned-search mode, the star (pin) is the selector; the row's
              // highlight reflects pinned membership rather than single-select.
              const active = searchPinned
                ? board.is_favourite
                : selectedBoardId === board.id;
              return (
                <li key={board.id}>
                  <div
                    className={`flex items-center justify-between rounded-lg border px-3 py-2 ${
                      active
                        ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950"
                        : "border-slate-200 dark:border-slate-800"
                    }`}
                  >
                    <button
                      className="min-w-0 flex-1 text-left"
                      onClick={() =>
                        searchPinned
                          ? toggleFav.mutate(board.id)
                          : setSelectedBoard(board.id)
                      }
                    >
                      <span className="block truncate text-sm font-medium">
                        {board.name}
                      </span>
                      <span className="text-xs text-slate-400">
                        {board.project_key ?? "no project"} · {board.type ?? "board"}
                      </span>
                    </button>
                    <button
                      onClick={() => toggleFav.mutate(board.id)}
                      title={board.is_favourite ? "Unpin" : "Pin for multi-board search"}
                      className="ml-2 shrink-0"
                    >
                      <Star
                        className={`h-4 w-4 ${
                          board.is_favourite
                            ? "fill-amber-400 text-amber-400"
                            : "text-slate-300"
                        }`}
                      />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : allBoards.length > 0 ? (
          <Banner tone="info">No boards match "{boardFilter}".</Banner>
        ) : (
          <Banner tone="info">
            No boards cached yet. Click Refresh to load them from Jira.
          </Banner>
        )}
      </Card>

      {createSession.isError && (
        <Banner tone="error">{String(createSession.error)}</Banner>
      )}

      <div className="flex flex-wrap gap-3">
        <Button onClick={findTicket} disabled={!canProceed}>
          <Search className="h-4 w-4" />
          Find ticket
        </Button>
        <Button
          variant="secondary"
          onClick={createTicket}
          disabled={!canProceed}
          title="Draft and create a brand new Jira issue from your description"
        >
          <Plus className="h-4 w-4" />
          Create new ticket
        </Button>
        <Button
          variant="ghost"
          onClick={startWithoutTicket}
          loading={createSession.isPending}
          disabled={draftDescription.trim().length === 0}
        >
          <TimerIcon className="h-4 w-4" />
          Start without a ticket
        </Button>
      </div>
    </div>
  );
}
