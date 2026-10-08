# AI Shift Scheduler

팀별 근무표 자동 생성을 위한 웹앱입니다. 현재 구현 단계는 Phase 2이며, 기술명세서 v2.0과 `docs/IMPLEMENTATION_PLAN.md`를 기준으로 기본 프로젝트 구조, 데이터 모델, API, 설정 폼, 근무형태 설정 챗봇을 제공합니다.

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
- 백엔드 기본 테스트

아직 구현하지 않음:

- OR-Tools CP-SAT 자동 배정 엔진
- Excel 내보내기
- 확정/개정 버전 워크플로 전체

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
.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --name workscheduler-api --paths backend launcher.py
cd ..
New-Item -ItemType Directory -Force backend\dist
Copy-Item -Force dist\workscheduler-api.exe backend\dist\workscheduler-api.exe
cd electron
$env:CSC_IDENTITY_AUTO_DISCOVERY="false"
npm run dist
```

설치파일은 `electron/dist/AI Shift Scheduler Setup 0.1.0.exe`에 생성됩니다. 앱 데이터베이스는 설치 디렉터리가 아닌 Electron `userData/data/workscheduler.db`에 저장됩니다. Codex CLI와 Claude Code는 고정된 명령 이름으로 설치 여부와 `--version` 실행 가능 여부만 확인하며, 임의 셸 명령 실행 IPC는 제공하지 않습니다.

현재 PoC에서 확인한 범위는 Electron 보안 설정, 기존 UI 실행, 로컬 FastAPI 자동 시작/종료, SQLite 재실행 보존 경로, 에이전트 감지 IPC, PyInstaller 백엔드 번들, NSIS 설치파일 생성입니다. 실제 OR-Tools 배정과 에이전트의 규칙 조정은 Phase 3 이후 범위입니다.

## Phase 3 이전 메모

Phase 3에서는 사용자 승인 후 OR-Tools CP-SAT 근무 배정 엔진을 진행합니다. 현재 Phase 2에서는 근무 배정 자동 생성 기능을 의도적으로 구현하지 않았습니다.
