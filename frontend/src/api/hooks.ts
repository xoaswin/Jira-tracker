// TanStack Query hooks over the typed api client (section 3: server state here).

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "./client";

export const keys = {
  auth: ["auth"] as const,
  boards: ["boards"] as const,
  issues: (boardId: number) => ["issues", boardId] as const,
  activeSession: ["session", "active"] as const,
  sessions: (state?: string) => ["sessions", state ?? "all"] as const,
  gitContext: ["git", "context"] as const,
  weekReport: ["reports", "week"] as const,
  unlogged: ["reports", "unlogged"] as const,
  aiStatus: ["ai", "status"] as const,
  settings: ["settings"] as const,
};

export function useAuthStatus() {
  return useQuery({ queryKey: keys.auth, queryFn: api.authStatus });
}

export function useConnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { base_url: string; email: string; token: string }) =>
      api.connect(v.base_url, v.email, v.token),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.auth }),
  });
}

export function useDisconnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.disconnect,
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useBoards() {
  return useQuery({ queryKey: keys.boards, queryFn: () => api.boards(false) });
}

export function useRefreshBoards() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.boards(true),
    onSuccess: (data) => qc.setQueryData(keys.boards, data),
  });
}

export function useToggleFavourite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (boardId: number) => api.toggleFavourite(boardId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.boards }),
  });
}

export function useIssues(boardId: number | null) {
  return useQuery({
    queryKey: boardId ? keys.issues(boardId) : ["issues", "none"],
    queryFn: () => api.issues(boardId as number, false),
    enabled: boardId != null,
  });
}

export function useRefreshIssues(boardId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.issues(boardId as number, true),
    onSuccess: (data) => {
      if (boardId) qc.setQueryData(keys.issues(boardId), data);
    },
  });
}

export function useActiveSession() {
  return useQuery({
    queryKey: keys.activeSession,
    queryFn: api.activeSession,
  });
}

export function useSessions(state?: string) {
  return useQuery({
    queryKey: keys.sessions(state),
    queryFn: () => api.sessions(state),
  });
}

export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { description: string; board_id: number | null }) =>
      api.createSession(v.description, v.board_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.activeSession }),
  });
}

function invalidateSessionQueries(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: keys.activeSession });
  qc.invalidateQueries({ queryKey: ["sessions"] });
}

export function useUpdateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: number;
      patch: Parameters<typeof api.updateSession>[1];
    }) => api.updateSession(v.id, v.patch),
    onSuccess: () => invalidateSessionQueries(qc),
  });
}

export function usePauseSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.pauseSession(id),
    onSuccess: () => invalidateSessionQueries(qc),
  });
}

export function useResumeSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.resumeSession(id),
    onSuccess: () => invalidateSessionQueries(qc),
  });
}

export function useCompleteSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: number;
      payload: Parameters<typeof api.completeSession>[1];
    }) => api.completeSession(v.id, v.payload),
    onSuccess: () => invalidateSessionQueries(qc),
  });
}

export function useAbandonSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.abandonSession(id),
    onSuccess: () => invalidateSessionQueries(qc),
  });
}

export function useRepushSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.repushSession(id),
    onSuccess: () => {
      invalidateSessionQueries(qc);
      qc.invalidateQueries({ queryKey: keys.unlogged });
      qc.invalidateQueries({ queryKey: keys.weekReport });
    },
  });
}

export function useManualSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.manualSession,
    onSuccess: () => {
      invalidateSessionQueries(qc);
      qc.invalidateQueries({ queryKey: keys.unlogged });
      qc.invalidateQueries({ queryKey: keys.weekReport });
    },
  });
}

// --- matching (Phase 3) ---

export function useMatch() {
  return useMutation({
    mutationFn: (v: {
      boards: number | number[];
      text: string;
      branch_key?: string | null;
    }) => api.match(v.boards, v.text, v.branch_key),
  });
}

export function useGitContext() {
  return useQuery({
    queryKey: keys.gitContext,
    queryFn: api.gitContext,
    // Git state changes out of band (branch switches); keep it fresh-ish but do
    // not hammer. Never throw the Start screen on failure.
    staleTime: 30_000,
    retry: false,
  });
}

// --- issue creation (Phase 4) ---

export function useDraftIssue() {
  return useMutation({ mutationFn: api.draftIssue });
}

export function useCreateIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createIssue,
    onSuccess: (data) => {
      // The new issue is cached server-side; refresh the board's issue list.
      if (data.issue.board_id) {
        qc.invalidateQueries({ queryKey: keys.issues(data.issue.board_id) });
      }
    },
  });
}

// --- reports, AI, settings (Phase 5) ---

export function useWeekReport() {
  return useQuery({ queryKey: keys.weekReport, queryFn: () => api.weekReport() });
}

export function useUnlogged() {
  return useQuery({ queryKey: keys.unlogged, queryFn: api.unlogged });
}

export function useAiStatus() {
  return useQuery({
    queryKey: keys.aiStatus,
    queryFn: api.aiStatus,
    retry: false,
    staleTime: 30_000,
  });
}

export function useCleanupComment() {
  return useMutation({ mutationFn: (text: string) => api.aiCleanupComment(text) });
}

