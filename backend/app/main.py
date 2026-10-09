from collections.abc import Sequence
from contextlib import asynccontextmanager
from calendar import monthrange
from datetime import UTC, date, datetime, time
import shutil
from typing import TypeVar

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.agent_runner import AGENT_NAMES
from app.excel_export import build_schedule_workbook
from app.generation import cancel_generation, submit_generation
from app import models, schemas
from app.setup_logic import analyze_setup, dumps, get_team_rows, loads, parse_setup_message, proposed_changes_from_patch


ModelT = TypeVar("ModelT")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    yield


app = FastAPI(title="AI Shift Scheduler API", version="0.1.0", lifespan=lifespan)
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_team(db: Session, team_id: int) -> models.Team:
    team = db.get(models.Team, team_id)
    if team is None or team.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="team not found")
    return team


def commit_or_409(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="data conflict") from exc


def update_model(instance: object, values: dict[str, object]) -> None:
    for key, value in values.items():
        if value is not None:
            setattr(instance, key, value)


def list_by_team(db: Session, model: type[ModelT], team_id: int) -> Sequence[ModelT]:
    ensure_team(db, team_id)
    return db.scalars(select(model).where(model.team_id == team_id)).all()


DEFAULT_LEAVE_TYPES = [
    {"code": "REGULAR", "name": "정기휴무", "color": "#e5e7eb", "is_paid": True, "requires_origin": False, "allows_split": False, "sort_order": 10},
    {"code": "ANNUAL", "name": "연차", "color": "#fed7aa", "is_paid": True, "requires_origin": False, "allows_split": False, "sort_order": 20},
    {"code": "COMPENSATORY", "name": "대체휴무", "color": "#bfdbfe", "is_paid": True, "requires_origin": True, "allows_split": False, "sort_order": 30},
    {"code": "SPECIAL", "name": "특별휴무", "color": "#ddd6fe", "is_paid": True, "requires_origin": False, "allows_split": False, "sort_order": 40},
    {"code": "UNSPECIFIED", "name": "유형 미지정", "color": "#f3f4f6", "is_paid": True, "requires_origin": False, "allows_split": False, "sort_order": 999},
]


def run_lightweight_migrations() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        table_names = set(inspect(connection).get_table_names())
        if "assignments" in table_names:
            columns = {column["name"] for column in inspect(connection).get_columns("assignments")}
            for column_name, column_type in {
                "leave_type_id": "INTEGER",
                "comp_origin_assignment_id": "INTEGER",
                "comp_origin_work_date": "DATE",
                "comp_amount_minutes": "INTEGER",
                "comp_approval_status": "VARCHAR(24)",
                "comp_validation_status": "VARCHAR(24)",
                "comp_validation_message": "TEXT",
            }.items():
                if column_name not in columns:
                    connection.execute(text(f"ALTER TABLE assignments ADD COLUMN {column_name} {column_type}"))
        if "availability" in table_names:
            columns = {column["name"] for column in inspect(connection).get_columns("availability")}
            for column_name, column_type in {
                "leave_type_id": "INTEGER",
                "comp_origin_assignment_id": "INTEGER",
                "comp_origin_work_date": "DATE",
                "comp_amount_minutes": "INTEGER",
                "comp_approval_status": "VARCHAR(24)",
            }.items():
                if column_name not in columns:
                    connection.execute(text(f"ALTER TABLE availability ADD COLUMN {column_name} {column_type}"))


def ensure_default_leave_types(db: Session, team_id: int) -> None:
    existing_codes = set(db.scalars(select(models.LeaveType.code).where(models.LeaveType.team_id == team_id)).all())
    for item in DEFAULT_LEAVE_TYPES:
        if item["code"] not in existing_codes:
            db.add(models.LeaveType(team_id=team_id, **item))


def leave_label(assignment: models.Assignment | None, leave_type: models.LeaveType | None) -> str | None:
    if assignment is None or assignment.status == models.AssignmentStatus.WORK:
        return None
    if leave_type is None:
        return "유형 미지정"
    if leave_type.code == models.LeaveTypeCode.COMPENSATORY:
        if assignment.comp_origin_work_date:
            return f"대휴({assignment.comp_origin_work_date.month}/{assignment.comp_origin_work_date.day})"
        return "대휴(발생일 필요)"
    return leave_type.name


def validate_leave_metadata(db: Session, team_id: int, employee_id: int, payload: object, assignment_id: int | None = None) -> models.LeaveType | None:
    leave_type_id = getattr(payload, "leave_type_id", None)
    status_value = getattr(payload, "status", None)
    if status_value == models.AssignmentStatus.WORK and leave_type_id is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="work assignments cannot include leave_type_id")
    if leave_type_id is None:
        return None

    leave_type = db.get(models.LeaveType, leave_type_id)
    if leave_type is None or leave_type.team_id != team_id or not leave_type.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="leave type does not belong to team")

    if leave_type.requires_origin:
        origin_assignment_id = getattr(payload, "comp_origin_assignment_id", None)
        origin_work_date = getattr(payload, "comp_origin_work_date", None)
        if origin_assignment_id is None and origin_work_date is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="compensatory leave requires origin work date or assignment")
        origin = db.get(models.Assignment, origin_assignment_id) if origin_assignment_id else None
        if origin_assignment_id is not None:
            if origin is None or origin.team_id != team_id or origin.employee_id != employee_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="origin assignment does not belong to employee")
            if origin.status != models.AssignmentStatus.WORK:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="origin assignment must be a work assignment")
            origin_work_date = origin.local_date
        elif origin_work_date is not None:
            origin = db.scalar(
                select(models.Assignment).where(
                    models.Assignment.team_id == team_id,
                    models.Assignment.employee_id == employee_id,
                    models.Assignment.local_date == origin_work_date,
                    models.Assignment.status == models.AssignmentStatus.WORK,
                )
            )
            if origin is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="origin work date has no work assignment")
            origin_assignment_id = origin.id
        if origin_work_date is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="compensatory leave requires origin work date")
        amount = getattr(payload, "comp_amount_minutes", None) or 480
        if origin_assignment_id is not None:
            used_query = select(models.Assignment).where(
                models.Assignment.team_id == team_id,
                models.Assignment.employee_id == employee_id,
                models.Assignment.leave_type_id == leave_type.id,
                models.Assignment.comp_origin_assignment_id == origin_assignment_id,
                models.Assignment.id != (assignment_id or -1),
                models.Assignment.comp_approval_status != "REJECTED",
            )
            used_assignments = db.scalars(used_query).all()
            if used_assignments and not leave_type.allows_split:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="origin work assignment already has compensatory leave")
            if leave_type.allows_split:
                origin_minutes = 480
                if origin and origin.shift_type_id:
                    shift = db.get(models.ShiftType, origin.shift_type_id)
                    origin_minutes = shift.paid_minutes if shift and shift.paid_minutes else 480
                used_minutes = sum(item.comp_amount_minutes or 480 for item in used_assignments)
                if used_minutes + amount > origin_minutes:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="compensatory leave exceeds remaining origin time")
    return leave_type


