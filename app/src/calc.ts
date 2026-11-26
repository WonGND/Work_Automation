// 계산: 근무 시간율 · 업무 로드 · 판정 · 일정 상태 (엑셀 v1.7.8 규칙과 같음)
import { q, q1, getSetting } from "./db";

export const DAY = 86400000;
export function ymd(d: Date) { return d.toISOString().slice(0, 10); }
export function parseD(s: string) { return new Date(s + "T00:00:00Z"); }
export function addDays(s: string, n: number) { return ymd(new Date(parseD(s).getTime() + n * DAY)); }
export function dow(s: string) { return parseD(s).getUTCDay(); } // 0 = 일

export function today(): string {
  const fix = getSetting("today_fix", "");
  if (/^\d{4}-\d{2}-\d{2}$/.test(fix)) return fix;
  const n = new Date();
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
}
export function num(k: string, def: number) { const v = parseFloat(getSetting(k, "")); return isNaN(v) ? def : v; }

export function periodRange(mode: string, base: string, from?: string, to?: string): [string, string] {
  if (mode === "custom" && from && to) return [from, to];
  if (mode === "month") { const y = base.slice(0, 4), m = base.slice(5, 7); const last = new Date(Date.UTC(+y, +m, 0)).getUTCDate(); return [`${y}-${m}-01`, `${y}-${m}-${String(last).padStart(2, "0")}`]; }
  if (mode === "year") { const y = base.slice(0, 4); return [`${y}-01-01`, `${y}-12-31`]; }
  const w = (dow(base) + 6) % 7; const mon = addDays(base, -w); return [mon, addDays(mon, 6)]; // 주간: 월~일
}

type Ctx = { grades: Map<string, number>; other: number; models: Map<number, any>; holidays: Set<string>; stagePct: number[] };
export function ctx(): Ctx {
  const grades = new Map<string, number>();
  for (const g of q("SELECT name,pct FROM grades")) grades.set(g.name, g.pct ?? 0);
  const models = new Map<number, any>();
  for (const m of q("SELECT * FROM models")) models.set(m.id, m);
  const holidays = new Set<string>(q("SELECT date FROM holidays").map((h: any) => h.date));
  const sp = JSON.parse(getSetting("stage_pct", "[0.1,0.3,0.5,0.7,0.9,1]"));
  return { grades, other: num("other_pct", 0), models, holidays, stagePct: sp };
}

// v1.7.8 배율 규칙 (단계 우선): 양산 → 양산 · 선행검토 → 선행검토 · 등급표에 모델 파트 이름이 있으면 그 파트 · 그 외 등급
export function weightOf(c: Ctx, modelId: number | null): number {
  if (!modelId) return c.other;
  const m = c.models.get(modelId); if (!m) return c.other;
  let key = m.grade;
  if (m.phase === "양산") key = "양산";
  else if (m.phase === "선행검토") key = "선행검토";
  else if (c.grades.has(m.part)) key = m.part;
  return c.grades.has(key) ? (c.grades.get(key) || 0) : c.other;
}

// 0.8.0: 한 칸의 시간을 모델별로 — 나눈 기록이 있으면 그대로, 없고 다중 모델이면 똑같이, 아니면 업무 모델 하나
export function taskModels(t: any): number[] { try { const a = JSON.parse(t.models || "[]"); return Array.isArray(a) ? a.map(Number).filter(Boolean) : []; } catch { return []; } }
export function taskParts(t: any, splits?: { model_id: number; hours: number }[]): [number | null, number][] {
  if (splits && splits.length) return splits.map(x => [x.model_id || null, x.hours]);
  const ms = taskModels(t);
  if (ms.length > 1) return ms.map(m => [m, t.hours / ms.length]);
  return [[t.model_id || null, t.hours]];
}
export function splitMap(userId: number, from: string, to: string) {
  const m = new Map<string, { model_id: number; hours: number; text: string }[]>();
  for (const x of q(`SELECT s.* FROM task_splits s JOIN tasks t ON t.id=s.task_id WHERE t.user_id=? AND s.date>=? AND s.date<=? ORDER BY s.hours DESC`, userId, from, to)) {
    const k = x.task_id + "|" + x.date; if (!m.has(k)) m.set(k, []); m.get(k)!.push(x);
  }
  return m;
}

