# Phase 6.1 장애 분석 및 수정 보고

검증일: 2026-10-09

## 수정 요약

- Electron 즉시 종료 원인을 수정했다.
  - `BrowserWindow` 참조를 전역으로 유지한다.
  - packaged 환경에서 `file://` 대신 로컬 정적 HTTP 서버로 Next.js export를 제공한다.
  - backend/frontend 시작, health check, 화면 로딩, renderer 종료, 예외를 userData 로그에 기록한다.
- 시작 실패 시 조용히 종료하지 않고 오류 화면과 로그 경로를 표시한다.
- FastAPI PyInstaller 하위 프로세스가 종료 후 남는 문제를 Windows process tree 종료로 수정했다.
- Codex CLI timeout으로 보였던 문제를 분석했다.
  - 실제 원인은 `--output-schema` strict schema와 확장 가능한 Constraint JSON 구조의 불일치였다.
  - CLI schema 강제는 제거하고, CLI JSON 응답 후 서버의 `normalize_agent_constraints()` 검증을 유지했다.
  - 에이전트 실행 로그에 command, cwd, 경과 시간, stdout/stderr 이벤트, output file 상태를 남긴다.

## 로그 위치

- Electron 시작 로그: `C:\Users\p\AppData\Roaming\AI Shift Scheduler\logs\startup.log`
- SQLite 데이터: `C:\Users\p\AppData\Roaming\AI Shift Scheduler\data\workscheduler.db`
- 설치 경로: `C:\Users\p\AppData\Local\Programs\AI Shift Scheduler`

## 설치본 검증 결과

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| NSIS 설치 | PASS | `AI Shift Scheduler Setup 0.1.0.exe /S` 실행 |
| 설치본 실행 | PASS | 설치 경로 exe 실행 후 main window 생성 |
| FastAPI 자동 시작 | PASS | `/api/health` 응답 `ok` |
| 데이터 재실행 유지 | PASS | 재실행 후 팀 2개 유지 |
| 재설치 후 데이터 유지 | PASS | 재설치 후 팀 2개, 2026-11 스케줄 30일 유지 |
| 종료 후 프로세스 정리 | PASS | 창 종료 후 `AI Shift Scheduler`, `workscheduler-api` 잔여 프로세스 없음 |

최종 설치본 smoke 결과:

```json
{
  "Health": "ok",
  "TeamCount": 2,
  "TeamNames": "검사실 A, C. 15명 조기 야간조기",
  "ScheduleDays": 30,
  "FirstDayAssignments": 15,
  "Remaining": "none"
}
```

## Codex CLI 실호출

| 항목 | 결과 |
| --- | --- |
| 설치 상태 | PASS, `codex doctor`에서 CLI 및 ChatGPT auth 확인 |
| 실제 모델 호출 | PASS |
| JSON 응답 수신 | PASS |
| 기존 timeout 원인 | `--output-schema` strict schema 오류로 확인 |
| 남은 주의 | Linear MCP 인증 경고가 stderr에 남지만 Codex 응답 자체는 성공 |

성공 호출 요약:

- elapsed: 7.85초
- returncode: 0
- output file bytes: 202
- payload: `schema_version`, `team_id`, `year`, `month`, `hard`, `soft`, `unsupported` 포함

## Claude Code

- 결과: BLOCKED
- 사유: 현재 환경에서 `claude` 명령이 설치되어 있지 않다.
- 프로그램 영향: Claude Code 미설치는 전체 프로그램 실행 실패 원인이 아니다.
- 설치 안내: 앱의 에이전트 상태/설치 안내 동선으로 공식 문서 링크를 열 수 있다.

## 월간 달력 UI 검증

실제 Electron 설치/실행 화면에서 2026년 11월 15명 가상 팀 스케줄을 표시했다.

- 7열 달력: PASS
- 날짜별 전체 직원 수 표시: PASS, 각 날짜 `15명`
- 주간/야간/조기/휴무 그룹 및 인원 표시: PASS
- 날짜 칸 내부 스크롤: PASS
- 직원 이름 누락 없음: PASS, API 및 Excel 검증 기준
- 캡처 파일: `artifacts/phase6/screenshots/phase6_1_calendar_electron_loaded.png`

## 회귀 테스트

| 테스트 | 결과 |
| --- | --- |
| Backend pytest | PASS, 14 passed, 2 warnings |
| Frontend typecheck | PASS |
| Frontend production build | PASS, Electron dist 과정에서 실행 |
| PyInstaller backend exe | PASS |
| Electron NSIS build | PASS |
| OR-Tools A-F | PASS |
| Excel openpyxl 재오픈 검증 | PASS |

Phase 6 A-F 결과:

- A: SUCCEEDED, FEASIBLE, 30.05초
- B: SUCCEEDED, OPTIMAL, 0.04초
- C: SUCCEEDED, OPTIMAL, 4.11초
- D: SUCCEEDED, OPTIMAL, 10.05초
- E: SUCCEEDED, OPTIMAL, 0.04초
- F: INFEASIBLE, 0.01초, 충돌 감지 정상

## 남은 BLOCKED 항목

- Claude Code live 호출은 로컬 미설치로 BLOCKED이다.
- Codex doctor에서 선택 MCP 서버(Linear) 인증 경고가 표시된다. Codex 모델 호출은 성공했으며, 이 경고는 현재 근무표 생성 흐름을 막지 않았다.
