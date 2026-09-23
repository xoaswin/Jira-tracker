"""Pydantic request/response schemas for the API surface (section 10)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# --- auth ---

class ConnectRequest(BaseModel):
    base_url: str
    email: str
    token: str


class AuthStatus(BaseModel):
    connected: bool
    account_id: str | None = None
    display_name: str | None = None
    email: str | None = None
    base_url: str | None = None
    secret_backend: str
    uses_tempo: bool = False


# --- boards ---

class BoardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: str | None = None
    project_key: str | None = None
    project_id: str | None = None
    is_favourite: bool = False
    last_synced_at: datetime | None = None


# --- issues ---

class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    jira_id: str
    issue_key: str
    board_id: int | None = None
    project_key: str | None = None
    issue_type: str | None = None
    parent_key: str | None = None
    summary: str
    description_text: str
    status: str | None = None
    status_category: str | None = None
    sprint_name: str | None = None
    updated_at: datetime | None = None


# --- sessions ---

class SessionCreate(BaseModel):
    description: str
    board_id: int | None = None


class SessionUpdate(BaseModel):
    issue_key: str | None = None
    notes: str | None = None
    adjusted_seconds: int | None = None
    issue_origin: str | None = None


class SessionComplete(BaseModel):
    notes: str | None = None
    adjusted_seconds: int | None = None
    transition_to: str | None = None
    issue_key: str | None = None  # allow setting issue at completion time


class ManualSessionCreate(BaseModel):
    """Log past work without a live timer (manual time entry)."""

    description: str
    duration_seconds: int
    board_id: int | None = None
    issue_key: str | None = None
    notes: str | None = None
    started_at: datetime | None = None
    transition_to: str | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    description: str
    notes: str | None = None
    board_id: int | None = None
    issue_key: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    paused_seconds: int
    adjusted_seconds: int | None = None
    state: str
    issue_origin: str | None = None
    created_at: datetime
    worklog_jira_id: str | None = None
    comment_jira_id: str | None = None
    sync_state: str
    sync_error: str | None = None
    elapsed_seconds: int | None = None


class CompleteResult(BaseModel):
    session: SessionOut
    duration_seconds: int
    rounded_up: bool = False
    warning: str | None = None


# --- matching (Phase 3) ---

class MatchRequest(BaseModel):
    # A single board to match against. Optional if ``board_ids`` is given.
    board_id: int | None = None
    # Match across multiple boards (pinned-board search). When present, this
    # takes precedence over ``board_id``. The candidate set is the union of
    # these boards' cached issues.
    board_ids: list[int] | None = None
    text: str
    # An issue key detected from the current git branch, preselected at full
    # confidence if it matches a candidate (section 9). Optional.
    branch_key: str | None = None


class MatchCandidate(BaseModel):
    """One ranked candidate with its score breakdown for the UI."""

    issue_key: str
    summary: str
    issue_type: str | None = None
    status: str | None = None
    status_category: str | None = None
    sprint_name: str | None = None
    # Who the ticket is assigned to (display name), and whether that is the
    # connected user. Surfaced so the search list is not a wall of same-looking
    # tickets when the board scope includes everyone's issues.
    assignee_name: str | None = None
    is_mine: bool = False
    score: float
    confidence_pct: int
    bm25: float
    embedding: float
    recency: float
    reason: str


class MatchResponse(BaseModel):
    candidates: list[MatchCandidate]
    used_embeddings: bool
    forced_key: str | None = None
    lead_with_create: bool = True
    preselect_top: bool = False
    # The board ids actually searched (after resolving board_id/board_ids), so
    # the UI can confirm the scope of a multi-board search.
    searched_board_ids: list[int] = Field(default_factory=list)


class GitContextOut(BaseModel):
    detected: bool = False
    repo_path: str | None = None
    branch: str | None = None
    commits: list[str] = Field(default_factory=list)
    issue_key: str | None = None
    suggested_text: str = ""
    error: str | None = None


# --- issue creation (Phase 4) ---

class RequiredFieldOut(BaseModel):
    field_id: str
    name: str
    schema_type: str
    allowed_values: list[dict] = Field(default_factory=list)


class DuplicateWarningOut(BaseModel):
    issue_key: str
    summary: str
    similarity: float


class DraftRequest(BaseModel):
    board_id: int
    text: str
    type_hint: str | None = None  # "story" | "subtask"
    parent_key: str | None = None


class DraftResponse(BaseModel):
    project_key: str
    issue_type: str
    summary: str
    description: str
    parent_key: str | None = None
    required_fields: list[RequiredFieldOut] = Field(default_factory=list)
    duplicate: DuplicateWarningOut | None = None


class CreateIssueRequest(BaseModel):
    board_id: int
    project_key: str
    type: str  # issue type name, e.g. "Story" | "Sub-task"
    summary: str
    description: str
    parent_key: str | None = None
    # User-supplied values for required custom fields, merged verbatim (5.5).
    fields: dict | None = None


class CreateIssueResponse(BaseModel):
    issue_key: str
    issue: IssueOut


# --- reports (Phase 5) ---

class DayBucketOut(BaseModel):
    day: str
    tracked_seconds: int
    logged_seconds: int


class IssueBucketOut(BaseModel):
    issue_key: str | None = None
    tracked_seconds: int
    logged_seconds: int


class WeekReportOut(BaseModel):
    week_start: str
    week_end: str
    total_tracked_seconds: int
    total_logged_seconds: int
    days: list[DayBucketOut] = Field(default_factory=list)
    issues: list[IssueBucketOut] = Field(default_factory=list)


# --- AI text (Phase 5) ---

class AITextRequest(BaseModel):
    text: str


class AITextResponse(BaseModel):
    text: str
    used_ai: bool


class AIStatusOut(BaseModel):
    provider: str
    available: bool


class DraftWorklogRequest(BaseModel):
    issue_key: str
    # ISO timestamp of the session start; git activity since then is summarised.
    since: str


class DraftWorklogResponse(BaseModel):
    text: str
    used_ai: bool
    commit_count: int = 0
    # True when a repo whose branch names the ticket was found; lets the UI
    # distinguish "no repo configured for this ticket" from "no commits yet".
    repo_found: bool = False


# --- settings (Phase 5) ---

class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ai_provider: str
    ollama_url: str | None = None
    ollama_model: str | None = None
    embedding_model: str | None = None
    nudge_time: str | None = None
    idle_threshold_minutes: int
    default_transition: str | None = None
    uses_tempo: bool
    needs_reauth: bool
    # Work window + accountability (local HH:MM; target/interval may be 0 = off).
    work_start_time: str | None = None
    work_end_time: str | None = None
    daily_target_hours: float = 0.0
    checkin_interval_minutes: int = 0
    auto_actual_dates: bool = False
    # Which issues are cached/searched per board (see ISSUE_SCOPE_JQL).
    issue_scope: str = "open_on_board"
    # Whether the third-party AI keys are present in the keychain (never the key
    # values themselves).
    has_gemini_key: bool = False
    has_groq_key: bool = False


class SettingsUpdate(BaseModel):
    ai_provider: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None
    nudge_time: str | None = None
    idle_threshold_minutes: int | None = None
    default_transition: str | None = None
    uses_tempo: bool | None = None
    issue_scope: str | None = None
    work_start_time: str | None = None
    work_end_time: str | None = None
    daily_target_hours: float | None = None
    checkin_interval_minutes: int | None = None
    auto_actual_dates: bool | None = None
    # Optional: set a third-party AI key (stored in the keychain, not the DB).
    gemini_api_key: str | None = None
    groq_api_key: str | None = None


# --- ticket management (Manage screen) ---

class TransitionOut(BaseModel):
    id: str
    name: str | None = None
    to: str | None = None


class DateFieldOut(BaseModel):
    field_id: str
    name: str
    schema_type: str
    value: str | None = None


class SubtaskOut(BaseModel):
    issue_key: str
    summary: str
    status: str | None = None
    status_category: str | None = None
    is_done: bool


class ManageViewOut(BaseModel):
    issue_key: str
    summary: str
    issue_type: str | None = None
    status: str | None = None
    status_category: str | None = None
    assignee_account_id: str | None = None
    assignee_name: str | None = None
    priority_id: str | None = None
    priority_name: str | None = None
    available_transitions: list[TransitionOut] = Field(default_factory=list)
    date_fields: list[DateFieldOut] = Field(default_factory=list)
    subtasks: list[SubtaskOut] = Field(default_factory=list)


class AssignableUserOut(BaseModel):
    account_id: str | None = None
    display_name: str | None = None
    email: str | None = None


class PriorityOut(BaseModel):
    id: str
    name: str | None = None


class SetAssigneeRequest(BaseModel):
    # None unassigns the ticket.
    account_id: str | None = None


class SetPriorityRequest(BaseModel):
    priority_id: str


class CreateSubtaskRequest(BaseModel):
    summary: str


class EditDatesRequest(BaseModel):
    # field_id -> value ("yyyy-MM-dd", ISO datetime, or "" / null to clear)
    values: dict[str, str | None]


class TransitionRequest(BaseModel):
    # Target status name to walk to (e.g. "Done", "In Progress").
    target: str


class TransitionResult(BaseModel):
    applied: list[str] = Field(default_factory=list)
    view: ManageViewOut


class AddWorklogRequest(BaseModel):
    # Time spent, split how the UI collects it. Total seconds = hours*3600 +
    # minutes*60; at least one must be > 0.
    hours: int = 0
    minutes: int = 0
    # When the work started. ISO string ("2026-09-18T14:30") or full offset form;
    # if omitted the server uses "now".
    started: str | None = None
    # Optional worklog comment (plain text, converted to ADF server-side).
    comment: str | None = None


class WorklogEntryOut(BaseModel):
    id: str
    time_spent_seconds: int
    started: str | None = None
    comment: str | None = None
    author: str | None = None


class AddWorklogResult(BaseModel):
    worklog: WorklogEntryOut
    rounded_up: bool = False


# --- my tickets (assigned to me, with due-date attention) ---

class MyTicketOut(BaseModel):
    issue_key: str
    summary: str
    issue_type: str | None = None
    status: str | None = None
    status_category: str | None = None
    priority: str | None = None
    project_key: str | None = None
    due_date: str | None = None
    urgency: str  # overdue | due_today | due_soon | scheduled | no_due
    days_until_due: int | None = None


class MyTicketsOut(BaseModel):
    tickets: list[MyTicketOut] = Field(default_factory=list)
    # Counts per urgency bucket, for the header/badges.
    overdue: int = 0
    due_today: int = 0
    due_soon: int = 0


# --- plan my day (rank + fit tickets to capacity, with learned velocity) ---

class TypeVelocityOut(BaseModel):
    issue_type: str | None = None
    sample_count: int
    avg_seconds: int
    median_seconds: int


class PlanItemOut(BaseModel):
    ticket: MyTicketOut
    estimate_seconds: int
    fits: bool
    cumulative_seconds: int


class DayPlanOut(BaseModel):
    capacity_seconds: int
    planned_seconds: int
    overflow_seconds: int
    fitted_count: int
    total_samples: int  # how much history the velocity is based on
    items: list[PlanItemOut] = Field(default_factory=list)
    velocity_by_type: list[TypeVelocityOut] = Field(default_factory=list)


class EstimateOut(BaseModel):
    issue_type: str | None = None
    estimate_seconds: int
    # Samples backing this specific type; 0 means we used the overall/default
    # fallback, so the UI can soften the wording ("rough estimate").
    sample_count: int
    based_on: str  # "type" | "overall" | "default"


# --- insights (analytics over a range) ---

class InsightBucketOut(BaseModel):
    key: str
    label: str
    tracked_seconds: int
    logged_seconds: int
    session_count: int


class InsightsOut(BaseModel):
    range_start: str
    range_end: str
    total_tracked_seconds: int
    total_logged_seconds: int
    session_count: int
    ticket_count: int
    by_project: list[InsightBucketOut] = Field(default_factory=list)
    by_type: list[InsightBucketOut] = Field(default_factory=list)
    by_ticket: list[InsightBucketOut] = Field(default_factory=list)
    by_day: list[InsightBucketOut] = Field(default_factory=list)


# --- git <-> time reconciliation ---

class ReconcileRowOut(BaseModel):
    issue_key: str
    repo_path: str | None = None
    commit_count: int = 0
    logged_seconds: int = 0
    # "commits_no_time" | "time_no_commits" | "ok"
    flag: str


class ReconcileOut(BaseModel):
    range_start: str
    range_end: str
    rows: list[ReconcileRowOut] = Field(default_factory=list)


# --- outbox (Phase 2) ---

class OutboxItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int | None = None
    kind: str
    state: str
    attempts: int
    last_error: str | None = None
    next_attempt_at: datetime
    jira_result_id: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    # A short human label for the item, derived from the payload (issue key).
    issue_key: str | None = None


class OutboxActionResult(BaseModel):
    item: OutboxItemOut | None = None
    processed: int = 0
    reason: str | None = None
