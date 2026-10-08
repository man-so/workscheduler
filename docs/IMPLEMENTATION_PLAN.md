# AI Shift Scheduler Implementation Plan

작성일: 2026-10-08
단계: Phase 0
근거 문서: AI Shift Scheduler Codex 기술명세서 v2 개선본

## 1. Phase 0 목적과 범위

이 문서는 기술명세서 v2를 기준으로 실제 운영 가능한 팀별 AI 근무표 자동 생성 웹앱의 구현 계획을 정리한다. Phase 0에서는 코드를 구현하지 않고, 요구사항 분석, 미확정 정책 분리, 데이터 모델, API 구조, OR-Tools CP-SAT 제약 설계, 개발 순서, 테스트 계획을 확정한다.

Phase 1 시작 전에는 이 문서의 미확정 항목에 대한 사용자 승인이 필요하다.

## 2. 구현 가능한 요구사항

### 2.0 요구사항 추적표

| 영역 | 명세서 요구 | Phase 0 해석 | 구현 단계 |
| --- | --- | --- | --- |
| 제품 범위 | 팀별 독립 근무표 생성, 지원근무 제외 | team_id 단위 독립 데이터와 solver 실행으로 분리하고 지원근무 모델은 두지 않음 | Phase 1~3 |
| 오프라인 동작 | AI 연결 없이 생성, 수정, 검증, 출력 가능 | LLM Provider Adapter는 선택 기능이며 기본 폼과 solver는 AI 없이 동작 | Phase 1~5 |
| 달력 UI | 날짜 칸마다 전 직원 상태를 숨김 없이 표시 | 월간 달력을 기본 화면으로 두고 직원별 보조 표는 선택 기능으로 제한 | Phase 1, Phase 4 |
| 데이터 무결성 | 계약, 자격, 근무유형 유효기간과 버전 스냅샷 보존 | 유효기간 필드와 ScheduleVersion, input_hash, config_hash를 모델에 포함 | Phase 1, Phase 5 |
| Hard 제약 | 날짜별 한 상태, 최소 인원, 자격, 연차, 휴식, 연속근무, 월 경계 | CP-SAT constraint와 서버 재검증 함수로 중복 구현 | Phase 3 |
| Soft 제약 | 희망 휴무와 야간, 조기, 주말, 공휴일 부담 균형 | RuleSet soft_weights_json과 FairnessMetric으로 저장 및 최적화 | Phase 3 |
| 불가능 해 처리 | INFEASIBLE 시 임의 근무표 생성 금지 | preflight 실패와 solver infeasible을 구분하고 완화 후보만 제시 | Phase 3 |
| AI 역할 | 자연어를 구조화 patch로 변환, DB 직접 쓰기 금지 | interpretSetup, interpretScheduleEdit만 제공하고 승인 전 적용 금지 | Phase 2 |
| 보안 운영 | 환경변수 API Key, 인증, CSRF, 로그 마스킹, 백업 정책 | MVP 인증과 백업 암호화 정책은 승인 필요 항목으로 분리 | Phase 1, Phase 5 |
| Excel | 날짜별 전체 인원과 직원별 요약, 버전 및 검증 결과 포함 | Excel export API에 schedule, summary, validation sheet 포함 | Phase 5 |
| 테스트 | 10/8 전체 직원 1회, 월 경계, 동명이인, 재현성, 장애 | Unit, API, Solver, UI, E2E, 운영 검증으로 분리 | Phase 1~6 |

### 2.1 제품 범위

- 팀별 독립 근무표 생성
- 타 팀 지원근무 제외
- 주간, 야간, 조기출근, 휴무, 연차, 사용자 정의 근무 지원
- AI 연결 없이도 설정 폼, 자동 배정, 검증, 수정, 저장, 확정, Excel 다운로드 가능
- LLM은 자연어 입력 해석과 질문 생성에만 사용
- 근무 배정과 재검증은 OR-Tools 및 결정적 서버 코드로 수행
- API Key는 서버 환경변수로 관리
- 직원별 근무 조건과 배정 결과는 데이터베이스에 저장
- 사용자 승인 없이 확정된 근무표를 직접 변경하지 않고 새 개정 버전을 생성

### 2.2 핵심 운영 흐름

1. 팀 생성
2. 직원, 근무유형, 자격, 계약, 필요 인원, 규칙 입력
3. 필수 필드 누락 및 충돌 검증
4. 관리자 승인 후 설정 저장
5. 대상 월 선택
6. 전월 말 및 익월 초 월 경계 배정 참조
7. 연차, 휴무 희망, 고정 배정, 잠금 입력
8. 사전 가능성 검사
9. CP-SAT 자동 생성
10. 월간 달력 검토
11. 날짜별 상세 수정 및 잠금
12. Hard 제약 재검증
13. 확정
14. Excel 다운로드

