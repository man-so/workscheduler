from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import TypeVar

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app import models, schemas


ModelT = TypeVar("ModelT")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
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


def list_by_team(db: Session, model: type[ModelT], team_id: int) -> Sequence[ModelT]:
    ensure_team(db, team_id)
    return db.scalars(select(model).where(model.team_id == team_id)).all()


@app.get("/api/health", response_model=schemas.HealthResponse)
def health() -> schemas.HealthResponse:
    return schemas.HealthResponse(status="ok", service="workscheduler-backend")


@app.post("/api/teams", response_model=schemas.TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(payload: schemas.TeamCreate, db: Session = Depends(get_db)) -> models.Team:
    team = models.Team(name=payload.name, timezone=payload.timezone)
    db.add(team)
    commit_or_409(db)
    db.refresh(team)
    return team


@app.get("/api/teams", response_model=list[schemas.TeamRead])
def list_teams(db: Session = Depends(get_db)) -> Sequence[models.Team]:
    return db.scalars(select(models.Team).where(models.Team.archived_at.is_(None))).all()


@app.get("/api/teams/{team_id}", response_model=schemas.TeamRead)
def get_team(team_id: int, db: Session = Depends(get_db)) -> models.Team:
    return ensure_team(db, team_id)


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
    assignment = models.Assignment(team_id=team_id, **payload.model_dump())
    db.add(assignment)
    commit_or_409(db)
    db.refresh(assignment)
    return assignment


@app.get("/api/teams/{team_id}/assignments", response_model=list[schemas.AssignmentRead])
def list_assignments(team_id: int, db: Session = Depends(get_db)) -> Sequence[models.Assignment]:
    return list_by_team(db, models.Assignment, team_id)
