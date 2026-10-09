from datetime import date, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HealthResponse(BaseModel):
    status: str
    service: str


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "Asia/Seoul"


class TeamRead(TeamCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class EmployeeCreate(BaseModel):
    employee_no: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    active_from: date | None = None
    active_to: date | None = None
    is_active: bool = True


class EmployeeRead(EmployeeCreate):
    id: int
    team_id: int
    model_config = ConfigDict(from_attributes=True)


class EmployeeUpdate(BaseModel):
    employee_no: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    active_from: date | None = None
    active_to: date | None = None
    is_active: bool | None = None


class ShiftTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    category: str
    start_time: time | None = None
    end_time: time | None = None
    ends_next_day: bool = False
    break_minutes: int = Field(default=0, ge=0)
    paid_minutes: int = Field(default=0, ge=0)
    required_qualification_code: str | None = None
    color: str | None = None
    is_work: bool = True

    @model_validator(mode="after")
    def validate_work_times(self) -> "ShiftTypeCreate":
        if self.is_work and (self.start_time is None or self.end_time is None):
            raise ValueError("work shift types require start_time and end_time")
        return self


class ShiftTypeRead(ShiftTypeCreate):
    id: int
    team_id: int
    model_config = ConfigDict(from_attributes=True)


class ShiftTypeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    ends_next_day: bool | None = None
    break_minutes: int | None = Field(default=None, ge=0)
    paid_minutes: int | None = Field(default=None, ge=0)
    required_qualification_code: str | None = None
    color: str | None = None
    is_work: bool | None = None


class WorkRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    min_rest_minutes: int | None = Field(default=None, ge=0)
    max_consecutive_work_days: int | None = Field(default=None, ge=1)
    max_consecutive_night_shifts: int | None = Field(default=None, ge=1)
    night_requires_next_day_off: bool = False
    week_starts_on: str = "MONDAY"
    hard_rules_json: str | None = None
    soft_weights_json: str | None = None
    fairness_config_json: str | None = None


class WorkRuleRead(WorkRuleCreate):
    id: int
    team_id: int
    model_config = ConfigDict(from_attributes=True)


class EmployeeContractCreate(BaseModel):
    employee_id: int
    effective_from: date | None = None
    effective_to: date | None = None
    weekly_work_days: int | None = Field(default=None, ge=1, le=7)
    weekly_pattern_json: str | None = None
    target_minutes_per_week: int | None = Field(default=None, ge=0)
    allowed_shift_type_ids_json: str | None = None
    restrictions_json: str | None = None


class EmployeeContractRead(EmployeeContractCreate):
    id: int
    team_id: int
    model_config = ConfigDict(from_attributes=True)


class CoverageRequirementCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    shift_type_id: int
    days_of_week_json: str
    min_count: int = Field(default=0, ge=0)
    target_count: int = Field(default=0, ge=0)
    max_count: int | None = Field(default=None, ge=0)
    priority: int = 100
    qualification_requirements_json: str | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_counts(self) -> "CoverageRequirementCreate":
        if self.target_count < self.min_count:
            raise ValueError("target_count must be greater than or equal to min_count")
        if self.max_count is not None and self.max_count < self.target_count:
            raise ValueError("max_count must be greater than or equal to target_count")
        return self


class CoverageRequirementRead(CoverageRequirementCreate):
    id: int
    team_id: int
    model_config = ConfigDict(from_attributes=True)


class LeaveRequestCreate(BaseModel):
    employee_id: int
    start_date: date
    end_date: date
    status: str = "REQUESTED"
    leave_type: str = "ANNUAL"
    reason: str | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "LeaveRequestCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class LeaveRequestRead(LeaveRequestCreate):
    id: int
    team_id: int
    model_config = ConfigDict(from_attributes=True)


class AvailabilityCreate(BaseModel):
    employee_id: int
    local_date: date
    availability_type: str = "PREFERRED_OFF"
    shift_type_id: int | None = None
    reason_code: str | None = None
    note: str | None = None
    source: str = "MANUAL"


class AvailabilityRead(AvailabilityCreate):
    id: int
    team_id: int
    model_config = ConfigDict(from_attributes=True)


class AssignmentCreate(BaseModel):
    employee_id: int
    local_date: date
    status: str
    shift_type_id: int | None = None
    version_id: int | None = None
    locked: bool = False
    source: str = "MANUAL"
    change_reason: str | None = None

    @model_validator(mode="after")
    def validate_work_assignment(self) -> "AssignmentCreate":
        if self.status == "WORK" and self.shift_type_id is None:
            raise ValueError("WORK assignments require shift_type_id")
        return self


class AssignmentRead(AssignmentCreate):
    id: int
    team_id: int
    model_config = ConfigDict(from_attributes=True)


class ScheduleAssignmentUpdate(BaseModel):
    employee_id: int
    local_date: date
    status: str = Field(pattern="^(WORK|OFF|LEAVE|OTHER)$")
    shift_type_id: int | None = None
    locked: bool = False
    change_reason: str | None = None

    @model_validator(mode="after")
    def validate_assignment(self) -> "ScheduleAssignmentUpdate":
        if self.status == "WORK" and self.shift_type_id is None:
            raise ValueError("WORK assignments require shift_type_id")
        if self.status != "WORK" and self.shift_type_id is not None:
            raise ValueError("non-work assignments cannot include shift_type_id")
        return self


class ScheduleValidationIssue(BaseModel):
    severity: str
    code: str
    message: str
    local_date: date | None = None
    employee_id: int | None = None
    shift_type_id: int | None = None


class ScheduleValidationRead(BaseModel):
    ok: bool
    issue_count: int
    issues: list[ScheduleValidationIssue]


class SetupQuestion(BaseModel):
    id: str
    label: str
    question: str
    kind: str
    options: list[str] = []


class SetupSummary(BaseModel):
    team: TeamRead
    employees: list[EmployeeRead]
    shift_types: list[ShiftTypeRead]
    work_rules: list[WorkRuleRead]
    employee_contracts: list[EmployeeContractRead]
    coverage_requirements: list[CoverageRequirementRead]
    leave_requests: list[LeaveRequestRead]
    availability: list[AvailabilityRead]
    missing_fields: list[str]
    conflicts: list[str]
    completion_percent: int
    questions: list[SetupQuestion]


class ChatMessage(BaseModel):
    role: str
    content: str


class ProposedChange(BaseModel):
    entity: str
    action: str
    label: str
    before: Any = None
    after: Any = None


class SetupSessionRead(BaseModel):
    id: int
    team_id: int
    status: str
    pending_patch: dict[str, Any] | None = None
    messages: list[ChatMessage] = []
    missing_fields: list[str] = []
    warnings: list[str] = []
    proposed_changes: list[ProposedChange] = []
    questions: list[SetupQuestion] = []


class SetupChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class SetupChatResponse(SetupSessionRead):
    needs_approval: bool


class GenerationCreate(BaseModel):
    year: int = Field(ge=2020, le=2200)
    month: int = Field(ge=1, le=12)
    agent_id: str = Field(pattern="^(codex|claude)$")
    timeout_seconds: int = Field(default=60, ge=5, le=600)


class ConstraintPayload(BaseModel):
    schema_version: str = "1.0"
    team_id: int
    year: int
    month: int
    hard: dict[str, Any] = Field(default_factory=dict)
    soft: dict[str, Any] = Field(default_factory=dict)
    unsupported: list[str] = Field(default_factory=list)
    source: str = "agent"


class GenerationRunRead(BaseModel):
    id: int
    team_id: int
    year: int
    month: int
    agent_id: str
    status: str
    timeout_seconds: int
    constraints: ConstraintPayload | None = None
    result: dict[str, Any] | None = None
    log_text: str | None = None
    error_message: str | None = None
    cancel_requested: bool
    started_at: Any = None
    completed_at: Any = None
    created_at: Any = None
    model_config = ConfigDict(from_attributes=True)


class CalendarAssignment(BaseModel):
    employee_id: int
    employee_name: str
    status: str
    shift_type_id: int | None = None
    shift_type_name: str | None = None
    category: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    ends_next_day: bool = False
    color: str | None = None


class CalendarDay(BaseModel):
    local_date: date
    groups: dict[str, list[CalendarAssignment]]
    assignments: list[CalendarAssignment]


class MonthlyScheduleRead(BaseModel):
    schedule_id: int
    version_id: int
    version_no: int
    year: int
    month: int
    status: str
    solver_status: str | None = None
    days: list[CalendarDay]


class SetupApproveResponse(BaseModel):
    applied: list[ProposedChange]
    summary: SetupSummary