### 2.3 UI 요구사항

- 월간 달력은 일요일부터 토요일까지 7열 구조로 표시
- 각 날짜 칸에는 해당 팀의 모든 직원을 정확히 한 번 표시
- 근무자는 이름과 근무유형을 표시
- 휴무자는 이름과 휴무 상태를 표시
- 조기출근, 주간, 야간, 야간 조기출근, 휴무, 연차를 구분
- 직원 수가 많으면 날짜 칸 내부 스크롤 허용
- 좁은 화면은 가로 및 세로 스크롤 허용
- 날짜 클릭 시 상세 배정 패널에서 수정 가능
- 색상만으로 상태를 구분하지 않고 텍스트, 범례, 접근성 레이블 제공
- 동명이인은 사번 또는 내부 ID로 구분
- 야간 근무는 시작일 기준 날짜 칸에 표시하고 익일 종료 시간은 상세 패널에 표시
- 날짜별 필요 인원, 배정 인원, 위반 상태 표시
- 직원별 보조 표는 제공 가능하지만 기본 월간 달력을 대체할 수 없음
- 지원근무 기능은 구현하지 않음

### 2.4 배정 및 검증

- 직원 x 날짜 x 상태 또는 근무유형을 CP-SAT 이진 변수로 모델링
- 휴무와 연차도 상태로 모델링
- 생성 전 preflight로 명백한 불가능 조건을 먼저 탐지
- INFEASIBLE이면 임의 근무표 생성 금지
- OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN 상태 기록
- FEASIBLE은 서버 Hard 재검증 후에만 제시
- UNKNOWN은 결과 미확정으로 처리
- solver 시간 제한, seed, worker 수, OR-Tools 버전, 입력 해시, 설정 해시 저장

### 2.5 저장, 버전, 감사

- ScheduleVersion 상태: draft, review, confirmed, superseded
- confirmed 버전은 불변
- 확정 이후 수정은 새 draft 또는 review 버전으로 생성
- 모든 수정은 AuditLog에 행위자, 시각, 사유, 변경 전후, 변경 출처를 기록
- 재생성 시 잠금된 배정은 유지
- 실패 시 원본 버전 보존

### 2.6 Excel 출력

- 날짜별 전체 직원의 근무상태 포함
- 직원별 요약 포함
- 버전, 확정 시각, 검증 결과 포함
- 공식 운영 양식 매핑은 실제 팀 파일 확인 후 추가

## 3. 추가 확인이 필요한 사항

명세서가 기본값을 임의 확정하지 말라고 명시한 항목이다. Phase 1에서 설정 UI와 seed data를 만들기 전 사용자 확인 또는 설정값 입력 구조가 필요하다.

### 3.1 업무 정책

- 주4일 및 주5일 직원의 주 기준: 예를 들어 월요일 시작인지 일요일 시작인지
- 연차와 공휴일을 근무일 산정에서 어떻게 처리할지
- 최소 휴식시간
- 연속 근무 상한
- 연속 야간 제한
- 야간 이후 필수 휴무 여부
- 야간, 조기, 주말, 공휴일 부담 계수
- 희망 휴무 반영 우선순위와 월별 허용 범위
- 개인별 예외 규칙
- 수동 수정 권한과 승인 절차

### 3.2 근무유형 정의

- 각 근무유형의 코드와 표시명
- 시작 시간
- 종료 시간
- 익일 종료 여부
- 휴게 시간
- 유급 시간
- 조기출근과 야간 조기출근의 정확한 시간 범위
- 근무유형별 필요 자격
- 사용자 정의 근무유형 허용 범위

### 3.3 수요 및 커버리지

- 날짜별, 요일별, 공휴일별 최소 인원
- 날짜별, 요일별, 공휴일별 목표 인원
- 날짜별, 요일별, 공휴일별 최대 인원
- 자격별 필수 배정 인원
- 중복 CoverageRequirement 충돌 시 우선순위
- 회사 운영일과 개인 근무일의 차이

### 3.4 운영 및 보안

- MVP 인증 방식
- 사용자 역할: 단일 관리자 이후 관리자, 편집자, 조회자 분리 기준
- 백업 암호화 여부
- 백업 보존 기간
- 로그 마스킹 범위
- 직원 실명 또는 휴무 사유를 LLM으로 전송할 수 있는지 여부
- LLM 사용 시 가명화 정책

### 3.5 기술 선택 충돌 확인

