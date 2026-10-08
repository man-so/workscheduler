# AI Shift Scheduler

팀별 근무표 자동 생성을 위한 웹앱입니다. 현재 구현 단계는 Phase 1이며, 기술명세서 v2.0과 `docs/IMPLEMENTATION_PLAN.md`를 기준으로 기본 프로젝트 구조, 데이터 모델, API, 프런트엔드 통신을 제공합니다.

## 현재 범위

구현됨:

- Next.js + TypeScript + Tailwind CSS 프런트엔드
- FastAPI 백엔드
- SQLite 기본 연결
- PostgreSQL 전환을 고려한 SQLAlchemy 기반 모델
- 팀, 직원, 근무유형, 근무규칙, 휴무신청, 근무배정 기본 API
- 프런트엔드의 백엔드 health 및 기본 데이터 조회
- 백엔드 기본 테스트

아직 구현하지 않음:

- AI 챗봇
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

## Phase 2 이전 메모

Phase 2에서는 사용자 승인 후 근무형태 설정 UI와 챗봇 인터페이스를 진행합니다. AI는 자연어 해석과 patch 제안에만 사용하고, 실제 저장은 검증과 관리자 승인 후 수행합니다.
