// 데이터베이스 (SQLite 파일 하나) · 스키마 · 공통 도우미
import { Database } from "bun:sqlite";
import { mkdirSync, existsSync, readdirSync, unlinkSync, statSync } from "node:fs";
import { join } from "node:path";

export let db: Database;
export let DATA_DIR = "";
export let BACKUP_DIR = "";

const SCHEMA = `
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, name TEXT NOT NULL, title TEXT DEFAULT '',
  part TEXT DEFAULT '', role TEXT NOT NULL CHECK (role IN ('member','pl','lead','master')),
  pw TEXT NOT NULL, must_change INTEGER DEFAULT 1, active INTEGER DEFAULT 1, ord INTEGER DEFAULT 0,
  fails INTEGER DEFAULT 0, locked_until TEXT, created TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS grades (name TEXT PRIMARY KEY, pct REAL, ord INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS parts (name TEXT PRIMARY KEY, ord INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS models (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, part TEXT DEFAULT '', grade TEXT DEFAULT '', phase TEXT DEFAULT '',
  customer TEXT DEFAULT '', sop TEXT, active INTEGER DEFAULT 1, ord INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS holidays (date TEXT PRIMARY KEY, name TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, big TEXT, mid TEXT, name TEXT UNIQUE, ord INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS leaves (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, start TEXT NOT NULL, end TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('통상','기타','휴가','조퇴')),
  model_id INTEGER, title TEXT NOT NULL, progress INTEGER, start TEXT, target TEXT, done TEXT,
  importance TEXT DEFAULT '', category TEXT DEFAULT '', note TEXT DEFAULT '', fixed INTEGER DEFAULT 0,
  hidden INTEGER DEFAULT 0, ord INTEGER DEFAULT 0,
  created TEXT DEFAULT (datetime('now','localtime')), updated TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS task_hours (task_id INTEGER NOT NULL, date TEXT NOT NULL, hours REAL NOT NULL, PRIMARY KEY (task_id, date));
CREATE TABLE IF NOT EXISTS issues (
  id INTEGER PRIMARY KEY, no TEXT UNIQUE NOT NULL, model_id INTEGER, title TEXT NOT NULL, source TEXT DEFAULT '',
  occurred TEXT, target TEXT, stage INTEGER DEFAULT 1, status_text TEXT DEFAULT '', delay_reason TEXT DEFAULT '',
  note TEXT DEFAULT '', cause TEXT DEFAULT '', plan TEXT DEFAULT '', importance TEXT DEFAULT '', done TEXT,
  created_by INTEGER, hidden INTEGER DEFAULT 0, hidden_reason TEXT DEFAULT '',
  created TEXT DEFAULT (datetime('now','localtime')), updated TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS issue_members (
  issue_id INTEGER NOT NULL, user_id INTEGER NOT NULL, role TEXT NOT NULL CHECK (role IN ('정','부1','부2')),
  duty TEXT DEFAULT '', category TEXT DEFAULT '', PRIMARY KEY (issue_id, role));
CREATE TABLE IF NOT EXISTS issue_logs (
  issue_id INTEGER NOT NULL, user_id INTEGER NOT NULL, date TEXT NOT NULL, hours REAL DEFAULT 0, text TEXT DEFAULT '',
  updated TEXT DEFAULT (datetime('now','localtime')), PRIMARY KEY (issue_id, user_id, date));
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at TEXT DEFAULT (datetime('now','localtime')), user_id INTEGER, action TEXT, target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS task_notes (task_id INTEGER NOT NULL, date TEXT NOT NULL, text TEXT DEFAULT '', updated TEXT DEFAULT (datetime('now','localtime')), PRIMARY KEY (task_id, date));
CREATE TABLE IF NOT EXISTS user_prefs (user_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT, PRIMARY KEY (user_id, key));
CREATE INDEX IF NOT EXISTS ix_th_date ON task_hours(date);
CREATE INDEX IF NOT EXISTS ix_il_user ON issue_logs(user_id, date);
CREATE INDEX IF NOT EXISTS ix_tasks_user ON tasks(user_id);
`;

export function openDb(dataDir: string) {
  DATA_DIR = dataDir;
  BACKUP_DIR = join(dataDir, "백업");
  mkdirSync(dataDir, { recursive: true });
  mkdirSync(BACKUP_DIR, { recursive: true });
  db = new Database(join(dataDir, "업무관리.db"), { create: true });
  db.exec(SCHEMA);
  migrate();
  return db;
}

