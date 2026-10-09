from __future__ import annotations

from datetime import date, time
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas


DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def get_team_rows(db: Session, team_id: int) -> dict[str, list[Any]]:
    return {
        "employees": list(db.scalars(select(models.Employee).where(models.Employee.team_id == team_id))),
        "shift_types": list(db.scalars(select(models.ShiftType).where(models.ShiftType.team_id == team_id))),
        "leave_types": list(db.scalars(select(models.LeaveType).where(models.LeaveType.team_id == team_id))),
        "work_rules": list(db.scalars(select(models.WorkRule).where(models.WorkRule.team_id == team_id))),
        "employee_contracts": list(db.scalars(select(models.EmployeeContract).where(models.EmployeeContract.team_id == team_id))),
        "coverage_requirements": list(db.scalars(select(models.CoverageRequirement).where(models.CoverageRequirement.team_id == team_id))),
        "leave_requests": list(db.scalars(select(models.LeaveRequest).where(models.LeaveRequest.team_id == team_id))),
        "availability": list(db.scalars(select(models.Availability).where(models.Availability.team_id == team_id))),
    }


def build_questions(missing_fields: list[str], conflicts: list[str]) -> list[schemas.SetupQuestion]:
    questions: list[schemas.SetupQuestion] = []
    if "employees" in missing_fields:
        questions.append(
            schemas.SetupQuestion(
                id="employees",
                label="직원",
                question="소속 직원 이름을 쉼표로 구분해 입력해 주세요.",
                kind="text",
            )
        )
    if "shift_types" in missing_fields:
        questions.append(
            schemas.SetupQuestion(
                id="shift_types",
                label="근무유형",
                question="근무유형과 시간을 입력해 주세요. 예: 주간 09:00-18:00, 야간 22:00-06:00",
                kind="text",
            )
        )
    if "coverage" in missing_fields:
        questions.append(
            schemas.SetupQuestion(
                id="coverage",
                label="필요 인원",
                question="요일별·근무유형별 필요 인원을 입력해 주세요. 예: 평일 주간 2명, 야간 1명",
                kind="text",
            )
        )
    if "work_rules" in missing_fields:
        questions.append(
            schemas.SetupQuestion(
                id="work_rules",
                label="근무규칙",
                question="최소 휴식시간과 연속근무 제한을 입력해 주세요. 예: 최소 휴식 11시간, 연속근무 5일",
                kind="text",
            )
        )
    if conflicts:
        questions.append(
            schemas.SetupQuestion(
                id="conflicts",
                label="충돌",
                question="표시된 충돌 항목을 확인하고 수정해 주세요.",
                kind="review",
            )
        )
    return questions[:3]


def analyze_setup(db: Session, team: models.Team) -> schemas.SetupSummary:
    rows = get_team_rows(db, team.id)
    missing: list[str] = []
    conflicts: list[str] = []

    employees = rows["employees"]
    shifts = [shift for shift in rows["shift_types"] if shift.is_active]
    rules = rows["work_rules"]
    contracts = rows["employee_contracts"]
    coverage = rows["coverage_requirements"]

    if not employees:
        missing.append("employees")
    if not shifts:
        missing.append("shift_types")
    if not coverage:
        missing.append("coverage")
    if not rules:
        missing.append("work_rules")

    employee_ids = {employee.id for employee in employees}
    contracted_ids = {contract.employee_id for contract in contracts}
    for employee in employees:
        if employee.id not in contracted_ids:
            missing.append(f"contract:{employee.id}")

    shift_ids = {shift.id for shift in shifts}
    for requirement in coverage:
        if requirement.shift_type_id not in shift_ids:
            conflicts.append(f"필요 인원이 비활성 또는 없는 근무유형을 참조합니다: {requirement.name}")
        if requirement.max_count is not None and requirement.max_count < requirement.target_count:
            conflicts.append(f"최대 인원이 목표 인원보다 작습니다: {requirement.name}")

    for contract in contracts:
        if contract.employee_id not in employee_ids:
            conflicts.append("직원 계약이 없는 직원을 참조합니다.")
        allowed_ids = set(loads(contract.allowed_shift_type_ids_json, []))
        if allowed_ids and not allowed_ids.issubset(shift_ids):
            conflicts.append("직원 가능 근무유형에 없는 근무유형 ID가 포함되어 있습니다.")

    complete_items = 4 - len({item for item in missing if item in {"employees", "shift_types", "coverage", "work_rules"}})
    completion = max(0, min(100, round((complete_items / 4) * 100)))

    return schemas.SetupSummary(
        team=team,
        employees=employees,
        shift_types=rows["shift_types"],
        leave_types=rows["leave_types"],
        work_rules=rules,
        employee_contracts=contracts,
        coverage_requirements=coverage,
        leave_requests=rows["leave_requests"],
        availability=rows["availability"],
        missing_fields=sorted(set(missing)),
        conflicts=conflicts,
        completion_percent=completion,
        questions=build_questions(sorted(set(missing)), conflicts),
    )