// Standup summary: fetched on demand (a click), not on mount, because it can be
// AI-bound and slow. Degrades to a plain roll-up when AI is off.
export function useDailySummary() {
  return useMutation({ mutationFn: () => api.dailySummary() });
}

// Draft a worklog comment from the git commits on the ticket's repo since the
// session started. On-demand (a click); degrades cleanly when there is no repo,
// no commits, or AI is off.
export function useDraftWorklog() {
  return useMutation({
    mutationFn: (v: { issueKey: string; since: string }) =>
      api.aiDraftWorklog(v.issueKey, v.since),
  });
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: api.settings });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.updateSettings,
    onSuccess: (data) => {
      qc.setQueryData(keys.settings, data);
      qc.invalidateQueries({ queryKey: keys.aiStatus });
    },
  });
}

export function useRetryAllOutbox() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.retryAllOutbox,
    onSuccess: () => {
      // Refresh session lists and reports after a retry drains the outbox.
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: keys.unlogged });
      qc.invalidateQueries({ queryKey: keys.weekReport });
    },
  });
}

// --- ticket management (Manage screen) ---

export function useManageView(issueKey: string | null) {
  return useQuery({
    queryKey: ["manage", issueKey],
    queryFn: () => api.manageView(issueKey as string),
    enabled: !!issueKey,
    retry: false,
  });
}

export function useEditDates(issueKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, string | null>) =>
      api.editDates(issueKey, values),
    onSuccess: (view) => qc.setQueryData(["manage", issueKey], view),
  });
}

export function useTransitionIssue(issueKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target: string) => api.transitionIssue(issueKey, target),
    onSuccess: (res) => qc.setQueryData(["manage", issueKey], res.view),
  });
}

export function useMarkDone(issueKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.markDone(issueKey),
    onSuccess: (res) => qc.setQueryData(["manage", issueKey], res.view),
  });
}

export function useTransitionSubtask(parentKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { subtaskKey: string; target: string }) =>
      api.transitionSubtask(parentKey, v.subtaskKey, v.target),
    onSuccess: (res) => qc.setQueryData(["manage", parentKey], res.view),
  });
}

export function usePriorities(issueKey: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["priorities", issueKey],
    queryFn: () => api.priorities(issueKey as string),
    enabled: !!issueKey && enabled,
    staleTime: 5 * 60_000,
  });
}

export function useAssignableUsers(issueKey: string | null, query: string, enabled: boolean) {
  return useQuery({
    queryKey: ["assignable", issueKey, query],
    queryFn: () => api.assignableUsers(issueKey as string, query),
    enabled: !!issueKey && enabled,
    staleTime: 60_000,
  });
}

export function useSetAssignee(issueKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string | null) => api.setAssignee(issueKey, accountId),
    onSuccess: (view) => qc.setQueryData(["manage", issueKey], view),
  });
}

export function useSetPriority(issueKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (priorityId: string) => api.setPriority(issueKey, priorityId),
    onSuccess: (view) => qc.setQueryData(["manage", issueKey], view),
  });
}

export function useCreateSubtask(issueKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (summary: string) => api.createSubtask(issueKey, summary),
    onSuccess: (view) => qc.setQueryData(["manage", issueKey], view),
  });
}

export function useMyTickets() {
  return useQuery({
    queryKey: ["my-tickets"],
    queryFn: api.myTickets,
    retry: false,
    // Due dates matter by the day; a short stale window keeps it fresh without
    // hammering Jira on every screen switch.
    staleTime: 60_000,
  });
}

export function usePlanToday(capacityHours: number) {
  return useQuery({
    queryKey: ["plan", "today", capacityHours],
    queryFn: () => api.planToday(capacityHours),
    retry: false,
    staleTime: 60_000,
  });
}

export function useEstimate(issueType: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["estimate", issueType],
    queryFn: () => api.estimate(issueType),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useSessionsInRange(fromIso: string | null, toIso: string | null) {
  return useQuery({
    queryKey: ["sessions", "range", fromIso, toIso],
    queryFn: () => api.sessionsInRange(fromIso as string, toIso as string),
    enabled: !!fromIso && !!toIso,
  });
}

export function useInsights(preset: string) {
  return useQuery({
    queryKey: ["insights", preset],
    queryFn: () => api.insights(preset),
    staleTime: 60_000,
  });
}

export function useReconcile(preset: string, enabled: boolean) {
  return useQuery({
    queryKey: ["reconcile", preset],
    queryFn: () => api.reconcile(preset),
    enabled,
    staleTime: 60_000,
  });
}

export function useWorklogs(issueKey: string | null) {
  return useQuery({
    queryKey: ["worklogs", issueKey],
    queryFn: () => api.worklogs(issueKey as string),
    enabled: !!issueKey,
    retry: false,
  });
}

export function useAddWorklog(issueKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      hours: number;
      minutes: number;
      started?: string | null;
      comment?: string | null;
    }) => api.addWorklog(issueKey, v),
    onSuccess: () => {
      // Refresh this ticket's worklog list, and any session/report views that
      // aggregate logged time so the dashboard stays honest.
      qc.invalidateQueries({ queryKey: ["worklogs", issueKey] });
      qc.invalidateQueries({ queryKey: keys.weekReport });
    },
  });
}
