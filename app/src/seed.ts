// 처음 실행할 때 (데이터베이스가 비어 있을 때) seed.json 으로 기준정보 · 계정 · 업무 · 이슈를 넣음
import { db, q, q1, run, setSetting, getSetting, audit, DATA_DIR, backup } from "./db";
import { join } from "node:path";
import { addDays } from "./calc";

export function shortName(full: string) { return full.split(" ")[0]; }

export const DEFAULT_ROWS: [string, string][] = [["기타", "회의·보고"], ["기타", "교육·행정·기타"], ["휴가", "연차·반차"], ["조퇴", "조퇴"], ["기타", "외근"]];   // 0.8.0: 5 = 외근 (칸에서 모델별 나누기)
// 표에 보이는 순서: 회의·보고 → 외근 → 교육 → 연차 → 조퇴
export const FIXED_ORDER = "CASE fixed_key WHEN '1' THEN 1 WHEN '5' THEN 2 WHEN '2' THEN 3 WHEN '3' THEN 4 WHEN '4' THEN 5 ELSE 9 END";

// 기본 행 5개 (회의 · 교육 · 연차 · 조퇴 · 외근). 0.2.1부터 이름을 고칠 수 있어 fixed_key(1~4)로 찾음
export async function ensureFixedRows(userId: number) {
  for (const [k, [kind, title]] of DEFAULT_ROWS.entries()) {
    const key = String(k + 1);
    const keyed = q1("SELECT id FROM tasks WHERE user_id=? AND fixed_key=?", userId, key);
    if (keyed) { run("UPDATE tasks SET fixed=1, hidden=0 WHERE id=?", keyed.id); continue; }
    const ex = key === "5" ? null : q1("SELECT id FROM tasks WHERE user_id=? AND kind=? AND title=? AND IFNULL(fixed_key,'')='' ORDER BY fixed DESC, id LIMIT 1", userId, kind, title);   // 외근: 각자 만든 '외근' 업무는 그대로 둠
    if (ex) { run("UPDATE tasks SET fixed=1, hidden=0, fixed_key=? WHERE id=?", key, ex.id); continue; }
    if (kind === "휴가" || kind === "조퇴") {
      const any = q1("SELECT id FROM tasks WHERE user_id=? AND kind=? AND hidden=0 AND IFNULL(fixed_key,'')='' ORDER BY fixed DESC, id LIMIT 1", userId, kind);
      if (any) { run("UPDATE tasks SET fixed=1, fixed_key=? WHERE id=?", key, any.id); continue; }
    }
    run("INSERT INTO tasks(user_id,kind,title,fixed,fixed_key,ord) VALUES(?,?,?,1,?,?)", userId, kind, title, key, -10);
  }
}

