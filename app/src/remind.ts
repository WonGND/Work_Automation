// 미입력 알림 (0.5.7)
//  - 매 근무일 아침(8시 이후 첫 확인): 바로 전 근무일에 시간이 없는 사람에게 🔔
//  - 그 주 첫 근무일: 지난주 미입력 요약을 팀장 · 마스터(전체) · PL(자기 파트)에게
//  - 웹 기준 시작일(web_start) 이전 날짜는 보지 않음 · 휴가 · 휴직 · 입사 전 · 퇴사 후는 personStats 가 뺌
import { q, getSetting, setSetting, notify } from "./db";
import { ctx, personStats, today, addDays, isWorkday, dow } from "./calc";

const DN = ["일", "월", "화", "수", "목", "금", "토"];
const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}(${DN[dow(d)]})`;

export function missReminder(force = false) {
  const t = today(), c = ctx();
  const R = { daily: 0, weekly: 0, day: "", week: "" };
  if (!isWorkday(c, t)) return R;
  if (!force && new Date().getHours() < 8) return R;
  const hs = getSetting("hstart", "2026-10-12"), ws = getSetting("web_start", "2026-11-16");
  const start = ws > hs ? ws : hs;
  const users = q("SELECT id, name, part, role FROM users WHERE active=1 AND role<>'lead' AND (IFNULL(left_on,'')='' OR left_on>=?) ORDER BY ord,id", t) as any[];
  // 1) 전 근무일 미입력 → 본인
  if (force || getSetting("miss_daily", "") !== t) {
    let d = addDays(t, -1); while (!isWorkday(c, d)) d = addDays(d, -1);
    if (d >= start) {
      R.day = d;
      for (const u of users) if (personStats(c, u.id, d, d).missing > 0) { notify(u.id, "미입력", `${md(d)} 시간이 입력되지 않았습니다 → 내 업무에서 '◀ 이전 주'로 가서 넣어 주세요`, "#/me"); R.daily++; }
    }
    setSetting("miss_daily", t);
  }
  // 2) 그 주 첫 근무일: 지난주 요약 → 팀장 · 마스터 · PL
  const mon = addDays(t, -((dow(t) + 6) % 7));
  let first = mon; while (!isWorkday(c, first)) first = addDays(first, 1);
  if (t === first && (force || getSetting("miss_week", "") !== mon)) {
    const lm = addDays(mon, -7), le = addDays(mon, -1), from = lm < start ? start : lm;
    if (from <= le) {
      R.week = `${from} ~ ${le}`;
      const miss = users.map(u => ({ u, n: personStats(c, u.id, from, le).missing })).filter(x => x.n > 0);
      const line = (l: typeof miss) => l.map(x => `${x.u.name.split(" ")[0]} ${x.n}일`).join(" · ");
      if (miss.length) {
        const admins = (q("SELECT id FROM users WHERE active=1 AND role IN ('lead','master') AND (IFNULL(left_on,'')='' OR left_on>=?)", t) as any[]).map(x => x.id);
        notify(admins, "미입력", `지난주(${md(from)}~${md(le)}) 미입력: ${line(miss)}`, "#/dash"); R.weekly += admins.length;
        for (const pl of users.filter(u => u.role === "pl")) {
          const mine = miss.filter(x => x.u.part === pl.part && x.u.id !== pl.id);
          if (mine.length) { notify(pl.id, "미입력", `지난주(${md(from)}~${md(le)}) ${pl.part} 미입력: ${line(mine)}`, "#/people"); R.weekly++; }
        }
      }
    }
    setSetting("miss_week", mon);
  }
  return R;
}
