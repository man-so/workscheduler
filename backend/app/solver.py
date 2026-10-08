from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from ortools.sat.python import cp_model

from app import models
from app.constraints import month_dates


@dataclass
class SolveResult:
    status: str
    solver_status: str
    assignments: list[dict[str, Any]]
    objective_value: float | None
    conflicts: list[str]


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    return time.fromisoformat(value)


def _days_of_week(value: Any) -> set[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    mapping = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
    return {mapping[item.upper()] for item in value if isinstance(item, str) and item.upper() in mapping}


def _shift_start_end(day: date, shift: dict[str, Any]) -> tuple[datetime, datetime]:
    start = datetime.combine(day, _parse_time(shift.get("start_time")) or time.min)
    end_day = day + timedelta(days=1) if shift.get("ends_next_day") else day
    end = datetime.combine(end_day, _parse_time(shift.get("end_time")) or time.min)
    if end <= start:
        end += timedelta(days=1)
    return start, end


class _StopOnCancel(cp_model.CpSolverSolutionCallback):
    def __init__(self, cancel_event: Any) -> None:
        super().__init__()
        self.cancel_event = cancel_event

    def on_solution_callback(self) -> None:
        if self.cancel_event.is_set():
            self.StopSearch()


def solve_month(
    payload: dict[str, Any],
    cancel_event: Any,
    max_seconds: int,
) -> SolveResult:
    employees = payload.get("employees", [])
    shifts = payload.get("shift_types", [])
    dates = month_dates(payload["year"], payload["month"])
    hard = payload.get("hard", {})
    soft = payload.get("soft", {})
    model = cp_model.CpModel()

    if not employees:
        return SolveResult("INFEASIBLE", "MODEL_INVALID", [], None, ["활성 직원이 없습니다."])
    if not shifts:
        return SolveResult("INFEASIBLE", "MODEL_INVALID", [], None, ["활성 근무유형이 없습니다."])

    work: dict[tuple[int, int, int], Any] = {}
    work_day: dict[tuple[int, int], Any] = {}
    for employee_index, employee in enumerate(employees):
        contract = next((item for item in hard.get("contracts", []) if item.get("employee_id") == employee["id"]), {})
        allowed = set(contract.get("allowed_shift_type_ids") or [shift["id"] for shift in shifts])
        for day_index, local_date in enumerate(dates):
            variables = []
            for shift_index, shift in enumerate(shifts):
                variable = model.NewBoolVar(f"work_e{employee['id']}_d{day_index}_s{shift['id']}")
                work[(employee_index, day_index, shift_index)] = variable
                variables.append(variable)
                if shift["id"] not in allowed:
                    model.Add(variable == 0)
            day_variable = model.NewBoolVar(f"work_day_e{employee['id']}_d{day_index}")
            work_day[(employee_index, day_index)] = day_variable
            model.Add(sum(variables) == day_variable)

            for item in hard.get("availability", []):
                if item.get("employee_id") != employee["id"] or item.get("local_date") != local_date.isoformat():
                    continue
                if item.get("availability_type") in {"UNAVAILABLE", "PREFERRED_OFF"}:
                    if item.get("availability_type") == "UNAVAILABLE":
                        model.Add(day_variable == 0)
                    if item.get("shift_type_id"):
                        for shift_index, shift in enumerate(shifts):
                            if shift["id"] == item["shift_type_id"]:
                                model.Add(work[(employee_index, day_index, shift_index)] == 0)

            for item in hard.get("leave_requests", []):
                if item.get("employee_id") == employee["id"] and item.get("start_date") <= local_date.isoformat() <= item.get("end_date"):
                    model.Add(day_variable == 0)

    for employee_index, employee in enumerate(employees):
        contract = next((item for item in hard.get("contracts", []) if item.get("employee_id") == employee["id"]), {})
        weekly_limit = contract.get("weekly_work_days")
        if weekly_limit:
            for week_start in range(0, len(dates), 7):
                model.Add(sum(work_day[(employee_index, index)] for index in range(week_start, min(week_start + 7, len(dates)))) <= weekly_limit)

        for window_start in range(len(dates)):
            max_consecutive = next((rule.get("max_consecutive_work_days") for rule in hard.get("work_rules", []) if rule.get("max_consecutive_work_days")), None)
            if max_consecutive and window_start + max_consecutive < len(dates):
                model.Add(sum(work_day[(employee_index, index)] for index in range(window_start, window_start + max_consecutive + 1)) <= max_consecutive)

            max_nights = next((rule.get("max_consecutive_night_shifts") for rule in hard.get("work_rules", []) if rule.get("max_consecutive_night_shifts")), None)
            if max_nights and window_start + max_nights < len(dates):
                nights = [work[(employee_index, index, shift_index)] for index in range(window_start, window_start + max_nights + 1) for shift_index, shift in enumerate(shifts) if shift.get("category") in {"NIGHT", "EARLY_NIGHT"}]
                model.Add(sum(nights) <= max_nights)

    for employee_index in range(len(employees)):
        for day_index in range(len(dates) - 1):
            for first_index, first_shift in enumerate(shifts):
                first_end = _shift_start_end(dates[day_index], first_shift)[1]
                for next_index, next_shift in enumerate(shifts):
                    next_start = _shift_start_end(dates[day_index + 1], next_shift)[0]
                    for rule in hard.get("work_rules", []):
                        minimum_rest = rule.get("min_rest_minutes")
                        if minimum_rest is not None and (next_start - first_end).total_seconds() / 60 < minimum_rest:
                            model.Add(work[(employee_index, day_index, first_index)] + work[(employee_index, day_index + 1, next_index)] <= 1)
                    if first_shift.get("category") in {"NIGHT", "EARLY_NIGHT"}:
                        if any(rule.get("night_requires_next_day_off") for rule in hard.get("work_rules", [])):
                            model.Add(work[(employee_index, day_index, first_index)] + work_day[(employee_index, day_index + 1)] <= 1)

    objective_terms = []
    for requirement in hard.get("coverage", []):
        days = _days_of_week(requirement.get("days_of_week", []))
        shift_id = requirement.get("shift_type_id")
        shift_index = next((index for index, shift in enumerate(shifts) if shift["id"] == shift_id), None)
        if shift_index is None:
            continue
        for day_index, local_date in enumerate(dates):
            if local_date.weekday() not in days:
                continue
            count = sum(work[(employee_index, day_index, shift_index)] for employee_index in range(len(employees)))
            model.Add(count >= requirement.get("min_count", 0))
            if requirement.get("max_count") is not None:
                model.Add(count <= requirement["max_count"])
            deviation = model.NewIntVar(0, len(employees), f"coverage_dev_{requirement.get('id')}_{day_index}")
            model.AddAbsEquality(deviation, count - requirement.get("target_count", 0))
            objective_terms.append((requirement.get("priority", 100), deviation))

    for item in hard.get("availability", []):
        if item.get("availability_type") == "PREFERRED_OFF":
            employee_index = next((index for index, employee in enumerate(employees) if employee["id"] == item.get("employee_id")), None)
            day_index = next((index for index, local_date in enumerate(dates) if local_date.isoformat() == item.get("local_date")), None)
            if employee_index is not None and day_index is not None:
                objective_terms.append((soft.get("weights", {}).get("preferred_off", 20), work_day[(employee_index, day_index)]))

    night_counts = []
    for employee_index in range(len(employees)):
        night_count = sum(work[(employee_index, day_index, shift_index)] for day_index in range(len(dates)) for shift_index, shift in enumerate(shifts) if shift.get("category") in {"NIGHT", "EARLY_NIGHT"})
        night_counts.append(night_count)
    fairness_weight = soft.get("fairness", {}).get("night", 10)
    for left in range(len(night_counts)):
        for right in range(left + 1, len(night_counts)):
            difference = model.NewIntVar(0, len(dates), f"night_fairness_{left}_{right}")
            model.AddAbsEquality(difference, night_counts[left] - night_counts[right])
            objective_terms.append((fairness_weight, difference))

    model.Minimize(sum(weight * variable for weight, variable in objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    callback = _StopOnCancel(cancel_event)
    status = solver.Solve(model, callback)
    status_name = solver.StatusName(status)
    if cancel_event.is_set():
        return SolveResult("CANCELED", status_name, [], None, ["사용자가 계산을 취소했습니다."])
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        conflicts = ["Hard constraint를 동시에 만족하는 해를 찾지 못했습니다."]
        if status == cp_model.INFEASIBLE:
            conflicts.append("필요 인원, 휴무, 근무 가능 유형, 휴식시간 또는 연속근무 제한을 확인하세요.")
        return SolveResult("INFEASIBLE", status_name, [], None, conflicts)

    assignments: list[dict[str, Any]] = []
    for employee_index, employee in enumerate(employees):
        for day_index, local_date in enumerate(dates):
            selected = next((shift for shift_index, shift in enumerate(shifts) if solver.Value(work[(employee_index, day_index, shift_index)])), None)
            assignments.append({
                "employee_id": employee["id"],
                "local_date": local_date.isoformat(),
                "status": "WORK" if selected else "OFF",
                "shift_type_id": selected.get("id") if selected else None,
            })
    return SolveResult("SUCCEEDED", status_name, assignments, solver.ObjectiveValue(), [])
