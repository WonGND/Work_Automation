// API: 로그인 · 권한 · 업무 · 시간 · 이슈 · 업무로드 · 기준정보 · 관리
import { db, q, q1, run, getSetting, setSetting, audit, backup, listBackups, BACKUP_DIR, notify, DATA_DIR } from "./db";
import { enc, randCode, tempPw } from "./secret";
import { sendMail, mailReady } from "./mail";
import { ctx, personStats, periodRange, today, addDays, scheduleState, num, isWorkday, dow, weightOf } from "./calc";
import { ensureFixedRows, importWork } from "./seed";
import { join } from "node:path";
import { existsSync, readdirSync, unlinkSync } from "node:fs";

export class HttpError extends Error { constructor(public status: number, msg: string) { super(msg); } }
const err = (s: number, m: string) => { throw new HttpError(s, m); };
const NOPERM = "입력 권한이 없습니다";

export type User = { id: number; login: string; name: string; title: string; part: string; role: string; must_change: number; active: number };
const isAdmin = (u: User) => u.role === "lead" || u.role === "master";
const hasSheet = (u: User) => u.role !== "lead";   // 팀장 계정은 개인 업무 화면 없음
const isPL = (u: User) => u.role === "pl";
const plPart = (u: User) => (isPL(u) ? u.part : "");

function json(data: any, status = 200) { return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } }); }
const isDate = (s: any) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);
const dOrNull = (s: any) => (s === "" || s == null ? null : isDate(s) ? s : err(400, `날짜 형식이 아닙니다: ${s} (예: 2026-11-04)`));
const str = (s: any, max = 2000) => (s == null ? "" : String(s).slice(0, max).trim());

// ── 접속 방식 (HTTPS · 프록시) : server.ts 에서 설정 ──
export const NET = { trustProxy: false, httpsOnly: false };
export function isHttps(req: Request) {
  if (new URL(req.url).protocol === "https:") return true;
  return NET.trustProxy && (req.headers.get("x-forwarded-proto") || "").split(",")[0].trim() === "https";
}
// 0.3.0 이전에 만든 계정표 파일 (처음 비밀번호가 적힌 파일)
export function acctFiles(): string[] { try { return readdirSync(DATA_DIR).filter(f => /계정표.*\.txt$/.test(f)); } catch { return []; } }

// ── 세션 ──
function newToken() { const a = new Uint8Array(24); crypto.getRandomValues(a); return Buffer.from(a).toString("hex"); }
function cookieOf(req: Request, k: string) { const c = req.headers.get("cookie") || ""; const m = c.match(new RegExp(`(?:^|; )${k}=([^;]+)`)); return m ? m[1] : ""; }
export function currentUser(req: Request): User | null {
  const t = cookieOf(req, "wl_sid"); if (!t) return null;
  const s = q1("SELECT user_id, expires FROM sessions WHERE token=?", t);
  if (!s || s.expires < new Date().toISOString()) return null;
  const u = q1<User>("SELECT id,login,name,title,part,role,must_change,active FROM users WHERE id=?", s.user_id);
  if (!u || !u.active) return null;
  run("UPDATE sessions SET expires=? WHERE token=?", new Date(Date.now() + 12 * 3600e3).toISOString(), t);
  return u;
}

// ── 공통 데이터 ──
function meta(u: User) {
  const users = q(`SELECT id,login,name,title,part,role,active,ord${isAdmin(u) ? ",email, (pw<>'') has_pw, must_change" : ""} FROM users ORDER BY ord,id`);
  return {
    user: u, today: today(),
    perms: { admin: isAdmin(u), sheet: hasSheet(u), pl: isPL(u), plPart: plPart(u), master: u.role === "master", std: isAdmin(u) || isPL(u), assign: isAdmin(u) || isPL(u) },
    acctFiles: isAdmin(u) ? acctFiles().length : 0,
    reqTargets: reqTargets(u).map((x: any) => ({ id: x.id, name: x.name, role: x.role, part: x.part })),
    myEmail: q1("SELECT email FROM users WHERE id=?", u.id)?.email || "", mailReady: mailReady(), mailDomain: getSetting("mail_domain", ""),
    notifUnread: q1("SELECT COUNT(*) n FROM notifs WHERE user_id=? AND read=0", u.id)?.n || 0,
    reqPending: q1("SELECT COUNT(*) n FROM requests WHERE to_id=? AND status='대기' AND hidden_to=0", u.id)?.n || 0,
    prefs: Object.fromEntries(q("SELECT key,value FROM user_prefs WHERE user_id=?", u.id).map((r: any) => [r.key, r.value])),
    users, models: q("SELECT * FROM models ORDER BY ord,id"), parts: q("SELECT name FROM parts ORDER BY ord").map((p: any) => p.name),
    grades: q("SELECT * FROM grades ORDER BY ord"), categories: q("SELECT * FROM categories ORDER BY ord"),
    stages: JSON.parse(getSetting("stage_names", "[]")), stagePct: JSON.parse(getSetting("stage_pct", "[]")),
    phases: JSON.parse(getSetting("phases", "[]")),
    settings: Object.fromEntries(q("SELECT key,value FROM settings").filter((r: any) => !["judge", "stage_pct", "stage_names", "phases"].includes(r.key) && !/^(smtp_|mail_from)/.test(r.key)).map((r: any) => [r.key, r.value])),
    judge: JSON.parse(getSetting("judge", "[]")),
  };
}

function canSeeUser(u: User, uid: number) { return u.id === uid || isAdmin(u); }
function partOfModel(modelId: number | null) { return modelId ? (q1("SELECT part FROM models WHERE id=?", modelId)?.part || "") : ""; }
function canManageIssue(u: User, iss: any) { return isAdmin(u) || (isPL(u) && partOfModel(iss.model_id) === u.part); }
function membersOf(issueId: number) { return q("SELECT m.*, u.name FROM issue_members m JOIN users u ON u.id=m.user_id WHERE issue_id=? ORDER BY role", issueId); }
function stageDone(i: any) { return !!i.done || i.stage === 6; }

function issueRow(i: any, c = ctx()) {
  const mem = membersOf(i.id);
  const m = i.model_id ? c.models.get(i.model_id) : null;
  const tot = q("SELECT user_id, SUM(hours) h, COUNT(CASE WHEN text<>'' THEN 1 END) n, MAX(CASE WHEN text<>'' THEN date END) last FROM issue_logs WHERE issue_id=? GROUP BY user_id", i.id);
  const st = scheduleState(i.target, i.done, stageDone(i));
  const plUsers = new Set(q("SELECT id FROM users WHERE role='pl'").map((x: any) => x.id));
  return { ...i, model: m?.name || "", part: m?.part || "", members: mem, hours: tot, sched: st,
    progress: (c.stagePct[(i.stage || 1) - 1] ?? 0),
    needDelay: st.cls === "late" && !str(i.delay_reason),
    plAssigned: mem.filter((x: any) => plUsers.has(x.user_id)).map((x: any) => x.name) };
}