def normalize_shift_code(name: str) -> tuple[str, str]:
    if "야간" in name and "조기" in name:
        return "EARLY_NIGHT", "EARLY_NIGHT"
    if "야간" in name:
        return "NIGHT", "NIGHT"
    if "조기" in name or "아침" in name:
        return "EARLY_DAY", "EARLY_DAY"
    if "휴무" in name:
        return "OFF", "OFF"
    return "DAY", "DAY"


def parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def parse_setup_message(message: str, team: models.Team, rows: dict[str, list[Any]]) -> dict[str, Any]:
    patch: dict[str, Any] = {
        "team": {},
        "employees": [],
        "shift_types": [],
        "work_rules": [],
        "coverage_requirements": [],
        "employee_contracts": [],
        "availability": [],
    }
    text = message.strip()

    team_match = re.search(r"팀\s*(?:이름은|명은|:)?\s*([가-힣A-Za-z0-9 _-]{2,40})", text)
    if team_match:
        patch["team"]["name"] = team_match.group(1).strip()

    employee_segment = None
    for keyword in ["직원은", "직원:", "직원 "]:
        if keyword in text:
            employee_segment = text.split(keyword, 1)[1]
            employee_segment = re.split(r"(?:근무유형|필요|규칙|휴식|연속|주간|야간)", employee_segment, maxsplit=1)[0]
            break
    if employee_segment:
        for raw_name in re.split(r"[,/、\n]+|그리고|및", employee_segment):
            name = raw_name.strip(" .입니다")
            if 1 < len(name) <= 30:
                patch["employees"].append({"display_name": name, "employee_no": slug_employee_no(name)})

    for match in re.finditer(r"([가-힣A-Za-z ]{1,12})\s*(\d{1,2}:\d{2})\s*[-~]\s*(\d{1,2}:\d{2})", text):
        name = match.group(1).strip()
        start = parse_time(match.group(2))
        end = parse_time(match.group(3))
        code, category = normalize_shift_code(name)
        patch["shift_types"].append(
            {
                "code": code,
                "name": name,
                "category": category,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "ends_next_day": end <= start,
                "break_minutes": 60 if category in {"DAY", "EARLY_DAY"} else 0,
                "paid_minutes": 480,
                "is_work": category != "OFF",
            }
        )

    min_rest = re.search(r"최소\s*휴식\s*(\d+)\s*(?:시간|h)", text)
    max_work = re.search(r"연속\s*근무\s*(\d+)\s*일", text)
    max_night = re.search(r"연속\s*야간\s*(\d+)\s*일", text)
    if min_rest or max_work or max_night or "야간 후 휴무" in text:
        patch["work_rules"].append(
            {
                "name": "기본 근무규칙",
                "min_rest_minutes": int(min_rest.group(1)) * 60 if min_rest else None,
                "max_consecutive_work_days": int(max_work.group(1)) if max_work else None,
                "max_consecutive_night_shifts": int(max_night.group(1)) if max_night else None,
                "night_requires_next_day_off": "야간 후 휴무" in text,
                "soft_weights_json": parse_fairness_weights(text),
            }
        )

    shift_name_to_id = {shift.name: shift.id for shift in rows["shift_types"]}
    shift_name_to_id.update({shift.category: shift.id for shift in rows["shift_types"]})
    for match in re.finditer(r"(평일|주말|월|화|수|목|금|토|일)?\s*(주간|야간|조기|아침 조기|야간 조기)\s*(\d+)\s*명", text):
        day_word = match.group(1) or "평일"
        shift_word = match.group(2)
        count = int(match.group(3))
        shift_id = find_shift_id(shift_word, rows["shift_types"])
        if shift_id:
            patch["coverage_requirements"].append(
                {
                    "name": f"{day_word} {shift_word}",
                    "shift_type_id": shift_id,
                    "days_of_week_json": dumps(days_for_word(day_word)),
                    "min_count": count,
                    "target_count": count,
                    "max_count": count,
                }
            )

    employees_by_name = {employee.display_name: employee for employee in rows["employees"]}
    for match in re.finditer(r"([가-힣A-Za-z0-9 _-]+)\s*(?:은|는)\s*주\s*([45])\s*일", text):
        employee = employees_by_name.get(match.group(1).strip().rstrip("은는"))
        if employee:
            patch["employee_contracts"].append({"employee_id": employee.id, "weekly_work_days": int(match.group(2))})

    leave_type_by_code = {leave_type.code: leave_type for leave_type in rows.get("leave_types", [])}
    leave_type_by_name = {leave_type.name: leave_type for leave_type in rows.get("leave_types", [])}
    leave_words = [
        ("대체휴무", "COMPENSATORY"),
        ("대휴", "COMPENSATORY"),
        ("연차", "ANNUAL"),
        ("정기휴무", "REGULAR"),
        ("특별휴무", "SPECIAL"),
        ("휴무", "UNSPECIFIED"),
    ]
    date_pattern = r"((?:\d{4}-\d{2}-\d{2})|(?:\d{1,2}월\s*\d{1,2}일))"
    for match in re.finditer(rf"{date_pattern}\s*([가-힣A-Za-z0-9 _-]+)\s*(대체휴무|대휴|연차|정기휴무|특별휴무|휴무|쉬)", text):
        employee = employees_by_name.get(match.group(2).strip(" ."))
        if employee:
            word = match.group(3)
            code = next(code for label, code in leave_words if label == word)
            local_date = normalize_date_text(match.group(1))
            availability = {
                "employee_id": employee.id,
                "local_date": local_date,
                "availability_type": "UNAVAILABLE" if code in {"ANNUAL", "COMPENSATORY", "SPECIAL"} else "PREFERRED_OFF",
                "leave_type_id": leave_type_by_code.get(code).id if leave_type_by_code.get(code) else None,
                "note": "챗봇 입력",
                "source": "CHAT",
            }
            origin_match = re.search(rf"{re.escape(match.group(0))}.*?{date_pattern}\s*근무", text)
            if code == "COMPENSATORY" and origin_match:
                availability["comp_origin_work_date"] = normalize_date_text(origin_match.group(1))
            if code == "COMPENSATORY" and not availability.get("comp_origin_work_date"):
                availability["requires_origin"] = True
            patch["availability"].append(availability)

    for match in re.finditer(rf"([가-힣A-Za-z0-9 _-]+?)\s*(?:은|는)?\s*{date_pattern}\s*(대체휴무|대휴|연차|정기휴무|특별휴무|휴무|쉬)", text):
        employee = employees_by_name.get(match.group(1).strip(" ."))
        if employee:
            word = match.group(3)
            code = next(code for label, code in leave_words if label == word or (word == "쉬" and label == "휴무"))
            local_date = normalize_date_text(match.group(2))
            if any(item["employee_id"] == employee.id and item["local_date"] == local_date for item in patch["availability"]):
                continue
            leave_type = leave_type_by_code.get(code) or leave_type_by_name.get(word)
            availability = {
                    "employee_id": employee.id,
                    "local_date": local_date,
                    "availability_type": "UNAVAILABLE" if code in {"ANNUAL", "COMPENSATORY", "SPECIAL"} else "PREFERRED_OFF",
                    "leave_type_id": leave_type.id if leave_type else None,
                    "note": "챗봇 입력",
                    "source": "CHAT",
                }
            if code == "COMPENSATORY":
                availability["requires_origin"] = True
            patch["availability"].append(availability)

    return patch