def find_origin_assignment(db: Session, team_id: int, employee_id: int, origin_work_date: date | None) -> models.Assignment | None:
    if origin_work_date is None:
        return None
    return db.scalar(
        select(models.Assignment).where(
            models.Assignment.team_id == team_id,
            models.Assignment.employee_id == employee_id,
            models.Assignment.local_date == origin_work_date,
            models.Assignment.status == models.AssignmentStatus.WORK,
        )
    )


def refresh_comp_validation(db: Session, assignment: models.Assignment, leave_type: models.LeaveType | None) -> None:
    assignment.comp_validation_status = None
    assignment.comp_validation_message = None
    if not leave_type or not leave_type.requires_origin:
        return
    if assignment.comp_origin_assignment_id is None:
        assignment.comp_validation_status = "WARN"
        assignment.comp_validation_message = "대체휴무 발생 근무 배정이 연결되지 않았습니다."
        return
    origin = db.get(models.Assignment, assignment.comp_origin_assignment_id)
    if origin is None or origin.status != models.AssignmentStatus.WORK or origin.employee_id != assignment.employee_id:
        assignment.comp_validation_status = "WARN"
        assignment.comp_validation_message = "대체휴무 발생 근무가 수정 또는 취소되었습니다."
        return
    assignment.comp_validation_status = "OK"


@app.get("/api/health", response_model=schemas.HealthResponse)
def health() -> schemas.HealthResponse:
    return schemas.HealthResponse(status="ok", service="workscheduler-backend")


@app.get("/api/agents")
def list_agents() -> list[dict[str, object]]:
    return [
        {"id": agent_id, "command": command, "installed": shutil.which(command) is not None}
        for agent_id, command in AGENT_NAMES.items()
    ]


@app.post("/api/teams", response_model=schemas.TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(payload: schemas.TeamCreate, db: Session = Depends(get_db)) -> models.Team:
    team = models.Team(name=payload.name, timezone=payload.timezone)
    db.add(team)
    db.flush()
    ensure_default_leave_types(db, team.id)
    commit_or_409(db)
    db.refresh(team)
    return team


@app.get("/api/teams", response_model=list[schemas.TeamRead])
def list_teams(db: Session = Depends(get_db)) -> Sequence[models.Team]:
    return db.scalars(select(models.Team).where(models.Team.archived_at.is_(None))).all()


@app.get("/api/teams/{team_id}", response_model=schemas.TeamRead)
def get_team(team_id: int, db: Session = Depends(get_db)) -> models.Team:
    team = ensure_team(db, team_id)
    ensure_default_leave_types(db, team_id)
    commit_or_409(db)
    return team


@app.patch("/api/teams/{team_id}", response_model=schemas.TeamRead)
def update_team(team_id: int, payload: schemas.TeamCreate, db: Session = Depends(get_db)) -> models.Team:
    team = ensure_team(db, team_id)
    team.name = payload.name
    team.timezone = payload.timezone
    commit_or_409(db)
    db.refresh(team)
    return team


@app.post("/api/teams/{team_id}/employees", response_model=schemas.EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(team_id: int, payload: schemas.EmployeeCreate, db: Session = Depends(get_db)) -> models.Employee:
    ensure_team(db, team_id)
    employee = models.Employee(team_id=team_id, **payload.model_dump())
    db.add(employee)
    commit_or_409(db)
    db.refresh(employee)
    return employee


@app.get("/api/teams/{team_id}/employees", response_model=list[schemas.EmployeeRead])
def list_employees(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.Employee]:
    return list_by_team(db, models.Employee, team_id)


@app.patch("/api/teams/{team_id}/employees/{employee_id}", response_model=schemas.EmployeeRead)
def update_employee(
    team_id: int,
    employee_id: int,
    payload: schemas.EmployeeUpdate,
    db: Session = Depends(get_db),
) -> models.Employee:
    ensure_team(db, team_id)
    employee = db.get(models.Employee, employee_id)
    if employee is None or employee.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    update_model(employee, payload.model_dump(exclude_unset=True))
    commit_or_409(db)
    db.refresh(employee)
    return employee


@app.post("/api/teams/{team_id}/shift-types", response_model=schemas.ShiftTypeRead, status_code=status.HTTP_201_CREATED)
def create_shift_type(team_id: int, payload: schemas.ShiftTypeCreate, db: Session = Depends(get_db)) -> models.ShiftType:
    ensure_team(db, team_id)
    shift_type = models.ShiftType(team_id=team_id, **payload.model_dump())
    db.add(shift_type)
    commit_or_409(db)
    db.refresh(shift_type)
    return shift_type


@app.get("/api/teams/{team_id}/shift-types", response_model=list[schemas.ShiftTypeRead])
def list_shift_types(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.ShiftType]:
    return list_by_team(db, models.ShiftType, team_id)


@app.patch("/api/teams/{team_id}/shift-types/{shift_type_id}", response_model=schemas.ShiftTypeRead)
def update_shift_type(
    team_id: int,
    shift_type_id: int,
    payload: schemas.ShiftTypeUpdate,
    db: Session = Depends(get_db),
) -> models.ShiftType:
    ensure_team(db, team_id)
    shift_type = db.get(models.ShiftType, shift_type_id)
    if shift_type is None or shift_type.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="shift type not found")
    update_model(shift_type, payload.model_dump(exclude_unset=True))
    if shift_type.is_work and (shift_type.start_time is None or shift_type.end_time is None):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="work shift types require times")
    commit_or_409(db)
    db.refresh(shift_type)
    return shift_type


