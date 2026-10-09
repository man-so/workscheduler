# AI Shift Scheduler

팀별 근무표 자동 생성을 위한 앱입니다. 현재 구현 단계는 Phase 5이며, 설정 폼, 근무형태 설정 챗봇, 에이전트 기반 Constraint JSON 생성, OR-Tools CP-SAT 월간 근무표 생성, 월간 달력 수정, 버전 관리, 확정, Excel 내보내기를 제공합니다.

## 현재 범위

구현됨:

- Next.js + TypeScript + Tailwind CSS 프런트엔드
- FastAPI 백엔드
- SQLite 기본 연결
- PostgreSQL 전환을 고려한 SQLAlchemy 기반 모델
- 팀, 직원, 근무유형, 근무규칙, 휴무신청, 근무배정 기본 API
- 직원별 계약, 요일별 필요 인원, 휴무 희망, 설정 대화 세션 저장
- 프런트엔드의 백엔드 health 및 설정 데이터 조회
- 왼쪽 설정 현황 및 직접 입력 폼
- 오른쪽 근무형태 설정 챗봇
- 누락 항목과 충돌 항목 표시
- 챗봇 변경사항 미리보기 및 승인 후 저장
- LLM API Key 없이 동작하는 오프라인 Provider Adapter
- 선택한 Codex CLI / Claude Code의 제한된 비대화형 실행과 실행 기록
- 승인된 설정 JSON 기반 Constraint JSON 검증
- OR-Tools CP-SAT 기반 월간 배정, Hard/Soft 제약, 공정성 목적함수
- INFEASIBLE 원인과 지원되지 않는 제약조건 보고
- 모든 직원·모든 날짜를 포함하는 7열 월간 달력 API/UI
- 날짜 클릭 상세 패널에서 직원별 근무/휴무 상태 수동 수정
- 수동 수정 후 월간표 기본 무결성 및 필요 인원 검증
- 확정된 근무표의 무단 변경 방지 API
- 월별 스케줄 버전 이력 조회
- 이전 버전에서 새 DRAFT 복제
- Hard Constraint 검증 기반 확정 차단
- Soft Constraint 확인 후 확정
- 확정 시 과거 버전 ARCHIVED 보관
- openpyxl 기반 월간 달력 Excel 내보내기
- Excel 내 직원별 현황, 근무유형 통계, 공정성 통계, 검증 결과 시트
- 백엔드 기본 테스트

아직 구현하지 않음:

- 운영용 DB 마이그레이션 도구

## 환경변수

`.env.example`을 참고해 루트 또는 실행 환경에 `.env`를 만듭니다.

```bash
DATABASE_URL=sqlite:///./data/workscheduler.db
BACKEND_CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

LLM 연결은 선택 사항입니다. `LLM_API_KEY`가 없어도 설정 폼과 규칙 기반 챗봇은 동작합니다.

PostgreSQL로 전환할 때는 `DATABASE_URL`을 다음과 같은 형식으로 바꿀 수 있도록 설계했습니다.

```bash
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/workscheduler
```

## 백엔드 실행

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

기본 주소는 `http://localhost:8000`입니다.

## 프런트엔드 실행

```bash
cd frontend
npm install
npm run dev
```

기본 주소는 `http://localhost:3000`입니다.

## 테스트

백엔드:

```bash
cd backend
pytest
```

프런트엔드:

```bash
cd frontend
npm run typecheck
npm run build
```

## API 요약

