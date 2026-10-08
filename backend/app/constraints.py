from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.setup_logic import dumps, loads


def month_dates(year: int, month: int) -> list[date]:
    return [date(year, month, day) for day in range(1, monthrange(year, month)[1] + 1)]


def build_constraint_payload(db: Session, team: models.Team, year: int, month: int) -> dict[str, Any]:
    employees = db.scalars(select(models.Employee).where(models.Employee.team_id == team.id, models.Employee.is_active.is_(True))).all()
    shifts = db.scalars(select(models.ShiftType).where(models.ShiftType.team_id == team.id, models.ShiftType.is_active.is_(True))).all()
    contracts = db.scalars(select(models.EmployeeContract).where(models.EmployeeContract.team_id == team.id)).all()
    rules = db.scalars(select(models.WorkRule).where(models.WorkRule.team_id == team.id)).all()
    coverage = db.scalars(select(models.CoverageRequirement).where(models.CoverageRequirement.team_id == team.id, models.CoverageRequirement.is_active.is_(True))).all()
    leave_requests = db.scalars(select(models.LeaveRequest).where(models.LeaveRequest.team_id == team.id)).all()
    availability = db.scalars(select(models.Availability).where(models.Availability.team_id == team.id)).all()

    hard_rules = []
    soft_weights: dict[str, Any] = {}
    for rule in rules:
        hard_rules.append({
            "name": rule.name,
            "min_rest_minutes": rule.min_rest_minutes,
            "max_consecutive_work_days": rule.max_consecutive_work_days,
            "max_consecutive_night_shifts": rule.max_consecutive_night_shifts,
            "night_requires_next_day_off": rule.night_requires_next_day_off,
            "hard_rules": loads(rule.hard_rules_json, {}),
        })
        soft_weights.update(loads(rule.soft_weights_json, {}))

    unsupported: list[str] = []
    for contract in contracts:
        if contract.target_minutes_per_week is not None:
            unsupported.append(f"employee {contract.employee_id}: target_minutes_per_week is not yet modeled")
        if loads(contract.weekly_pattern_json, {}):
            unsupported.append(f"employee {contract.employee_id}: weekly_pattern requires additional modeling")
        if loads(contract.restrictions_json, {}):
            unsupported.append(f"employee {contract.employee_id}: custom restrictions require explicit schema support")
    for requirement in coverage:
        if loads(requirement.qualification_requirements_json, []):
            unsupported.append(f"coverage {requirement.id}: qualification requirements need employee qualification data")
    for rule in rules:
        if loads(rule.hard_rules_json, {}):
            unsupported.append(f"work rule {rule.id}: custom hard_rules_json requires explicit engine support")

    return {
        "schema_version": "1.0",
        "team_id": team.id,
        "team_name": team.name,
        "timezone": team.timezone,
        "year": year,
        "month": month,
        "employees": [
            {"id": employee.id, "employee_no": employee.employee_no, "display_name": employee.display_name}
            for employee in employees
        ],
        "shift_types": [
            {
                "id": shift.id,
                "code": shift.code,
                "name": shift.name,
                "category": shift.category,
                "start_time": shift.start_time.isoformat() if shift.start_time else None,
                "end_time": shift.end_time.isoformat() if shift.end_time else None,
                "ends_next_day": shift.ends_next_day,
                "paid_minutes": shift.paid_minutes,
                "required_qualification_code": shift.required_qualification_code,
            }
            for shift in shifts
            if shift.is_work
        ],
        "hard": {
            "work_rules": hard_rules,
            "contracts": [
                {
                    "employee_id": contract.employee_id,
                    "weekly_work_days": contract.weekly_work_days,
                    "weekly_pattern": loads(contract.weekly_pattern_json, {}),
                    "target_minutes_per_week": contract.target_minutes_per_week,
                    "allowed_shift_type_ids": loads(contract.allowed_shift_type_ids_json, []),
                    "restrictions": loads(contract.restrictions_json, {}),
                }
                for contract in contracts
            ],
            "coverage": [
                {
                    "id": requirement.id,
                    "shift_type_id": requirement.shift_type_id,
                    "days_of_week": loads(requirement.days_of_week_json, []),
                    "min_count": requirement.min_count,
                    "target_count": requirement.target_count,
                    "max_count": requirement.max_count,
                    "priority": requirement.priority,
                    "qualifications": loads(requirement.qualification_requirements_json, []),
                }
                for requirement in coverage
            ],
            "leave_requests": [
                {
                    "employee_id": leave.employee_id,
                    "start_date": leave.start_date.isoformat(),
                    "end_date": leave.end_date.isoformat(),
                    "status": leave.status,
                }
                for leave in leave_requests
                if leave.status == models.LeaveStatus.APPROVED
            ],
            "availability": [
                {
                    "employee_id": item.employee_id,
                    "local_date": item.local_date.isoformat(),
                    "availability_type": item.availability_type,
                    "shift_type_id": item.shift_type_id,
                }
                for item in availability
            ],
        },
        "soft": {
            "weights": soft_weights,
            "fairness": {"night": 10, "early": 6, "weekend": 4, "total_work_minutes": 2},
        },
        "unsupported": unsupported,
        "source": "approved-settings",
    }


def normalize_agent_constraints(raw: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") != "1.0":
        raise ValueError("unsupported constraint schema_version")
    if raw.get("team_id") != base["team_id"] or raw.get("year") != base["year"] or raw.get("month") != base["month"]:
        raise ValueError("constraint scope does not match the requested team or month")
    if not isinstance(raw.get("hard"), dict) or not isinstance(raw.get("soft"), dict):
        raise ValueError("hard and soft constraints must be objects")
    unsupported = raw.get("unsupported", [])
    if not isinstance(unsupported, list) or any(not isinstance(item, str) for item in unsupported):
        raise ValueError("unsupported must be a list of strings")
    normalized = {**base, "hard": raw["hard"], "soft": raw["soft"], "unsupported": sorted(set(base.get("unsupported", []) + unsupported)), "source": "agent"}
    if "work_rules" not in normalized["hard"] or "contracts" not in normalized["hard"] or "coverage" not in normalized["hard"]:
        raise ValueError("agent response omitted required hard constraint sections")
    return normalized


def constraint_json(payload: dict[str, Any]) -> str:
    return dumps(payload)
