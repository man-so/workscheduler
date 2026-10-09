"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  approveSetupPatch,
  createCoverageRequirement,
  createEmployee,
  createShiftType,
  createTeam,
  createWorkRule,
  createLeaveType,
  cancelGeneration,
  cloneScheduleVersion,
  confirmMonthlySchedule,
  generateSchedule,
  getScheduleExportUrl,
  getScheduleVersion,
  getGenerationRun,
  getActiveSetupSession,
  getHealth,
  getMonthlySchedule,
  getSetupSummary,
  listScheduleVersions,
  listTeams,
  sendSetupMessage,
  updateScheduleAssignment,
  validateMonthlySchedule,
  type GenerationRun,
  type CalendarAssignment,
  type CalendarDay,
  type MonthlySchedule,
  type ScheduleVersion,
  type ScheduleValidation,
  type LeaveType,
  type SetupSession,
  type SetupSummary,
  type ShiftType,
  type Team
} from "@/lib/api";

type LoadState = "loading" | "ready" | "error";

const dayOptions = [
  { label: "평일", value: "[\"MON\",\"TUE\",\"WED\",\"THU\",\"FRI\"]" },
  { label: "주말", value: "[\"SAT\",\"SUN\"]" },
  { label: "매일", value: "[\"MON\",\"TUE\",\"WED\",\"THU\",\"FRI\",\"SAT\",\"SUN\"]" }
];