기술명세서에는 Next.js Node runtime, Python solver subprocess 또는 로컬 서비스, SQLite+Prisma가 적혀 있고, 현재 사용자 지시에는 Backend Python FastAPI, SQLite MVP, PostgreSQL 전환 가능 구조가 적혀 있다.

Phase 1 제안은 다음과 같다.

- Frontend: Next.js + TypeScript + Tailwind CSS
- Backend API: FastAPI
- Solver: FastAPI 내부 Python 모듈 또는 별도 solver package
- Database: SQLite + SQLAlchemy/Alembic
- PostgreSQL 전환을 위해 DB 접근 계층과 migration을 분리
- Excel: Python openpyxl 또는 xlsxwriter
- LLM: FastAPI Provider Adapter

사용자 승인이 필요하다. 이 방향을 승인하면 명세서의 Node runtime 및 Prisma 언급은 v2 명세의 구현 후보였으나 현재 개발 지시의 FastAPI 우선 원칙으로 대체한다.

## 4. 데이터 모델 설계

아래 모델은 SQLite MVP를 기준으로 하되 PostgreSQL 전환을 고려해 명시적 외래키, 유니크 제약, 상태 enum, JSON 설정 컬럼을 분리한다.

### 4.1 Team

- id
- name
- timezone
- created_at
- updated_at
- archived_at

용도: 팀 단위 독립 운영 범위. 모든 주요 데이터는 team_id 범위 검증을 거친다.

### 4.2 Employee

- id
- team_id
- employee_no
- display_name
- active_from
- active_to
- is_active
- metadata_json
- created_at
- updated_at

제약:

- team_id, employee_no 유니크
- 삭제 대신 비활성화
- 동명이인 표시에 employee_no 또는 내부 ID 사용

### 4.3 ShiftType

- id
- team_id
- code
- name
- category: DAY, EARLY_DAY, NIGHT, EARLY_NIGHT, OFF, LEAVE, OTHER
- start_time
- end_time
- ends_next_day
- break_minutes
- paid_minutes
- required_qualification_code
- color
- is_work
- is_active
- effective_from
- effective_to

제약:

- team_id, code, effective_from 유니크 후보
- WORK 성격의 근무유형만 start_time/end_time 필수

### 4.4 EmployeeContract

- id
- employee_id
- effective_from
- effective_to
- weekly_pattern_json
- target_minutes_per_week
- target_minutes_per_month_override
- allowed_shift_type_ids_json
- max_consecutive_work_days
- min_rest_minutes
- metadata_json

용도: 주4일/주5일, 계약 근무량, 허용 근무유형, 개인 예외의 기준.

### 4.5 EmployeeQualification

- id
- employee_id
- qualification_code
- effective_from
- effective_to
- source
- notes

용도: 자격별 필수 인원 및 근무유형 배정 가능성 검증.

### 4.6 OperatingCalendar

- id
- team_id
- local_date
- date_type: WORKDAY, WEEKEND, HOLIDAY, SUBSTITUTE_HOLIDAY, COMPANY_CLOSED
- holiday_name
- source
- is_manual_override
- created_at
- updated_at

제약:

- team_id, local_date 유니크

### 4.7 CoverageRequirement

- id
- team_id
- name
- priority
- effective_from
- effective_to
- date_rule_json
- shift_type_id
- min_count
- target_count
- max_count
- qualification_requirements_json
- is_active

date_rule_json 예:

```json
{
  "daysOfWeek": ["MON", "TUE", "WED", "THU", "FRI"],
  "dateTypes": ["WORKDAY"],
  "specificDates": []
}
```

검증:

- 동일 기간, 동일 날짜 조건, 동일 shift_type_id에 대해 우선순위 충돌 검사
- min_count <= target_count <= max_count

### 4.8 Availability

- id
- employee_id
- local_date
- availability_type: AVAILABLE, UNAVAILABLE, PREFERRED_OFF, PREFERRED_WORK
- shift_type_id nullable
- reason_code
- note
- priority
- source

용도: 희망 휴무, 근무 가능/불가능 조건, 선호.

### 4.9 LeaveRequest

- id
- employee_id
- start_date
- end_date
- status: REQUESTED, APPROVED, REJECTED, CANCELED
- leave_type
- reason
- approved_by
- approved_at

승인 연차는 Hard 제약으로 처리한다.

### 4.10 RuleSet

- id
- team_id
- name
- effective_from
- effective_to
- hard_rules_json
- soft_weights_json
- fairness_config_json
- solver_config_json
- approved_by
- approved_at
- version

용도: 하드코딩 금지 정책을 설정 데이터로 분리.

