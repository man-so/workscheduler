"use client";

import { useEffect, useMemo, useState } from "react";
import { getHealth, listEmployees, listShiftTypes, listTeams, type Employee, type HealthResponse, type ShiftType, type Team } from "@/lib/api";

type LoadState = "loading" | "ready" | "error";

export default function Home() {
  const [state, setState] = useState<LoadState>("loading");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [shiftTypes, setShiftTypes] = useState<ShiftType[]>([]);
  const selectedTeam = teams[0] ?? null;

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const [healthResult, teamsResult] = await Promise.all([getHealth(), listTeams()]);
        if (!active) return;

        setHealth(healthResult);
        setTeams(teamsResult);

        if (teamsResult[0]) {
          const [employeeResult, shiftTypeResult] = await Promise.all([
            listEmployees(teamsResult[0].id),
            listShiftTypes(teamsResult[0].id)
          ]);
          if (!active) return;
          setEmployees(employeeResult);
          setShiftTypes(shiftTypeResult);
        }

        setState("ready");
      } catch {
        if (active) setState("error");
      }
    }

    load();
    return () => {
      active = false;
    };
  }, []);

  const readiness = useMemo(
    () => [
      { label: "팀", value: teams.length },
      { label: "직원", value: employees.length },
      { label: "근무유형", value: shiftTypes.length }
    ],
    [employees.length, shiftTypes.length, teams.length]
  );

  return (
    <main className="min-h-screen px-6 py-8 text-slate-950">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-2 border-b border-slate-200 pb-5">
          <p className="text-sm font-semibold text-emerald-700">Phase 1</p>
          <h1 className="text-3xl font-semibold">AI Shift Scheduler</h1>
          <p className="max-w-3xl text-sm leading-6 text-slate-600">
            팀, 직원, 근무유형, 규칙, 휴무신청, 근무배정 데이터를 관리하기 위한 기본 작업 화면입니다. AI 챗봇과 자동 배정 엔진은 아직 연결하지 않았습니다.
          </p>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          {readiness.map((item) => (
            <div key={item.label} className="rounded border border-slate-200 bg-white p-4">
              <div className="text-sm text-slate-500">{item.label}</div>
              <div className="mt-2 text-3xl font-semibold">{item.value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-5 lg:grid-cols-[1fr_2fr]">
          <div className="rounded border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-semibold">API 연결</h2>
            <div className="mt-4 space-y-2 text-sm">
              <p>
                상태: <span className="font-semibold">{state}</span>
              </p>
              <p>
                백엔드: <span className="font-semibold">{health?.service ?? "확인 중"}</span>
              </p>
              <p>
                선택 팀: <span className="font-semibold">{selectedTeam?.name ?? "없음"}</span>
              </p>
            </div>
          </div>

          <div className="rounded border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-semibold">월간 달력 준비 상태</h2>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left">
                    <th className="py-2 pr-3">데이터</th>
                    <th className="py-2 pr-3">Phase 1 상태</th>
                    <th className="py-2 pr-3">다음 단계</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  <tr>
                    <td className="py-3 pr-3 font-medium">직원</td>
                    <td className="py-3 pr-3">API 및 모델 구현</td>
                    <td className="py-3 pr-3 text-slate-600">달력 날짜별 전 직원 표시</td>
                  </tr>
                  <tr>
                    <td className="py-3 pr-3 font-medium">근무유형</td>
                    <td className="py-3 pr-3">주간, 조기, 야간 등 확장 가능</td>
                    <td className="py-3 pr-3 text-slate-600">근무유형별 그룹 UI</td>
                  </tr>
                  <tr>
                    <td className="py-3 pr-3 font-medium">배정</td>
                    <td className="py-3 pr-3">수동 데이터 저장 API 구현</td>
                    <td className="py-3 pr-3 text-slate-600">OR-Tools 생성 결과 연결</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {state === "error" ? (
          <p className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            백엔드 API에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요.
          </p>
        ) : null}
      </div>
    </main>
  );
}