@app.delete("/api/teams/{team_id}/shift-types/{shift_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift_type(team_id: int, shift_type_id: int, db: Session = Depends(get_db)) -> None:
    ensure_team(db, team_id)
    shift_type = db.get(models.ShiftType, shift_type_id)
    if shift_type is None or shift_type.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="shift type not found")
    shift_type.is_active = False
    commit_or_409(db)


@app.post("/api/teams/{team_id}/work-rules", response_model=schemas.WorkRuleRead, status_code=status.HTTP_201_CREATED)
def create_work_rule(team_id: int, payload: schemas.WorkRuleCreate, db: Session = Depends(get_db)) -> models.WorkRule:
    ensure_team(db, team_id)
    rule = models.WorkRule(team_id=team_id, **payload.model_dump())
    db.add(rule)
    commit_or_409(db)
    db.refresh(rule)
    return rule


@app.get("/api/teams/{team_id}/work-rules", response_model=list[schemas.WorkRuleRead])
def list_work_rules(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.WorkRule]:
    return list_by_team(db, models.WorkRule, team_id)


@app.post("/api/teams/{team_id}/leave-types", response_model=schemas.LeaveTypeRead, status_code=status.HTTP_201_CREATED)
def create_leave_type(team_id: int, payload: schemas.LeaveTypeCreate, db: Session = Depends(get_db)) -> models.LeaveType:
    ensure_team(db, team_id)
    leave_type = models.LeaveType(team_id=team_id, **payload.model_dump())
    db.add(leave_type)
    commit_or_409(db)
    db.refresh(leave_type)
    return leave_type


@app.get("/api/teams/{team_id}/leave-types", response_model=list[schemas.LeaveTypeRead])
def list_leave_types(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.LeaveType]:
    ensure_team(db, team_id)
    ensure_default_leave_types(db, team_id)
    commit_or_409(db)
    return db.scalars(select(models.LeaveType).where(models.LeaveType.team_id == team_id, models.LeaveType.is_active.is_(True)).order_by(models.LeaveType.sort_order, models.LeaveType.name)).all()


@app.post("/api/teams/{team_id}/employee-contracts", response_model=schemas.EmployeeContractRead, status_code=status.HTTP_201_CREATED)
def create_employee_contract(
    team_id: int,
    payload: schemas.EmployeeContractCreate,
    db: Session = Depends(get_db),
) -> models.EmployeeContract:
    ensure_team(db, team_id)
    employee = db.get(models.Employee, payload.employee_id)
    if employee is None or employee.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="employee does not belong to team")
    contract = models.EmployeeContract(team_id=team_id, **payload.model_dump())
    db.add(contract)
    commit_or_409(db)
    db.refresh(contract)
    return contract


@app.get("/api/teams/{team_id}/employee-contracts", response_model=list[schemas.EmployeeContractRead])
def list_employee_contracts(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.EmployeeContract]:
    return list_by_team(db, models.EmployeeContract, team_id)


@app.post("/api/teams/{team_id}/coverage-requirements", response_model=schemas.CoverageRequirementRead, status_code=status.HTTP_201_CREATED)
def create_coverage_requirement(
    team_id: int,
    payload: schemas.CoverageRequirementCreate,
    db: Session = Depends(get_db),
) -> models.CoverageRequirement:
    ensure_team(db, team_id)
    shift_type = db.get(models.ShiftType, payload.shift_type_id)
    if shift_type is None or shift_type.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shift type does not belong to team")
    requirement = models.CoverageRequirement(team_id=team_id, **payload.model_dump())
    db.add(requirement)
    commit_or_409(db)
    db.refresh(requirement)
    return requirement


@app.get("/api/teams/{team_id}/coverage-requirements", response_model=list[schemas.CoverageRequirementRead])
def list_coverage_requirements(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.CoverageRequirement]:
    return list_by_team(db, models.CoverageRequirement, team_id)


@app.post("/api/teams/{team_id}/leave-requests", response_model=schemas.LeaveRequestRead, status_code=status.HTTP_201_CREATED)
def create_leave_request(team_id: int, payload: schemas.LeaveRequestCreate, db: Session = Depends(get_db)) -> models.LeaveRequest:
    ensure_team(db, team_id)
    employee = db.get(models.Employee, payload.employee_id)
    if employee is None or employee.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="employee does not belong to team")
    leave_request = models.LeaveRequest(team_id=team_id, **payload.model_dump())
    db.add(leave_request)
    commit_or_409(db)
    db.refresh(leave_request)
    return leave_request


@app.get("/api/teams/{team_id}/leave-requests", response_model=list[schemas.LeaveRequestRead])
def list_leave_requests(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.LeaveRequest]:
    return list_by_team(db, models.LeaveRequest, team_id)


@app.post("/api/teams/{team_id}/availability", response_model=schemas.AvailabilityRead, status_code=status.HTTP_201_CREATED)
def create_availability(team_id: int, payload: schemas.AvailabilityCreate, db: Session = Depends(get_db)) -> models.Availability:
    ensure_team(db, team_id)
    employee = db.get(models.Employee, payload.employee_id)
    if employee is None or employee.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="employee does not belong to team")
    validate_leave_metadata(db, team_id, payload.employee_id, payload)
    availability = models.Availability(team_id=team_id, **payload.model_dump())
    db.add(availability)
    commit_or_409(db)
    db.refresh(availability)
    return availability


@app.get("/api/teams/{team_id}/availability", response_model=list[schemas.AvailabilityRead])
def list_availability(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.Availability]:
    return list_by_team(db, models.Availability, team_id)