### 4.11 Schedule

- id
- team_id
- year
- month
- status
- active_version_id
- created_at
- updated_at

제약:

- team_id, year, month 유니크

### 4.12 ScheduleVersion

- id
- schedule_id
- version_no
- status: DRAFT, REVIEW, CONFIRMED, SUPERSEDED
- input_hash
- config_hash
- solver_engine
- solver_version
- solver_seed
- solver_workers
- solver_time_limit_seconds
- solver_status
- generated_at
- confirmed_at
- confirmed_by
- parent_version_id
- notes

제약:

- schedule_id, version_no 유니크
- CONFIRMED는 애플리케이션 레벨에서 불변 처리

### 4.13 Assignment

- id
- version_id
- employee_id
- local_date
- status: WORK, OFF, LEAVE, OTHER
- shift_type_id nullable
- locked
- source: SOLVER, MANUAL, IMPORT, REVISION
- change_reason
- validation_state
- created_at
- updated_at

제약:

- version_id, employee_id, local_date 유니크
- status가 WORK이면 shift_type_id 필수
- status가 WORK가 아니면 shift_type_id는 null 또는 OFF/LEAVE 전용 shift type만 허용하는 정책 중 선택 필요

### 4.14 AssignmentLock

- id
- version_id
- employee_id
- local_date
- locked_by
- locked_at
- reason

Assignment.locked로 단순화할 수 있으나 잠금 이력 보존이 필요하면 별도 테이블을 둔다.

### 4.15 ValidationResult

- id
- version_id
- severity: ERROR, WARNING, INFO
- rule_code
- message
- local_date nullable
- employee_id nullable
- shift_type_id nullable
- details_json
- created_at

용도: preflight, solver 결과, 수동 수정 후 재검증 결과를 UI와 Excel에 표시.

### 4.16 FairnessMetric

- id
- version_id
- employee_id
- metric_period
- work_days
- paid_minutes
- night_score
- early_score
- weekend_score
- holiday_score
- preferred_off_satisfaction_rate
- expected_burden_score
- actual_burden_score
- deviation_score
- history_status
- details_json

history_status 예: ENOUGH_HISTORY, INSUFFICIENT_HISTORY.

### 4.17 AuditLog

- id
- team_id
- actor_id
- action
- entity_type
- entity_id
- before_json
- after_json
- reason
- created_at
- request_id

용도: 설정 승인, 배정 수정, 확정, 개정, 복원, Excel export 이력.

### 4.18 AiInteractionLog

- id
- team_id
- actor_id
- provider
- adapter_method
- input_hash
- redaction_mode
- token_input_count
- token_output_count
- cost_estimate
- latency_ms
- status
- error_message
- created_at

실제 민감 입력 전문 저장은 기본 비활성화한다.

## 5. API 구조 설계

API는 FastAPI 기준으로 설계한다. 모든 엔드포인트는 team_id 권한 범위와 입력 스키마 검증을 수행한다.

### 5.1 Teams

- GET /api/teams
- POST /api/teams
- GET /api/teams/{team_id}
- PATCH /api/teams/{team_id}
- DELETE /api/teams/{team_id}

삭제는 archive 처리한다.

### 5.2 Configuration

- GET /api/teams/{team_id}/config
- POST /api/teams/{team_id}/config/validate
- POST /api/teams/{team_id}/config/approve
- GET /api/teams/{team_id}/rulesets
- POST /api/teams/{team_id}/rulesets
- PATCH /api/teams/{team_id}/rulesets/{ruleset_id}

### 5.3 Employees

- GET /api/teams/{team_id}/employees
- POST /api/teams/{team_id}/employees
- GET /api/teams/{team_id}/employees/{employee_id}
- PATCH /api/teams/{team_id}/employees/{employee_id}
- POST /api/teams/{team_id}/employees/import
- GET /api/teams/{team_id}/employees/export-template

### 5.4 Shift Types and Coverage

- GET /api/teams/{team_id}/shift-types
- POST /api/teams/{team_id}/shift-types
- PATCH /api/teams/{team_id}/shift-types/{shift_type_id}
- GET /api/teams/{team_id}/coverage-requirements
- POST /api/teams/{team_id}/coverage-requirements
- PATCH /api/teams/{team_id}/coverage-requirements/{requirement_id}

### 5.5 Availability and Leave

- GET /api/teams/{team_id}/availability?year=&month=
- POST /api/teams/{team_id}/availability
- PATCH /api/teams/{team_id}/availability/{availability_id}
- GET /api/teams/{team_id}/leave-requests?year=&month=
- POST /api/teams/{team_id}/leave-requests
- PATCH /api/teams/{team_id}/leave-requests/{leave_request_id}

