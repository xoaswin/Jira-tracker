// Types mirroring the backend Pydantic schemas (kept in sync by hand, section 12).

export interface AuthStatus {
  connected: boolean;
  account_id: string | null;
  display_name: string | null;
  email: string | null;
  base_url: string | null;
  secret_backend: string;
  uses_tempo: boolean;
}

export interface Board {
  id: number;
  name: string;
  type: string | null;
  project_key: string | null;
  project_id: string | null;
  is_favourite: boolean;
  last_synced_at: string | null;
}

export interface Issue {
  id: number;
  jira_id: string;
  issue_key: string;
  board_id: number | null;
  project_key: string | null;
  issue_type: string | null;
  parent_key: string | null;
  summary: string;
  description_text: string;
  status: string | null;
  status_category: string | null;
  sprint_name: string | null;
  updated_at: string | null;
}

export type SessionState = "active" | "paused" | "completed" | "abandoned";
export type SyncState = "unsynced" | "synced" | "error";

export interface WorkSession {
  id: number;
  description: string;
  notes: string | null;
  board_id: number | null;
  issue_key: string | null;
  started_at: string;
  ended_at: string | null;
  paused_seconds: number;
  adjusted_seconds: number | null;
  state: SessionState;
  issue_origin: string | null;
  created_at: string;
  worklog_jira_id: string | null;
  comment_jira_id: string | null;
  sync_state: SyncState;
  sync_error: string | null;
  elapsed_seconds: number | null;
}

export interface CompleteResult {
  session: WorkSession;
  duration_seconds: number;
  rounded_up: boolean;
  warning: string | null;
}

// --- matching (Phase 3) ---

export interface MatchCandidate {
  issue_key: string;
  summary: string;
  issue_type: string | null;
  status: string | null;
  status_category: string | null;
  sprint_name: string | null;
  assignee_name: string | null;
  is_mine: boolean;
  score: number;
  confidence_pct: number;
  bm25: number;
  embedding: number;
  recency: number;
  reason: string;
}

export interface MatchResponse {
  candidates: MatchCandidate[];
  used_embeddings: boolean;
  forced_key: string | null;
  lead_with_create: boolean;
  preselect_top: boolean;
  searched_board_ids: number[];
}

export interface GitContext {
  detected: boolean;
  repo_path: string | null;
  branch: string | null;
  commits: string[];
  issue_key: string | null;
  suggested_text: string;
  error: string | null;
}

// --- issue creation (Phase 4) ---

export interface RequiredField {
  field_id: string;
  name: string;
  schema_type: string;
  allowed_values: Array<{ id?: string; value?: string; name?: string }>;
}

export interface DuplicateWarning {
  issue_key: string;
  summary: string;
  similarity: number;
}

export interface DraftResponse {
  project_key: string;
  issue_type: string;
  summary: string;
  description: string;
  parent_key: string | null;
  required_fields: RequiredField[];
  duplicate: DuplicateWarning | null;
}

export interface CreateIssueResponse {
  issue_key: string;
  issue: Issue;
}

// --- reports, AI, settings (Phase 5) ---

export interface DayBucket {
  day: string;
  tracked_seconds: number;
  logged_seconds: number;
}

export interface IssueBucket {
  issue_key: string | null;
  tracked_seconds: number;
  logged_seconds: number;
}

export interface WeekReport {
  week_start: string;
  week_end: string;
  total_tracked_seconds: number;
  total_logged_seconds: number;
  days: DayBucket[];
  issues: IssueBucket[];
}

export interface AITextResponse {
  text: string;
  used_ai: boolean;
}

export interface DraftWorklogResponse {
  text: string;
  used_ai: boolean;
  commit_count: number;
  repo_found: boolean;
}

export interface AIStatus {
  provider: string;
  available: boolean;
}

// --- start-of-day intention ---

export interface DayIntention {
  plan_date: string;
  note: string;
  ticket_keys: string[];
  created_at: string;
  updated_at: string;
}

// --- contextual assistant ---

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ProposedAction {
  type: string;
  args: Record<string, unknown>;
  summary: string;
}

export interface AssistantChatResponse {
  reply: string;
  used_ai: boolean;
  action: ProposedAction | null;
}

export interface AssistantActResult {
  ok: boolean;
  message: string;
  session_id?: number | null;
}

// A rendered chat turn (shared by the slide-over panel and the Assistant tab).
export interface AssistantMsg {
  role: "user" | "assistant";
  content: string;
  action?: ProposedAction | null;
  usedAi?: boolean;
  system?: boolean; // action-result line, styled differently
}

// --- ticket management (Manage screen) ---

export interface TransitionOption {
  id: string;
  name: string | null;
  to: string | null;
}

export interface DateField {
  field_id: string;
  name: string;
  schema_type: string;
  value: string | null;
}

export interface Subtask {
  issue_key: string;
  summary: string;
  status: string | null;
  status_category: string | null;
  is_done: boolean;
}

export interface ManageView {
  issue_key: string;
  summary: string;
  issue_type: string | null;
  status: string | null;
  status_category: string | null;
  assignee_account_id: string | null;
  assignee_name: string | null;
  priority_id: string | null;
  priority_name: string | null;
  available_transitions: TransitionOption[];
  date_fields: DateField[];
  subtasks: Subtask[];
}