@app.post("/api/teams/{team_id}/assignments", response_model=schemas.AssignmentRead, status_code=status.HTTP_201_CREATED)
def create_assignment(team_id: int, payload: schemas.AssignmentCreate, db: Session = Depends(get_db)) -> models.Assignment:
    ensure_team(db, team_id)
    employee = db.get(models.Employee, payload.employee_id)
    if employee is None or employee.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="employee does not belong to team")
    if payload.shift_type_id is not None:
        shift_type = db.get(models.ShiftType, payload.shift_type_id)
        if shift_type is None or shift_type.team_id != team_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shift type does not belong to team")
    leave_type = validate_leave_metadata(db, team_id, payload.employee_id, payload)
    assignment = models.Assignment(team_id=team_id, **payload.model_dump())
    if leave_type and leave_type.requires_origin and assignment.comp_origin_assignment_id:
        origin = db.get(models.Assignment, assignment.comp_origin_assignment_id)
        if origin is not None:
            assignment.comp_origin_work_date = origin.local_date
    elif leave_type and leave_type.requires_origin:
        origin = find_origin_assignment(db, team_id, payload.employee_id, assignment.comp_origin_work_date)
        if origin is not None:
            assignment.comp_origin_assignment_id = origin.id
    refresh_comp_validation(db, assignment, leave_type)
    db.add(assignment)
    commit_or_409(db)
    db.refresh(assignment)
    return assignment


@app.get("/api/teams/{team_id}/assignments", response_model=list[schemas.AssignmentRead])
def list_assignments(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.Assignment]:
    return list_by_team(db, models.Assignment, team_id)


def read_generation_run(run: models.AgentRun) -> schemas.GenerationRunRead:
    return schemas.GenerationRunRead(
        id=run.id,
        team_id=run.team_id,
        year=run.year,
        month=run.month,
        agent_id=run.agent_id,
        status=run.status,
        timeout_seconds=run.timeout_seconds,
        constraints=loads(run.constraints_json, None),
        result=loads(run.result_json, None),
        log_text=run.log_text,
        error_message=run.error_message,
        cancel_requested=run.cancel_requested,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


def get_active_schedule_version(
    db: Session,
    team_id: int,
    year: int,
    month: int,
) -> tuple[models.Schedule, models.ScheduleVersion]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="month must be between 1 and 12")
    schedule = db.scalar(select(models.Schedule).where(models.Schedule.team_id == team_id, models.Schedule.year == year, models.Schedule.month == month))
    if schedule is None or schedule.active_version_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="schedule not found")
    version = db.get(models.ScheduleVersion, schedule.active_version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="schedule version not found")
    return schedule, version


def get_schedule_version_or_404(
    db: Session,
    team_id: int,
    year: int,
    month: int,
    version_id: int,
) -> tuple[models.Schedule, models.ScheduleVersion]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="month must be between 1 and 12")
    schedule = db.scalar(select(models.Schedule).where(models.Schedule.team_id == team_id, models.Schedule.year == year, models.Schedule.month == month))
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="schedule not found")
    version = db.get(models.ScheduleVersion, version_id)
    if version is None or version.schedule_id != schedule.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="schedule version not found")
    return schedule, version


def read_schedule_version(db: Session, schedule: models.Schedule, version: models.ScheduleVersion) -> schemas.ScheduleVersionRead:
    modified_at = db.scalar(select(func.max(models.Assignment.updated_at)).where(models.Assignment.version_id == version.id))
    return schemas.ScheduleVersionRead(
        id=version.id,
        schedule_id=version.schedule_id,
        version_no=version.version_no,
        status=version.status,
        solver_status=version.solver_status,
        generated_at=version.generated_at,
        confirmed_at=version.confirmed_at,
        modified_at=modified_at,
        notes=version.notes,
        is_active=schedule.active_version_id == version.id,
    )


def build_monthly_schedule_read(
    db: Session,
    schedule: models.Schedule,
    version: models.ScheduleVersion,
) -> schemas.MonthlyScheduleRead:
    employees = db.scalars(select(models.Employee).where(models.Employee.team_id == schedule.team_id, models.Employee.is_active.is_(True))).all()
    shift_types = db.scalars(select(models.ShiftType).where(models.ShiftType.team_id == schedule.team_id)).all()
    shift_by_id = {shift.id: shift for shift in shift_types}
    leave_types = db.scalars(select(models.LeaveType).where(models.LeaveType.team_id == schedule.team_id)).all()
    leave_by_id = {leave_type.id: leave_type for leave_type in leave_types}
    assignments = db.scalars(select(models.Assignment).where(models.Assignment.version_id == version.id)).all()
    assignment_by_key = {(item.employee_id, item.local_date): item for item in assignments}
    days: list[schemas.CalendarDay] = []
    for day in range(1, monthrange(schedule.year, schedule.month)[1] + 1):
        local_date = date(schedule.year, schedule.month, day)
        day_items: list[schemas.CalendarAssignment] = []
        for employee in employees:
            item = assignment_by_key.get((employee.id, local_date))
            shift = shift_by_id.get(item.shift_type_id) if item and item.shift_type_id else None
            leave_type = leave_by_id.get(item.leave_type_id) if item and item.leave_type_id else None
            day_items.append(schemas.CalendarAssignment(
                assignment_id=item.id if item else None,
                employee_id=employee.id,
                employee_name=employee.display_name,
                status=item.status if item else models.AssignmentStatus.OFF,
                shift_type_id=shift.id if shift else None,
                shift_type_name=shift.name if shift else None,
                category=shift.category if shift else models.AssignmentStatus.OFF,
                start_time=shift.start_time if shift else None,
                end_time=shift.end_time if shift else None,
                ends_next_day=shift.ends_next_day if shift else False,
                color=shift.color if shift else None,
                leave_type_id=leave_type.id if leave_type else None,
                leave_type_code=leave_type.code if leave_type else None,
                leave_type_name=leave_type.name if leave_type else None,
                leave_label=leave_label(item, leave_type),
                comp_origin_assignment_id=item.comp_origin_assignment_id if item else None,
                comp_origin_work_date=item.comp_origin_work_date if item else None,
                comp_amount_minutes=item.comp_amount_minutes if item else None,
                comp_approval_status=item.comp_approval_status if item else None,
                comp_validation_status=item.comp_validation_status if item else None,
                comp_validation_message=item.comp_validation_message if item else None,
            ))
        groups: dict[str, list[schemas.CalendarAssignment]] = {}
        for item in day_items:
            group_key = item.category or item.status
            if item.status != models.AssignmentStatus.WORK:
                group_key = item.leave_type_code or group_key
            groups.setdefault(group_key, []).append(item)
        days.append(schemas.CalendarDay(local_date=local_date, groups=groups, assignments=day_items))
    return schemas.MonthlyScheduleRead(
        schedule_id=schedule.id,
        version_id=version.id,
        version_no=version.version_no,
        year=schedule.year,
        month=schedule.month,
        status=version.status,
        solver_status=version.solver_status,
        days=days,
    )