### 5.6 AI Interpretation

- POST /api/teams/{team_id}/ai/interpret-setup
- POST /api/teams/{team_id}/ai/interpret-schedule-edit

응답 공통 형식:

```json
{
  "intent": "string",
  "proposedPatch": {},
  "missingFields": [],
  "clarificationQuestion": "string|null",
  "confidence": 0.0,
  "warnings": []
}
```

AI 응답은 JSON Schema로 검증하고 허용된 필드만 적용한다. 적용 전에는 관리자 승인 또는 미리보기를 거친다.

### 5.7 Scheduling

- POST /api/teams/{team_id}/schedules/preflight
- POST /api/teams/{team_id}/schedules/generate
- GET /api/teams/{team_id}/schedules/{year}/{month}
- GET /api/teams/{team_id}/schedules/{schedule_id}/versions
- GET /api/teams/{team_id}/schedules/{schedule_id}/versions/{version_id}
- POST /api/teams/{team_id}/schedules/{schedule_id}/versions/{version_id}/validate
- POST /api/teams/{team_id}/schedules/{schedule_id}/versions/{version_id}/confirm
- POST /api/teams/{team_id}/schedules/{schedule_id}/versions/{version_id}/revise
- POST /api/teams/{team_id}/schedules/{schedule_id}/versions/{version_id}/restore

### 5.8 Assignments

- PATCH /api/teams/{team_id}/schedule-versions/{version_id}/assignments/{assignment_id}
- POST /api/teams/{team_id}/schedule-versions/{version_id}/assignments/bulk-patch
- POST /api/teams/{team_id}/schedule-versions/{version_id}/assignments/{assignment_id}/lock
- POST /api/teams/{team_id}/schedule-versions/{version_id}/assignments/{assignment_id}/unlock

모든 수정은 트랜잭션 안에서 적용하고 전체 Hard 제약 재검증을 수행한다.

### 5.9 Export, Backup, History

- GET /api/teams/{team_id}/schedule-versions/{version_id}/export.xlsx
- GET /api/teams/{team_id}/audit-logs
- POST /api/teams/{team_id}/backup
- POST /api/teams/{team_id}/restore

## 6. Solver 입력 및 출력 구조

### 6.1 SolverInput

```json
{
  "schemaVersion": "1.0",
  "team": {
    "id": "team-id",
    "timezone": "Asia/Seoul"
  },
  "period": {
    "year": 2026,
    "month": 11,
    "startDate": "2026-11-01",
    "endDate": "2026-11-30",
    "boundaryDates": {
      "previous": ["2026-10-30", "2026-10-31"],
      "next": ["2026-12-01", "2026-12-02"]
    }
  },
  "employees": [],
  "shiftTypes": [],
  "coverageRequirements": [],
  "availability": [],
  "leaveRequests": [],
  "lockedAssignments": [],
  "previousAssignments": [],
  "ruleSet": {},
  "fairnessHistory": [],
  "solverConfig": {
    "seed": 1,
    "timeLimitSeconds": 30,
    "workers": 8
  }
}
```

### 6.2 SolverOutput

```json
{
  "schemaVersion": "1.0",
  "status": "OPTIMAL",
  "objectiveValue": 0,
  "assignments": [],
  "fairnessMetrics": [],
  "validationResults": [],
  "solverStats": {
    "engine": "ortools-cp-sat",
    "version": "string",
    "wallTimeSeconds": 0,
    "seed": 1,
    "workers": 8
  }
}
```

상태는 OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN 중 하나다.

## 7. Hard 제약

Hard 제약은 위반 시 결과를 저장하거나 확정할 수 없다.

### 7.1 날짜별 직원 상태 유일성

- 각 직원은 각 local_date에 정확히 하나의 상태를 가진다.
- 상태는 WORK, OFF, LEAVE, OTHER 중 하나다.
- WORK 상태일 때 근무유형이 반드시 존재한다.

### 7.2 커버리지 최소 인원

- CoverageRequirement의 min_count 이상을 만족한다.
- 자격 조건이 있는 CoverageRequirement는 해당 자격 보유 직원만 집계한다.
- max_count가 설정된 경우 초과 배정 금지.

### 7.3 자격 및 허용 근무유형

- 직원은 보유 자격의 유효기간 내에서만 해당 자격 근무에 배정 가능.
- EmployeeContract.allowed_shift_type_ids 범위를 벗어나면 배정 금지.
- 직원의 active_from, active_to 밖 날짜에는 WORK 배정 금지.

### 7.4 승인 연차