- `GET /api/health`
- `GET /api/teams`
- `POST /api/teams`
- `GET /api/teams/{team_id}/employees`
- `POST /api/teams/{team_id}/employees`
- `GET /api/teams/{team_id}/shift-types`
- `POST /api/teams/{team_id}/shift-types`
- `GET /api/teams/{team_id}/work-rules`
- `POST /api/teams/{team_id}/work-rules`
- `GET /api/teams/{team_id}/leave-requests`
- `POST /api/teams/{team_id}/leave-requests`
- `GET /api/teams/{team_id}/assignments`
- `POST /api/teams/{team_id}/assignments`
- `GET /api/teams/{team_id}/setup-summary`
- `GET /api/teams/{team_id}/setup-sessions/active`
- `POST /api/teams/{team_id}/setup-sessions`
- `POST /api/teams/{team_id}/setup-sessions/{session_id}/messages`
- `POST /api/teams/{team_id}/setup-sessions/{session_id}/approve`
- `GET /api/teams/{team_id}/employee-contracts`
- `POST /api/teams/{team_id}/employee-contracts`
- `GET /api/teams/{team_id}/coverage-requirements`
- `POST /api/teams/{team_id}/coverage-requirements`
- `GET /api/teams/{team_id}/availability`
- `GET /api/agents`
- `POST /api/teams/{team_id}/schedules/generate`
- `GET /api/teams/{team_id}/generation-runs/{run_id}`
- `POST /api/teams/{team_id}/generation-runs/{run_id}/cancel`
- `GET /api/teams/{team_id}/schedules/{year}/{month}`
- `GET /api/teams/{team_id}/schedules/{year}/{month}/versions`
- `GET /api/teams/{team_id}/schedules/{year}/{month}/versions/{version_id}`
- `POST /api/teams/{team_id}/schedules/{year}/{month}/versions/{version_id}/clone`
- `POST /api/teams/{team_id}/schedules/{year}/{month}/confirm`
- `PATCH /api/teams/{team_id}/schedules/{year}/{month}/assignments`
- `GET /api/teams/{team_id}/schedules/{year}/{month}/validation`
- `GET /api/teams/{team_id}/schedules/{year}/{month}/export.xlsx`
- `POST /api/teams/{team_id}/availability`

## Phase 2 챗봇 동작

- 기존 팀 설정을 먼저 조회합니다.
- 누락 항목과 충돌 항목을 계산합니다.
- 한 번에 최대 3개 질문을 표시합니다.
- 자연어 답변은 서버의 규칙 기반 파서로 구조화합니다.
- 변경사항은 pending patch로 세션에 저장합니다.
- 관리자가 승인해야 데이터베이스에 반영됩니다.
- 대화 도중 종료해도 active setup session으로 복구합니다.
- 외부 LLM 연결은 선택 사항이며 Phase 2에서는 직접 호출하지 않습니다.

## Phase 3 동작

- 에이전트에는 전체 챗봇 대화가 아니라 승인된 팀 설정 JSON만 전달합니다.
- Codex는 `exec --sandbox read-only --skip-git-repo-check --output-schema`와 임시 작업 디렉터리를 사용합니다.
- Claude Code는 `-p --output-format json --permission-mode plan --max-turns 3`을 사용합니다.
- 생성된 Python 코드나 셸 명령은 실행하지 않습니다. 에이전트 응답은 JSON schema와 서버 검증을 통과해야 합니다.
- CP-SAT는 직원 계약, 가능 유형, 휴무, 필요 인원, 휴식, 연속근무, 야간 후 휴무 데이터를 동적으로 제약으로 구성합니다.
- 결과는 `DRAFT` 버전으로 저장되며 관리자 확정 전 상태입니다.
- Codex/Claude 인증·사용량·timeout 실패는 실행 기록에 저장하고 근무표를 생성하지 않습니다.

## Phase 4 달력 동작

- 월간 달력은 7열 구조를 유지하며 각 날짜 칸에 모든 활성 직원을 근무유형 또는 휴무 상태별로 그룹화합니다.
- 날짜를 클릭하면 우측 상세 패널에서 해당 날짜의 모든 직원 배정을 확인하고 근무유형, 휴무, 연차, 기타 상태로 수정할 수 있습니다.
- 수정은 활성 `DRAFT` 스케줄 버전에 저장되며, 저장 직후 필요 인원 최소·최대·목표값과 누락 배정을 다시 검증합니다.
- `CONFIRMED` 상태의 스케줄 버전은 API에서 수정을 거부합니다.

## Phase 5 버전·확정·Excel 동작