// ── 업무 ──
function taskOut(t: any) {
  const h = q1("SELECT SUM(hours) s FROM task_hours WHERE task_id=?", t.id)?.s || 0;
  const fin = !!t.done || t.progress === 100;
  const by = t.assigned_by ? q1("SELECT name FROM users WHERE id=?", t.assigned_by)?.name || "" : "";
  const notes = q1("SELECT COUNT(*) n FROM task_notes WHERE task_id=? AND text<>''", t.id)?.n || 0;
  return { ...t, total: h, assigned_name: by, notes, sched: t.kind === "통상" ? scheduleState(t.target, t.done, fin) : { cls: "", text: "" } };
}
// 요청을 보낼 수 있는 사람: 마스터 · 팀장 · 우리 파트 PL (나 제외)
function reqTargets(me: User) {
  return q("SELECT * FROM users WHERE active=1 AND id<>? AND (role IN ('master','lead') OR (role='pl' AND part=?)) ORDER BY CASE role WHEN 'pl' THEN 1 WHEN 'master' THEN 2 ELSE 3 END, ord", me.id, me.part || "");
}
function reqOut(r: any) {
  return { ...r, from_name: q1("SELECT name FROM users WHERE id=?", r.from_id)?.name || "", to_name: q1("SELECT name FROM users WHERE id=?", r.to_id)?.name || "", to_role: q1("SELECT role FROM users WHERE id=?", r.to_id)?.role || "" };
}
export function setupNeeded() { return !q1("SELECT 1 FROM users WHERE active=1 AND role IN ('master','lead') AND pw<>''"); }
// 업무를 고칠 수 있는 사람: 본인 · 마스터 · 그 업무를 지정해 준 PL
function canEditTask(me: User, t: any) { return t.user_id === me.id || me.role === "master" || (t.assigned_by && t.assigned_by === me.id); }
// PL이 업무를 지정할 수 있는 사람: 우리 파트 (팀장 · 마스터는 모두)
function canAssignTo(me: User, u: any) { return u && u.active && u.role !== "lead" && (isAdmin(me) || (isPL(me) && u.part === me.part)); }
function checkTaskInput(b: any, isNew: boolean) {
  const out: any = {};
  if (isNew || "kind" in b) { if (!["통상", "기타", "휴가", "조퇴"].includes(b.kind)) err(400, "구분은 통상 · 기타 · 휴가 · 조퇴 중에서 고릅니다 (이슈는 PL이 등록)"); out.kind = b.kind; }
  if (isNew || "title" in b) { out.title = str(b.title, 200); if (!out.title) err(400, "업무명을 입력하세요"); }
  if ("model_id" in b) { out.model_id = b.model_id ? Number(b.model_id) : null; if (out.model_id && !q1("SELECT id FROM models WHERE id=?", out.model_id)) err(400, "모델 목록에 없는 모델입니다"); }
  if ("progress" in b) { const p = b.progress === "" || b.progress == null ? null : Number(b.progress); if (p !== null && (!(p >= 0 && p <= 100) || p % 10 !== 0)) err(400, "진행률은 0~100% (10% 단위)"); out.progress = p; }
  for (const k of ["start", "target", "done"]) if (k in b) out[k] = dOrNull(b[k]);
  if (out.start && out.target && out.target < out.start) err(400, "목표 마감일이 시작일보다 빠릅니다");
  if ("importance" in b) { if (!["", "상", "중", "하"].includes(b.importance || "")) err(400, "중요도는 상 · 중 · 하"); out.importance = b.importance || ""; }
  if ("category" in b) { out.category = str(b.category, 200); if (out.category && !q1("SELECT 1 FROM categories WHERE name=?", out.category)) err(400, "업무 분류 목록에 없는 값입니다"); }
  if ("note" in b) out.note = str(b.note, 2000);
  return out;
}

// ── 시간 ──
function checkHours(h: any) {
  const unit = num("unit", 0.5);
  if (h === "" || h == null) return 0;
  const v = Number(h);
  if (!isFinite(v) || v < 0 || v > 24) err(400, "시간은 0 ~ 24 사이 숫자입니다");
  if (Math.abs(v / unit - Math.round(v / unit)) > 1e-9) err(400, `시간은 ${unit}시간 단위로 넣습니다 (30분 = 0.5)`);
  return v;
}

function weekData(uid: number, from: string) {
  const c = ctx(); const days = Array.from({ length: 7 }, (_, k) => addDays(from, k)); const to = days[6];
  const t = today(); const hstart = getSetting("hstart", "2026-10-12");
  const tasks = q(`SELECT * FROM tasks WHERE user_id=? AND (hidden=0 OR id IN (SELECT task_id FROM task_hours WHERE date BETWEEN ? AND ?)) ORDER BY fixed DESC, ord, id`, uid, from, to);
  const rows: any[] = [];
  for (const tk of tasks) {
    const fin = !!tk.done || tk.progress === 100;
    const hrs = Object.fromEntries(q("SELECT date,hours FROM task_hours WHERE task_id=? AND date BETWEEN ? AND ?", tk.id, from, to).map((r: any) => [r.date, r.hours]));
    const has = Object.keys(hrs).length > 0;
    const started = !tk.start || tk.start <= to;
    if (!tk.fixed && !has && (tk.hidden || (fin && tk.done && tk.done < from) || !started)) continue;
    const texts = Object.fromEntries(q("SELECT date,text FROM task_notes WHERE task_id=? AND date BETWEEN ? AND ? AND text<>''", tk.id, from, to).map((r: any) => [r.date, r.text]));
    rows.push({ type: "task", id: tk.id, kind: tk.kind, title: tk.title, model: tk.model_id ? c.models.get(tk.model_id)?.name : "", fixed: tk.fixed, hidden: tk.hidden, done: fin, hours: hrs, texts,
      assigned: tk.assigned_by ? (q1("SELECT name FROM users WHERE id=?", tk.assigned_by)?.name || "") : "", progress: tk.progress });
  }
  const iss = q(`SELECT i.*, m.role FROM issues i JOIN issue_members m ON m.issue_id=i.id WHERE m.user_id=? ORDER BY i.no`, uid);
  const seen = new Set<number>();
  for (const i of iss) {
    seen.add(i.id);
    const logs = q("SELECT date,hours,text FROM issue_logs WHERE issue_id=? AND user_id=? AND date BETWEEN ? AND ?", i.id, uid, from, to);
    const fin = stageDone(i);
    if (!logs.length && (i.hidden || (fin && i.done && i.done < from))) continue;
    rows.push({ type: "issue", id: i.id, no: i.no, title: i.title, role: i.role, duty: q1("SELECT duty FROM issue_members WHERE issue_id=? AND user_id=?", i.id, uid)?.duty || "", model: i.model_id ? c.models.get(i.model_id)?.name : "", hidden: i.hidden, done: fin,
      hours: Object.fromEntries(logs.map((l: any) => [l.date, l.hours])), texts: Object.fromEntries(logs.filter((l: any) => l.text).map((l: any) => [l.date, l.text])) });
  }
  // 담당에서 빠졌지만 이번 주 기록이 있는 이슈 (기록 보존)
  for (const i of q(`SELECT DISTINCT i.* FROM issues i JOIN issue_logs l ON l.issue_id=i.id WHERE l.user_id=? AND l.date BETWEEN ? AND ?`, uid, from, to)) {
    if (seen.has(i.id)) continue;
    const logs = q("SELECT date,hours,text FROM issue_logs WHERE issue_id=? AND user_id=? AND date BETWEEN ? AND ?", i.id, uid, from, to);
    rows.push({ type: "issue", id: i.id, no: i.no, title: i.title, role: "담당 해제", released: true, model: i.model_id ? c.models.get(i.model_id)?.name : "", hidden: i.hidden, done: stageDone(i),
      hours: Object.fromEntries(logs.map((l: any) => [l.date, l.hours])), texts: Object.fromEntries(logs.filter((l: any) => l.text).map((l: any) => [l.date, l.text])) });
  }
  const lv = q("SELECT start,end FROM leaves WHERE user_id=?", uid);
  const dayInfo = days.map(d => ({ date: d, workday: isWorkday(c, d), holiday: q1("SELECT name FROM holidays WHERE date=?", d)?.name || "",
    leave: lv.some((l: any) => d >= l.start && (!l.end || d < l.end)), past: d <= t, beforeStart: d < hstart, today: d === t }));
  return { from, to, days: dayInfo, rows, dayHours: num("day_hours", 8), earlyHours: num("early_hours", 2), unit: num("unit", 0.5) };
}

// ── 이슈 번호 (다시 쓰지 않음) ──
function nextIssueNo() {
  const yy = today().slice(2, 4);
  const seq = getSetting("issue_seq", "");
  let n = seq.startsWith(yy + "-") ? parseInt(seq.slice(3), 10) : 0;
  const mx = q1("SELECT MAX(CAST(substr(no,4) AS INTEGER)) n FROM issues WHERE no LIKE ?", yy + "-%")?.n || 0;
  n = Math.max(n, mx) + 1;
  const no = `${yy}-${String(n).padStart(3, "0")}`;
  setSetting("issue_seq", no);
  return no;
}