- 승인된 LeaveRequest 기간에는 LEAVE 상태로 고정.
- 승인 연차와 고정 WORK 배정이 충돌하면 preflight 오류.

### 7.5 고정 배정 및 잠금

- lockedAssignment는 solver가 변경할 수 없다.
- 재생성 시 잠금 배정은 유지.

### 7.6 최소 휴식

- 전날 또는 월 경계의 직전 근무 종료 datetime과 다음 근무 시작 datetime 사이가 설정된 min_rest_minutes 이상이어야 한다.
- 야간처럼 익일 종료되는 근무는 실제 종료 datetime으로 계산한다.

### 7.7 연속 근무 상한

- 설정된 max_consecutive_work_days를 초과하는 연속 WORK 금지.
- 월 경계 확인을 위해 전월 말 및 익월 초 배정을 포함해 계산한다.

### 7.8 월 경계

- 전월 말 확정 배정과 대상 월 초 배정 사이의 휴식 및 연속근무 제약을 검증한다.
- 대상 월 말 배정과 익월 초 예정 또는 확정 배정 사이도 검증한다.

### 7.9 계약 및 운영일 규칙

- 직원 계약 유효기간과 weeklyPattern을 적용한다.
- 회사 운영일과 개인 근무 가능일을 분리해 검증한다.
- 주4일/주5일, 공휴일, 연차 산정 방식은 RuleSet 설정에 따른다.

### 7.10 법규 및 사내 규칙

- 법적 요건은 하드코딩하지 않는다.
- 노무 검토 후 승인된 RuleSet에 들어온 규칙만 Hard 제약으로 적용한다.

## 8. Soft 제약

Soft 제약은 목적함수에서 비용으로 반영하며 Hard 제약을 침해할 수 없다.

### 8.1 희망 휴무 및 선호

- PREFERRED_OFF 미충족 비용
- PREFERRED_WORK 미충족 비용
- 선호 가중치는 관리자가 설정

### 8.2 부담 균형

- 야간 근무 점수 편차 최소화
- 조기출근 점수 편차 최소화
- 주말 근무 점수 편차 최소화
- 공휴일 근무 점수 편차 최소화
- 유급시간 또는 근무일 수 편차 최소화

### 8.3 기대 부담 대비 편차

직원별 기대점수는 계약 근무량, 가능일, 자격, 휴무를 반영해 정규화한다.

예:

```text
actual_burden(employee, metric) =
  sum(assigned_shift_count_or_minutes * approved_burden_weight)

expected_burden(employee, metric) =
  total_metric_burden * normalized_employee_opportunity_share

deviation =
  abs(actual_burden - expected_burden)
```

### 8.4 최근 이력 반영

- 월별 및 최근 3개월 누적 야간, 조기, 주말, 공휴일 점수 반영
- 데이터가 부족하면 이력 부족으로 표시하고 현재 월 기준으로 계산

### 8.5 패턴 안정성

- 불필요한 근무유형 변동 비용
- 과도한 짧은 패턴 반복 비용
- 관리자가 승인한 패턴 선호만 적용

## 9. 목적함수 설계

목표함수는 단계형 우선순위를 따른다.

1. Hard 제약 충족
2. 직원별 과도한 부담 방지
3. 전체 불균형 최소화
4. 희망 휴무, 개인 선호, 패턴 안정성 최적화

구현 방식:

- Hard 제약은 CP-SAT constraint로 모델링
- Soft 제약은 penalty 변수와 weighted sum으로 모델링
- 우선순위 보장을 위해 큰 가중치 계층을 사용하거나 순차 최적화를 검토
- 가중치 값은 RuleSet에 저장하고 변경 이력을 남김
- 수치 스케일은 테스트 데이터로 검증

## 10. Preflight 설계

Solver 실행 전 다음 항목을 deterministic code로 검사한다.

- 필수 설정 누락
- 근무유형 시간 정의 오류
- min_count, target_count, max_count 순서 오류
- 총 필요 근무 슬롯 대비 직원별 최대 가능 슬롯 부족
- 자격별 공급 부족
- 승인 연차와 고정 배정 충돌
- 잠금 배정과 계약 또는 자격 충돌
- 최소 휴식 조건상 불가능한 인접 근무 조합
- 월 경계 데이터 누락
- 동일 날짜 동일 직원 중복 입력
- CoverageRequirement 우선순위 충돌

Preflight 실패와 CP-SAT INFEASIBLE은 UI에서 구분한다.

## 11. 개발 순서

### Phase 1. 프로젝트 초기화 및 데이터 모델

구현:

- Next.js 프론트엔드 초기화
- FastAPI 백엔드 초기화
- SQLite 연결
- SQLAlchemy/Alembic 모델 및 마이그레이션
- Team, Employee, ShiftType, CoverageRequirement, RuleSet 기본 CRUD
- 달력 전체 표시를 검증할 테스트 fixture
- LLM 없이 동작하는 설정 폼의 기초

테스트:

- DB migration 테스트
- 모델 제약 테스트
- 기본 CRUD API 테스트
- 날짜별 전 직원 1회 표시 fixture 테스트

완료 기준:

- 로컬에서 frontend/backend 실행 가능
- seed data로 팀, 직원, 근무유형, 수요 저장 가능
- 월간 달력 mock 화면에서 날짜별 모든 직원이 표시됨

### Phase 2. 근무형태 설정 UI와 챗봇

구현:

- 직원, 계약, 자격, 근무유형, 커버리지 설정 UI
- 누락 필드 표시
- config validate/approve
- LLM Provider Adapter 인터페이스
- interpretSetup 오프라인 폴백
- AI 응답 JSON Schema 검증

테스트:

- AI 미설정 상태에서 폼 기능 정상 동작
- 잘못된 AI 응답 reject
- 민감정보 마스킹 단위 테스트
- 설정 승인 전 저장 제한 테스트

완료 기준:

- AI 없이 전체 설정 가능
- AI는 승인 가능한 patch 제안만 생성하고 직접 DB 변경 불가

### Phase 3. OR-Tools 근무 배정 엔진

구현:

- SolverInput/SolverOutput 스키마
- preflight
- CP-SAT Hard 제약
- solver 실행 및 상태 기록
- INFEASIBLE/UNKNOWN 처리
- 월 경계 검증
- 결과 저장 전 Hard 재검증

테스트:

- 최소 인원 충족
- 직원별 날짜당 하나의 상태
- 승인 연차 고정
- 야간 후 익일 조기 금지 예시
- 자격 부족 INFEASIBLE
- 동일 seed 재현성
- FEASIBLE 후 Hard 재검증

완료 기준:

- 샘플 팀 한 달 근무표 생성
- Hard 위반 0건
- INFEASIBLE 시 임의 결과 미생성

### Phase 4. 월간 달력 UI

구현:

- 실제 ScheduleVersion 기반 월간 달력
- 날짜 칸 내부 그룹 표시
- 날짜 상세 패널
- 수동 수정
- 잠금
- 재검증 결과 표시
- 접근성 레이블 및 범례

테스트:

- 10/8 날짜 칸에 모든 직원 정확히 1회 표시
- 동명이인 구분
- 많은 직원 내부 스크롤
- 모바일/좁은 화면 스크롤
- 색상 없이 상태 텍스트 확인 가능

완료 기준:

- 기본 화면이 월간 달력이며 팀 전체 직원 상태를 누락 없이 표시

### Phase 5. 저장, 수정, 확정, Excel 내보내기

구현:

- draft/review/confirmed/superseded 버전 상태
- 확정본 불변 처리
- 개정 생성
- AuditLog
- Excel export
- backup/restore
- Windows 실행 스크립트

테스트:

- 확정 후 직접 수정 금지
- revise로 새 버전 생성
- AuditLog 기록
- Excel의 날짜별 전체 인원 대조
- 백업 복원 리허설

완료 기준:

- 운영자가 생성, 수정, 확정, 개정, Excel 다운로드까지 완료 가능

### Phase 6. 통합 테스트 및 배포 준비

구현:

- 실제 운영 유사 fixture 3개월
- 성능 측정
- 장애 처리
- 배포 문서
- 환경변수 문서

테스트:

- 10~20개 시나리오
- 100회 반복 결과 검증
- AI 장애
- solver timeout
- 네트워크 장애
- 모바일/인쇄 확인

완료 기준:

- 파일럿 운영 전 팀장 검토 가능한 수준의 안정성 확보

## 12. 테스트 계획 상세

### 12.1 Unit Tests

- 날짜 및 시간 계산
- 익일 종료 근무 datetime 계산
- 최소 휴식 계산
- 연속 근무일 계산
- RuleSet 파싱
- CoverageRequirement 적용
- 공정성 점수 계산
- AI JSON Schema 검증
- Excel export 데이터 생성

### 12.2 API Tests

- CRUD 정상/오류 경로
- team_id 범위 검증
- config validate/approve
- preflight/generate/validate/confirm
- assignment patch/lock/unlock
- confirmed 버전 수정 금지
- revise/restore

### 12.3 Solver Tests