def validate_schedule_version(
    db: Session,
    schedule: models.Schedule,
    version: models.ScheduleVersion,
) -> schemas.ScheduleValidationRead:
    issues: list[schemas.ScheduleValidationIssue] = []
    employees = db.scalars(select(models.Employee).where(models.Employee.team_id == schedule.team_id, models.Employee.is_active.is_(True))).all()
    shift_types = db.scalars(select(models.ShiftType).where(models.ShiftType.team_id == schedule.team_id)).all()
    shift_by_id = {shift.id: shift for shift in shift_types}
    leave_types = db.scalars(select(models.LeaveType).where(models.LeaveType.team_id == schedule.team_id)).all()
    leave_by_id = {leave_type.id: leave_type for leave_type in leave_types}
    assignments = db.scalars(select(models.Assignment).where(models.Assignment.version_id == version.id)).all()
    assignment_by_key = {(item.employee_id, item.local_date): item for item in assignments}
    dates = [date(schedule.year, schedule.month, day) for day in range(1, monthrange(schedule.year, schedule.month)[1] + 1)]

    for local_date in dates:
        for employee in employees:
            item = assignment_by_key.get((employee.id, local_date))
            if item is None:
                issues.append(schemas.ScheduleValidationIssue(severity="ERROR", code="MISSING_ASSIGNMENT", message="직원의 일자별 배정이 없습니다.", local_date=local_date, employee_id=employee.id))
                continue
            if item.status == models.AssignmentStatus.WORK and item.shift_type_id is None:
                issues.append(schemas.ScheduleValidationIssue(severity="ERROR", code="WORK_WITHOUT_SHIFT", message="근무 상태에는 근무유형이 필요합니다.", local_date=local_date, employee_id=employee.id))
            if item.status != models.AssignmentStatus.WORK and item.shift_type_id is not None:
                issues.append(schemas.ScheduleValidationIssue(severity="ERROR", code="OFF_WITH_SHIFT", message="비근무 상태에는 근무유형을 지정할 수 없습니다.", local_date=local_date, employee_id=employee.id, shift_type_id=item.shift_type_id))
            if item.shift_type_id is not None and item.shift_type_id not in shift_by_id:
                issues.append(schemas.ScheduleValidationIssue(severity="ERROR", code="UNKNOWN_SHIFT", message="팀에 속하지 않는 근무유형입니다.", local_date=local_date, employee_id=employee.id, shift_type_id=item.shift_type_id))
            if item.leave_type_id is not None and item.leave_type_id not in leave_by_id:
                issues.append(schemas.ScheduleValidationIssue(severity="ERROR", code="UNKNOWN_LEAVE_TYPE", message="팀에 속하지 않는 휴무유형입니다.", local_date=local_date, employee_id=employee.id))
            leave_type = leave_by_id.get(item.leave_type_id) if item.leave_type_id else None
            if leave_type and leave_type.requires_origin:
                refresh_comp_validation(db, item, leave_type)
                if item.comp_validation_status == "WARN":
                    issues.append(schemas.ScheduleValidationIssue(severity="WARN", code="COMP_ORIGIN_RECHECK", message=item.comp_validation_message or "대체휴무 발생 근무를 재확인해야 합니다.", local_date=local_date, employee_id=employee.id))

    weekday_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
    requirements = db.scalars(select(models.CoverageRequirement).where(models.CoverageRequirement.team_id == schedule.team_id, models.CoverageRequirement.is_active.is_(True))).all()
    for requirement in requirements:
        days_of_week = loads(requirement.days_of_week_json, [])
        day_numbers = {weekday_map[item.upper()] for item in days_of_week if isinstance(item, str) and item.upper() in weekday_map}
        for local_date in dates:
            if local_date.weekday() not in day_numbers:
                continue
            count = sum(1 for item in assignments if item.local_date == local_date and item.status == models.AssignmentStatus.WORK and item.shift_type_id == requirement.shift_type_id)
            if count < requirement.min_count:
                issues.append(schemas.ScheduleValidationIssue(severity="ERROR", code="COVERAGE_BELOW_MIN", message=f"필요 인원 최소값 {requirement.min_count}명보다 적습니다.", local_date=local_date, shift_type_id=requirement.shift_type_id))
            if requirement.max_count is not None and count > requirement.max_count:
                issues.append(schemas.ScheduleValidationIssue(severity="ERROR", code="COVERAGE_ABOVE_MAX", message=f"필요 인원 최대값 {requirement.max_count}명을 초과했습니다.", local_date=local_date, shift_type_id=requirement.shift_type_id))
            if count != requirement.target_count:
                issues.append(schemas.ScheduleValidationIssue(severity="WARN", code="COVERAGE_TARGET_MISMATCH", message=f"목표 인원 {requirement.target_count}명과 다릅니다.", local_date=local_date, shift_type_id=requirement.shift_type_id))
    error_count = sum(1 for issue in issues if issue.severity == "ERROR")
    return schemas.ScheduleValidationRead(ok=error_count == 0, issue_count=len(issues), issues=issues)


