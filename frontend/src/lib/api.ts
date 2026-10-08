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