- 성공 가능한 최소 케이스
- 직원 수 부족
- 자격 부족
- 승인 연차 충돌
- 고정 배정 충돌
- 야간 후 최소 휴식 위반
- 월 경계 연속 근무 위반
- max_count 초과 방지
- 동일 seed 재현성
- timeout FEASIBLE/UNKNOWN 처리

### 12.4 UI Tests

- 월간 달력 렌더링
- 각 날짜별 전체 직원 1회 표시
- 날짜 상세 패널 수정
- 근무자가 많을 때 내부 스크롤
- 동명이인 표시
- 접근성 레이블
- 모바일 폭에서 레이아웃 유지

### 12.5 End-to-End Tests

- 팀 생성부터 Excel 다운로드까지
- AI 오프라인 상태에서 전체 플로우
- 생성 후 수동 수정, 재검증, 확정
- 확정 후 개정 생성
- 백업 후 복원

### 12.6 운영 검증

- 실제 직원 수 기준 3개월 시나리오 10~20개
- 100회 반복 실행
- 작성시간 측정
- 수동 수정 횟수 측정
- Hard 위반 0건 확인
- 공정성 편차 측정
- 관리자 만족도 수집

## 13. 기술 위험 및 대응

### 13.1 Windows 환경

위험:

- Python, OR-Tools, Node, SQLite, 파일 경로, 한글 경로에서 문제가 발생할 수 있음.

대응:

- Windows 로컬 실행 스크립트 제공
- 의존성 설치 문서화
- 한글 경로 smoke test
- solver subprocess 대신 FastAPI 내부 모듈 우선 검토

### 13.2 CP-SAT 모델 복잡도

위험:

- 실제 직원 수와 규칙 수에 따라 생성 시간이 증가할 수 있음.

대응:

- preflight로 명백한 실패를 조기 반환
- timeLimitSeconds 설정
- 단계별 Hard 우선 구현
- solver 통계 저장
- 성능 fixture 반복 측정

### 13.3 업무 규칙 불명확성

위험:

- 임의 기본값을 넣으면 운영 결과가 틀릴 수 있음.

대응:

- 미확정 정책은 RuleSet에 null 또는 incomplete로 저장
- UI에 미완료 표시
- generate 전에 필수 정책 누락 차단

### 13.4 LLM 신뢰성

위험:

- LLM 응답이 잘못된 patch를 제안할 수 있음.

대응:

- JSON Schema 검증
- 허용 필드 allowlist
- 적용 전 미리보기 및 승인
- AI가 DB, 파일 시스템, solver를 직접 실행하지 못하게 설계
- AI 미연결 오프라인 폴백 유지

### 13.5 확정본 무결성

위험:

- 확정 근무표가 실수로 변경되면 운영 신뢰가 깨짐.

대응:

- confirmed 버전 수정 API 차단
- DB 레벨 또는 애플리케이션 레벨 불변 가드
- 개정 버전 생성만 허용
- AuditLog 필수 기록

## 14. Phase 1 착수 전 승인 요청 항목

1. Backend를 FastAPI + SQLAlchemy/Alembic으로 진행해도 되는지
2. SQLite MVP 이후 PostgreSQL 전환 가능 구조를 목표로 해도 되는지
3. Prisma와 Next.js API route는 사용하지 않는 방향으로 확정해도 되는지
4. Excel 처리를 Python openpyxl 또는 xlsxwriter로 진행해도 되는지
5. 초기 인증은 단일 관리자 로컬 로그인 또는 간단한 패스워드 방식 중 어떤 방향으로 할지
6. 샘플 팀 규칙을 실제 값으로 받을 수 있는지, 아니면 Phase 1에서는 incomplete 설정 상태와 테스트 fixture만 둘지

## 15. Phase 0 완료 기준

- 기술명세서 요구사항 분석 완료
- 구현 가능 요구사항과 확인 필요 사항 분리 완료
- 데이터 모델 초안 작성 완료
- API 구조 초안 작성 완료
- Hard/Soft 제약 정리 완료
- 개발 순서와 테스트 계획 작성 완료
- Phase 1 승인 전 대기

## 16. Phase 0 검증 기록

수행한 확인:

- 첨부 DOCX에서 78개 문단을 추출해 요구사항을 분석
- 현재 작업 폴더가 비어 있음을 확인
- 현재 폴더가 Git 저장소가 아님을 확인
- 생성 파일이 docs/IMPLEMENTATION_PLAN.md 하나뿐임을 확인

테스트 결과:

- Phase 0은 구현 단계가 아니므로 애플리케이션 테스트는 실행하지 않음
- 문서 생성 후 내용을 재읽어 주요 섹션과 산출 범위를 확인함