export function q<T = any>(sql: string, ...p: any[]): T[] { return db.query(sql).all(...p) as T[]; }
export function q1<T = any>(sql: string, ...p: any[]): T | null { return (db.query(sql).get(...p) as T) ?? null; }
export function run(sql: string, ...p: any[]) { return db.query(sql).run(...p); }

export function getSetting(k: string, def = ""): string {
  const r = q1<{ value: string }>("SELECT value FROM settings WHERE key=?", k);
  return r ? r.value : def;
}
export function setSetting(k: string, v: string) {
  run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", k, v);
}

export function audit(userId: number | null, action: string, target: string, detail: any) {
  run("INSERT INTO audit(user_id,action,target,detail) VALUES(?,?,?,?)", userId, action, target,
    typeof detail === "string" ? detail : JSON.stringify(detail));
}

// ── 백업: 데이터베이스 파일 통째로 복사 (VACUUM INTO) · 최근 90개 보관 ──
export function backup(tag: string): string {
  const now = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const nm = `${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}_${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}_${tag}.db`;
  const file = join(BACKUP_DIR, nm);
  if (existsSync(file)) return nm;
  db.exec(`VACUUM INTO '${file.replace(/'/g, "''")}'`);
  const all = readdirSync(BACKUP_DIR).filter(f => f.endsWith(".db")).sort();
  for (const f of all.slice(0, Math.max(0, all.length - 90))) { try { unlinkSync(join(BACKUP_DIR, f)); } catch {} }
  setSetting("last_backup", nm);
  return nm;
}
export function listBackups() {
  return readdirSync(BACKUP_DIR).filter(f => f.endsWith(".db")).sort().reverse()
    .map(f => ({ name: f, size: statSync(join(BACKUP_DIR, f)).size }));
}

// 0.2.0: 열 추가 (있는 데이터는 그대로 둠)
function addCol(table: string, col: string, def: string) {
  const cols = (db.query(`PRAGMA table_info(${table})`).all() as any[]).map(c => c.name);
  if (!cols.includes(col)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${col} ${def}`);
}
function migrate() {
  addCol("tasks", "assigned_by", "INTEGER");          // PL이 지정해서 내려준 업무 (지정한 사람)
  addCol("tasks", "assign_group", "TEXT DEFAULT ''"); // 여러 명에게 한 번에 지정한 묶음
  addCol("issue_members", "ord", "INTEGER DEFAULT 0");
  addCol("tasks", "fixed_key", "TEXT DEFAULT ''");
  addCol("users", "email", "TEXT DEFAULT ''");
  addCol("tasks", "excel_key", "TEXT DEFAULT ''");
  addCol("users", "joined", "TEXT");                   // 0.5.6: 입사일 (이전 날짜는 기준 시간 · 미입력에서 빠짐)
  addCol("users", "left_on", "TEXT");                  // 0.5.6: 퇴사일 (다음 날부터 로그인 막힘 · 목록에서 숨김 · 기록은 남음)     // 0.5.1: 엑셀 행 (사람|행번호) — 엑셀에서 업무명을 바꿔도 같은 업무로 맞춤          // 0.3.0: 비밀번호 찾기용 회사 메일
  db.exec(`CREATE TABLE IF NOT EXISTS notifs (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT, text TEXT, link TEXT DEFAULT '', created TEXT DEFAULT (datetime('now','localtime')), read INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS ix_notif_user ON notifs(user_id, read);
    CREATE TABLE IF NOT EXISTS pw_resets (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, code_hash TEXT, expires TEXT, tries INTEGER DEFAULT 0, used INTEGER DEFAULT 0, created TEXT DEFAULT (datetime('now','localtime')));`);   // 0.2.1: 기본 행 구분 (이름을 고쳐도 같은 행)
  db.exec(`CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, text TEXT NOT NULL,
    status TEXT DEFAULT '대기', reply TEXT DEFAULT '', created TEXT DEFAULT (datetime('now','localtime')), updated TEXT DEFAULT (datetime('now','localtime')), hidden_from INTEGER DEFAULT 0, hidden_to INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS ix_req_to ON requests(to_id, status);`);
}

// 알림 (우상단 🔔)
export function notify(userIds: number | number[], kind: string, text: string, link = "") {
  for (const u of ([] as number[]).concat(userIds)) if (u) db.query("INSERT INTO notifs(user_id,kind,text,link) VALUES(?,?,?,?)").run(u, kind, text, link);
}
