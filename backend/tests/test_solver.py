from datetime import date
from threading import Event

from app.solver import solve_month


def payload(*, employees=None, coverage=None, rules=None, contracts=None, availability=None, shifts=None):
    return {
        "schema_version": "1.0",
        "team_id": 1,
        "year": 2026,
        "month": 2,
        "employees": employees or [{"id": 1, "display_name": "직원A"}, {"id": 2, "display_name": "직원B"}, {"id": 3, "display_name": "직원C"}],
        "shift_types": shifts or [
            {"id": 10, "name": "주간", "category": "DAY", "start_time": "09:00:00", "end_time": "17:00:00", "ends_next_day": False, "paid_minutes": 480},
            {"id": 11, "name": "야간", "category": "NIGHT", "start_time": "22:00:00", "end_time": "06:00:00", "ends_next_day": True, "paid_minutes": 480},
            {"id": 12, "name": "조기", "category": "EARLY_DAY", "start_time": "06:00:00", "end_time": "14:00:00", "ends_next_day": False, "paid_minutes": 480},
            {"id": 13, "name": "야간조기", "category": "EARLY_NIGHT", "start_time": "18:00:00", "end_time": "02:00:00", "ends_next_day": True, "paid_minutes": 480},
        ],
        "hard": {
            "work_rules": rules or [],
            "contracts": contracts or [],
            "coverage": coverage or [{"id": 1, "shift_type_id": 10, "days_of_week": ["MON", "TUE", "WED", "THU", "FRI"], "min_count": 1, "target_count": 1, "max_count": 1, "priority": 100}],
            "leave_requests": [],
            "availability": availability or [],
        },
        "soft": {"weights": {}, "fairness": {"night": 5}},
        "unsupported": [],
    }


def test_general_and_mixed_day_night_team_covers_every_employee_date():
    result = solve_month(payload(), Event(), 5)

    assert result.status == "SUCCEEDED"
    assert len(result.assignments) == 3 * 28
    assert {item["status"] for item in result.assignments} <= {"WORK", "OFF"}


def test_mixed_four_and_five_day_contracts_with_early_shifts():
    contracts = [
        {"employee_id": 1, "weekly_work_days": 4, "allowed_shift_type_ids": [10, 12]},
        {"employee_id": 2, "weekly_work_days": 5, "allowed_shift_type_ids": [10, 11, 13]},
    ]
    result = solve_month(payload(contracts=contracts), Event(), 5)

    assert result.status == "SUCCEEDED"
    employee_one = [item for item in result.assignments if item["employee_id"] == 1 and item["status"] == "WORK"]
    assert all(item["shift_type_id"] in {10, 12} for item in employee_one)


def test_rest_and_night_followed_by_off_are_hard_constraints():
    result = solve_month(payload(rules=[{"min_rest_minutes": 660, "night_requires_next_day_off": True}]), Event(), 5)

    assert result.status == "SUCCEEDED"
    by_employee = {}
    for item in result.assignments:
        by_employee.setdefault(item["employee_id"], {})[item["local_date"]] = item
    for days in by_employee.values():
        ordered = sorted(days)
        for index, day in enumerate(ordered[:-1]):
            if days[day]["shift_type_id"] == 11:
                assert days[ordered[index + 1]]["status"] == "OFF"


def test_conflicting_coverage_returns_infeasible_with_reason():
    result = solve_month(payload(employees=[{"id": 1, "display_name": "직원A"}], coverage=[{"id": 1, "shift_type_id": 10, "days_of_week": ["MON"], "min_count": 2, "target_count": 2, "max_count": 2, "priority": 100}]), Event(), 5)

    assert result.status == "INFEASIBLE"
    assert result.conflicts