export async function importSeed(seed: any): Promise<string> {
  const lines: string[] = [];
  const tx = db.transaction(() => {
    seed.grades.forEach((g: any, i: number) => run("INSERT OR REPLACE INTO grades(name,pct,ord) VALUES(?,?,?)", g.name, g.pct ?? 0, i));
    const parts = Array.from(new Set([...seed.parts.map((p: any) => p.name), ...seed.models.map((m: any) => m.part)].filter(Boolean)));
    parts.forEach((p, i) => run("INSERT OR IGNORE INTO parts(name,ord) VALUES(?,?)", p, i));
    seed.models.forEach((m: any, i: number) => run("INSERT OR IGNORE INTO models(name,part,grade,phase,customer,sop,active,ord) VALUES(?,?,?,?,?,?,?,?)",
      m.name, m.part, m.grade, m.phase, m.customer || "", m.sop, m.active ? 1 : 0, i));
    for (const h of seed.holidays) run("INSERT OR IGNORE INTO holidays(date,name) VALUES(?,?)", h.date, h.name);
    seed.categories.forEach((c: any, i: number) => run("INSERT OR IGNORE INTO categories(big,mid,name,ord) VALUES(?,?,?,?)", c.big, c.mid, c.name, i));
    const st = seed.settings;
    for (const k of Object.keys(st)) setSetting(k, String(st[k]));
    setSetting("stage_pct", JSON.stringify(seed.stages.map((x: any) => x.pct)));
    setSetting("stage_names", JSON.stringify(seed.stages.map((x: any) => x.name)));
    setSetting("phases", JSON.stringify(seed.phases));
    setSetting("judge", JSON.stringify(seed.judge));
    setSetting("issue_seq", seed.issue_seq || "");
    setSetting("seed_source", seed.source + " · " + seed.extracted);
  });
  tx();

  // 계정 (비밀번호는 처음 로그인 때 바꿈)
  // 0.4.0: 처음 비밀번호를 만들지 않음 (파일로 남기지 않음). 마스터는 '처음 설정' 화면에서, 나머지는 관리 > 계정 '초기화'로 받음
  const mk = async (login: string, name: string, title: string, part: string, role: string, ord: number) => {
    run("INSERT INTO users(login,name,title,part,role,pw,must_change,ord) VALUES(?,?,?,?,?,'',1,?)", login, name, title, part, role, ord);
  };
  let ord = 0;
  for (const p of seed.people) {
    // 마스터: seed.master (또는 WL_MASTER) 에 적은 이름
    const master = String(seed.master || process.env.WL_MASTER || "");
    const role = master && shortName(p.name) === master ? "master" : p.role;
    await mk(shortName(p.name), p.name, p.title, p.part, role, ord++);
  }
  await mk("팀장", "팀장", "팀장", "", "lead", ord++);
  const uid = new Map<string, number>(q("SELECT id,name FROM users").map((u: any) => [u.name, u.id]));
  const mid = new Map<string, number>(q("SELECT id,name FROM models").map((m: any) => [m.name, m.id]));
  for (const l of seed.leaves || []) if (uid.has(l.name)) run("INSERT INTO leaves(user_id,start,end) VALUES(?,?,?)", uid.get(l.name), l.start, l.end);

  const tx2 = db.transaction(() => {
    for (const t of seed.tasks) {
      const u = uid.get(t.user); if (!u) continue;
      // 개인 업무는 '목표 마감일' 하나만 씀 (수정 마감일이 있으면 그 날을 목표로)
      const target = t.revised || t.target;
      const note = t.note + (t.revised && t.target && t.revised !== t.target ? `${t.note ? " / " : ""}(처음 목표 ${t.target})` : "");
      const r = run(`INSERT INTO tasks(user_id,kind,model_id,title,progress,start,target,done,importance,category,note,ord) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`,
        u, t.kind, t.model ? (mid.get(t.model) ?? null) : null, t.title, t.kind === "통상" ? t.progress : null, t.start, target, t.done,
        t.importance, t.category, note, t.row);
      const id = Number(r.lastInsertRowid);
      for (const [d, h] of Object.entries(t.hours)) run("INSERT OR REPLACE INTO task_hours(task_id,date,hours) VALUES(?,?,?)", id, d, h);
    }
    let seq = seed.issue_seq || "";
    const seqNum = (s: string) => parseInt(s.split("-")[1] || "0", 10);
    for (const i of seed.issues) if (!i.no.startsWith("NEW") && i.no > seq) seq = i.no;
    for (const i of seed.issues) {
      let no = i.no;
      if (no.startsWith("NEW")) { seq = `${seq.slice(0, 2)}-${String(seqNum(seq) + 1).padStart(3, "0")}`; no = seq; lines.push(`번호 없던 이슈 '${i.title}' → ${no}`); }
      const r = run(`INSERT INTO issues(no,model_id,title,source,occurred,target,stage,status_text,note,cause,plan,importance,done) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`,
        no, i.model ? (mid.get(i.model) ?? null) : null, i.title, i.source, i.occurred, i.target, i.stage || 1, i.status_text, i.note, i.cause, i.plan, i.importance, i.done);
      const id = Number(r.lastInsertRowid);
      const outside: string[] = [];
      for (const m of i.members) {
        const u = uid.get(m.name);
        if (!u) { outside.push(`${m.role} ${m.name}`); continue; }
        run("INSERT OR REPLACE INTO issue_members(issue_id,user_id,role,duty,category) VALUES(?,?,?,?,?)", id, u, m.role, m.duty || "", m.category || "");
      }
      if (outside.length) { run("UPDATE issues SET note = note || ? WHERE id=?", `${i.note ? " / " : ""}시범판 밖 담당: ${outside.join(", ")}`, id); lines.push(`${no}: 시범판 밖 담당 ${outside.join(", ")} (비고에 적음)`); }
      for (const lg of i.logs) {
        const u = uid.get(lg.user); if (!u) continue;
        for (const [d, h] of Object.entries(lg.hours)) run(`INSERT INTO issue_logs(issue_id,user_id,date,hours,text) VALUES(?,?,?,?,'')
          ON CONFLICT(issue_id,user_id,date) DO UPDATE SET hours=hours+excluded.hours`, id, u, d, h);
      }
    }
    setSetting("issue_seq", seq);
  });
  tx2();
  for (const u of q("SELECT id FROM users WHERE role<>'lead'")) await ensureFixedRows(u.id);
  audit(null, "처음 데이터 가져오기", seed.source, { people: seed.people.length, tasks: seed.tasks.length, issues: seed.issues.length, warnings: seed.warnings, notes: lines });
  return [...seed.warnings, ...lines].join("\n");
}

