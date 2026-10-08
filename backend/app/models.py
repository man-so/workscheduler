from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ShiftCategory(StrEnum):
    DAY = "DAY"
    EARLY_DAY = "EARLY_DAY"
    NIGHT = "NIGHT"
    EARLY_NIGHT = "EARLY_NIGHT"
    OFF = "OFF"
    LEAVE = "LEAVE"
    OTHER = "OTHER"


class LeaveStatus(StrEnum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


class ScheduleVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"


class AssignmentStatus(StrEnum):
    WORK = "WORK"
    OFF = "OFF"
    LEAVE = "LEAVE"
    OTHER = "OTHER"


class AssignmentSource(StrEnum):
    SOLVER = "SOLVER"
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"
    REVISION = "REVISION"


class AvailabilityType(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PREFERRED_OFF = "PREFERRED_OFF"
    PREFERRED_WORK = "PREFERRED_WORK"


class SetupSessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    employees: Mapped[list["Employee"]] = relationship(back_populates="team")


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("team_id", "employee_no", name="uq_employee_team_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    employee_no: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    team: Mapped[Team] = relationship(back_populates="employees")


class ShiftType(Base):
    __tablename__ = "shift_types"
    __table_args__ = (UniqueConstraint("team_id", "code", name="uq_shift_type_team_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    ends_next_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paid_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    required_qualification_code: Mapped[str | None] = mapped_column(String(80))
    color: Mapped[str | None] = mapped_column(String(24))
    is_work: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)


class EmployeeContract(Base):
    __tablename__ = "employee_contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    weekly_work_days: Mapped[int | None] = mapped_column(Integer)
    weekly_pattern_json: Mapped[str | None] = mapped_column(Text)
    target_minutes_per_week: Mapped[int | None] = mapped_column(Integer)
    allowed_shift_type_ids_json: Mapped[str | None] = mapped_column(Text)
    restrictions_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CoverageRequirement(Base):
    __tablename__ = "coverage_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    shift_type_id: Mapped[int] = mapped_column(ForeignKey("shift_types.id"), nullable=False, index=True)
    days_of_week_json: Mapped[str] = mapped_column(Text, nullable=False)
    min_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_count: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    qualification_requirements_json: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WorkRule(Base):
    __tablename__ = "work_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    min_rest_minutes: Mapped[int | None] = mapped_column(Integer)
    max_consecutive_work_days: Mapped[int | None] = mapped_column(Integer)
    max_consecutive_night_shifts: Mapped[int | None] = mapped_column(Integer)
    night_requires_next_day_off: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    week_starts_on: Mapped[str] = mapped_column(String(12), default="MONDAY", nullable=False)
    hard_rules_json: Mapped[str | None] = mapped_column(Text)
    soft_weights_json: Mapped[str | None] = mapped_column(Text)
    fairness_config_json: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=LeaveStatus.REQUESTED, nullable=False)
    leave_type: Mapped[str] = mapped_column(String(60), default="ANNUAL", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class Availability(Base):
    __tablename__ = "availability"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    local_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    availability_type: Mapped[str] = mapped_column(String(32), nullable=False)
    shift_type_id: Mapped[int | None] = mapped_column(ForeignKey("shift_types.id"))
    reason_code: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(24), default="MANUAL", nullable=False)


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("team_id", "year", "month", name="uq_schedule_team_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    active_version_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ScheduleVersion(Base):
    __tablename__ = "schedule_versions"
    __table_args__ = (UniqueConstraint("schedule_id", "version_no", name="uq_schedule_version_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id"), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=ScheduleVersionStatus.DRAFT, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(128))
    config_hash: Mapped[str | None] = mapped_column(String(128))
    solver_status: Mapped[str | None] = mapped_column(String(32))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("version_id", "employee_id", "local_date", name="uq_assignment_employee_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_versions.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    local_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    shift_type_id: Mapped[int | None] = mapped_column(ForeignKey("shift_types.id"))
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(24), default=AssignmentSource.MANUAL, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SetupSession(Base):
    __tablename__ = "setup_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default=SetupSessionStatus.ACTIVE, nullable=False)
    pending_patch_json: Mapped[str | None] = mapped_column(Text)
    messages_json: Mapped[str | None] = mapped_column(Text)
    missing_fields_json: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