function setMembers(issueId: number, members: any[], confirmPl = false) {
  if (!Array.isArray(members)) err(400, "담당자 형식 오류");
  const roles = new Set<string>(); const usersSeen = new Set<number>();
  for (const m of members) {
    if (!m.user_id) continue;
    if (!["정", "부1", "부2"].includes(m.role)) err(400, "담당은 정 · 부1 · 부2");
    if (roles.has(m.role)) err(400, `${m.role} 담당이 두 번 지정됐습니다`);
    const u = q1<User>("SELECT * FROM users WHERE id=?", Number(m.user_id)); if (!u || !u.active) err(400, "없는 사용자입니다");
    if (u!.role === "lead") err(400, `${u!.name}: 팀장 계정은 이슈 담당이 될 수 없습니다`);
    if (u!.role === "pl" && !confirmPl) err(409, `CONFIRM_PL:${m.role}이(가) PL입니다 (${u!.name}). 정말 입력하시겠습니까?`);
    if (usersSeen.has(u!.id)) err(400, `${u!.name} 이 두 번 지정됐습니다`);
    roles.add(m.role); usersSeen.add(u!.id);
  }
  if (members.some(m => m.user_id) && !roles.has("정")) err(400, "정 담당을 먼저 지정하세요");
  const old = q("SELECT * FROM issue_members WHERE issue_id=?", issueId);
  const iss = q1("SELECT no, title FROM issues WHERE id=?", issueId);
  run("DELETE FROM issue_members WHERE issue_id=?", issueId);
  for (const m of members) if (m.user_id) {
    const prev = old.find((o: any) => o.user_id === Number(m.user_id));
    const duty = "duty" in m ? str(m.duty, 500) : prev?.duty || "";
    run("INSERT INTO issue_members(issue_id,user_id,role,duty,category) VALUES(?,?,?,?,?)", issueId, Number(m.user_id), m.role, duty, "category" in m ? str(m.category, 200) : prev?.category || "");
    if (iss && (!prev || prev.role !== m.role)) notify(Number(m.user_id), "이슈", `이슈 ${m.role} 담당이 됐습니다: ${iss.no} ${iss.title}${duty ? ` · 할 일: ${duty.slice(0, 60)}` : ""}`, "#/myissues");
    else if (iss && prev && prev.duty !== duty) notify(Number(m.user_id), "이슈", `${iss.no} 할 일이 바뀌었습니다: ${duty.slice(0, 80) || "(비움)"}`, "#/myissues");
  }
  for (const o of old) if (iss && !members.some(m => Number(m.user_id) === o.user_id)) notify(o.user_id, "이슈", `${iss.no} ${iss.title} 담당에서 빠졌습니다`, "#/myissues");
}

// ── 업무로드 ──
function dashboard(from: string, to: string) {
  const c = ctx();
  const users = q("SELECT * FROM users WHERE active=1 AND role<>'lead' ORDER BY ord,id");
  const people = users.map((u: any) => ({ ...personStats(c, u.id, from, to), name: u.name, part: u.part, role: u.role }));
  const agg = (list: any[]) => {
    const base = list.reduce((a, p) => a + p.base, 0), input = list.reduce((a, p) => a + p.input, 0), w = list.reduce((a, p) => a + p.weighted, 0);
    return { n: list.length, base, input, weighted: w, rate: base > 0 ? input / base : null, load: base > 0 ? w / base : null,
      over: list.filter(p => p.rateCls === "과부하").length, fit: list.filter(p => p.rateCls === "적정").length, spare: list.filter(p => p.rateCls === "여유").length,
      high: list.filter(p => p.loadCls === "높음").length, w52: list.filter(p => p.maxWeek > 52).length,
      issuesOpen: 0, issuesLate: 0, cross: 0, models: 0 };
  };
  const parts = Array.from(new Set(users.map((u: any) => u.part))).filter(Boolean).map(pt => ({ part: pt, ...agg(people.filter(p => p.part === pt)) }));
  // 파트별 이슈 수 (모델의 파트 기준) · cross join (다른 파트 모델 시간)
  const iss = q("SELECT * FROM issues WHERE hidden=0");
  for (const pr of parts) {
    for (const i of iss) {
      if (partOfModel(i.model_id) !== pr.part || stageDone(i)) continue;
      pr.issuesOpen++; if (i.target && i.target < today()) pr.issuesLate++;
    }
    const mset = new Set<string>(); let cross = 0;
    for (const p of people.filter(p => p.part === pr.part)) for (const [mn, h] of Object.entries(p.models)) {
      if (!(h as number)) continue; mset.add(mn);
      const m = [...c.models.values()].find((x: any) => x.name === mn); if (m && m.part && m.part !== pr.part) cross++;
    }
    pr.models = [...mset].filter(x => x !== "공통·기타").length; pr.cross = cross;
  }
  const modelCols = [...c.models.values()].filter((m: any) => m.active).sort((a: any, b: any) => {
    const g = (m: any) => (["ES", "DV", "PD", "PV"].includes(m.phase) ? 0 : m.phase === "선행검토" ? 1 : m.phase === "양산" ? 2 : 3);
    return g(a) - g(b) || String(a.part).localeCompare(String(b.part)) || a.ord - b.ord;
  }).map((m: any) => ({ id: m.id, name: m.name, part: m.part, phase: m.phase, grade: m.grade, weight: weightLabel(c, m) }));
  return { from, to, today: today(), team: agg(people), parts, people, modelCols };
}
function weightLabel(c: any, m: any) { return weightOf(c, m.id); }

function issueSummary() {
  const c = ctx(); const t = today(); const soon = num("soon_days", 7);
  const all = q("SELECT * FROM issues WHERE hidden=0 ORDER BY no").map((i: any) => issueRow(i, c));
  const cnt = { open: 0, late: 0, soon: 0, done: 0, needDelay: 0 };
  for (const i of all) {
    if (stageDone(i)) { cnt.done++; continue; }
    cnt.open++; if (i.sched.cls === "late") cnt.late++; else if (i.target && i.target <= addDays(t, soon)) cnt.soon++;
    if (i.needDelay) cnt.needDelay++;
  }
  return { count: cnt, issues: all };
}