// 0.2.0: 이미 쓰던 데이터에 seed.json 의 새 사람(다른 파트)만 더함. 있는 계정 · 업무 · 이슈 · 기록은 건드리지 않음.
//  - 계정: 아이디(이름)가 없는 사람만 새로 만듦 (사용 중지한 계정도 '있음'으로 봄)
//  - 업무 · 시간: 새로 만든 사람 것만
//  - 이슈: 번호가 없는 이슈는 새로 만들고, 있는 이슈에는 새 사람의 담당(빈 자리일 때만) · 시간만 더함
//  - 기준정보: 없는 모델 · 파트 · 공휴일 · 업무 분류 · 등급만 더함 (고친 값은 그대로)
export async function mergeSeed(seed: any): Promise<string> {
  const key = `${seed.source} · ${seed.extracted}`;
  if (getSetting("seed_merged", "") === key || getSetting("seed_source", "") === key) return "";
  const lines: string[] = [];
  backup("추가반영전");
  db.transaction(() => {
    seed.grades.forEach((g: any) => run("INSERT OR IGNORE INTO grades(name,pct,ord) VALUES(?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM grades))", g.name, g.pct ?? 0));
    const parts = Array.from(new Set([...seed.parts.map((p: any) => p.name), ...seed.models.map((m: any) => m.part)].filter(Boolean)));
    for (const p of parts) run("INSERT OR IGNORE INTO parts(name,ord) VALUES(?,(SELECT IFNULL(MAX(ord),0)+1 FROM parts))", p);
    for (const m of seed.models) {
      const r = run("INSERT OR IGNORE INTO models(name,part,grade,phase,customer,sop,active,ord) VALUES(?,?,?,?,?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM models))",
        m.name, m.part, m.grade, m.phase, m.customer || "", m.sop, m.active ? 1 : 0);
      if (r.changes) lines.push(`모델 추가: ${m.name} (${m.part})`);
    }
    for (const h of seed.holidays) run("INSERT OR IGNORE INTO holidays(date,name) VALUES(?,?)", h.date, h.name);
    for (const c of seed.categories) run("INSERT OR IGNORE INTO categories(big,mid,name,ord) VALUES(?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM categories))", c.big, c.mid, c.name);
  })();
  const accounts: string[] = [];
  const fresh = new Set<string>();   // 이번에 새로 만든 사람 이름
  let ord = (q1("SELECT IFNULL(MAX(ord),0) n FROM users")?.n || 0) + 1;
  for (const p of seed.people) {
    const login = shortName(p.name);
    if (q1("SELECT 1 FROM users WHERE login=? OR name=?", login, p.name)) continue;
    run("INSERT INTO users(login,name,title,part,role,pw,must_change,ord) VALUES(?,?,?,?,?,'',1,?)", login, p.name, p.title, p.part, p.role, ord++);
    accounts.push(p.name);
    fresh.add(p.name);
  }
  const uid = new Map<string, number>(q("SELECT id,name FROM users").map((u: any) => [u.name, u.id]));
  const mid = new Map<string, number>(q("SELECT id,name FROM models").map((m: any) => [m.name, m.id]));
  db.transaction(() => {
    for (const l of seed.leaves || []) if (fresh.has(l.name)) run("INSERT INTO leaves(user_id,start,end) VALUES(?,?,?)", uid.get(l.name), l.start, l.end);
    for (const t of seed.tasks) {
      if (!fresh.has(t.user)) continue;
      const target = t.revised || t.target;
      const note = t.note + (t.revised && t.target && t.revised !== t.target ? `${t.note ? " / " : ""}(처음 목표 ${t.target})` : "");
      const r = run(`INSERT INTO tasks(user_id,kind,model_id,title,progress,start,target,done,importance,category,note,ord) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`,
        uid.get(t.user), t.kind, t.model ? (mid.get(t.model) ?? null) : null, t.title, t.kind === "통상" ? t.progress : null, t.start, target, t.done, t.importance, t.category, note, t.row);
      for (const [d, h] of Object.entries(t.hours)) run("INSERT OR REPLACE INTO task_hours(task_id,date,hours) VALUES(?,?,?)", Number(r.lastInsertRowid), d, h);
    }
    let added = 0;
    for (const i of seed.issues) {
      if (i.no.startsWith("NEW")) continue;
      let iss = q1("SELECT * FROM issues WHERE no=?", i.no);
      if (!iss) {
        const r = run(`INSERT INTO issues(no,model_id,title,source,occurred,target,stage,status_text,note,cause,plan,importance,done) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`,
          i.no, i.model ? (mid.get(i.model) ?? null) : null, i.title, i.source, i.occurred, i.target, i.stage || 1, i.status_text, i.note, i.cause, i.plan, i.importance, i.done);
        iss = q1("SELECT * FROM issues WHERE id=?", Number(r.lastInsertRowid)); added++;
        for (const m of i.members) { const u = uid.get(m.name); if (u) run("INSERT OR IGNORE INTO issue_members(issue_id,user_id,role,duty,category) VALUES(?,?,?,?,?)", iss.id, u, m.role, m.duty || "", m.category || ""); }
        for (const lg of i.logs) { const u = uid.get(lg.user); if (!u) continue;
          for (const [d, h] of Object.entries(lg.hours)) run(`INSERT INTO issue_logs(issue_id,user_id,date,hours,text) VALUES(?,?,?,?,'') ON CONFLICT(issue_id,user_id,date) DO UPDATE SET hours=hours+excluded.hours`, iss.id, u, d, h); }
        continue;
      }
      // 있는 이슈: 새 사람 것만
      for (const m of i.members) {
        if (!fresh.has(m.name)) continue;
        const r = run("INSERT OR IGNORE INTO issue_members(issue_id,user_id,role,duty,category) VALUES(?,?,?,?,?)", iss.id, uid.get(m.name), m.role, m.duty || "", m.category || "");
        if (!r.changes) lines.push(`${i.no}: ${m.role} 자리가 이미 있어 ${m.name} 은 담당으로 넣지 않음 (시간은 넣음)`);
        else run("UPDATE issues SET note = replace(note, ?, '') WHERE id=?", `${m.role} ${m.name}`, iss.id);
      }
      for (const lg of i.logs) { if (!fresh.has(lg.user)) continue; const u = uid.get(lg.user);
        for (const [d, h] of Object.entries(lg.hours)) run(`INSERT INTO issue_logs(issue_id,user_id,date,hours,text) VALUES(?,?,?,?,'') ON CONFLICT(issue_id,user_id,date) DO NOTHING`, iss.id, u, d, h); }
    }
    const mx = q1("SELECT MAX(no) n FROM issues")?.n || ""; if (mx > getSetting("issue_seq", "")) setSetting("issue_seq", mx);
    if (added) lines.push(`이슈 ${added}건 추가`);
    setSetting("seed_merged", key);
  })();
  for (const n of fresh) await ensureFixedRows(uid.get(n)!);
  if (accounts.length) {
    lines.unshift(`계정 ${accounts.length}개 추가 (${accounts.join(", ")}) → 관리 > 계정에서 '비밀번호 초기화'로 처음 비밀번호를 만들어 전달`);
  }
  audit(null, "seed 추가 반영", seed.source, { people: [...fresh], notes: lines });
  return lines.join("\n");
}

