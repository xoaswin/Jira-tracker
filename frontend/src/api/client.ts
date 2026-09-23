// Thin typed fetch wrapper. Surfaces the backend's error body verbatim so the UI
// can show Jira's actual message (rule 8: fail loudly with the real response).

import type {
  AddWorklogResult,
  AIStatus,
  AITextResponse,
  AppSettingsData,
  AssignableUser,
  AuthStatus,
  Board,
  CompleteResult,
  CreateIssueResponse,
  DayPlan,
  DraftResponse,
  DraftWorklogResponse,
  EstimateOut,
  GitContext,
  Insights,
  Issue,
  ManageView,
  MatchResponse,
  MyTickets,
  Priority,
  Reconcile,
  TransitionResult,
  WeekReport,
  WorklogEntry,
  WorkSession,
} from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  code?: string;
  constructor(status: number, detail: unknown, code?: string) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return undefined as T;

  let payload: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    const code =
      payload && typeof payload === "object" && "code" in payload
        ? (payload as { code?: string }).code
        : undefined;
    throw new ApiError(res.status, detail, code);
  }

  return payload as T;
}

export const api = {
  // auth
  authStatus: () => request<AuthStatus>("GET", "/api/auth/status"),
  connect: (base_url: string, email: string, token: string) =>
    request<AuthStatus>("POST", "/api/auth/connect", { base_url, email, token }),
  disconnect: () => request<void>("DELETE", "/api/auth"),

  // boards
  boards: (refresh = false) =>
    request<Board[]>("GET", `/api/boards${refresh ? "?refresh=true" : ""}`),
  toggleFavourite: (boardId: number) =>
    request<Board>("POST", `/api/boards/${boardId}/favourite`),

  // issues
  issues: (boardId: number, refresh = false) =>
    request<Issue[]>(
      "GET",
      `/api/boards/${boardId}/issues${refresh ? "?refresh=true" : ""}`,
    ),

  // sessions
  createSession: (description: string, board_id: number | null) =>
    request<WorkSession>("POST", "/api/sessions", { description, board_id }),
  sessions: (state?: string) =>
    request<WorkSession[]>(
      "GET",
      `/api/sessions${state ? `?state=${state}` : ""}`,
    ),
  // Sessions within an ISO datetime range (used by the history view). The
  // backend accepts ?from=&to= on the list endpoint.
  sessionsInRange: (fromIso: string, toIso: string) =>
    request<WorkSession[]>(
      "GET",
      `/api/sessions?from=${encodeURIComponent(fromIso)}&to=${encodeURIComponent(toIso)}`,
    ),
  activeSession: () => request<WorkSession | null>("GET", "/api/sessions/active"),
  updateSession: (
    id: number,
    patch: Partial<
      Pick<WorkSession, "issue_key" | "notes" | "adjusted_seconds" | "issue_origin">
    >,
  ) => request<WorkSession>("PATCH", `/api/sessions/${id}`, patch),
  pauseSession: (id: number) =>
    request<WorkSession>("POST", `/api/sessions/${id}/pause`),
  resumeSession: (id: number) =>
    request<WorkSession>("POST", `/api/sessions/${id}/resume`),
  completeSession: (
    id: number,
    payload: {
      notes?: string;
      adjusted_seconds?: number;
      transition_to?: string;
      issue_key?: string;
    },
  ) => request<CompleteResult>("POST", `/api/sessions/${id}/complete`, payload),
  abandonSession: (id: number) =>
    request<WorkSession>("DELETE", `/api/sessions/${id}`),
  repushSession: (id: number) =>
    request<WorkSession>("POST", `/api/sessions/${id}/repush`),
  manualSession: (v: {
    description: string;
    duration_seconds: number;
    board_id?: number | null;
    issue_key?: string | null;
    notes?: string | null;
    started_at?: string | null;
    transition_to?: string | null;
  }) => request<CompleteResult>("POST", "/api/sessions/manual", v),

  // matching (Phase 3, extended: single board or a set of pinned boards)
  match: (
    boards: number | number[],
    text: string,
    branch_key?: string | null,
  ) =>
    request<MatchResponse>("POST", "/api/match", {
      ...(Array.isArray(boards)
        ? { board_ids: boards }
        : { board_id: boards }),
      text,
      branch_key: branch_key ?? null,
    }),
  gitContext: () => request<GitContext>("GET", "/api/git/context"),

  // issue creation (Phase 4)
  draftIssue: (v: {
    board_id: number;
    text: string;
    type_hint?: string | null;
    parent_key?: string | null;
  }) => request<DraftResponse>("POST", "/api/issues/draft", v),
  createIssue: (v: {
    board_id: number;
    project_key: string;
    type: string;
    summary: string;
    description: string;
    parent_key?: string | null;
    fields?: Record<string, unknown> | null;
  }) => request<CreateIssueResponse>("POST", "/api/issues", v),

  // reports (Phase 5)
  weekReport: (week?: string) =>
    request<WeekReport>("GET", `/api/reports/week${week ? `?week=${week}` : ""}`),
  unlogged: () => request<WorkSession[]>("GET", "/api/reports/unlogged"),
  dailySummary: () => request<AITextResponse>("GET", "/api/reports/daily-summary"),

  // AI (Phase 5)
  aiStatus: () => request<AIStatus>("GET", "/api/ai/status"),
  aiCleanupComment: (text: string) =>
    request<AITextResponse>("POST", "/api/ai/cleanup-comment", { text }),
  aiDraftSummary: (text: string) =>
    request<AITextResponse>("POST", "/api/ai/draft-summary", { text }),
  aiDraftWorklog: (issue_key: string, since: string) =>
    request<DraftWorklogResponse>("POST", "/api/ai/draft-worklog", {
      issue_key,
      since,
    }),

  // settings (Phase 5)
  settings: () => request<AppSettingsData>("GET", "/api/settings"),
  updateSettings: (patch: Partial<AppSettingsData> & {
    gemini_api_key?: string;
    groq_api_key?: string;
  }) => request<AppSettingsData>("PATCH", "/api/settings", patch),

  // outbox (Phase 2 UI, surfaced in Phase 5 dashboard)
  retryAllOutbox: () =>
    request<{ processed: number; reason: string | null }>(
      "POST",
      "/api/outbox/retry-all",
    ),

  // ticket management (Manage screen)
  manageView: (key: string) =>
    request<ManageView>("GET", `/api/manage/${encodeURIComponent(key)}`),
  editDates: (key: string, values: Record<string, string | null>) =>
    request<ManageView>("PATCH", `/api/manage/${encodeURIComponent(key)}/dates`, {
      values,
    }),
  transitionIssue: (key: string, target: string) =>
    request<TransitionResult>(
      "POST",
      `/api/manage/${encodeURIComponent(key)}/transition`,
      { target },
    ),
  markDone: (key: string) =>
    request<TransitionResult>("POST", `/api/manage/${encodeURIComponent(key)}/done`),
  transitionSubtask: (parentKey: string, subtaskKey: string, target: string) =>
    request<TransitionResult>(
      "POST",
      `/api/manage/${encodeURIComponent(parentKey)}/subtasks/${encodeURIComponent(
        subtaskKey,
      )}/transition`,
      { target },
    ),
  worklogs: (key: string) =>
    request<WorklogEntry[]>(
      "GET",
      `/api/manage/${encodeURIComponent(key)}/worklogs`,
    ),
  addWorklog: (
    key: string,
    v: { hours: number; minutes: number; started?: string | null; comment?: string | null },
  ) =>
    request<AddWorklogResult>(
      "POST",
      `/api/manage/${encodeURIComponent(key)}/worklog`,
      v,
    ),

  // my tickets (assigned to me, due-date attention)
  myTickets: () => request<MyTickets>("GET", "/api/my-tickets"),

  // plan my day (ranked + fitted to capacity, learned velocity)
  planToday: (capacityHours: number) =>
    request<DayPlan>("GET", `/api/plan/today?capacity_hours=${capacityHours}`),

  // velocity estimate for an issue type (mid-session over-budget warning)
  estimate: (issueType: string | null) =>
    request<EstimateOut>(
      "GET",
      `/api/velocity/estimate${issueType ? `?issue_type=${encodeURIComponent(issueType)}` : ""}`,
    ),

  // insights + reconciliation (analytics over a range)
  insights: (preset: string) =>
    request<Insights>("GET", `/api/insights?preset=${encodeURIComponent(preset)}`),
  reconcile: (preset: string) =>
    request<Reconcile>("GET", `/api/reconcile?preset=${encodeURIComponent(preset)}`),

  // export URLs (used as direct download links, not fetched)
  backupUrl: () => "/api/export/backup",
  timesheetCsvUrl: (preset: string) =>
    `/api/export/timesheet.csv?preset=${encodeURIComponent(preset)}`,

  // manage: reassign + priority
  assignableUsers: (key: string, q: string) =>
    request<AssignableUser[]>(
      "GET",
      `/api/manage/${encodeURIComponent(key)}/assignable?q=${encodeURIComponent(q)}`,
    ),
  priorities: (key: string) =>
    request<Priority[]>(
      "GET",
      `/api/manage/${encodeURIComponent(key)}/priorities`,
    ),
  setAssignee: (key: string, account_id: string | null) =>
    request<ManageView>("PUT", `/api/manage/${encodeURIComponent(key)}/assignee`, {
      account_id,
    }),
  setPriority: (key: string, priority_id: string) =>
    request<ManageView>("PUT", `/api/manage/${encodeURIComponent(key)}/priority`, {
      priority_id,
    }),
  createSubtask: (key: string, summary: string) =>
    request<ManageView>("POST", `/api/manage/${encodeURIComponent(key)}/subtasks`, {
      summary,
    }),
};