def clone_schedule_version(db: Session, schedule: models.Schedule, source_version: models.ScheduleVersion) -> models.ScheduleVersion:
    latest = db.scalar(select(models.ScheduleVersion).where(models.ScheduleVersion.schedule_id == schedule.id).order_by(models.ScheduleVersion.version_no.desc()))
    version_no = (latest.version_no + 1) if latest else 1
    version = models.ScheduleVersion(
        schedule_id=schedule.id,
        version_no=version_no,
        status=models.ScheduleVersionStatus.DRAFT,
        input_hash=source_version.input_hash,
        config_hash=source_version.config_hash,
        solver_status=source_version.solver_status,
        generated_at=datetime.now(UTC),
        notes=f"Draft cloned from version {source_version.version_no}.",
    )
    db.add(version)
    db.flush()
    assignments = db.scalars(select(models.Assignment).where(models.Assignment.version_id == source_version.id)).all()
    for item in assignments:
        db.add(models.Assignment(
            team_id=item.team_id,
            version_id=version.id,
            employee_id=item.employee_id,
            local_date=item.local_date,
            status=item.status,
            shift_type_id=item.shift_type_id,
            leave_type_id=item.leave_type_id,
            comp_origin_assignment_id=item.comp_origin_assignment_id,
            comp_origin_work_date=item.comp_origin_work_date,
            comp_amount_minutes=item.comp_amount_minutes,
            comp_approval_status=item.comp_approval_status,
            comp_validation_status=item.comp_validation_status,
            comp_validation_message=item.comp_validation_message,
            locked=False,
            source=models.AssignmentSource.REVISION,
            change_reason=f"cloned from version {source_version.version_no}",
        ))
    schedule.active_version_id = version.id
    return version


@app.post("/api/teams/{team_id}/schedules/generate", response_model=schemas.GenerationRunRead, status_code=status.HTTP_202_ACCEPTED)
def start_schedule_generation(
    team_id: int,
    payload: schemas.GenerationCreate,
    db: Session = Depends(get_db),
) -> schemas.GenerationRunRead:
    ensure_team(db, team_id)
    run = models.AgentRun(
        team_id=team_id,
        year=payload.year,
        month=payload.month,
        agent_id=payload.agent_id,
        timeout_seconds=payload.timeout_seconds,
        status=models.AgentRunStatus.QUEUED,
    )
    db.add(run)
    commit_or_409(db)
    db.refresh(run)
    submit_generation(run.id, team_id, payload.year, payload.month, payload.agent_id, payload.timeout_seconds)
    return read_generation_run(run)


@app.get("/api/teams/{team_id}/generation-runs/{run_id}", response_model=schemas.GenerationRunRead)
def get_generation_run(team_id: int, run_id: int, db: Session = Depends(get_db)) -> schemas.GenerationRunRead:
    ensure_team(db, team_id)
    run = db.get(models.AgentRun, run_id)
    if run is None or run.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="generation run not found")
    return read_generation_run(run)


@app.post("/api/teams/{team_id}/generation-runs/{run_id}/cancel", response_model=schemas.GenerationRunRead)
def stop_generation(team_id: int, run_id: int, db: Session = Depends(get_db)) -> schemas.GenerationRunRead:
    ensure_team(db, team_id)
    run = db.get(models.AgentRun, run_id)
    if run is None or run.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="generation run not found")
    run.cancel_requested = True
    if run.status == models.AgentRunStatus.QUEUED:
        run.status = models.AgentRunStatus.CANCELED
    commit_or_409(db)
    cancel_generation(run_id)
    db.refresh(run)
    return read_generation_run(run)


@app.get("/api/teams/{team_id}/schedules/{year}/{month}", response_model=schemas.MonthlyScheduleRead)
def get_monthly_schedule(team_id: int, year: int, month: int, db: Session = Depends(get_db)) -> schemas.MonthlyScheduleRead:
    ensure_team(db, team_id)
    schedule, version = get_active_schedule_version(db, team_id, year, month)
    return build_monthly_schedule_read(db, schedule, version)


@app.get("/api/teams/{team_id}/schedules/{year}/{month}/versions", response_model=list[schemas.ScheduleVersionRead])
def list_schedule_versions(team_id: int, year: int, month: int, db: Session = Depends(get_db)) -> list[schemas.ScheduleVersionRead]:
    ensure_team(db, team_id)
    if month < 1 or month > 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="month must be between 1 and 12")
    schedule = db.scalar(select(models.Schedule).where(models.Schedule.team_id == team_id, models.Schedule.year == year, models.Schedule.month == month))
    if schedule is None:
        return []
    versions = db.scalars(select(models.ScheduleVersion).where(models.ScheduleVersion.schedule_id == schedule.id).order_by(models.ScheduleVersion.version_no.desc())).all()
    return [read_schedule_version(db, schedule, version) for version in versions]


@app.get("/api/teams/{team_id}/schedules/{year}/{month}/versions/{version_id}", response_model=schemas.MonthlyScheduleRead)
def get_monthly_schedule_version(team_id: int, year: int, month: int, version_id: int, db: Session = Depends(get_db)) -> schemas.MonthlyScheduleRead:
    ensure_team(db, team_id)
    schedule, version = get_schedule_version_or_404(db, team_id, year, month, version_id)
    return build_monthly_schedule_read(db, schedule, version)


@app.post("/api/teams/{team_id}/schedules/{year}/{month}/versions/{version_id}/clone", response_model=schemas.ScheduleVersionRead, status_code=status.HTTP_201_CREATED)
def clone_monthly_schedule_version(team_id: int, year: int, month: int, version_id: int, db: Session = Depends(get_db)) -> schemas.ScheduleVersionRead:
    ensure_team(db, team_id)
    schedule, version = get_schedule_version_or_404(db, team_id, year, month, version_id)
    cloned = clone_schedule_version(db, schedule, version)
    commit_or_409(db)
    db.refresh(cloned)
    return read_schedule_version(db, schedule, cloned)


@app.post("/api/teams/{team_id}/schedules/{year}/{month}/confirm", response_model=schemas.ScheduleVersionRead)
def confirm_monthly_schedule(
    team_id: int,
    year: int,
    month: int,
    payload: schemas.ConfirmScheduleRequest,
    db: Session = Depends(get_db),
) -> schemas.ScheduleVersionRead:
    ensure_team(db, team_id)
    schedule, version = get_active_schedule_version(db, team_id, year, month)
    if version.status != models.ScheduleVersionStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only draft schedules can be confirmed")
    validation = validate_schedule_version(db, schedule, version)
    hard_issues = [issue for issue in validation.issues if issue.severity == "ERROR"]
    soft_issues = [issue for issue in validation.issues if issue.severity == "WARN"]
    if hard_issues:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=[issue.model_dump(mode="json") for issue in hard_issues])
    if soft_issues and not payload.approve_soft_issues:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=[issue.model_dump(mode="json") for issue in soft_issues])

    versions = db.scalars(select(models.ScheduleVersion).where(models.ScheduleVersion.schedule_id == schedule.id, models.ScheduleVersion.id != version.id)).all()
    for old_version in versions:
        old_version.status = models.ScheduleVersionStatus.ARCHIVED
    version.status = models.ScheduleVersionStatus.CONFIRMED
    version.confirmed_at = datetime.now(UTC)
    commit_or_409(db)
    db.refresh(version)
    return read_schedule_version(db, schedule, version)


