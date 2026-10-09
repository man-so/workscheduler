export type HealthResponse = {
  status: string;
  service: string;
};

export type Team = {
  id: number;
  name: string;
  timezone: string;
};

export type Employee = {
  id: number;
  team_id: number;
  employee_no: string;
  display_name: string;
  is_active: boolean;
};

export type ShiftType = {
  id: number;
  team_id: number;
  code: string;
  name: string;
  category: string;
  start_time: string | null;
  end_time: string | null;
  ends_next_day: boolean;
  break_minutes: number;
  paid_minutes: number;
  is_work: boolean;
};

export type WorkRule = {
  id: number;
  team_id: number;
  name: string;
  min_rest_minutes: number | null;
  max_consecutive_work_days: number | null;
  max_consecutive_night_shifts: number | null;
  night_requires_next_day_off: boolean;
};

export type CoverageRequirement = {
  id: number;
  team_id: number;
  name: string;
  shift_type_id: number;
  days_of_week_json: string;
  min_count: number;
  target_count: number;
  max_count: number | null;
  priority: number;
  qualification_requirements_json: string | null;
  is_active: boolean;
};

export type SetupQuestion = {
  id: string;
  label: string;
  question: string;
  kind: string;
  options: string[];
};

export type ProposedChange = {
  entity: string;
  action: string;
  label: string;
  before: unknown;
  after: unknown;
};

export type SetupSummary = {
  team: Team;
  employees: Employee[];
  shift_types: ShiftType[];
  work_rules: WorkRule[];
  employee_contracts: unknown[];
  coverage_requirements: CoverageRequirement[];
  leave_requests: unknown[];
  availability: unknown[];
  missing_fields: string[];
  conflicts: string[];
  completion_percent: number;
  questions: SetupQuestion[];
};

export type SetupSession = {
  id: number;
  team_id: number;
  status: string;
  pending_patch: Record<string, unknown> | null;
  messages: { role: string; content: string }[];
  missing_fields: string[];
  warnings: string[];
  proposed_changes: ProposedChange[];
  questions: SetupQuestion[];
  needs_approval?: boolean;
};

export type GenerationRun = {
  id: number;
  team_id: number;
  year: number;
  month: number;
  agent_id: string;
  status: string;
  timeout_seconds: number;
  constraints: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  log_text: string | null;
  error_message: string | null;
  cancel_requested: boolean;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
};

export type CalendarAssignment = {
  employee_id: number;
  employee_name: string;
  status: string;
  shift_type_id: number | null;
  shift_type_name: string | null;
  category: string | null;
  start_time: string | null;
  end_time: string | null;
  ends_next_day: boolean;
  color: string | null;
};

export type CalendarDay = {
  local_date: string;
  groups: Record<string, CalendarAssignment[]>;
  assignments: CalendarAssignment[];
};

export type MonthlySchedule = {
  schedule_id: number;
  version_id: number;
  version_no: number;
  year: number;
  month: number;
  status: string;
  solver_status: string | null;
  days: CalendarDay[];
};

export type ScheduleValidationIssue = {
  severity: string;
  code: string;
  message: string;
  local_date: string | null;
  employee_id: number | null;
  shift_type_id: number | null;
};

export type ScheduleValidation = {
  ok: boolean;
  issue_count: number;
  issues: ScheduleValidationIssue[];
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    },
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

export function listTeams(): Promise<Team[]> {
  return request<Team[]>("/api/teams");
}

export function listEmployees(teamId: number): Promise<Employee[]> {
  return request<Employee[]>(`/api/teams/${teamId}/employees`);
}

export function listShiftTypes(teamId: number): Promise<ShiftType[]> {
  return request<ShiftType[]>(`/api/teams/${teamId}/shift-types`);
}

export function createTeam(name: string): Promise<Team> {
  return post<Team>("/api/teams", { name });
}

export function createEmployee(teamId: number, displayName: string): Promise<Employee> {
  return post<Employee>(`/api/teams/${teamId}/employees`, {
    employee_no: `EMP-${displayName}`,
    display_name: displayName
  });
}

export function createShiftType(teamId: number, payload: Partial<ShiftType> & { code: string; name: string; category: string }): Promise<ShiftType> {
  return post<ShiftType>(`/api/teams/${teamId}/shift-types`, payload);
}

export function createWorkRule(teamId: number, payload: Partial<WorkRule> & { name: string }): Promise<WorkRule> {
  return post<WorkRule>(`/api/teams/${teamId}/work-rules`, payload);
}

export function createCoverageRequirement(
  teamId: number,
  payload: Omit<CoverageRequirement, "id" | "team_id">
): Promise<CoverageRequirement> {
  return post<CoverageRequirement>(`/api/teams/${teamId}/coverage-requirements`, payload);
}

export function getSetupSummary(teamId: number): Promise<SetupSummary> {
  return request<SetupSummary>(`/api/teams/${teamId}/setup-summary`);
}

export function getActiveSetupSession(teamId: number): Promise<SetupSession> {
  return request<SetupSession>(`/api/teams/${teamId}/setup-sessions/active`);
}

export function sendSetupMessage(teamId: number, sessionId: number, message: string): Promise<SetupSession> {
  return post<SetupSession>(`/api/teams/${teamId}/setup-sessions/${sessionId}/messages`, { message });
}

export function approveSetupPatch(teamId: number, sessionId: number): Promise<{ applied: ProposedChange[]; summary: SetupSummary }> {
  return post<{ applied: ProposedChange[]; summary: SetupSummary }>(`/api/teams/${teamId}/setup-sessions/${sessionId}/approve`, {});
}

export function generateSchedule(teamId: number, payload: { year: number; month: number; agent_id: "codex" | "claude"; timeout_seconds: number }): Promise<GenerationRun> {
  return post<GenerationRun>(`/api/teams/${teamId}/schedules/generate`, payload);
}

export function getGenerationRun(teamId: number, runId: number): Promise<GenerationRun> {
  return request<GenerationRun>(`/api/teams/${teamId}/generation-runs/${runId}`);
}

export function cancelGeneration(teamId: number, runId: number): Promise<GenerationRun> {
  return post<GenerationRun>(`/api/teams/${teamId}/generation-runs/${runId}/cancel`, {});
}

export function getMonthlySchedule(teamId: number, year: number, month: number): Promise<MonthlySchedule> {
  return request<MonthlySchedule>(`/api/teams/${teamId}/schedules/${year}/${month}`);
}

export function updateScheduleAssignment(
  teamId: number,
  year: number,
  month: number,
  payload: {
    employee_id: number;
    local_date: string;
    status: "WORK" | "OFF" | "LEAVE" | "OTHER";
    shift_type_id: number | null;
    locked?: boolean;
    change_reason?: string | null;
  }
): Promise<MonthlySchedule> {
  return patch<MonthlySchedule>(`/api/teams/${teamId}/schedules/${year}/${month}/assignments`, payload);
}

export function validateMonthlySchedule(teamId: number, year: number, month: number): Promise<ScheduleValidation> {
  return request<ScheduleValidation>(`/api/teams/${teamId}/schedules/${year}/${month}/validation`);
}