export function isWorkday(c: Ctx, s: string) { const w = dow(s); return w !== 0 && w !== 6 && !c.holidays.has(s); }

function leaveDays(userId: number) {
  return q("SELECT start, end FROM leaves WHERE user_id=?", userId) as { start: string; end: string | null }[];
}
function onLeave(lv: { start: string; end: string | null }[], s: string) {
  return lv.some(l => s >= l.start && (!l.end || s < l.end)); // 복직일 = 다시 출근하는 첫날
}

export type PersonStats = {
  user_id: number; from: string; to: string; base: number; input: number; weighted: number;
  rate: number | null; load: number | null; judge: string; action: string; rateCls: string; loadCls: string;
  missing: number; leaveH: number; workdays: number; models: Record<string, number>; daily: Record<string, number>;
  tasksOpen: number; tasksLate: number; issuesOpen: number; issuesLate: number; issuesSoon: number; issuesDone: number; maxWeek: number;
};

export function personStats(c: Ctx, userId: number, from: string, to: string): PersonStats {
  const hstart = getSetting("hstart", "2026-10-12");
  const t = today();
  const uu = q1("SELECT joined, left_on FROM users WHERE id=?", userId) || {};
  let s = from < hstart ? hstart : from;
  let e = to > t ? t : to;
  if (uu.joined && uu.joined > s) s = uu.joined;      // 입사 전 날짜는 기준 시간 · 미입력에서 뺌
  if (uu.left_on && uu.left_on < e) e = uu.left_on;   // 퇴사 다음 날부터도 뺌
  const dayH = num("day_hours", 8), earlyH = num("early_hours", 2);
  const lv = leaveDays(userId);
  let workdays = 0; const wd = new Set<string>();
  if (s <= e) for (let d = s; d <= e; d = addDays(d, 1)) if (isWorkday(c, d) && !onLeave(lv, d)) { workdays++; wd.add(d); }
  const daily: Record<string, number> = {}; const models: Record<string, number> = {};
  let leaveH = 0, earlyDays = 0, input = 0, weighted = 0;
  const leaveDay = new Set<string>();
  const th = q(`SELECT t.id, t.kind, t.model_id, t.models, h.date, h.hours FROM task_hours h JOIN tasks t ON t.id=h.task_id
                WHERE t.user_id=? AND h.date>=? AND h.date<=?`, userId, s, e);
  const sp = splitMap(userId, s, e);
  for (const r of th) {
    if (r.kind === "휴가") { if (wd.has(r.date)) { leaveH += r.hours; leaveDay.add(r.date); } continue; }
    if (r.kind === "조퇴") { if (wd.has(r.date) && r.hours > 0) { earlyDays++; leaveDay.add(r.date); } continue; }
    input += r.hours;
    daily[r.date] = (daily[r.date] || 0) + r.hours;
    for (const [mid, h] of taskParts(r, sp.get(r.id + "|" + r.date))) {   // 0.8.0: 모델별로 나눈 시간 × 각 모델 배율
      weighted += h * weightOf(c, mid);
      const mn = mid ? (c.models.get(mid)?.name || "") : "공통·기타";
      models[mn] = (models[mn] || 0) + h;
    }
  }
  const il = q(`SELECT i.model_id, l.date, l.hours FROM issue_logs l JOIN issues i ON i.id=l.issue_id
                WHERE l.user_id=? AND l.date>=? AND l.date<=? AND l.hours>0`, userId, s, e);
  for (const r of il) {
    input += r.hours; weighted += r.hours * weightOf(c, r.model_id);
    daily[r.date] = (daily[r.date] || 0) + r.hours;
    const mn = r.model_id ? (c.models.get(r.model_id)?.name || "") : "공통·기타";
    models[mn] = (models[mn] || 0) + r.hours;
  }
  let base = workdays * dayH - leaveH - earlyDays * earlyH; if (base < 0) base = 0;
  let missing = 0; for (const d of wd) if (!(daily[d] > 0) && !leaveDay.has(d)) missing++;
  const rate = base > 0 ? input / base : null, load = base > 0 ? weighted / base : null;
  const over = num("over", 1.2), fit = num("fit", 1), lhi = num("lhi", 0.7), llo = num("llo", 0.35);
  const rateCls = rate === null ? "" : rate > over ? "과부하" : rate >= fit ? "적정" : "여유";
  const loadCls = load === null ? "" : rateCls === "여유" ? "-" : load >= lhi ? "높음" : load < llo ? "낮음" : "중간";
  const onLeaveAll = rate === null && s <= e && lv.some(l => l.start <= e && (!l.end || l.end > s));
  let judge = rate === null ? (onLeaveAll ? "휴직" : "기준 시간 없음") : "", action = "";
  if (rate !== null) {
    const j = JSON.parse(getSetting("judge", "[]")).find((x: any) => x.rate === rateCls && x.load === loadCls);
    judge = j?.text || `${rateCls}${loadCls && loadCls !== "-" ? " · 로드 " + loadCls : ""}`; action = j?.action || "";
  }
  // 주별 최대 투입 (주 52h 초과 확인용)
  const wk: Record<string, number> = {};
  for (const [d, h] of Object.entries(daily)) { const w = addDays(d, -((dow(d) + 6) % 7)); wk[w] = (wk[w] || 0) + h; }
  const maxWeek = Math.max(0, ...Object.values(wk));
  // 일정 상태
  const soon = num("soon_days", 7);
  const tk = q(`SELECT target, done, progress FROM tasks WHERE user_id=? AND kind='통상' AND hidden=0`, userId);
  let tasksOpen = 0, tasksLate = 0;
  for (const r of tk) { const dn = !!r.done || r.progress === 100; if (!dn) { tasksOpen++; if (r.target && r.target < t) tasksLate++; } }
  const is = q(`SELECT i.target, i.done, i.stage FROM issues i JOIN issue_members m ON m.issue_id=i.id WHERE m.user_id=? AND i.hidden=0`, userId);
  let issuesOpen = 0, issuesLate = 0, issuesSoon = 0, issuesDone = 0;
  for (const r of is) {
    const dn = !!r.done || r.stage === 6;
    if (dn) { issuesDone++; continue; }
    issuesOpen++;
    if (r.target && r.target < t) issuesLate++;
    else if (r.target && r.target <= addDays(t, soon)) issuesSoon++;
  }
  return { user_id: userId, from: s, to: e, base, input, weighted, rate, load, judge, action, rateCls, loadCls, missing, leaveH,
    workdays, models, daily, tasksOpen, tasksLate, issuesOpen, issuesLate, issuesSoon, issuesDone, maxWeek };
}

export function scheduleState(target: string | null, done: string | null, finished: boolean) {
  const t = today();
  if (finished) {
    if (done && target && done > target) return { cls: "done-late", text: `완료+${Math.round((parseD(done).getTime() - parseD(target).getTime()) / DAY)}일` };
    return { cls: "done", text: "완료" };
  }
  if (!target) return { cls: "", text: "" };
  const diff = Math.round((parseD(target).getTime() - parseD(t).getTime()) / DAY);
  if (diff < 0) return { cls: "late", text: `D+${-diff} 지연` };
  if (diff === 0) return { cls: "soon", text: "D-Day" };
  return { cls: diff <= num("soon_days", 7) ? "soon" : "", text: `D-${diff}` };
}