@app.patch("/api/teams/{team_id}/schedules/{year}/{month}/assignments", response_model=schemas.MonthlyScheduleRead)
def update_schedule_assignment(
    team_id: int,
    year: int,
    month: int,
    payload: schemas.ScheduleAssignmentUpdate,
    db: Session = Depends(get_db),
) -> schemas.MonthlyScheduleRead:
    ensure_team(db, team_id)
    schedule, version = get_active_schedule_version(db, team_id, year, month)
    if version.status != models.ScheduleVersionStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="confirmed schedules cannot be changed")
    if payload.local_date.year != year or payload.local_date.month != month:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="assignment date is outside the schedule month")
    employee = db.get(models.Employee, payload.employee_id)
    if employee is None or employee.team_id != team_id or not employee.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="employee does not belong to team")
    if payload.shift_type_id is not None:
        shift_type = db.get(models.ShiftType, payload.shift_type_id)
        if shift_type is None or shift_type.team_id != team_id or not shift_type.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shift type does not belong to team")
    leave_type = validate_leave_metadata(db, team_id, payload.employee_id, payload)

    assignment = db.scalar(
        select(models.Assignment).where(
            models.Assignment.version_id == version.id,
            models.Assignment.employee_id == payload.employee_id,
            models.Assignment.local_date == payload.local_date,
        )
    )
    if assignment is None:
        assignment = models.Assignment(team_id=team_id, version_id=version.id, employee_id=payload.employee_id, local_date=payload.local_date, status=payload.status)
        db.add(assignment)
    assignment.status = payload.status
    assignment.shift_type_id = payload.shift_type_id
    assignment.leave_type_id = payload.leave_type_id
    assignment.comp_origin_assignment_id = payload.comp_origin_assignment_id
    assignment.comp_origin_work_date = payload.comp_origin_work_date
    assignment.comp_amount_minutes = payload.comp_amount_minutes
    assignment.comp_approval_status = payload.comp_approval_status
    if leave_type and leave_type.requires_origin and assignment.comp_origin_assignment_id:
        origin = db.get(models.Assignment, assignment.comp_origin_assignment_id)
        if origin is not None:
            assignment.comp_origin_work_date = origin.local_date
    elif leave_type and leave_type.requires_origin:
        origin = find_origin_assignment(db, team_id, payload.employee_id, assignment.comp_origin_work_date)
        if origin is not None:
            assignment.comp_origin_assignment_id = origin.id
    if payload.status == models.AssignmentStatus.WORK:
        assignment.leave_type_id = None
        assignment.comp_origin_assignment_id = None
        assignment.comp_origin_work_date = None
        assignment.comp_amount_minutes = None
        assignment.comp_approval_status = None
        assignment.comp_validation_status = None
        assignment.comp_validation_message = None
    else:
        refresh_comp_validation(db, assignment, leave_type)
    assignment.locked = payload.locked
    assignment.source = models.AssignmentSource.MANUAL
    assignment.change_reason = payload.change_reason
    commit_or_409(db)
    db.refresh(version)
    return build_monthly_schedule_read(db, schedule, version)


@app.get("/api/teams/{team_id}/schedules/{year}/{month}/validation", response_model=schemas.ScheduleValidationRead)
def validate_monthly_schedule(team_id: int, year: int, month: int, db: Session = Depends(get_db)) -> schemas.ScheduleValidationRead:
    ensure_team(db, team_id)
    schedule, version = get_active_schedule_version(db, team_id, year, month)
    return validate_schedule_version(db, schedule, version)


@app.get("/api/teams/{team_id}/schedules/{year}/{month}/export.xlsx")
def export_monthly_schedule(team_id: int, year: int, month: int, db: Session = Depends(get_db)) -> StreamingResponse:
    team = ensure_team(db, team_id)
    schedule, version = get_active_schedule_version(db, team_id, year, month)
    calendar = build_monthly_schedule_read(db, schedule, version)
    validation = validate_schedule_version(db, schedule, version)
    output = build_schedule_workbook(team, version, calendar, validation)
    filename = f"workscheduler_{team_id}_{year}_{month:02d}_v{version.version_no}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/teams/{team_id}/setup-summary", response_model=schemas.SetupSummary)
def get_setup_summary(team_id: int, db: Session = Depends(get_db)) -> schemas.SetupSummary:
    team = ensure_team(db, team_id)
    ensure_default_leave_types(db, team_id)
    commit_or_409(db)
    return analyze_setup(db, team)


@app.post("/api/teams/{team_id}/setup-sessions", response_model=schemas.SetupSessionRead, status_code=status.HTTP_201_CREATED)
def create_setup_session(team_id: int, db: Session = Depends(get_db)) -> schemas.SetupSessionRead:
    team = ensure_team(db, team_id)
    ensure_default_leave_types(db, team_id)
    commit_or_409(db)
    summary = analyze_setup(db, team)
    session = models.SetupSession(
        team_id=team_id,
        messages_json=dumps([]),
        missing_fields_json=dumps(summary.missing_fields),
        warnings_json=dumps(summary.conflicts),
    )
    db.add(session)
    commit_or_409(db)
    db.refresh(session)
    return read_setup_session(session, summary.questions, team)


@app.get("/api/teams/{team_id}/setup-sessions/active", response_model=schemas.SetupSessionRead)
def get_active_setup_session(team_id: int, db: Session = Depends(get_db)) -> schemas.SetupSessionRead:
    team = ensure_team(db, team_id)
    ensure_default_leave_types(db, team_id)
    commit_or_409(db)
    session = db.scalars(
        select(models.SetupSession)
        .where(models.SetupSession.team_id == team_id, models.SetupSession.status == models.SetupSessionStatus.ACTIVE)
        .order_by(models.SetupSession.updated_at.desc())
    ).first()
    summary = analyze_setup(db, team)
    if session is None:
        session = models.SetupSession(
            team_id=team_id,
            messages_json=dumps([]),
            missing_fields_json=dumps(summary.missing_fields),
            warnings_json=dumps(summary.conflicts),
        )
        db.add(session)
        commit_or_409(db)
        db.refresh(session)
    return read_setup_session(session, summary.questions, team)