export interface AssignableUser {
  account_id: string | null;
  display_name: string | null;
  email: string | null;
}

export interface Priority {
  id: string;
  name: string | null;
}

export interface TransitionResult {
  applied: string[];
  view: ManageView;
}

export interface WorklogEntry {
  id: string;
  time_spent_seconds: number;
  started: string | null;
  comment: string | null;
  author: string | null;
}

export interface AddWorklogResult {
  worklog: WorklogEntry;
  rounded_up: boolean;
}

// --- my tickets (assigned to me, with due-date attention) ---

export type Urgency =
  | "overdue"
  | "due_today"
  | "due_soon"
  | "scheduled"
  | "no_due";

export interface MyTicket {
  issue_key: string;
  summary: string;
  issue_type: string | null;
  status: string | null;
  status_category: string | null;
  priority: string | null;
  project_key: string | null;
  due_date: string | null;
  urgency: Urgency;
  days_until_due: number | null;
}

export interface MyTickets {
  tickets: MyTicket[];
  overdue: number;
  due_today: number;
  due_soon: number;
}

// --- plan my day ---

export interface TypeVelocity {
  issue_type: string | null;
  sample_count: number;
  avg_seconds: number;
  median_seconds: number;
}

export interface PlanItem {
  ticket: MyTicket;
  estimate_seconds: number;
  fits: boolean;
  cumulative_seconds: number;
}

export interface DayPlan {
  capacity_seconds: number;
  planned_seconds: number;
  overflow_seconds: number;
  fitted_count: number;
  total_samples: number;
  items: PlanItem[];
  velocity_by_type: TypeVelocity[];
}

export interface EstimateOut {
  issue_type: string | null;
  estimate_seconds: number;
  sample_count: number;
  based_on: "type" | "overall" | "default";
}

// --- insights / reconcile ---

export interface InsightBucket {
  key: string;
  label: string;
  tracked_seconds: number;
  logged_seconds: number;
  session_count: number;
}

export interface Insights {
  range_start: string;
  range_end: string;
  total_tracked_seconds: number;
  total_logged_seconds: number;
  session_count: number;
  ticket_count: number;
  by_project: InsightBucket[];
  by_type: InsightBucket[];
  by_ticket: InsightBucket[];
  by_day: InsightBucket[];
}

export type ReconcileFlag = "commits_no_time" | "time_no_commits" | "ok";

export interface ReconcileRow {
  issue_key: string;
  repo_path: string | null;
  commit_count: number;
  logged_seconds: number;
  flag: ReconcileFlag;
}

export interface Reconcile {
  range_start: string;
  range_end: string;
  rows: ReconcileRow[];
}

export interface AppSettingsData {
  ai_provider: string;
  ollama_url: string | null;
  ollama_model: string | null;
  embedding_model: string | null;
  nudge_time: string | null;
  idle_threshold_minutes: number;
  default_transition: string | null;
  uses_tempo: boolean;
  needs_reauth: boolean;
  issue_scope: string;
  work_start_time: string | null;
  work_end_time: string | null;
  daily_target_hours: number;
  checkin_interval_minutes: number;
  // IANA zone the workday is measured in (default Asia/Kolkata).
  timezone: string;
  // Local git repos (Code folders) and the zero-click tracking switch.
  git_repo_paths: string[];
  auto_track: boolean;
  auto_actual_dates: boolean;
  has_gemini_key: boolean;
  has_groq_key: boolean;
}

// --- phone companion (pairing) ---

export interface MobileDevice {
  id: number;
  name: string;
  created_at: string | null;
  last_seen_at: string | null;
  user_agent: string | null;
}

export interface MobileStatus {
  running: boolean;
  port: number;
  lan_ip: string | null;
  devices: MobileDevice[];
}

export interface MobilePairResult extends MobileStatus {
  device: MobileDevice;
  url: string;
  qr_svg: string;
  // Other laptop addresses to try if the phone can't open the QR link.
  alternate_urls: string[];
}

// --- activity: timeline + focus radar ---

export type ActivityCategory = "code" | "browser" | "meeting" | "chat" | "docs" | "other" | "away";

export interface ActivityBlock {
  start: string;
  end: string;
  seconds: number;
  app: string;
  kind: "active" | "idle" | "locked";
  category: ActivityCategory;
  issue_key: string | null;
  title: string;
}

export interface TimelineSession {
  id: number;
  issue_key: string | null;
  description: string;
  state: string;
  origin: string | null;
  sync_state: string;
  start: string;
  end: string;
  seconds: number;
}

export interface TimelineCommit {
  at: string;
  subject: string;
  repo: string;
  issue_key: string | null;
}

export interface DayTimeline {
  date: string;
  day_start: string;
  day_end: string;
  now: string;
  work: { start: string; end: string } | null;
  activity: ActivityBlock[];
  sessions: TimelineSession[];
  commits: TimelineCommit[];
  by_category: Partial<Record<ActivityCategory, number>>;
  recording: boolean;
}

export interface FocusDay {
  date: string;
  active_seconds: number;
  tracked_seconds: number;
  switches: number;
  switches_per_hour: number | null;
  deep_blocks: number;
  deep_seconds: number;
  longest_deep_seconds: number;
  late_seconds: number;
}

export interface FocusReport {
  days: FocusDay[];
  deep_by_hour: Record<string, number>;
  tips: string[];
  recording: boolean;
}