- 스케줄 버전 상태는 `DRAFT`, `CONFIRMED`, `ARCHIVED`를 사용합니다.
- 확정 전 검증을 다시 실행하며 `ERROR` 이슈가 있으면 확정을 차단합니다.
- `WARN` 이슈는 UI에서 확인 후 `approve_soft_issues`로 확정할 수 있습니다.
- 확정된 버전은 직접 수정할 수 없고, 이전 버전에서 새 `DRAFT`를 복제한 뒤 수정합니다.
- Excel 내보내기는 활성 버전을 기준으로 월요일~일요일 7열 달력, 날짜별 전체 직원, 동적 근무유형 그룹, 인원 수, 색상 구분, 인쇄 설정을 포함합니다.
- 추가 시트는 직원별 월간 근무현황, 근무유형별 배정 횟수, 야간/조기/주말/휴무 공정성 통계, 검증 결과입니다.

## Electron 전환 PoC

`electron/`에 Windows 데스크톱 셸을 추가했습니다. 개발 모드에서는 Electron이 기존 Next.js dev server와 FastAPI를 자동 시작하고, 배포 모드에서는 정적 Next export와 PyInstaller로 번들한 FastAPI 실행파일을 사용합니다.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-desktop.txt
cd ..
cd electron
npm install
npm run dev
```

Windows 설치파일 생성:

```bash
cd backend
.venv\Scripts\pyinstaller.exe --noconfirm --clean workscheduler-api.spec
cd ..
cd electron
$env:CSC_IDENTITY_AUTO_DISCOVERY="false"
npm run dist
```

설치파일은 `electron/dist/AI Shift Scheduler Setup 0.1.0.exe`에 생성됩니다. 앱 데이터베이스는 설치 디렉터리가 아닌 Electron `userData/data/workscheduler.db`에 저장됩니다. Codex CLI와 Claude Code는 고정된 명령 이름으로 설치 여부와 `--version` 실행 가능 여부만 확인하며, 임의 셸 명령 실행 IPC는 제공하지 않습니다.

현재 PoC에서 확인한 범위는 Electron 보안 설정, 기존 UI 실행, 로컬 FastAPI 자동 시작/종료, SQLite 재실행 보존 경로, 에이전트 감지 IPC, PyInstaller 백엔드 번들, NSIS 설치파일 생성입니다. 실제 OR-Tools 배정과 에이전트의 규칙 조정은 Phase 3 이후 범위입니다.

## Phase 6 통합 검증

재현 가능한 가상 팀 A~F 검증은 다음 명령으로 실행합니다.

```bash
python scripts/phase6_validation.py
```

검증 결과는 `artifacts/phase6/phase6_scenarios.json`에 저장됩니다. A(8명), B(주4·주5 혼합), C(15명 조기·야간조기), D(25명·10개 유형), E(집중 휴무)는 CP-SAT 계산과 저장된 배정 검증, openpyxl 재오픈 검사를 통과했습니다. F는 충돌하는 Hard Constraint로 `INFEASIBLE`을 반환했으며 임의 배정을 만들지 않았습니다. A는 30초 제한에서 `FEASIBLE` 해를 반환했고 나머지는 `OPTIMAL`입니다.

2026-10-09 환경에서 Codex CLI 설치는 확인했지만 15초 제한 내 실제 호출이 완료되지 않아 LIVE 검증은 `BLOCKED`입니다. Claude Code는 설치되어 있지 않아 `BLOCKED`입니다. 인증 우회나 대체 자격증명은 사용하지 않았습니다. Windows unpacked Electron은 포함된 FastAPI 실행파일 단독 기동까지 확인했으나 Electron 전체 실행은 즉시 종료되어 설치형 앱 검증은 `BLOCKED`로 남아 있습니다.

달력 화면 캡처 도구는 다음 명령으로 실행할 수 있습니다. 화면 데이터와 Excel 산출물은 검증용 로컬 artifacts에 저장되며 개인정보가 없는 가상 직원만 사용합니다.

```bash
cd frontend
npm run build
cd ../electron
npm exec -- electron ../scripts/capture_phase6_screenshots.cjs
```

## Phase 3 이전 메모

Phase 3에서는 사용자 승인 후 OR-Tools CP-SAT 근무 배정 엔진을 진행합니다. 현재 Phase 2에서는 근무 배정 자동 생성 기능을 의도적으로 구현하지 않았습니다.