export default function Home() {
  const [state, setState] = useState<LoadState>("loading");
  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [summary, setSummary] = useState<SetupSummary | null>(null);
  const [session, setSession] = useState<SetupSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chatMessage, setChatMessage] = useState("");
  const [teamName, setTeamName] = useState("검사실 A");
  const [employeeName, setEmployeeName] = useState("");
  const [shiftForm, setShiftForm] = useState({ code: "DAY", name: "주간", category: "DAY", start: "09:00", end: "18:00" });
  const [coverageForm, setCoverageForm] = useState({ shiftTypeId: "", days: dayOptions[0].value, count: "1" });
  const [ruleForm, setRuleForm] = useState({ minRestHours: "11", maxConsecutive: "5", nightOff: true });
  const [leaveTypeForm, setLeaveTypeForm] = useState({ code: "CUSTOM_OFF", name: "사용자 정의 휴무", color: "#f3f4f6" });
  const [generation, setGeneration] = useState<GenerationRun | null>(null);
  const [calendar, setCalendar] = useState<MonthlySchedule | null>(null);
  const [selectedDay, setSelectedDay] = useState<CalendarDay | null>(null);
  const [validation, setValidation] = useState<ScheduleValidation | null>(null);
  const [versions, setVersions] = useState<ScheduleVersion[]>([]);
  const [approveSoftIssues, setApproveSoftIssues] = useState(false);
  const [generationMonth, setGenerationMonth] = useState({ year: 2026, month: 11 });
  const [agentId, setAgentId] = useState<"codex" | "claude">("codex");

  const selectedTeam = useMemo(() => teams.find((team) => team.id === selectedTeamId) ?? null, [selectedTeamId, teams]);

  async function refresh(teamId = selectedTeamId) {
    if (!teamId) return;
    const [nextSummary, nextSession] = await Promise.all([getSetupSummary(teamId), getActiveSetupSession(teamId)]);
    setSummary(nextSummary);
    setSession(nextSession);
  }

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        await getHealth();
        let nextTeams = await listTeams();
        if (nextTeams.length === 0) {
          const created = await createTeam(teamName);
          nextTeams = [created];
        }
        if (!active) return;
        setTeams(nextTeams);
        setSelectedTeamId(nextTeams[0].id);
        const [nextSummary, nextSession] = await Promise.all([
          getSetupSummary(nextTeams[0].id),
          getActiveSetupSession(nextTeams[0].id)
        ]);
        if (!active) return;
        setSummary(nextSummary);
        setSession(nextSession);
        setState("ready");
      } catch {
        if (!active) return;
        setState("error");
        setError("백엔드 API에 연결할 수 없습니다.");
      }
    }

    load();
    return () => {
      active = false;
    };
  }, []);

  async function handleCreateTeam(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const team = await createTeam(teamName);
    const nextTeams = await listTeams();
    setTeams(nextTeams);
    setSelectedTeamId(team.id);
    await refresh(team.id);
  }

  async function handleSelectTeam(teamId: number) {
    setSelectedTeamId(teamId);
    setCalendar(null);
    setSelectedDay(null);
    setValidation(null);
    setVersions([]);
    await refresh(teamId);
  }

  async function handleCreateEmployee(event: FormEvent) {
    event.preventDefault();
    if (!selectedTeamId || !employeeName.trim()) return;
    await createEmployee(selectedTeamId, employeeName.trim());
    setEmployeeName("");
    await refresh();
  }

  async function handleCreateShift(event: FormEvent) {
    event.preventDefault();
    if (!selectedTeamId) return;
    const endsNextDay = shiftForm.end <= shiftForm.start;
    await createShiftType(selectedTeamId, {
      code: shiftForm.code,
      name: shiftForm.name,
      category: shiftForm.category,
      start_time: `${shiftForm.start}:00`,
      end_time: `${shiftForm.end}:00`,
      ends_next_day: endsNextDay,
      break_minutes: shiftForm.category.includes("DAY") ? 60 : 0,
      paid_minutes: 480,
      is_work: true
    });
    await refresh();
  }

  async function handleCreateCoverage(event: FormEvent) {
    event.preventDefault();
    if (!selectedTeamId || !coverageForm.shiftTypeId) return;
    const count = Number(coverageForm.count);
    await createCoverageRequirement(selectedTeamId, {
      name: "기본 필요 인원",
      shift_type_id: Number(coverageForm.shiftTypeId),
      days_of_week_json: coverageForm.days,
      min_count: count,
      target_count: count,
      max_count: count,
      priority: 100,
      qualification_requirements_json: null,
      is_active: true
    });
    await refresh();
  }

  async function handleCreateRule(event: FormEvent) {
    event.preventDefault();
    if (!selectedTeamId) return;
    await createWorkRule(selectedTeamId, {
      name: "기본 근무규칙",
      min_rest_minutes: Number(ruleForm.minRestHours) * 60,
      max_consecutive_work_days: Number(ruleForm.maxConsecutive),
      night_requires_next_day_off: ruleForm.nightOff
    });
    await refresh();
  }

  async function handleSendMessage(event: FormEvent) {
    event.preventDefault();
    if (!selectedTeamId || !session || !chatMessage.trim()) return;
    const nextSession = await sendSetupMessage(selectedTeamId, session.id, chatMessage.trim());
    setSession(nextSession);
    setChatMessage("");
  }

  async function handleApprove() {
    if (!selectedTeamId || !session) return;
    const result = await approveSetupPatch(selectedTeamId, session.id);
    setSummary(result.summary);
    await refresh();
  }

  async function handleGenerate(event: FormEvent) {
    event.preventDefault();
    if (!selectedTeamId) return;
    setError(null);
    setCalendar(null);
    setSelectedDay(null);
    setValidation(null);
    setVersions([]);
    try {
      let next = await generateSchedule(selectedTeamId, { ...generationMonth, agent_id: agentId, timeout_seconds: 120 });
      setGeneration(next);
      for (let attempt = 0; attempt < 180 && ["SUCCEEDED", "FAILED", "INFEASIBLE", "CANCELED"].indexOf(next.status) === -1; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        next = await getGenerationRun(selectedTeamId, next.id);
        setGeneration(next);
      }
      if (next.status === "SUCCEEDED") {
        const nextCalendar = await getMonthlySchedule(selectedTeamId, generationMonth.year, generationMonth.month);
        setCalendar(nextCalendar);
        setValidation(await validateMonthlySchedule(selectedTeamId, generationMonth.year, generationMonth.month));
        setVersions(await listScheduleVersions(selectedTeamId, generationMonth.year, generationMonth.month));
      } else if (next.status === "INFEASIBLE") {
        const conflicts = Array.isArray(next.result?.conflicts) ? next.result.conflicts.join(" ") : "Hard constraint 충돌을 확인하세요.";
        setError(`근무표를 생성하지 못했습니다. ${conflicts}`);
      } else if (next.status === "FAILED") {
        const unsupported = Array.isArray(next.result?.unsupported) ? next.result.unsupported.join(" ") : "";
        setError((next.error_message ?? unsupported) || "에이전트 실행에 실패했습니다.");
      }
    } catch {
      setError("근무표 생성 API에 연결할 수 없습니다.");
    }
  }

  async function handleLoadSchedule() {
    if (!selectedTeamId) return;
    setError(null);
    setSelectedDay(null);
    try {
      const nextCalendar = await getMonthlySchedule(selectedTeamId, generationMonth.year, generationMonth.month);
      setCalendar(nextCalendar);
      setValidation(await validateMonthlySchedule(selectedTeamId, generationMonth.year, generationMonth.month));
      setVersions(await listScheduleVersions(selectedTeamId, generationMonth.year, generationMonth.month));
    } catch {
      setError("저장된 근무표를 찾을 수 없습니다.");
    }
  }

  async function handleViewVersion(versionId: number) {
    if (!selectedTeamId) return;
    setError(null);
    const nextCalendar = await getScheduleVersion(selectedTeamId, generationMonth.year, generationMonth.month, versionId);
    setCalendar(nextCalendar);
    setSelectedDay(null);
  }

  async function handleCloneVersion(versionId: number) {
    if (!selectedTeamId) return;
    setError(null);
    await cloneScheduleVersion(selectedTeamId, generationMonth.year, generationMonth.month, versionId);
    await handleLoadSchedule();
  }

  async function handleConfirmSchedule() {
    if (!selectedTeamId) return;
    setError(null);
    try {
      await confirmMonthlySchedule(selectedTeamId, generationMonth.year, generationMonth.month, approveSoftIssues);
      await handleLoadSchedule();
    } catch {
      setError("확정할 수 없습니다. Hard Constraint 오류가 있거나 Soft Constraint 승인 표시가 필요합니다.");
    }
  }

  function handleExportExcel() {
    if (!selectedTeamId) return;
    window.location.href = getScheduleExportUrl(selectedTeamId, generationMonth.year, generationMonth.month);
  }

  async function handleCancelGeneration() {
    if (!selectedTeamId || !generation) return;
    const next = await cancelGeneration(selectedTeamId, generation.id);
    setGeneration(next);
  }

  async function handleCreateLeaveType(event: FormEvent) {
    event.preventDefault();
    if (!selectedTeamId || !leaveTypeForm.code.trim() || !leaveTypeForm.name.trim()) return;
    await createLeaveType(selectedTeamId, {
      code: leaveTypeForm.code.trim().toUpperCase(),
      name: leaveTypeForm.name.trim(),
      color: leaveTypeForm.color,
      is_paid: true,
      requires_origin: false,
      allows_split: false,
      sort_order: 200,
      is_active: true
    });
    setLeaveTypeForm({ code: "CUSTOM_OFF", name: "사용자 정의 휴무", color: "#f3f4f6" });
    await refresh();
  }

  async function handleAssignmentChange(assignment: CalendarAssignment, value: string) {
    if (!selectedTeamId || !calendar || !selectedDay) return;
    const isLeaveType = value.startsWith("LEAVE_TYPE:");
    const leaveTypeId = isLeaveType ? Number(value.replace("LEAVE_TYPE:", "")) : null;
    const leaveType = summary?.leave_types.find((item) => item.id === leaveTypeId) ?? null;
    let originDate: string | null = null;
    if (leaveType?.requires_origin) {
      originDate = window.prompt("대체휴무 발생 근무일을 YYYY-MM-DD 형식으로 입력하세요.", assignment.comp_origin_work_date ?? "")?.trim() || null;
      if (!originDate) return;
    }
    const isOff = isLeaveType || value === "OFF" || value === "LEAVE" || value === "OTHER";
    const status = isOff ? value : "WORK";
    const shiftTypeId = isOff ? null : Number(value);
    const nextCalendar = await updateScheduleAssignment(selectedTeamId, calendar.year, calendar.month, {
      employee_id: assignment.employee_id,
      local_date: selectedDay.local_date,
      status: isLeaveType ? (leaveType?.code === "ANNUAL" || leaveType?.code === "SPECIAL" || leaveType?.code === "COMPENSATORY" ? "LEAVE" : "OFF") : status as "WORK" | "OFF" | "LEAVE" | "OTHER",
      shift_type_id: shiftTypeId,
      leave_type_id: leaveTypeId,
      comp_origin_work_date: originDate,
      comp_amount_minutes: leaveType?.requires_origin ? 480 : null,
      comp_approval_status: leaveType?.requires_origin ? "APPROVED" : null,
      change_reason: "calendar manual edit"
    });
    setCalendar(nextCalendar);
    setSelectedDay(nextCalendar.days.find((day) => day.local_date === selectedDay.local_date) ?? null);
    setValidation(await validateMonthlySchedule(selectedTeamId, calendar.year, calendar.month));
    setVersions(await listScheduleVersions(selectedTeamId, calendar.year, calendar.month));
  }

  const shiftTypes: ShiftType[] = summary?.shift_types ?? [];
  const activeVersion = calendar ? versions.find((version) => version.id === calendar.version_id) : null;
  const canEditCalendar = Boolean(calendar && calendar.status === "DRAFT" && (activeVersion?.is_active ?? true));

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-5 text-slate-950 md:px-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <header className="flex flex-col gap-3 border-b border-slate-200 pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm font-semibold text-emerald-700">Phase 5</p>
            <h1 className="text-3xl font-semibold">AI 근무표 생성 및 확정</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              왼쪽에서 설정 상태와 직접 입력 폼을 관리하고, 오른쪽 챗봇에서 누락된 항목만 질문받아 변경사항을 승인합니다.
            </p>
          </div>
          <div className="flex flex-col gap-2 text-sm text-slate-600">
            <label>
              팀
              <select className="mt-1 block min-w-48 rounded border border-slate-300 bg-white px-2 py-2 text-sm text-slate-950" value={selectedTeamId ?? ""} onChange={(event) => handleSelectTeam(Number(event.target.value))}>
                {teams.map((team) => (
                  <option key={team.id} value={team.id}>{team.name}</option>
                ))}
              </select>
            </label>
            <div>상태 <span className="font-semibold text-slate-950">{state}</span></div>
          </div>
        </header>

        {error ? <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
          <section className="space-y-5">
            <div className="rounded border border-slate-200 bg-white p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-lg font-semibold">팀 설정 현황</h2>
                  <p className="text-sm text-slate-500">{selectedTeam?.name ?? "팀 없음"}</p>
                </div>
                <div className="text-3xl font-semibold">{summary?.completion_percent ?? 0}%</div>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-4">
                <Metric label="직원" value={summary?.employees.length ?? 0} />
                <Metric label="근무유형" value={summary?.shift_types.length ?? 0} />
                <Metric label="필요 인원" value={summary?.coverage_requirements.length ?? 0} />
                <Metric label="규칙" value={summary?.work_rules.length ?? 0} />
              </div>
              <StatusList title="누락 항목" items={summary?.missing_fields ?? []} empty="필수 누락 항목 없음" />
              <StatusList title="충돌 항목" items={summary?.conflicts ?? []} empty="충돌 없음" tone="red" />
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <Panel title="팀">
                <form onSubmit={handleCreateTeam} className="flex gap-2">
                  <input className="min-w-0 flex-1 rounded border border-slate-300 px-3 py-2 text-sm" value={teamName} onChange={(event) => setTeamName(event.target.value)} />
                  <button className="rounded bg-slate-950 px-3 py-2 text-sm font-semibold text-white">추가</button>
                </form>
              </Panel>

              <Panel title="직원">
                <form onSubmit={handleCreateEmployee} className="flex gap-2">
                  <input className="min-w-0 flex-1 rounded border border-slate-300 px-3 py-2 text-sm" placeholder="직원 이름" value={employeeName} onChange={(event) => setEmployeeName(event.target.value)} />
                  <button className="rounded bg-slate-950 px-3 py-2 text-sm font-semibold text-white">추가</button>
                </form>
                <ItemList items={(summary?.employees ?? []).map((employee) => `${employee.display_name} (${employee.employee_no})`)} />
              </Panel>

              <Panel title="근무유형">
                <form onSubmit={handleCreateShift} className="grid gap-2 sm:grid-cols-2">
                  <input className="rounded border border-slate-300 px-3 py-2 text-sm" value={shiftForm.name} onChange={(event) => setShiftForm({ ...shiftForm, name: event.target.value })} />
                  <select className="rounded border border-slate-300 px-3 py-2 text-sm" value={shiftForm.category} onChange={(event) => setShiftForm({ ...shiftForm, category: event.target.value, code: event.target.value })}>
                    <option value="DAY">주간</option>
                    <option value="EARLY_DAY">아침 조기</option>
                    <option value="NIGHT">야간</option>
                    <option value="EARLY_NIGHT">야간 조기</option>
                  </select>
                  <input type="time" className="rounded border border-slate-300 px-3 py-2 text-sm" value={shiftForm.start} onChange={(event) => setShiftForm({ ...shiftForm, start: event.target.value })} />
                  <input type="time" className="rounded border border-slate-300 px-3 py-2 text-sm" value={shiftForm.end} onChange={(event) => setShiftForm({ ...shiftForm, end: event.target.value })} />
                  <button className="rounded bg-slate-950 px-3 py-2 text-sm font-semibold text-white sm:col-span-2">저장</button>
                </form>
                <ItemList items={shiftTypes.map((shift) => `${shift.name} ${shift.start_time?.slice(0, 5)}-${shift.end_time?.slice(0, 5)}${shift.ends_next_day ? " 익일" : ""}`)} />
              </Panel>

              <Panel title="필요 인원">
                <form onSubmit={handleCreateCoverage} className="grid gap-2 sm:grid-cols-3">
                  <select className="rounded border border-slate-300 px-3 py-2 text-sm" value={coverageForm.shiftTypeId} onChange={(event) => setCoverageForm({ ...coverageForm, shiftTypeId: event.target.value })}>
                    <option value="">근무유형</option>
                    {shiftTypes.map((shift) => (
                      <option key={shift.id} value={shift.id}>{shift.name}</option>
                    ))}
                  </select>
                  <select className="rounded border border-slate-300 px-3 py-2 text-sm" value={coverageForm.days} onChange={(event) => setCoverageForm({ ...coverageForm, days: event.target.value })}>
                    {dayOptions.map((option) => (
                      <option key={option.label} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  <input type="number" min="0" className="rounded border border-slate-300 px-3 py-2 text-sm" value={coverageForm.count} onChange={(event) => setCoverageForm({ ...coverageForm, count: event.target.value })} />
                  <button className="rounded bg-slate-950 px-3 py-2 text-sm font-semibold text-white sm:col-span-3">저장</button>
                </form>
              </Panel>

              <Panel title="근무규칙">
                <form onSubmit={handleCreateRule} className="grid gap-2 sm:grid-cols-3">
                  <input type="number" min="0" className="rounded border border-slate-300 px-3 py-2 text-sm" value={ruleForm.minRestHours} onChange={(event) => setRuleForm({ ...ruleForm, minRestHours: event.target.value })} />
                  <input type="number" min="1" className="rounded border border-slate-300 px-3 py-2 text-sm" value={ruleForm.maxConsecutive} onChange={(event) => setRuleForm({ ...ruleForm, maxConsecutive: event.target.value })} />
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={ruleForm.nightOff} onChange={(event) => setRuleForm({ ...ruleForm, nightOff: event.target.checked })} />
                    야간 후 휴무
                  </label>
                  <button className="rounded bg-slate-950 px-3 py-2 text-sm font-semibold text-white sm:col-span-3">저장</button>
                </form>
              </Panel>

              <Panel title="휴무유형">
                <form onSubmit={handleCreateLeaveType} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                  <input className="rounded border border-slate-300 px-3 py-2 text-sm" placeholder="코드" value={leaveTypeForm.code} onChange={(event) => setLeaveTypeForm({ ...leaveTypeForm, code: event.target.value })} />
                  <input className="rounded border border-slate-300 px-3 py-2 text-sm" placeholder="휴무유형명" value={leaveTypeForm.name} onChange={(event) => setLeaveTypeForm({ ...leaveTypeForm, name: event.target.value })} />
                  <input type="color" className="h-10 rounded border border-slate-300 px-1 py-1" value={leaveTypeForm.color} onChange={(event) => setLeaveTypeForm({ ...leaveTypeForm, color: event.target.value })} />
                  <button className="rounded bg-slate-950 px-3 py-2 text-sm font-semibold text-white sm:col-span-3">추가</button>
                </form>
                <ItemList items={(summary?.leave_types ?? []).map((leaveType) => `${leaveType.name}${leaveType.requires_origin ? " · 발생근무 연결" : ""}`)} />
              </Panel>
            </div>
          </section>

          <aside className="flex min-h-[680px] flex-col rounded border border-slate-200 bg-white">
            <div className="border-b border-slate-200 p-4">
              <h2 className="text-lg font-semibold">설정 챗봇</h2>
              <p className="mt-1 text-sm text-slate-500">규칙 기반 질문이 우선이며, 변경사항은 승인 전까지 저장되지 않습니다.</p>
            </div>
            <div className="space-y-3 border-b border-slate-200 p-4">
              {(session?.questions ?? []).map((question) => (
                <div key={question.id} className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">
                  <div className="font-semibold">{question.label}</div>
                  <div className="mt-1 text-slate-700">{question.question}</div>
                </div>
              ))}
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
              {(session?.messages ?? []).map((message, index) => (
                <div key={`${message.role}-${index}`} className={message.role === "user" ? "ml-8 rounded bg-slate-950 p-3 text-sm text-white" : "mr-8 rounded bg-slate-100 p-3 text-sm text-slate-800"}>
                  {message.content}
                </div>
              ))}
              {(session?.proposed_changes ?? []).length > 0 ? (
                <div className="rounded border border-emerald-200 bg-emerald-50 p-3">
                  <h3 className="text-sm font-semibold">변경 미리보기</h3>
                  <div className="mt-2 space-y-2 text-xs">
                    {session?.proposed_changes.map((change, index) => (
                      <pre key={index} className="overflow-x-auto rounded bg-white p-2">{JSON.stringify(change.after, null, 2)}</pre>
                    ))}
                  </div>
                  <button onClick={handleApprove} className="mt-3 w-full rounded bg-emerald-700 px-3 py-2 text-sm font-semibold text-white">승인 후 저장</button>
                </div>
              ) : null}
            </div>
            <form onSubmit={handleSendMessage} className="border-t border-slate-200 p-4">
              <textarea className="h-28 w-full resize-none rounded border border-slate-300 px-3 py-2 text-sm" placeholder="예: 직원은 김하나, 이둘. 주간 09:00-18:00, 야간 22:00-06:00. 최소 휴식 11시간, 연속근무 5일." value={chatMessage} onChange={(event) => setChatMessage(event.target.value)} />
              <button className="mt-2 w-full rounded bg-slate-950 px-3 py-2 text-sm font-semibold text-white">미리보기 생성</button>
            </form>
          </aside>
        </div>

        <section className="rounded border border-slate-200 bg-white p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 className="text-lg font-semibold">에이전트 → CP-SAT 근무표</h2>
              <p className="mt-1 text-sm text-slate-500">승인된 설정만 에이전트에 전달하고, 계산과 검증은 로컬에서 수행합니다.</p>
            </div>
            <form onSubmit={handleGenerate} className="flex flex-wrap items-end gap-2">
              <label className="text-xs text-slate-500">연도<input type="number" min="2020" max="2200" className="mt-1 block w-24 rounded border border-slate-300 px-2 py-2 text-sm text-slate-950" value={generationMonth.year} onChange={(event) => setGenerationMonth({ ...generationMonth, year: Number(event.target.value) })} /></label>
              <label className="text-xs text-slate-500">월<input type="number" min="1" max="12" className="mt-1 block w-16 rounded border border-slate-300 px-2 py-2 text-sm text-slate-950" value={generationMonth.month} onChange={(event) => setGenerationMonth({ ...generationMonth, month: Number(event.target.value) })} /></label>
              <label className="text-xs text-slate-500">에이전트<select className="mt-1 block rounded border border-slate-300 px-2 py-2 text-sm text-slate-950" value={agentId} onChange={(event) => setAgentId(event.target.value as "codex" | "claude")}><option value="codex">Codex CLI</option><option value="claude">Claude Code</option></select></label>
              <button className="rounded bg-emerald-700 px-3 py-2 text-sm font-semibold text-white">근무표 생성</button>
              <button type="button" onClick={handleLoadSchedule} className="rounded border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">불러오기</button>
              {generation && ["QUEUED", "RUNNING", "SOLVING"].includes(generation.status) ? <button type="button" onClick={handleCancelGeneration} className="rounded border border-red-300 px-3 py-2 text-sm font-semibold text-red-700">취소</button> : null}
            </form>
          </div>
          {generation ? <p className="mt-3 text-sm text-slate-600">실행 #{generation.id} · {generation.status} · {generation.error_message ?? ""}</p> : null}
          {validation ? (
            <div className={`mt-3 rounded border p-3 text-sm ${validation.ok ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
              검증 {validation.ok ? "통과" : "확인 필요"} · 이슈 {validation.issue_count}건
              {validation.issues.length > 0 ? <span className="ml-2">{validation.issues.slice(0, 2).map((issue) => issue.message).join(" / ")}</span> : null}
            </div>
          ) : null}
          {calendar ? (
            <div className="mt-3 flex flex-col gap-3 rounded border border-slate-200 bg-slate-50 p-3 md:flex-row md:items-center md:justify-between">
              <div className="text-sm text-slate-700">
                현재 버전 <span className="font-semibold">v{calendar.version_no}</span> · {calendar.status}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={approveSoftIssues} onChange={(event) => setApproveSoftIssues(event.target.checked)} />
                  Soft 이슈 확인
                </label>
                <button type="button" onClick={handleConfirmSchedule} className="rounded bg-slate-950 px-3 py-2 text-sm font-semibold text-white">확정</button>
                <button type="button" onClick={handleExportExcel} className="rounded border border-emerald-300 px-3 py-2 text-sm font-semibold text-emerald-700">Excel 다운로드</button>
              </div>
            </div>
          ) : null}
          {versions.length > 0 ? (
            <div className="mt-3 rounded border border-slate-200 bg-white p-3">
              <h3 className="text-sm font-semibold">버전 이력</h3>
              <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {versions.map((version) => (
                  <div key={version.id} className="rounded border border-slate-200 p-2 text-sm">
                    <div className="font-semibold">v{version.version_no} · {version.status}{version.is_active ? " · active" : ""}</div>
                    <div className="mt-1 text-xs text-slate-500">수정 {version.modified_at ? new Date(version.modified_at).toLocaleString() : "-"}</div>
                    <div className="mt-2 flex gap-2">
                      <button type="button" onClick={() => handleViewVersion(version.id)} className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700">보기</button>
                      <button type="button" onClick={() => handleCloneVersion(version.id)} className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700">DRAFT 복제</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {calendar ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
              <MonthlyCalendar calendar={calendar} selectedDate={selectedDay?.local_date ?? null} onSelectDay={setSelectedDay} />
              <DayDetailPanel day={selectedDay} shiftTypes={shiftTypes} leaveTypes={summary?.leave_types ?? []} editable={canEditCalendar} onChangeAssignment={handleAssignmentChange} />
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}

function MonthlyCalendar({ calendar, selectedDate, onSelectDay }: { calendar: MonthlySchedule; selectedDate: string | null; onSelectDay: (day: CalendarDay) => void }) {
  const firstDay = new Date(calendar.year, calendar.month - 1, 1).getDay();
  const cells = [...Array(firstDay).fill(null), ...calendar.days];
  const groupOrder = ["DAY", "EARLY_DAY", "NIGHT", "EARLY_NIGHT", "OTHER", "ANNUAL", "COMPENSATORY", "REGULAR", "SPECIAL", "UNSPECIFIED", "LEAVE", "OFF"];
  return (
    <div className="mt-5 overflow-x-auto rounded border border-slate-200">
      <div className="min-w-[980px]">
        <div className="grid grid-cols-7 border-b border-slate-200 bg-slate-50 text-center text-xs font-semibold text-slate-600">
          {["일", "월", "화", "수", "목", "금", "토"].map((day) => <div key={day} className="p-2">{day}</div>)}
        </div>
        <div className="grid grid-cols-7">
          {cells.map((day, index) => day ? (
            <button key={day.local_date} type="button" onClick={() => onSelectDay(day)} className={`min-h-44 border-b border-r border-slate-200 p-2 text-left align-top transition ${selectedDate === day.local_date ? "bg-emerald-50 ring-2 ring-inset ring-emerald-500" : "bg-white hover:bg-slate-50"}`}>
              <div className="text-xs font-semibold text-slate-500">{day.local_date.slice(8, 10)}일 · {day.assignments.length}명</div>
              <div className="mt-2 max-h-36 space-y-2 overflow-y-auto">
                {(Object.entries(day.groups) as [string, CalendarAssignment[]][]).sort(([left], [right]) => groupRank(left, groupOrder) - groupRank(right, groupOrder)).map(([group, assignments]) => (
                  <div key={group}>
                    <div className="text-[11px] font-semibold text-slate-500">{groupLabel(group)} ({assignments.length})</div>
                    <div className="text-xs leading-5 text-slate-800">{assignments.map(assignmentDisplayName).join(", ")}</div>
                  </div>
                ))}
              </div>
            </button>
          ) : <div key={`blank-${index}`} className="min-h-44 border-b border-r border-slate-200 bg-slate-50" />)}
        </div>
      </div>
    </div>
  );
}

function DayDetailPanel({ day, shiftTypes, leaveTypes, editable, onChangeAssignment }: { day: CalendarDay | null; shiftTypes: ShiftType[]; leaveTypes: LeaveType[]; editable: boolean; onChangeAssignment: (assignment: CalendarAssignment, value: string) => void }) {
  if (!day) {
    return (
      <aside className="mt-5 rounded border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
        날짜를 선택하면 직원별 배정을 확인하고 수정할 수 있습니다.
      </aside>
    );
  }
  return (
    <aside className="mt-5 rounded border border-slate-200 bg-white p-4">
      <div className="border-b border-slate-200 pb-3">
        <h3 className="text-base font-semibold">{day.local_date}</h3>
        <p className="mt-1 text-sm text-slate-500">{editable ? "변경 즉시 저장되고 월간표 검증이 다시 실행됩니다." : "확정 또는 과거 버전은 직접 수정할 수 없습니다."}</p>
      </div>
      <div className="mt-3 max-h-[520px] space-y-2 overflow-y-auto">
        {day.assignments.map((assignment) => (
          <div key={assignment.employee_id} className="grid grid-cols-[minmax(84px,1fr)_minmax(140px,1.3fr)] items-center gap-2 rounded border border-slate-200 p-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">{assignment.employee_name}</div>
              <div className="text-xs text-slate-500">{assignment.shift_type_name ?? assignment.leave_label ?? statusLabel(assignment.status)}</div>
              {assignment.comp_validation_status === "WARN" ? <div className="mt-1 text-xs text-amber-700">{assignment.comp_validation_message}</div> : null}
            </div>
            <select disabled={!editable} className="min-w-0 rounded border border-slate-300 px-2 py-2 text-sm disabled:bg-slate-100" value={assignment.status === "WORK" && assignment.shift_type_id ? String(assignment.shift_type_id) : assignment.leave_type_id ? `LEAVE_TYPE:${assignment.leave_type_id}` : assignment.status} onChange={(event) => onChangeAssignment(assignment, event.target.value)}>
              <option value="OFF">휴무</option>
              {leaveTypes.map((leaveType) => (
                <option key={leaveType.id} value={`LEAVE_TYPE:${leaveType.id}`}>{leaveType.name}</option>
              ))}
              <option value="OTHER">기타</option>
              {shiftTypes.filter((shift) => shift.is_work).map((shift) => (
                <option key={shift.id} value={shift.id}>{shift.name}</option>
              ))}
            </select>
          </div>
        ))}
      </div>
    </aside>
  );
}

function groupLabel(value: string) {
  const labels: Record<string, string> = {
    DAY: "주간",
    EARLY_DAY: "조기",
    NIGHT: "야간",
    EARLY_NIGHT: "야간 조기",
    REGULAR: "정기휴무",
    ANNUAL: "연차",
    COMPENSATORY: "대체휴무",
    SPECIAL: "특별휴무",
    UNSPECIFIED: "유형 미지정",
    OFF: "휴무",
    LEAVE: "연차",
    OTHER: "기타"
  };
  return labels[value] ?? value;
}

function assignmentDisplayName(assignment: CalendarAssignment) {
  if (assignment.status === "WORK") return assignment.employee_name;
  return `${assignment.employee_name} · ${assignment.leave_label ?? statusLabel(assignment.status)}`;
}

function groupRank(value: string, order: string[]) {
  const index = order.indexOf(value);
  return index === -1 ? order.length : index;
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    WORK: "근무",
    OFF: "휴무",
    LEAVE: "연차",
    OTHER: "기타"
  };
  return labels[value] ?? value;
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-slate-200 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function ItemList({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="mt-3 text-sm text-slate-500">아직 없음</p>;
  return (
    <ul className="mt-3 space-y-1 text-sm text-slate-700">
      {items.map((item) => (
        <li key={item} className="rounded bg-slate-50 px-2 py-1">{item}</li>
      ))}
    </ul>
  );
}

function StatusList({ title, items, empty, tone = "amber" }: { title: string; items: string[]; empty: string; tone?: "amber" | "red" }) {
  const color = tone === "red" ? "text-red-700" : "text-amber-700";
  return (
    <div className="mt-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">{empty}</p>
      ) : (
        <ul className={`mt-1 space-y-1 text-sm ${color}`}>
          {items.map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
    </div>
  );
}