def slug_employee_no(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9가-힣]+", "-", name).strip("-")
    return f"EMP-{slug[:24]}"


def parse_fairness_weights(text: str) -> str | None:
    weights: dict[str, int] = {}
    for key, label in [("night", "야간"), ("early", "조기"), ("weekend", "주말")]:
        match = re.search(rf"{label}\s*(?:가중치|공정성)?\s*(\d+)", text)
        if match:
            weights[key] = int(match.group(1))
    return dumps(weights) if weights else None


def normalize_date_text(value: str) -> str:
    value = value.replace(" ", "")
    if "-" in value:
        return value
    match = re.match(r"(\d{1,2})월(\d{1,2})일", value)
    if not match:
        return value
    year = date.today().year
    return f"{year}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"


def days_for_word(word: str) -> list[str]:
    if word == "평일":
        return ["MON", "TUE", "WED", "THU", "FRI"]
    if word == "주말":
        return ["SAT", "SUN"]
    mapping = {"월": "MON", "화": "TUE", "수": "WED", "목": "THU", "금": "FRI", "토": "SAT", "일": "SUN"}
    return [mapping.get(word, "MON")]


def find_shift_id(word: str, shifts: list[models.ShiftType]) -> int | None:
    for shift in shifts:
        if word in shift.name or word in shift.category:
            return shift.id
    return None


def proposed_changes_from_patch(patch: dict[str, Any], team: models.Team) -> list[schemas.ProposedChange]:
    changes: list[schemas.ProposedChange] = []
    if patch.get("team", {}).get("name"):
        changes.append(
            schemas.ProposedChange(
                entity="team",
                action="update",
                label="팀 이름",
                before=team.name,
                after=patch["team"]["name"],
            )
        )
    for key, label in [
        ("employees", "직원"),
        ("shift_types", "근무유형"),
        ("work_rules", "근무규칙"),
        ("coverage_requirements", "필요 인원"),
        ("employee_contracts", "직원 계약"),
        ("availability", "휴무 희망"),
    ]:
        for value in patch.get(key, []):
            changes.append(schemas.ProposedChange(entity=key, action="create", label=label, after=value))
    return changes