@app.post("/api/teams/{team_id}/setup-sessions/{session_id}/messages", response_model=schemas.SetupChatResponse)
def answer_setup_chat(
    team_id: int,
    session_id: int,
    payload: schemas.SetupChatRequest,
    db: Session = Depends(get_db),
) -> schemas.SetupChatResponse:
    team = ensure_team(db, team_id)
    ensure_default_leave_types(db, team_id)
    commit_or_409(db)
    session = get_session_or_404(db, team_id, session_id)
    rows = get_team_rows(db, team_id)
    patch = parse_setup_message(payload.message, team, rows)
    warnings = validate_patch(patch)
    messages = loads(session.messages_json, [])
    messages.append({"role": "user", "content": payload.message})
    if empty_patch(patch):
        messages.append({"role": "assistant", "content": "입력에서 적용 가능한 설정을 찾지 못했습니다. 왼쪽 폼으로 입력하거나 더 구체적으로 알려주세요."})
    else:
        messages.append({"role": "assistant", "content": "변경 미리보기를 만들었습니다. 내용을 확인한 뒤 승인해 주세요."})
    session.messages_json = dumps(messages)
    session.pending_patch_json = dumps(patch)
    session.warnings_json = dumps(warnings)
    summary = analyze_setup(db, team)
    session.missing_fields_json = dumps(summary.missing_fields)
    commit_or_409(db)
    db.refresh(session)
    response = read_setup_session(session, summary.questions, team)
    return schemas.SetupChatResponse(**response.model_dump(), needs_approval=not empty_patch(patch))


@app.post("/api/teams/{team_id}/setup-sessions/{session_id}/approve", response_model=schemas.SetupApproveResponse)
def approve_setup_patch(team_id: int, session_id: int, db: Session = Depends(get_db)) -> schemas.SetupApproveResponse:
    team = ensure_team(db, team_id)
    ensure_default_leave_types(db, team_id)
    commit_or_409(db)
    session = get_session_or_404(db, team_id, session_id)
    patch = loads(session.pending_patch_json, {})
    if empty_patch(patch):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no pending patch")
    warnings = validate_patch(patch)
    if warnings:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=warnings)
    changes = proposed_changes_from_patch(patch, team)
    apply_patch_to_db(db, team, patch)
    session.pending_patch_json = None
    session.status = models.SetupSessionStatus.ACTIVE
    commit_or_409(db)
    summary = analyze_setup(db, team)
    return schemas.SetupApproveResponse(applied=changes, summary=summary)


def get_session_or_404(db: Session, team_id: int, session_id: int) -> models.SetupSession:
    session = db.get(models.SetupSession, session_id)
    if session is None or session.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="setup session not found")
    return session


def read_setup_session(
    session: models.SetupSession,
    questions: list[schemas.SetupQuestion],
    team: models.Team,
) -> schemas.SetupSessionRead:
    patch = loads(session.pending_patch_json, None)
    return schemas.SetupSessionRead(
        id=session.id,
        team_id=session.team_id,
        status=session.status,
        pending_patch=patch,
        messages=[schemas.ChatMessage(**message) for message in loads(session.messages_json, [])],
        missing_fields=loads(session.missing_fields_json, []),
        warnings=loads(session.warnings_json, []),
        proposed_changes=proposed_changes_from_patch(patch or {}, team),
        questions=questions,
    )


def empty_patch(patch: dict[str, object]) -> bool:
    return not any(value for value in patch.values())


def validate_patch(patch: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    for item in patch.get("shift_types", []):
        if not isinstance(item, dict):
            warnings.append("근무유형 patch 형식이 올바르지 않습니다.")
            continue
        if item.get("is_work", True) and (not item.get("start_time") or not item.get("end_time")):
            warnings.append("근무유형 시작·종료 시간이 필요합니다.")
    for item in patch.get("coverage_requirements", []):
        if not isinstance(item, dict):
            warnings.append("필요 인원 patch 형식이 올바르지 않습니다.")
            continue
        if item.get("max_count") is not None and item["max_count"] < item["target_count"]:
            warnings.append("필요 인원의 최대값이 목표값보다 작습니다.")
    for item in patch.get("availability", []):
        if isinstance(item, dict) and item.get("requires_origin"):
            warnings.append("대체휴무는 발생 근무일을 함께 입력해야 합니다.")
    return warnings


def apply_patch_to_db(db: Session, team: models.Team, patch: dict[str, object]) -> None:
    team_patch = patch.get("team") or {}
    if isinstance(team_patch, dict) and team_patch.get("name"):
        team.name = str(team_patch["name"])

    for item in patch.get("employees", []):
        if isinstance(item, dict):
            db.add(models.Employee(team_id=team.id, **item))
    db.flush()

    for item in patch.get("shift_types", []):
        if isinstance(item, dict):
            clean = item.copy()
            for key in ["start_time", "end_time"]:
                if isinstance(clean.get(key), str):
                    clean[key] = time.fromisoformat(clean[key])
            db.add(models.ShiftType(team_id=team.id, **clean))
    db.flush()

    for item in patch.get("work_rules", []):
        if isinstance(item, dict):
            clean = {key: value for key, value in item.items() if value is not None}
            db.add(models.WorkRule(team_id=team.id, **clean))

    for item in patch.get("coverage_requirements", []):
        if isinstance(item, dict):
            db.add(models.CoverageRequirement(team_id=team.id, **item))

    for item in patch.get("employee_contracts", []):
        if isinstance(item, dict):
            db.add(models.EmployeeContract(team_id=team.id, **item))

    for item in patch.get("availability", []):
        if isinstance(item, dict):
            clean = {key: value for key, value in item.items() if key != "requires_origin"}
            for key in ["local_date", "comp_origin_work_date"]:
                if isinstance(clean.get(key), str):
                    clean[key] = date.fromisoformat(clean[key])
            db.add(models.Availability(team_id=team.id, **clean))