// ── 라우터 ──
export async function handle(req: Request, url: URL): Promise<Response> {
  const p = url.pathname, m = req.method;
  if (m !== "GET" && req.headers.get("x-req") !== "1") err(403, "잘못된 요청입니다");
  const body = m === "GET" ? {} : await req.json().catch(() => ({}));

  if (p === "/api/login" && m === "POST") {
    const login = str(body.login, 50); const u = q1("SELECT * FROM users WHERE login=?", login);
    if (!u || !u.active) { await Bun.sleep(400); err(401, "아이디 또는 비밀번호가 맞지 않습니다"); }
    if (u.locked_until && u.locked_until > new Date().toISOString()) err(429, "비밀번호를 여러 번 틀려 잠시 잠겼습니다. 1분 뒤 다시 시도하세요");
    if (!u.pw) { await Bun.sleep(400); err(403, "아직 비밀번호가 없는 계정입니다. 팀장 · 마스터에게 '비밀번호 초기화'를 요청해 처음 비밀번호를 받으세요."); }
    if (!(await Bun.password.verify(String(body.pw || ""), u.pw))) {
      const f = u.fails + 1;
      run("UPDATE users SET fails=?, locked_until=? WHERE id=?", f >= 5 ? 0 : f, f >= 5 ? new Date(Date.now() + 60e3).toISOString() : null, u.id);
      await Bun.sleep(400); err(401, "아이디 또는 비밀번호가 맞지 않습니다");
    }
    run("UPDATE users SET fails=0, locked_until=NULL WHERE id=?", u.id);
    const tok = newToken();
    run("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)", tok, u.id, new Date(Date.now() + 12 * 3600e3).toISOString());
    run("DELETE FROM sessions WHERE expires < ?", new Date().toISOString());
    audit(u.id, "로그인", u.login, "");
    const res = json({ ok: true, must_change: !!u.must_change });
    res.headers.append("set-cookie", `wl_sid=${tok}; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200${isHttps(req) ? "; Secure" : ""}`);
    return res;
  }
  // ── 처음 설정 (로그인 전): 비밀번호가 있는 관리자 계정이 하나도 없을 때만 ──
  if (p === "/api/setup" && m === "GET") return json({ needed: setupNeeded() });
  if (p === "/api/setup" && m === "POST") {
    if (!setupNeeded()) err(403, "이미 처음 설정을 마쳤습니다");
    const code = str(body.code, 20); const h = getSetting("setup_code_hash", "");
    if (!h || !(await Bun.password.verify(code, h))) { await Bun.sleep(800); err(403, "설정 코드가 맞지 않습니다 (프로그램을 실행한 창 · 로그에 나온 코드)"); }
    const u = q1("SELECT * FROM users WHERE login=? AND active=1 AND role IN ('master','lead')", str(body.login, 50));
    if (!u) err(400, "마스터 또는 팀장 계정의 아이디를 적으세요");
    const pw = String(body.pw || ""); if (pw.length < 8) err(400, "관리자 비밀번호는 8자 이상");
    run("UPDATE users SET pw=?, must_change=0, fails=0, locked_until=NULL WHERE id=?", await Bun.password.hash(pw), u.id);
    setSetting("setup_code_hash", ""); audit(u.id, "처음 설정", u.login, "");
    return json({ ok: true });
  }
  // ── 비밀번호 찾기 (로그인 전) ──
  if (p === "/api/reset/request" && m === "POST") {
    const login = str(body.login, 50), email = str(body.email, 120).toLowerCase();
    const generic = "아이디와 등록된 회사 메일이 맞으면 인증번호를 보냈습니다. 메일함(스팸함 포함)을 확인하세요. 10분 안에 입력합니다.";
    if (!mailReady()) err(503, "메일 보내기가 아직 설정되지 않았습니다. '관리자에게 초기화 요청'을 누르세요.");
    await Bun.sleep(300);
    const u = q1("SELECT * FROM users WHERE login=? AND active=1", login);
    if (!u || !u.email || u.email.toLowerCase() !== email) { audit(u?.id ?? null, "비밀번호 찾기 실패", login, { email }); return json({ ok: true, msg: generic }); }
    const recent = q1("SELECT created FROM pw_resets WHERE user_id=? ORDER BY id DESC LIMIT 1", u.id);
    if (recent && (Date.now() - new Date(recent.created.replace(" ", "T")).getTime()) < 60e3) err(429, "1분 뒤에 다시 요청하세요");
    const code = randCode(6);
    run("UPDATE pw_resets SET used=1 WHERE user_id=? AND used=0", u.id);
    run("INSERT INTO pw_resets(user_id,code_hash,expires) VALUES(?,?,?)", u.id, await Bun.password.hash(code), new Date(Date.now() + 10 * 60e3).toISOString());
    try { await sendMail(u.email, "[회로팀 업무관리] 비밀번호 인증번호", `${u.name} 님\n\n비밀번호를 새로 정하는 인증번호입니다.\n\n    ${code}\n\n10분 안에 업무관리 로그인 화면 > 비밀번호 찾기에 입력하세요.\n요청하지 않았다면 이 메일은 무시하고 팀장 · 마스터에게 알려 주세요.`); }
    catch (e: any) { audit(u.id, "인증 메일 실패", u.login, String(e?.message || e)); err(502, "메일을 보내지 못했습니다. '관리자에게 초기화 요청'을 누르세요."); }
    audit(u.id, "인증 메일 보냄", u.login, { email: u.email });
    return json({ ok: true, msg: generic });
  }
  if (p === "/api/reset/confirm" && m === "POST") {
    const login = str(body.login, 50), code = str(body.code, 10), pw = String(body.new || "");
    const u = q1("SELECT * FROM users WHERE login=? AND active=1", login);
    const r = u ? q1("SELECT * FROM pw_resets WHERE user_id=? AND used=0 ORDER BY id DESC LIMIT 1", u.id) : null;
    if (!u || !r || r.expires < new Date().toISOString() || r.tries >= 5) { await Bun.sleep(400); err(400, "인증번호가 없거나 시간이 지났습니다. 다시 받으세요."); }
    if (!(await Bun.password.verify(code, r.code_hash))) { run("UPDATE pw_resets SET tries=tries+1 WHERE id=?", r.id); await Bun.sleep(400); err(400, `인증번호가 맞지 않습니다 (남은 횟수 ${4 - r.tries})`); }
    if (pw.length < 6) err(400, "새 비밀번호는 6자 이상");
    run("UPDATE users SET pw=?, must_change=0, fails=0, locked_until=NULL WHERE id=?", await Bun.password.hash(pw), u.id);
    run("UPDATE pw_resets SET used=1 WHERE id=?", r.id); run("DELETE FROM sessions WHERE user_id=?", u.id);
    audit(u.id, "비밀번호 찾기로 변경", u.login, "");
    return json({ ok: true });
  }
  if (p === "/api/reset/askadmin" && m === "POST") {
    const login = str(body.login, 50); const u = q1("SELECT * FROM users WHERE login=? AND active=1", login);
    await Bun.sleep(300);
    if (u) {
      const last = getSetting("askadmin_" + u.id, "");
      if (!last || Date.now() - Number(last) > 10 * 60e3) {
        setSetting("askadmin_" + u.id, String(Date.now()));
        notify(q("SELECT id FROM users WHERE active=1 AND role IN ('master','lead')").map((x: any) => x.id), "계정", `${u.name} (${u.login}) 이(가) 비밀번호 초기화를 요청했습니다 → 관리 > 계정에서 초기화`, "#/admin");
        audit(u.id, "초기화 요청", u.login, "");
      }
    }
    return json({ ok: true, msg: "팀장 · 마스터에게 초기화 요청을 보냈습니다. 받은 처음 비밀번호로 로그인하세요." });
  }
  const u = currentUser(req);
  if (!u) err(401, "로그인이 필요합니다");
  const me = u!;
  if (p === "/api/logout" && m === "POST") {
    run("DELETE FROM sessions WHERE token=?", cookieOf(req, "wl_sid"));
    const res = json({ ok: true }); res.headers.append("set-cookie", `wl_sid=; Path=/; Max-Age=0${isHttps(req) ? "; Secure" : ""}`); return res;
  }
  if (p === "/api/password" && m === "POST") {
    const row = q1("SELECT pw FROM users WHERE id=?", me.id);
    if (!(await Bun.password.verify(String(body.old || ""), row.pw))) err(400, "지금 비밀번호가 맞지 않습니다");
    const nw = String(body.new || "");
    if (nw.length < 6) err(400, "새 비밀번호는 6자 이상");
    if (nw === String(body.old)) err(400, "지금과 다른 비밀번호를 쓰세요");
    run("UPDATE users SET pw=?, must_change=0 WHERE id=?", await Bun.password.hash(nw), me.id);
    audit(me.id, "비밀번호 변경", me.login, ""); return json({ ok: true });
  }
  if (me.must_change && p !== "/api/meta") err(403, "처음 로그인입니다. 비밀번호를 먼저 바꾸세요");
  if (p === "/api/meta") return json(meta(me));

  // 통계 (내 요약 · 사람별)
  if (p === "/api/stats" && m === "GET") {
    const uid = Number(url.searchParams.get("user") || me.id); if (!canSeeUser(me, uid)) err(403, "볼 수 없습니다");
    const [f, t] = periodRange(url.searchParams.get("mode") || "week", url.searchParams.get("base") || today(), url.searchParams.get("from") || "", url.searchParams.get("to") || "");
    return json(personStats(ctx(), uid, f, t));
  }

  // ── 업무 ──
  if (p === "/api/tasks" && m === "GET") {
    const uid = Number(url.searchParams.get("user") || me.id); if (!canSeeUser(me, uid)) err(403, "볼 수 없습니다");
    const hid = url.searchParams.get("hidden") === "1";
    return json(q(`SELECT * FROM tasks WHERE user_id=? ${hid ? "" : "AND hidden=0"} ORDER BY hidden, fixed, (done IS NOT NULL OR progress=100), ord, id`, uid).map(taskOut));
  }
  if (p === "/api/tasks" && m === "POST") {
    if (!hasSheet(me)) err(403, NOPERM);
    const v = checkTaskInput(body, true);
    const hrs: { date: string; hours: number; text: string }[] = [];
    for (const x of Array.isArray(body.hours) ? body.hours.slice(0, 62) : []) {
      const date = dOrNull(x?.date); if (!date) err(400, "시간을 넣은 줄에 날짜가 없습니다");
      if (date! < getSetting("hstart", "2026-10-12")) err(400, `시간 기록 시작일 이전 날짜입니다: ${date}`);
      if (date! > addDays(today(), 31)) err(400, `한 달 넘게 앞선 날짜에는 넣을 수 없습니다: ${date}`);
      const h = checkHours(x.hours); if (!h) continue;
      if (hrs.some(y => y.date === date)) err(400, `같은 날짜가 두 줄 있습니다: ${date}`);
      hrs.push({ date: date!, hours: h, text: str(x.text, 1000) });
    }
    db.exec("BEGIN IMMEDIATE");
    try {
    const r = run(`INSERT INTO tasks(user_id,kind,model_id,title,progress,start,target,done,importance,category,note,ord) VALUES(?,?,?,?,?,?,?,?,?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM tasks WHERE user_id=?))`,
      me.id, v.kind, v.model_id ?? null, v.title, v.kind === "통상" ? v.progress ?? 0 : null, v.start ?? null, v.target ?? null, v.done ?? null, v.importance ?? "", v.category ?? "", v.note ?? "", me.id);
    const tid = Number(r.lastInsertRowid);
    for (const x of hrs) {
      run("INSERT INTO task_hours(task_id,date,hours) VALUES(?,?,?)", tid, x.date, x.hours);
      if (x.text) run("INSERT INTO task_notes(task_id,date,text) VALUES(?,?,?)", tid, x.date, x.text);
    }
    audit(me.id, "업무 추가", `task ${tid}`, hrs.length ? { ...v, 시간: hrs.map(x => `${x.date} ${x.hours}h`).join(", ") } : v);
    db.exec("COMMIT");
    return json(taskOut(q1("SELECT * FROM tasks WHERE id=?", tid)));
    } catch (e) { try { db.exec("ROLLBACK"); } catch {} throw e; }
  }
  let mt = p.match(/^\/api\/tasks\/(\d+)(\/hide)?$/);
  if (mt) {
    const t = q1("SELECT * FROM tasks WHERE id=?", Number(mt[1])); if (!t) err(404, "없는 업무입니다");
    if (m === "GET") {
      if (!canSeeUser(me, t.user_id) && t.assigned_by !== me.id) err(403, "볼 수 없습니다");
      return json({ ...taskOut(t), notes_list: q("SELECT n.date, n.text, IFNULL(h.hours,0) hours FROM task_notes n LEFT JOIN task_hours h ON h.task_id=n.task_id AND h.date=n.date WHERE n.task_id=? AND n.text<>'' ORDER BY n.date DESC", t.id),
        hours_list: q("SELECT date, hours FROM task_hours WHERE task_id=? ORDER BY date DESC LIMIT 60", t.id), canEdit: canEditTask(me, t) });
    }
    if (!canEditTask(me, t)) err(403, "본인 업무만 고칠 수 있습니다");
    if (mt[2] && m === "POST") {
      if (t.fixed) err(400, "기본 행은 숨길 수 없습니다");
      run("UPDATE tasks SET hidden=?, updated=datetime('now','localtime') WHERE id=?", body.hidden ? 1 : 0, t.id);
      audit(me.id, body.hidden ? "업무 삭제(숨김)" : "업무 되살리기", `task ${t.id}`, { title: t.title });
      return json({ ok: true });
    }
    if (m === "PUT") {
      const v = checkTaskInput(body, false);
      if (t.fixed && (v.kind && v.kind !== t.kind)) err(400, "기본 행의 구분은 바꿀 수 없습니다");
      const keys = Object.keys(v); if (!keys.length) return json(taskOut(t));
      run(`UPDATE tasks SET ${keys.map(k => k + "=?").join(",")}, updated=datetime('now','localtime') WHERE id=?`, ...keys.map(k => v[k]), t.id);
      audit(me.id, "업무 수정", `task ${t.id}`, { before: Object.fromEntries(keys.map(k => [k, t[k]])), after: v });
      return json(taskOut(q1("SELECT * FROM tasks WHERE id=?", t.id)));
    }
  }

  // 업무 순서 (끌어서 옮기기)
  if (p === "/api/tasks/order" && m === "PUT") {
    const ids: number[] = (body.ids || []).map(Number);
    const own = new Set(q("SELECT id FROM tasks WHERE user_id=?", me.id).map((r: any) => r.id));
    if (!ids.length || ids.some(id => !own.has(id))) err(400, "본인 업무만 순서를 바꿀 수 있습니다");
    db.transaction(() => ids.forEach((id, k) => run("UPDATE tasks SET ord=? WHERE id=?", k + 1, id)))();
    return json({ ok: true });
  }
  // PL이 통상 업무 지정 (여러 명에게 한 번에) · 내가 지정한 업무 보기
  if (p === "/api/assign" && m === "POST") {
    if (!isAdmin(me) && !isPL(me)) err(403, "업무 지정은 PL · 팀장이 합니다");
    const ids: number[] = Array.from(new Set((body.user_ids || []).map(Number)));
    if (!ids.length) err(400, "받을 사람을 고르세요");
    const v = checkTaskInput({ ...body, kind: "통상" }, true);
    const grp = `${Date.now().toString(36)}-${me.id}`;
    const made: string[] = [];
    db.transaction(() => {
      for (const id of ids) {
        const u = q1("SELECT * FROM users WHERE id=?", id);
        if (!canAssignTo(me, u)) err(403, `${u?.name || id}: ${isPL(me) ? me.part + " 사람에게만" : ""} 지정할 수 있습니다`);
        run(`INSERT INTO tasks(user_id,kind,model_id,title,progress,start,target,done,importance,category,note,ord,assigned_by,assign_group) VALUES(?,?,?,?,0,?,?,NULL,?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM tasks WHERE user_id=?),?,?)`,
          id, "통상", v.model_id ?? null, v.title, v.start ?? null, v.target ?? null, v.importance ?? "", v.category ?? "", v.note ?? "", id, me.id, grp);
        made.push(u.name);
        if (id !== me.id) notify(id, "업무", `${me.name} 이(가) 업무를 지정했습니다: ${v.title}${v.target ? ` (목표 ${v.target})` : ""}`, "#/me");
      }
    })();
    audit(me.id, "업무 지정", v.title, { to: made, ...v });
    return json({ ok: true, to: made });
  }
  if (p === "/api/assign" && m === "GET") {
    if (!isAdmin(me) && !isPL(me)) err(403, "볼 수 없습니다");
    const rows = q(`SELECT t.*, u.name uname FROM tasks t JOIN users u ON u.id=t.user_id WHERE t.assigned_by=? ORDER BY t.id DESC`, me.id).map((t: any) => ({ ...taskOut(t), uname: t.uname }));
    return json(rows);
  }
  // 요청하기 (팀원 → 마스터 · PL · 팀장)
  if (p === "/api/requests" && m === "GET") {
    const box = url.searchParams.get("box") === "out" ? "out" : "in";
    const rows = box === "in" ? q("SELECT * FROM requests WHERE to_id=? AND hidden_to=0 ORDER BY status='완료', id DESC LIMIT 300", me.id)
      : q("SELECT * FROM requests WHERE from_id=? AND hidden_from=0 ORDER BY id DESC LIMIT 300", me.id);
    return json(rows.map(reqOut));
  }
  if (p === "/api/requests" && m === "POST") {
    const to = Number(body.to_id); const text = str(body.text, 2000);
    if (!reqTargets(me).some((x: any) => x.id === to)) err(403, "요청은 마스터 · 팀장 · 우리 파트 PL에게 보낼 수 있습니다");
    if (!text) err(400, "요청 내용을 적어 주세요");
    const r = run("INSERT INTO requests(from_id,to_id,text) VALUES(?,?,?)", me.id, to, text);
    audit(me.id, "요청 보냄", String(to), { text });
    notify(to, "요청", `${me.name} 의 요청: ${text.slice(0, 80)}`, "#/requests");
    return json(reqOut(q1("SELECT * FROM requests WHERE id=?", Number(r.lastInsertRowid))));
  }
  const mrq = p.match(/^\/api\/requests\/(\d+)$/);
  if (mrq && m === "PUT") {
    const r = q1("SELECT * FROM requests WHERE id=?", Number(mrq[1])); if (!r) err(404, "요청이 없습니다");
    if (r.to_id !== me.id && r.from_id !== me.id) err(403, "볼 수 없습니다");
    if ("hide" in body) { run(`UPDATE requests SET ${r.to_id === me.id ? "hidden_to" : "hidden_from"}=? WHERE id=?`, body.hide ? 1 : 0, r.id); return json({ ok: true }); }
    if (r.to_id !== me.id) err(403, "받은 사람만 처리합니다");
    const st = ["대기", "확인", "완료"].includes(body.status) ? body.status : r.status;
    run("UPDATE requests SET status=?, reply=?, updated=datetime('now','localtime') WHERE id=?", st, "reply" in body ? str(body.reply, 2000) : r.reply, r.id);
    audit(me.id, "요청 처리", String(r.id), { status: st, reply: body.reply });
    if (st !== r.status || (body.reply && body.reply !== r.reply)) { notify(r.from_id, "요청", `${me.name} 이(가) 요청을 '${st}'(으)로 처리했습니다${body.reply ? `: ${String(body.reply).slice(0, 60)}` : ""}`, "#/requests"); }
    return json(reqOut(q1("SELECT * FROM requests WHERE id=?", r.id)));
  }
  if (p === "/api/me/email" && m === "PUT") {
    const e = str(body.email, 120).toLowerCase();
    if (e && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)) err(400, "메일 주소 형식이 아닙니다");
    const dom = getSetting("mail_domain", "").toLowerCase().replace(/^@/, "");
    if (e && dom && !e.endsWith("@" + dom)) err(400, `회사 메일(@${dom})만 등록할 수 있습니다`);
    run("UPDATE users SET email=? WHERE id=?", e, me.id); audit(me.id, "메일 등록", me.login, { email: e });
    return json({ ok: true });
  }
  if (p === "/api/notifs" && m === "GET") {
    return json({ unread: q1("SELECT COUNT(*) n FROM notifs WHERE user_id=? AND read=0", me.id)?.n || 0, list: q("SELECT * FROM notifs WHERE user_id=? ORDER BY id DESC LIMIT 60", me.id) });
  }
  if (p === "/api/notifs/read" && m === "POST") {
    if (body.all) run("UPDATE notifs SET read=1 WHERE user_id=?", me.id); else run("UPDATE notifs SET read=1 WHERE user_id=? AND id=?", me.id, Number(body.id));
    return json({ ok: true });
  }
  if (p === "/api/prefs" && m === "PUT") {
    for (const [k, v] of Object.entries(body || {})) { if (String(k).length > 80) continue; if (v === null || v === "") run("DELETE FROM user_prefs WHERE user_id=? AND key=?", me.id, k); else run("INSERT INTO user_prefs(user_id,key,value) VALUES(?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", me.id, k, String(v).slice(0, 4000)); }
    return json({ ok: true });
  }

  // ── 주간 시간 ──
  if (p === "/api/week" && m === "GET") {
    const uid = Number(url.searchParams.get("user") || me.id); if (!canSeeUser(me, uid)) err(403, "볼 수 없습니다");
    let from = url.searchParams.get("from") || today(); if (!isDate(from)) err(400, "날짜 오류");
    from = addDays(from, -((dow(from) + 6) % 7));
    return json(weekData(uid, from));
  }
  if (p === "/api/hours" && m === "PUT") {
    const date = dOrNull(body.date); if (!date) err(400, "날짜가 없습니다");
    if (date! < getSetting("hstart", "2026-10-12")) err(400, "시간 기록 시작일 이전 날짜입니다");
    if (date! > addDays(today(), 31)) err(400, "한 달 넘게 앞선 날짜에는 넣을 수 없습니다");
    const h = checkHours(body.hours);
    if (body.type === "task") {
      const t = q1("SELECT * FROM tasks WHERE id=?", Number(body.id)); if (!t) err(404, "없는 업무입니다");
      if (t.user_id !== me.id && me.role !== "master") err(403, "본인 시간만 넣을 수 있습니다");
      const old = q1("SELECT hours FROM task_hours WHERE task_id=? AND date=?", t.id, date)?.hours ?? 0;
      if (h === 0) run("DELETE FROM task_hours WHERE task_id=? AND date=?", t.id, date);
      else run("INSERT INTO task_hours(task_id,date,hours) VALUES(?,?,?) ON CONFLICT(task_id,date) DO UPDATE SET hours=excluded.hours", t.id, date, h);
      if ("text" in body) {   // 그날 한 일 (통상 · 기타 업무)
        const txt = str(body.text, 1000); const was = q1("SELECT text FROM task_notes WHERE task_id=? AND date=?", t.id, date)?.text || "";
        if (!txt) run("DELETE FROM task_notes WHERE task_id=? AND date=?", t.id, date);
        else run("INSERT INTO task_notes(task_id,date,text) VALUES(?,?,?) ON CONFLICT(task_id,date) DO UPDATE SET text=excluded.text, updated=datetime('now','localtime')", t.id, date, txt);
        if (was !== txt) audit(me.id, "업무 기록", `task ${t.id} ${date}`, { from: was, to: txt });
      }
      return json({ ok: true });
    }
    if (body.type === "issue") {
      const iss = q1("SELECT * FROM issues WHERE id=?", Number(body.id)); if (!iss) err(404, "없는 이슈입니다");
      const uid = Number(body.user || me.id);
      if (uid !== me.id && me.role !== "master") err(403, "본인 기록만 넣을 수 있습니다");
      const isMem = q1("SELECT 1 FROM issue_members WHERE issue_id=? AND user_id=?", iss.id, uid);
      const had = q1("SELECT * FROM issue_logs WHERE issue_id=? AND user_id=? AND date=?", iss.id, uid, date);
      if (!isMem && !had) err(403, "담당이 아닌 이슈에는 기록할 수 없습니다");
      const text = "text" in body ? str(body.text, 1000) : had?.text || "";
      if (h === 0 && !text) run("DELETE FROM issue_logs WHERE issue_id=? AND user_id=? AND date=?", iss.id, uid, date);
      else run(`INSERT INTO issue_logs(issue_id,user_id,date,hours,text) VALUES(?,?,?,?,?) ON CONFLICT(issue_id,user_id,date)
               DO UPDATE SET hours=excluded.hours, text=excluded.text, updated=datetime('now','localtime')`, iss.id, uid, date, h, text);
      if ((had?.text || "") !== text) audit(me.id, "이슈 기록", `${iss.no} ${date}`, { from: had?.text || "", to: text });
      return json({ ok: true });
    }
    err(400, "종류 오류");
  }

  // ── 이슈 ──
  if (p === "/api/issues" && m === "GET") {
    const scope = url.searchParams.get("scope") || "mine"; const c = ctx();
    const hid = url.searchParams.get("hidden") === "1" && isAdmin(me);
    let list: any[];
    if (scope === "all") { if (!isAdmin(me)) err(403, "볼 수 없습니다"); list = q(`SELECT * FROM issues ${hid ? "" : "WHERE hidden=0"} ORDER BY no`); }
    else if (scope === "part") {
      const pt = isAdmin(me) ? (url.searchParams.get("part") || "") : plPart(me); if (!pt) err(403, "PL만 볼 수 있습니다");
      list = q("SELECT i.* FROM issues i LEFT JOIN models md ON md.id=i.model_id WHERE i.hidden=0 AND md.part=? ORDER BY i.no", pt);
    } else list = q("SELECT i.* FROM issues i JOIN issue_members m ON m.issue_id=i.id WHERE m.user_id=? AND i.hidden=0 ORDER BY i.no", me.id);
    const keep = num("done_keep_days", 30); const t = today();
    const showDone = url.searchParams.get("done") !== "0";
    return json(list.map((i: any) => issueRow(i, c)).filter(i => showDone || !stageDone(i) || (i.done && i.done >= addDays(t, -keep))));
  }
  if (p === "/api/issues" && m === "POST") {
    if (!isAdmin(me) && !isPL(me)) err(403, "이슈는 PL이 등록합니다");
    const model_id = Number(body.model_id) || null; if (!model_id) err(400, "모델을 고르세요");
    if (isPL(me) && partOfModel(model_id) !== me.part) err(403, `${me.part} 모델만 등록할 수 있습니다`);
    const title = str(body.title, 200); if (!title) err(400, "이슈명을 입력하세요");
    if (q1("SELECT no FROM issues WHERE title=? AND model_id=? AND hidden=0 AND done IS NULL AND stage<6", title, model_id))
      err(400, "같은 모델에 같은 이름의 진행 중 이슈가 이미 있습니다");
    let id = 0, no = "";
    db.transaction(() => {
      no = nextIssueNo();
      const r = run(`INSERT INTO issues(no,model_id,title,source,occurred,target,stage,status_text,note,importance,created_by) VALUES(?,?,?,?,?,?,1,?,?,?,?)`,
        no, model_id, title, str(body.source, 20), dOrNull(body.occurred) || today(), dOrNull(body.target), str(body.status_text), str(body.note), str(body.importance, 5), me.id);
      id = Number(r.lastInsertRowid);
      setMembers(id, body.members || [], !!body.confirm_pl);
    })();
    audit(me.id, "이슈 등록", no, body);
    return json(issueRow(q1("SELECT * FROM issues WHERE id=?", id)));
  }
  mt = p.match(/^\/api\/issues\/(\d+)(\/me|\/hide)?$/);
  if (mt) {
    const iss = q1("SELECT * FROM issues WHERE id=?", Number(mt[1])); if (!iss) err(404, "없는 이슈입니다");
    const mem = membersOf(iss.id); const myRole = mem.find((x: any) => x.user_id === me.id)?.role;
    const manage = canManageIssue(me, iss);
    if (m === "GET") {
      if (!manage && !myRole) err(403, "볼 수 없습니다 (우리 파트 이슈 · 내가 담당인 이슈만)");
      const logs = q("SELECT l.*, u.name FROM issue_logs l JOIN users u ON u.id=l.user_id WHERE issue_id=? ORDER BY date DESC, u.ord", iss.id);
      return json({ ...issueRow(iss), logs, canManage: manage, myRole: myRole || "" });
    }
    if (mt[2] === "/hide" && m === "POST") {
      if (!manage) err(403, "PL · 팀장만 지울 수 있습니다");
      const reason = str(body.reason, 300); if (body.hidden && !reason) err(400, "삭제 사유를 적어 주세요");
      run("UPDATE issues SET hidden=?, hidden_reason=?, updated=datetime('now','localtime') WHERE id=?", body.hidden ? 1 : 0, body.hidden ? reason : "", iss.id);
      audit(me.id, body.hidden ? "이슈 삭제(숨김)" : "이슈 되살리기", iss.no, { reason });
      return json({ ok: true });
    }
    if (mt[2] === "/me" && m === "PUT") {
      if (!myRole) err(403, "담당자만 고칠 수 있습니다");
      const cat = str(body.category, 200); if (cat && !q1("SELECT 1 FROM categories WHERE name=?", cat)) err(400, "업무 분류 목록에 없는 값입니다");
      run("UPDATE issue_members SET category=? WHERE issue_id=? AND user_id=?", cat, iss.id, me.id);   // 맡은 일(할 일)은 PL이 지정
      audit(me.id, "이슈 내 업무 분류", iss.no, { category: cat });
      return json({ ok: true });
    }
    if (m === "PUT") {
      const set: any = {};
      const want = (k: string) => k in body && String(body[k] ?? "") !== String(iss[k] ?? "");
      const plOnly = ["title", "model_id", "source", "occurred", "target", "status_text", "delay_reason", "note", "importance", "done"];
      for (const k of plOnly) if (want(k)) {
        if (!manage) err(403, k === "delay_reason" ? "입력 권한이 없습니다 (지연 사유는 PL이 입력)" : `${NOPERM} (PL · 팀장만 고칠 수 있는 칸)`);
        set[k] = ["occurred", "target", "done"].includes(k) ? dOrNull(body[k]) : k === "model_id" ? (Number(body[k]) || null) : str(body[k], 2000);
      }
      if (set.model_id && isPL(me) && partOfModel(set.model_id) !== me.part) err(403, `${me.part} 모델만 고를 수 있습니다`);
      if ("title" in set && !set.title) err(400, "이슈명을 입력하세요");
      if (want("stage")) { if (!manage) err(403, `${NOPERM} (단계는 PL이 고칩니다)`); set.stage = Math.min(6, Math.max(1, Number(body.stage) || 1)); }
      for (const k of ["cause", "plan"]) if (want(k)) {
        if (!manage && myRole !== "정") err(403, `${NOPERM} (정 담당 · PL만 고칠 수 있는 칸)`);
        set[k] = k === "stage" ? Math.min(6, Math.max(1, Number(body[k]) || 1)) : str(body[k], 2000);
      }
      if (set.stage === 6 && !iss.done && !("done" in set)) set.done = today();
      if (set.stage && set.stage < 6 && iss.done && !("done" in set)) set.done = null;
      db.transaction(() => {
        const keys = Object.keys(set);
        if (keys.length) run(`UPDATE issues SET ${keys.map(k => k + "=?").join(",")}, updated=datetime('now','localtime') WHERE id=?`, ...keys.map(k => set[k]), iss.id);
        if ("members" in body) { if (!manage) err(403, "담당자는 PL · 팀장만 지정합니다"); setMembers(iss.id, body.members, !!body.confirm_pl); }
      })();
      audit(me.id, "이슈 수정", iss.no, { before: Object.fromEntries(Object.keys(set).map(k => [k, iss[k]])), after: set, members: body.members ? body.members : undefined });
      return json(issueRow(q1("SELECT * FROM issues WHERE id=?", iss.id)));
    }
  }

  // ── 팀장 화면 ──
  if (p === "/api/dashboard" && m === "GET") {
    if (!isAdmin(me)) err(403, "팀장 · 마스터만 볼 수 있습니다");
    const [f, t] = periodRange(url.searchParams.get("mode") || "week", url.searchParams.get("base") || today(), url.searchParams.get("from") || "", url.searchParams.get("to") || "");
    return json(dashboard(f, t));
  }
  if (p === "/api/summary" && m === "GET") { if (!isAdmin(me)) err(403, "팀장 · 마스터만 볼 수 있습니다"); return json(issueSummary()); }

  // ── 기준정보 (팀장 · 마스터) ──
  if (p.startsWith("/api/master/")) {
    if (!isAdmin(me) && !isPL(me)) err(403, "기준정보는 마스터 · 팀장 · PL만 고칩니다");
    const what = p.slice(12);
    if (m === "PUT" && what === "judge") {
      const list = JSON.parse(getSetting("judge", "[]"));
      for (const it of body.items || []) { const j = list[Number(it.i)]; if (!j) continue; j.text = str(it.text, 60); j.action = str(it.action, 200); }
      setSetting("judge", JSON.stringify(list)); audit(me.id, "판정 문구 수정", "", body); return json({ ok: true });
    }
    if (m === "PUT" && what === "grades") {
      db.transaction(() => { for (const g of body.items || []) { const v = Number(g.pct); if (!(v >= 0 && v <= 2)) err(400, `${g.name} 배율은 0 ~ 200%`); run("UPDATE grades SET pct=? WHERE name=?", v, g.name); } })();
      if ("other_pct" in body) setSetting("other_pct", String(Number(body.other_pct) || 0));
      audit(me.id, "기준정보 배율", "", body); return json({ ok: true });
    }
    if (m === "POST" && what === "grades") { const nm = str(body.name, 30); if (!nm) err(400, "이름"); run("INSERT OR IGNORE INTO grades(name,pct,ord) VALUES(?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM grades))", nm, Number(body.pct) || 0); audit(me.id, "등급 추가", nm, body); return json({ ok: true }); }
    if (what === "models" && (m === "POST" || m === "PUT")) {
      const v = { name: str(body.name, 60), part: str(body.part, 30), grade: str(body.grade, 30), phase: str(body.phase, 20), customer: str(body.customer, 60), sop: dOrNull(body.sop), active: body.active ? 1 : 0 };
      if (!v.name) err(400, "모델명을 입력하세요");
      if (isPL(me)) {   // PL: 우리 파트 모델만
        if (v.part !== me.part) err(403, `${me.part} 모델만 추가 · 수정할 수 있습니다`);
        if (m === "PUT" && q1("SELECT part FROM models WHERE id=?", Number(body.id))?.part !== me.part) err(403, `${me.part} 모델만 수정할 수 있습니다`);
      }
      if (q1("SELECT 1 FROM models WHERE name=? AND id<>?", v.name, Number(body.id) || 0)) err(400, "같은 이름의 모델이 이미 있습니다");
      if (m === "POST") run("INSERT INTO models(name,part,grade,phase,customer,sop,active,ord) VALUES(?,?,?,?,?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM models))", v.name, v.part, v.grade, v.phase, v.customer, v.sop, v.active);
      else run("UPDATE models SET name=?,part=?,grade=?,phase=?,customer=?,sop=?,active=? WHERE id=?", v.name, v.part, v.grade, v.phase, v.customer, v.sop, v.active, Number(body.id));
      audit(me.id, m === "POST" ? "모델 추가" : "모델 수정", v.name, v); return json({ ok: true });
    }
    if (what === "holidays" && m === "POST") { const d = dOrNull(body.date); if (!d) err(400, "날짜"); run("INSERT OR REPLACE INTO holidays(date,name) VALUES(?,?)", d, str(body.name, 60)); audit(me.id, "공휴일 추가", d!, body); return json({ ok: true }); }
    if (what === "holidays" && m === "DELETE") { run("DELETE FROM holidays WHERE date=?", body.date); audit(me.id, "공휴일 삭제", body.date, ""); return json({ ok: true }); }
    if (what === "leaves" && m === "GET") return json(q("SELECT l.*, u.name FROM leaves l JOIN users u ON u.id=l.user_id ORDER BY start"));
    if (what === "leaves" && m === "POST") { const s = dOrNull(body.start); if (!s) err(400, "시작일"); run("INSERT INTO leaves(user_id,start,end) VALUES(?,?,?)", Number(body.user_id), s, dOrNull(body.end)); audit(me.id, "휴직 추가", String(body.user_id), body); return json({ ok: true }); }
    if (what === "leaves" && m === "PUT") { run("UPDATE leaves SET start=?, end=? WHERE id=?", dOrNull(body.start), dOrNull(body.end), Number(body.id)); audit(me.id, "휴직 수정", String(body.id), body); return json({ ok: true }); }
    if (what === "holidays" && m === "GET") return json(q("SELECT * FROM holidays ORDER BY date"));
    if (what === "settings" && m === "PUT") {
      const allowed: Record<string, [number, number]> = { day_hours: [1, 24], early_hours: [0, 8], unit: [0.25, 1], over: [0.5, 3], fit: [0.5, 2], lhi: [0, 2], llo: [0, 2], soon_days: [0, 60], done_keep_days: [0, 365] };
      for (const [k, v] of Object.entries(body)) {
        if (k === "today_fix") { setSetting(k, v ? String(dOrNull(v)) : ""); continue; }
        if (k === "hstart") { setSetting(k, String(dOrNull(v))); continue; }
        if (!(k in allowed)) continue;
        const n = Number(v); if (!(n >= allowed[k][0] && n <= allowed[k][1])) err(400, `${k} 값 범위 오류`); setSetting(k, String(n));
      }
      audit(me.id, "기준값 수정", "", body); return json({ ok: true });
    }
    if (what === "categories" && m === "POST") { const nm = str(body.name, 200); if (!nm) err(400, "이름"); run("INSERT OR IGNORE INTO categories(big,mid,name,ord) VALUES(?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM categories))", str(body.big, 100), str(body.mid, 100), nm); audit(me.id, "업무 분류 추가", nm, body); return json({ ok: true }); }
  }

  // ── 관리 (팀장 · 마스터) ──
  if (p.startsWith("/api/admin/")) {
    if (!isAdmin(me)) err(403, "팀장 · 마스터만 쓸 수 있습니다");
    const what = p.slice(11);
    if (what === "users" && m === "POST") {
      const login = str(body.login, 30), name = str(body.name, 40); if (!login || !name) err(400, "아이디 · 이름을 입력하세요");
      if (!["member", "pl", "lead", "master"].includes(body.role)) err(400, "권한 오류");
      if (body.role === "master" && me.role !== "master") err(403, "마스터 계정은 마스터만 만들 수 있습니다");
      if (q1("SELECT 1 FROM users WHERE login=?", login)) err(400, "이미 있는 아이디입니다");
      const pw = tempPw();
      const r = run("INSERT INTO users(login,name,title,part,role,pw,must_change,ord) VALUES(?,?,?,?,?,?,1,(SELECT IFNULL(MAX(ord),0)+1 FROM users))", login, name, str(body.title, 20), str(body.part, 30), body.role, await Bun.password.hash(pw));
      if (body.role !== "lead") await ensureFixedRows(Number(r.lastInsertRowid));
      audit(me.id, "계정 추가", login, { name, role: body.role, part: body.part }); return json({ ok: true, temp: pw });
    }
    // 엑셀 → 웹 전환 (기준일까지 엑셀 값) · dry=true 면 미리보기만
    if (what === "import" && m === "POST") {
      if (!body.seed?.tasks || !body.seed?.issues) err(400, "가져오기 파일(seed.json) 형식이 아닙니다");
      try { const r = await importWork(body.seed, str(body.from || "2000-01-01", 10), str(body.to || body.cutoff, 10), !!body.dry); return json({ ok: true, dry: !!body.dry, ...r }); }
      catch (e: any) { err(400, "가져오기 실패: " + String(e?.message || e).slice(0, 200)); }
    }
    mt = what.match(/^users\/(\d+)(\/reset)?$/);
    if (mt) {
      const tu = q1("SELECT * FROM users WHERE id=?", Number(mt[1])); if (!tu) err(404, "없는 계정");
      if (tu.role === "master" && me.role !== "master") err(403, "마스터 계정은 마스터만 고칩니다");
      if (mt[2] && m === "POST") {
        const pw = tempPw();
        run("UPDATE users SET pw=?, must_change=1, fails=0, locked_until=NULL WHERE id=?", await Bun.password.hash(pw), tu.id);
        run("DELETE FROM sessions WHERE user_id=?", tu.id);
        audit(me.id, "비밀번호 초기화", tu.login, ""); return json({ ok: true, temp: pw });
      }
      if (m === "PUT") {
        const role = body.role ?? tu.role; if (!["member", "pl", "lead", "master"].includes(role)) err(400, "권한 오류");
        if (role === "master" && me.role !== "master") err(403, "마스터 권한은 마스터만 줄 수 있습니다");
        if (tu.id === me.id && role !== tu.role) err(400, "자기 권한은 바꿀 수 없습니다");
        if (role === "pl" && q1("SELECT 1 FROM issue_members m JOIN issues i ON i.id=m.issue_id WHERE m.user_id=? AND i.hidden=0 AND i.done IS NULL AND i.stage<6", tu.id))
          audit(me.id, "알림", tu.login, "PL로 바꾼 사람이 진행 중 이슈 담당으로 남아 있음");
        run("UPDATE users SET name=?, title=?, part=?, role=?, active=?, email=? WHERE id=?", str(body.name ?? tu.name, 40), str(body.title ?? tu.title, 20), str(body.part ?? tu.part, 30), role, body.active === undefined ? tu.active : body.active ? 1 : 0, str(body.email ?? tu.email ?? "", 120).toLowerCase(), tu.id);
        if (role !== "lead") await ensureFixedRows(tu.id);
        if (body.active === false || body.active === 0) run("DELETE FROM sessions WHERE user_id=?", tu.id);
        audit(me.id, "계정 수정", tu.login, body); return json({ ok: true });
      }
    }
    if (what === "acctfiles" && m === "GET") return json(acctFiles());
    if (what === "acctfiles" && m === "DELETE") {
      const del: string[] = [];
      for (const f of acctFiles()) { try { unlinkSync(join(DATA_DIR, f)); del.push(f); } catch {} }
      audit(me.id, "계정표 파일 삭제", "", del); return json({ ok: true, deleted: del });
    }
    if (what === "mail" && m === "GET") return json({ smtp_host: getSetting("smtp_host", ""), smtp_port: getSetting("smtp_port", "25"), smtp_secure: getSetting("smtp_secure", "0"), smtp_user: getSetting("smtp_user", ""), smtp_pass_set: !!getSetting("smtp_pass", ""), smtp_tls_check: getSetting("smtp_tls_check", "1"), mail_from: getSetting("mail_from", ""), mail_domain: getSetting("mail_domain", "") });
    if (what === "mail" && m === "PUT") {
      for (const k of ["smtp_host", "smtp_port", "smtp_secure", "smtp_user", "smtp_tls_check", "mail_from", "mail_domain"]) if (k in body) setSetting(k, str(body[k], 200));
      if (body.smtp_pass) setSetting("smtp_pass", enc(String(body.smtp_pass).slice(0, 200)));   // 암호화해서 저장
      if (body.smtp_pass_clear) setSetting("smtp_pass", "");
      audit(me.id, "메일 설정", "", { ...body, smtp_pass: body.smtp_pass ? "(바꿈)" : undefined }); return json({ ok: true });
    }
    if (what === "mail/test" && m === "POST") {
      const to = str(body.to, 120); if (!to) err(400, "받을 메일 주소를 적으세요");
      try { await sendMail(to, "[회로팀 업무관리] 시험 메일", "메일 설정이 정상입니다. 비밀번호 찾기 인증번호가 이 주소로 갑니다."); }
      catch (e: any) { err(502, "보내지 못했습니다: " + String(e?.message || e).slice(0, 300)); }
      audit(me.id, "시험 메일", to, ""); return json({ ok: true });
    }
    if (what === "audit" && m === "GET") {
      // 시간 입력(숫자만 바뀐 것)은 보이지 않음 · 이슈 기록은 '그날 한 일' 글이 바뀐 것만
      const lim = Math.min(2000, Number(url.searchParams.get("limit") || 300));
      const rows = q("SELECT a.*, u.name FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE a.action<>'시간' ORDER BY a.id DESC LIMIT ?", lim * 3);
      const textChanged = (r: any) => { try { const d = JSON.parse(r.detail); const f = d.from && typeof d.from === "object" ? d.from.t || "" : d.from || ""; const t = d.to && typeof d.to === "object" ? d.to.t || "" : d.to || ""; return f !== t; } catch { return true; } };
      return json(rows.filter((r: any) => r.action !== "이슈 기록" || textChanged(r)).slice(0, lim));
    }
    if (what === "backups" && m === "GET") return json({ list: listBackups(), last: getSetting("last_backup", "") });
    if (what === "backups" && m === "POST") { const nm = backup("수동"); audit(me.id, "백업", nm, ""); return json({ ok: true, name: nm }); }
    mt = what.match(/^backups\/([^/]+\.db)$/);
    if (mt && m === "GET") {
      const nm = decodeURIComponent(mt[1]); if (nm.includes("/") || nm.includes("\\") || nm.includes("..")) err(400, "파일 이름 오류");
      const f = join(BACKUP_DIR, nm); if (!existsSync(f)) err(404, "없는 백업");
      audit(me.id, "백업 내려받기", nm, "");
      return new Response(Bun.file(f), { headers: { "content-type": "application/octet-stream", "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(nm)}` } });
    }
  }
  err(404, "없는 주소입니다");
  return json({});
}