// 엑셀 → 웹 반영 (기간 지정). 기간(from ~ to) 안의 시간은 엑셀 값으로, 기간 밖과 웹에서 만든 것은 그대로
//  - 계정 · 비밀번호 · 개인 설정 · 요청 · 알림 · 웹에서 만든 업무/이슈 · 웹에 적은 '한 일' 글은 그대로
//  - 업무 맞추기: ① 엑셀 행(사람|행번호)  ② 같은 사람 · 구분 · 업무명  ③ (처음 한 번) 같은 사람 · 구분 · 행 순서 → 업무명이 바뀌었으면 엑셀 이름으로
//  - 시간: 엑셀과 연결된 업무 · 기본 행 · 이슈의 '기간 안' 시간을 엑셀 값으로 바꿈 (엑셀에서 지운 칸은 지움)
//  - 엑셀에서 없어진 행: 기간 안 시간만 빠지고, 남은 시간이 하나도 없으면 목록에서 숨김 (지우지 않음)
//  - 이슈: 번호로 맞춰 내용 고침 · 새 번호는 추가 · 담당(정 · 부1 · 부2)은 엑셀 기준 (웹에서 쓴 할 일은 남김)
//  - 기준정보: 모델 · 공휴일 · 업무 분류 · 휴직을 엑셀 기준으로 더하거나 고침 (지우지 않음)
//  - 웹 기준 시작일(web_start, 기본 2026-11-16)부터는 웹이 우선 (0.5.6):
//      시간 — 웹에 값이 있으면 그대로, 웹에 없고 엑셀에만 있으면 엑셀 값 · 지우지 않음
//      업무 · 이슈 내용 · 담당 — 그날 이후 웹에서 고친 업무 · 이슈는 엑셀로 덮어쓰지 않음
export async function importWork(seed: any, from: string, to: string, dry = false, webStart?: string) {
  const R = { users: 0, tasksNew: 0, tasksUpd: 0, renamed: [] as string[], hidden: 0, issuesHidden: [] as string[], hoursSet: 0, issuesNew: 0, issuesUpd: 0, models: 0, leaves: 0, skipped: [] as string[],
    webStart: "", webKeptHours: 0, webKeptTasks: [] as string[], webKeptIssues: [] as string[] };
  const okD = (d: string) => /^\d{4}-\d{2}-\d{2}$/.test(d);
  if (!okD(from) || !okD(to) || from > to) throw new Error("기간 형식이 아닙니다");
  const inP = (d: string) => d >= from && d <= to;
  const W = webStart && okD(webStart) ? webStart : getSetting("web_start", "2026-11-16"); R.webStart = W;
  const oldTo = to < W ? to : addDays(W, -1);          // 엑셀 값으로 바꾸는(지우기 포함) 마지막 날
  const webEdited = (action: string, target: string) => !!q1("SELECT 1 FROM audit WHERE action=? AND target=? AND user_id IS NOT NULL AND at>=? LIMIT 1", action, target, W);
  if (!dry) backup("엑셀가져오기전");
  const work = async () => {
    let ord = (q1("SELECT IFNULL(MAX(ord),0) n FROM users")?.n || 0) + 1;
    for (const p of seed.people) {
      if (q1("SELECT 1 FROM users WHERE login=? OR name=?", shortName(p.name), p.name)) continue;
      run("INSERT INTO users(login,name,title,part,role,pw,must_change,ord) VALUES(?,?,?,?,?,'',1,?)", shortName(p.name), p.name, p.title, p.part, p.role, ord++); R.users++;
    }
    for (const p of seed.parts) if (p.name) run("INSERT OR IGNORE INTO parts(name,ord) VALUES(?,(SELECT IFNULL(MAX(ord),0)+1 FROM parts))", p.name);
    for (const m of seed.models) {
      const ex = q1("SELECT id FROM models WHERE name=?", m.name);
      if (ex) run("UPDATE models SET part=?, grade=?, phase=?, customer=?, sop=?, active=? WHERE id=?", m.part, m.grade, m.phase, m.customer || "", m.sop, m.active ? 1 : 0, ex.id);
      else { run("INSERT INTO models(name,part,grade,phase,customer,sop,active,ord) VALUES(?,?,?,?,?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM models))", m.name, m.part, m.grade, m.phase, m.customer || "", m.sop, m.active ? 1 : 0); R.models++; }
    }
    for (const h of seed.holidays) run("INSERT OR IGNORE INTO holidays(date,name) VALUES(?,?)", h.date, h.name);
    for (const c of seed.categories) run("INSERT OR IGNORE INTO categories(big,mid,name,ord) VALUES(?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM categories))", c.big, c.mid, c.name);
    const uid = new Map<string, number>(q("SELECT id,name FROM users").map((u: any) => [u.name, u.id]));
    const mid = new Map<string, number>(q("SELECT id,name FROM models").map((m: any) => [m.name, m.id]));
    for (const l of seed.leaves || []) {
      const u = uid.get(l.name); if (!u || !l.start) continue;
      if (!q1("SELECT 1 FROM leaves WHERE user_id=? AND start=?", u, l.start)) { run("INSERT INTO leaves(user_id,start,end) VALUES(?,?,?)", u, l.start, l.end); R.leaves++; }
      else run("UPDATE leaves SET end=? WHERE user_id=? AND start=?", l.end, u, l.start);
    }
    // 업무
    const seedUsers = new Set<number>();
    const want = new Map<number, Record<string, number>>();   // 업무 id → 날짜별 엑셀 시간 (같은 기본 행에 여러 엑셀 행이 오면 더함)
    const keys = new Set<string>();
    for (const t of seed.tasks) {
      const u = uid.get(t.user); if (!u) { R.skipped.push(`${t.user}: 계정 없음`); continue; }
      seedUsers.add(u);
      const key = `${u}|${t.row}`; keys.add(key);
      const target = t.revised || t.target;
      const note = t.note + (t.revised && t.target && t.revised !== t.target ? `${t.note ? " / " : ""}(처음 목표 ${t.target})` : "");
      const model = t.model ? (mid.get(t.model) ?? null) : null;
      let tk: any = null;
      if (t.kind === "휴가" || t.kind === "조퇴") tk = q1("SELECT * FROM tasks WHERE user_id=? AND kind=? AND fixed=1 ORDER BY id LIMIT 1", u, t.kind);
      if (!tk) tk = q1("SELECT * FROM tasks WHERE user_id=? AND excel_key=? AND fixed=0", u, key);
      if (!tk) tk = q1("SELECT * FROM tasks WHERE user_id=? AND kind=? AND title=? AND (fixed=1 OR IFNULL(excel_key,'')='') ORDER BY fixed DESC, id LIMIT 1", u, t.kind, t.title);
      if (!tk) { tk = q1("SELECT * FROM tasks WHERE user_id=? AND kind=? AND ord=? AND fixed=0 AND IFNULL(excel_key,'')='' AND assigned_by IS NULL LIMIT 1", u, t.kind, t.row); if (tk) R.renamed.push(`${t.user}: '${tk.title}' → '${t.title}'`); }
      if (tk) {
        if (!tk.fixed && webEdited("업무 수정", `task ${tk.id}`)) { R.webKeptTasks.push(`${t.user}: ${tk.title}`); run("UPDATE tasks SET excel_key=?, hidden=0 WHERE id=?", key, tk.id); }
        else if (tk.fixed) run("UPDATE tasks SET model_id=COALESCE(?, model_id), category=CASE WHEN ?<>'' THEN ? ELSE category END WHERE id=?", model, t.category, t.category, tk.id);
        else run(`UPDATE tasks SET title=?, model_id=?, progress=?, start=?, target=?, done=?, importance=?, category=?, note=?, excel_key=?, hidden=0 WHERE id=?`,
          t.title, model, t.kind === "통상" ? t.progress : null, t.start, target, t.done, t.importance, t.category, note, key, tk.id);
        R.tasksUpd++;
      } else {
        const r = run(`INSERT INTO tasks(user_id,kind,model_id,title,progress,start,target,done,importance,category,note,ord,excel_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,(SELECT IFNULL(MAX(ord),0)+1 FROM tasks WHERE user_id=?),?)`,
          u, t.kind, model, t.title, t.kind === "통상" ? t.progress : null, t.start, target, t.done, t.importance, t.category, note, u, key);
        tk = { id: Number(r.lastInsertRowid) }; R.tasksNew++;
      }
      const w = want.get(tk.id) || {}; for (const [d, h] of Object.entries(t.hours)) if (inP(d)) w[d] = (w[d] || 0) + (h as number); want.set(tk.id, w);
    }
    // 기간 안 시간: 엑셀과 연결된 업무(엑셀 행 · 기본 행)는 엑셀 값으로. 웹에서 만든 업무는 손대지 않음
    for (const u of seedUsers) {
      for (const tk of q("SELECT id FROM tasks WHERE user_id=? AND (fixed=1 OR IFNULL(excel_key,'')<>'')", u)) {
        if (!want.has(tk.id)) run("DELETE FROM task_hours WHERE task_id=? AND date BETWEEN ? AND ?", tk.id, from, oldTo);
      }
    }
    for (const [id, w] of want) {
      run("DELETE FROM task_hours WHERE task_id=? AND date BETWEEN ? AND ?", id, from, oldTo);
      for (const [d, h] of Object.entries(w)) if (h) {
        if (d >= W) { const r = run("INSERT OR IGNORE INTO task_hours(task_id,date,hours) VALUES(?,?,?)", id, d, h); if (r.changes) R.hoursSet++; else R.webKeptHours++; continue; }   // 웹 우선
        run("INSERT INTO task_hours(task_id,date,hours) VALUES(?,?,?)", id, d, h); R.hoursSet++;
      }
    }
    // 엑셀에서 없어진 행: 남은 시간이 없으면 숨김
    for (const u of seedUsers) for (const tk of q("SELECT id, excel_key FROM tasks WHERE user_id=? AND fixed=0 AND hidden=0 AND IFNULL(excel_key,'')<>''", u)) {
      if (keys.has(tk.excel_key)) continue;
      if (!q1("SELECT 1 FROM task_hours WHERE task_id=? LIMIT 1", tk.id)) { run("UPDATE tasks SET hidden=1 WHERE id=?", tk.id); R.hidden++; }
    }
    // 이슈
    let seq = getSetting("issue_seq", "");
    for (const i of seed.issues) {
      if (!i.no || i.no.startsWith("NEW")) { R.skipped.push(`번호 없는 이슈: ${i.title}`); continue; }
      if (i.no > seq) seq = i.no;
      const model = i.model ? (mid.get(i.model) ?? null) : null;
      let iss = q1("SELECT * FROM issues WHERE no=?", i.no);
      const keepWeb = !!iss && webEdited("이슈 수정", i.no);
      if (keepWeb) { R.webKeptIssues.push(`${i.no} ${iss.title}`); }
      else if (iss) {
        run(`UPDATE issues SET model_id=?, title=?, source=?, occurred=?, target=?, stage=?, status_text=?, note=?, cause=?, plan=?, importance=?, done=?, delay_reason=CASE WHEN ?<>'' THEN ? ELSE delay_reason END WHERE id=?`,
          model, i.title, i.source, i.occurred, i.target, i.stage || 1, i.status_text, i.note, i.cause, i.plan, i.importance, i.done, i.delay_reason || "", i.delay_reason || "", iss.id); R.issuesUpd++;
      } else {
        const r = run(`INSERT INTO issues(no,model_id,title,source,occurred,target,stage,status_text,note,cause,plan,importance,done,delay_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
          i.no, model, i.title, i.source, i.occurred, i.target, i.stage || 1, i.status_text, i.note, i.cause, i.plan, i.importance, i.done, i.delay_reason || "");
        iss = { id: Number(r.lastInsertRowid) }; R.issuesNew++;
      }
      const old = q("SELECT * FROM issue_members WHERE issue_id=?", iss.id);
      if (!keepWeb) run("DELETE FROM issue_members WHERE issue_id=?", iss.id);
      if (!keepWeb) for (const m of i.members) {
        const u = uid.get(m.name); if (!u) continue;
        const prev = old.find((o: any) => o.user_id === u);
        run("INSERT OR IGNORE INTO issue_members(issue_id,user_id,role,duty,category) VALUES(?,?,?,?,?)", iss.id, u, m.role, prev?.duty || m.duty || "", m.category || prev?.category || "");
      }
      // 기간 안 이슈 시간: 엑셀 값으로 (웹에 쓴 '한 일' 글은 남기고 시간만 0)
      const lw = new Map<number, Record<string, number>>();
      for (const lg of i.logs) { const u = uid.get(lg.user); if (!u) continue; const w = lw.get(u) || {}; for (const [d, h] of Object.entries(lg.hours)) if (inP(d)) w[d] = (w[d] || 0) + (h as number); lw.set(u, w); }
      for (const r of q("SELECT user_id, date, text FROM issue_logs WHERE issue_id=? AND date BETWEEN ? AND ?", iss.id, from, oldTo)) {
        if (lw.get(r.user_id)?.[r.date]) continue;
        if (r.text) run("UPDATE issue_logs SET hours=0 WHERE issue_id=? AND user_id=? AND date=?", iss.id, r.user_id, r.date);
        else run("DELETE FROM issue_logs WHERE issue_id=? AND user_id=? AND date=?", iss.id, r.user_id, r.date);
      }
      for (const [u, w] of lw) for (const [d, h] of Object.entries(w)) {
        if (d >= W) {   // 웹 우선: 웹에 시간이 없을 때만 엑셀 값
          const r = run(`INSERT INTO issue_logs(issue_id,user_id,date,hours,text) VALUES(?,?,?,?,'') ON CONFLICT(issue_id,user_id,date) DO UPDATE SET hours=excluded.hours WHERE IFNULL(issue_logs.hours,0)=0`, iss.id, u, d, h);
          if (r.changes) R.hoursSet++; else R.webKeptHours++; continue;
        }
        run(`INSERT INTO issue_logs(issue_id,user_id,date,hours,text) VALUES(?,?,?,?,'') ON CONFLICT(issue_id,user_id,date) DO UPDATE SET hours=excluded.hours`, iss.id, u, d, h); R.hoursSet++;
      }
    }
    // 엑셀 '이슈 정리'에서 없어진 이슈 (웹에서 등록한 이슈는 제외): 기간 안 시간을 빼고, 남은 시간이 없으면 숨김
    const nos = new Set(seed.issues.map((i: any) => i.no));
    for (const iss of q("SELECT * FROM issues WHERE hidden=0", )) {
      if (nos.has(iss.no) || q1("SELECT 1 FROM audit WHERE action='이슈 등록' AND target=?", iss.no)) continue;
      for (const r of q("SELECT user_id, date, text FROM issue_logs WHERE issue_id=? AND date BETWEEN ? AND ?", iss.id, from, oldTo)) {
        if (!seedUsers.has(r.user_id)) continue;
        if (r.text) run("UPDATE issue_logs SET hours=0 WHERE issue_id=? AND user_id=? AND date=?", iss.id, r.user_id, r.date);
        else run("DELETE FROM issue_logs WHERE issue_id=? AND user_id=? AND date=?", iss.id, r.user_id, r.date);
      }
      if (!q1("SELECT 1 FROM issue_logs WHERE issue_id=? AND hours>0 LIMIT 1", iss.id)) {
        run("UPDATE issues SET hidden=1, hidden_reason=? WHERE id=?", "엑셀 이슈 정리에서 없어짐 (엑셀 가져오기)", iss.id); R.issuesHidden.push(`${iss.no} ${iss.title}`);
      }
    }
    if (seq > getSetting("issue_seq", "")) setSetting("issue_seq", seq);
    if (dry) throw new DryRun();
  };
  try { await runTx(work); }
  catch (e) { if (!(e instanceof DryRun)) throw e; }
  if (!dry) {
    for (const u of q("SELECT id FROM users WHERE role<>'lead'")) await ensureFixedRows(u.id);
    audit(null, "엑셀 가져오기", seed.source, { from, to, ...R, skipped: R.skipped.slice(0, 50) });
  }
  return R;
}
class DryRun extends Error {}
// 비동기 작업을 하나의 트랜잭션으로 (실패 · 미리보기면 모두 되돌림)
async function runTx(fn: () => Promise<void>) {
  db.exec("BEGIN IMMEDIATE");
  try { await fn(); db.exec("COMMIT"); } catch (e) { db.exec("ROLLBACK"); throw e; }
}
