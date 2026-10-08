from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def setup_module() -> None:
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db


def teardown_module() -> None:
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_phase_one_core_data_flow() -> None:
    team = client.post("/api/teams", json={"name": "검사실 A"}).json()

    employee_response = client.post(
        f"/api/teams/{team['id']}/employees",
        json={"employee_no": "EMP-001", "display_name": "직원 1"},
    )
    assert employee_response.status_code == 201
    employee = employee_response.json()

    shift_response = client.post(
        f"/api/teams/{team['id']}/shift-types",
        json={
            "code": "DAY",
            "name": "주간",
            "category": "DAY",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
            "break_minutes": 60,
            "paid_minutes": 480,
        },
    )
    assert shift_response.status_code == 201
    shift = shift_response.json()

    rule_response = client.post(
        f"/api/teams/{team['id']}/work-rules",
        json={"name": "기본 규칙", "min_rest_minutes": 660, "max_consecutive_work_days": 5},
    )
    assert rule_response.status_code == 201

    leave_response = client.post(
        f"/api/teams/{team['id']}/leave-requests",
        json={
            "employee_id": employee["id"],
            "start_date": "2026-11-10",
            "end_date": "2026-11-10",
            "status": "APPROVED",
        },
    )
    assert leave_response.status_code == 201

    assignment_response = client.post(
        f"/api/teams/{team['id']}/assignments",
        json={
            "employee_id": employee["id"],
            "local_date": "2026-11-11",
            "status": "WORK",
            "shift_type_id": shift["id"],
        },
    )
    assert assignment_response.status_code == 201

    employees = client.get(f"/api/teams/{team['id']}/employees").json()
    assignments = client.get(f"/api/teams/{team['id']}/assignments").json()
    assert len(employees) == 1
    assert len(assignments) == 1
