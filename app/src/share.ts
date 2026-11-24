// 0.7.6: 이슈 폴더 — 파일 서버(SMB) 폴더를 NAS가 연결해 컨테이너의 /share 로 넘겨 줌.
//   이슈마다 <모델>/<번호> <이슈명> 폴더를 만든다. 파일은 읽지 · 쓰지 · 지우지 않는다.
//   예전에 손으로 만든 '<번호>' 폴더가 맨 위에 있으면 위 이름으로 옮겨 본다 (권한이 없으면 그대로 두고 목록으로 알림).
// 0.7.7: 파일 서버 작업은 모두 비동기 + 시간 제한. 파일 서버가 느리거나 멈춰도 사이트(다른 요청)는 멈추지 않는다.
//   한 번에 한 작업만 · 시간 초과면 그 회차는 멈추고 10분 동안 쉼 · 폴더 목록은 회차마다 한 번만 읽음.
import { promises as fsp, statSync } from "fs";
import { join } from "path";
import { q, q1, run, getSetting, audit, DATA_DIR } from "./db";

export const SHARE_ROOT = process.env.WL_SHARE_DIR || "/share";
const OP_MS = Number(process.env.WL_SHARE_TIMEOUT_MS || 8000);   // 파일 서버 작업 하나의 제한 시간
const REST_MS = 10 * 60e3;                                        // 시간 초과 뒤 쉬는 시간

export function shareUnc(): string {
  return (getSetting("share_unc", "") || process.env.WL_SHARE_UNC || "").trim().replace(/[\\/]+$/, "");
}

class Slow extends Error { code = "응답 없음"; }
// 파일 서버 작업 하나: 제한 시간이 지나면 기다리지 않음 (작업 자체는 뒤에서 끝나도 결과는 버림)
let hung = 0;                // 아직 안 끝난(멈춘) 작업 수 — 남아 있으면 새 작업을 시작하지 않음
function op<T>(p: Promise<T>): Promise<T> {
  hung++;
  let done = false;
  p.finally(() => { done = true; hung--; }).catch(() => {});
  return new Promise<T>((res, rej) => {
    const t = setTimeout(() => { if (!done) rej(new Slow(`파일 서버가 ${OP_MS / 1000}초 안에 답하지 않습니다`)); }, OP_MS);
    p.then(v => { clearTimeout(t); res(v); }, e => { clearTimeout(t); rej(e); });
  });
}
// 폴더 이름만 (종류를 모르는 항목은 stat 으로 확인 — 일부 파일 서버는 종류를 안 알려 줌)
const dirs = async (p: string) => {
  try {
    const out: string[] = [];
    for (const d of await op(fsp.readdir(p, { withFileTypes: true }))) {
      if (d.isDirectory()) out.push(d.name);
      else if (!d.isFile()) { try { if ((await op(fsp.stat(join(p, d.name)))).isDirectory()) out.push(d.name); } catch (e) { if (e instanceof Slow) throw e; } }
    }
    return out;
  } catch (e) { if (e instanceof Slow) throw e; return []; }
};

let restUntil = 0, lastWhy = "";
// 연결 상태: 폴더가 있고 · 쓸 수 있고 · 실제로 다른 서버가 연결된 폴더인지 (연결이 끊겨 NAS의 빈 폴더만 남으면 만들지 않음)
export async function shareStatus(): Promise<{ ok: boolean; why: string }> {
  if (Date.now() < restUntil) return { ok: false, why: `${lastWhy} — ${Math.ceil((restUntil - Date.now()) / 60e3)}분 뒤 다시 시도 (관리 > 이슈 폴더 [지금 맞추기]로 바로 시도)` };
  if (hung > 0) return { ok: false, why: "이전 파일 서버 작업이 아직 끝나지 않았습니다 (파일 서버 응답 대기 중)" };
  try {
    const st = await op(fsp.stat(SHARE_ROOT));
    if (!st.isDirectory()) return { ok: false, why: `${SHARE_ROOT} 가 폴더가 아닙니다` };
    if (process.env.WL_SHARE_LOCAL !== "1" && DATA_DIR && st.dev === statSync(DATA_DIR).dev)
      return { ok: false, why: "파일 서버가 연결되어 있지 않습니다 (NAS의 원격 폴더 마운트가 끊겼거나, 마운트 뒤에 업무관리를 다시 시작하지 않음)" };
    await op(fsp.access(SHARE_ROOT, 2 /* W_OK */));
    return { ok: true, why: "" };
  } catch (e: any) {
    if (e instanceof Slow) { lastWhy = e.message; restUntil = Date.now() + REST_MS; return { ok: false, why: e.message }; }
    if (e?.code === "ENOENT") return { ok: false, why: `${SHARE_ROOT} 폴더가 없습니다 (YAML의 share 연결 확인)` };
    return { ok: false, why: "파일 서버 폴더를 열 수 없습니다: " + (e?.code || e?.message || e) };
  }
}

// 윈도우 폴더 이름에 못 쓰는 글자(\ / : * ? " < > |)는 _ 로, 끝의 점 · 공백은 뺌
export function safeName(s: string, max = 60): string {
  let t = String(s || "").replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").replace(/\s+/g, " ").trim();
  if (t.length > max) t = t.slice(0, max).trim();
  return t.replace(/[. ]+$/, "");
}
export function folderFor(iss: any): string {
  const m = iss.model_id ? q1("SELECT name FROM models WHERE id=?", iss.model_id)?.name : "";
  return `${safeName(m || "", 40) || "모델 없음"}/${`${iss.no} ${safeName(iss.title)}`.trim()}`;
}
const isNo = (name: string, no: string) => name === no || (name.startsWith(no) && /^[ _\-(]/.test(name.slice(no.length)));

// 한 회차의 폴더 목록 (맨 위 + 필요한 모델 폴더 안) — 회차마다 한 번씩만 읽음
class Index {
  top: string[] = []; sub = new Map<string, string[]>();
  async load() { this.top = await dirs(SHARE_ROOT); }
  async in(d: string) { if (!this.sub.has(d)) this.sub.set(d, this.top.includes(d) ? await dirs(join(SHARE_ROOT, d)) : []); return this.sub.get(d)!; }
  async has(rel: string) { const [a, b] = rel.split("/"); if (!b) return this.top.includes(a); return (await this.in(a)).includes(b); }
  async find(no: string): Promise<{ rel: string; top: boolean } | null> {
    const t = this.top.find(n => isNo(n, no)); if (t) return { rel: t, top: true };
    for (const d of this.top) { if (d.startsWith("_") || isNo(d, no)) continue; const s = (await this.in(d)).find(n => isNo(n, no)); if (s) return { rel: `${d}/${s}`, top: false }; }
    return null;
  }
  add(rel: string) { const [a, b] = rel.split("/"); if (!this.top.includes(a)) this.top.push(a); if (b) { const l = this.sub.get(a) || []; l.push(b); this.sub.set(a, l); } }
  drop(rel: string) { const [a, b] = rel.split("/"); if (!b) this.top = this.top.filter(x => x !== a); else this.sub.set(a, (this.sub.get(a) || []).filter(x => x !== b)); }
}

export type FolderResult = { no: string; result: "있음" | "만듦" | "연결" | "옮김" | "옮기기 실패" | "실패"; path: string; to?: string; why?: string };

async function ensureOne(ix: Index, iss: any, by: number | null): Promise<FolderResult> {
  const want = folderFor(iss);
  if (iss.folder && await ix.has(iss.folder)) {
    if (!String(iss.folder).includes("/")) return tryMove(ix, iss, iss.folder, want, by);   // 맨 위에 남은 예전 폴더는 다시 옮겨 봄
    return { no: iss.no, result: "있음", path: iss.folder };
  }
  const ex = await ix.find(iss.no);
  if (ex && ex.top) return tryMove(ix, iss, ex.rel, want, by);
  if (ex) { setFolder(iss, ex.rel, by, "연결"); return { no: iss.no, result: "연결", path: ex.rel }; }
  try {
    const model = want.split("/")[0];
    if (!ix.top.includes(model)) { await op(fsp.mkdir(join(SHARE_ROOT, model), { recursive: true })); ix.add(model); }
    await op(fsp.mkdir(join(SHARE_ROOT, want), { recursive: true })); ix.add(want);
    setFolder(iss, want, by, "만듦"); return { no: iss.no, result: "만듦", path: want };
  } catch (e: any) { if (e instanceof Slow) throw e; return { no: iss.no, result: "실패", path: want, why: String(e?.code || e?.message || e) }; }
}
async function tryMove(ix: Index, iss: any, from: string, want: string, by: number | null): Promise<FolderResult> {
  try {
    if (await ix.has(want)) throw Object.assign(new Error("같은 이름 있음"), { code: "옮길 자리에 같은 이름 폴더가 있음" });
    const model = want.split("/")[0];
    if (!ix.top.includes(model)) { await op(fsp.mkdir(join(SHARE_ROOT, model), { recursive: true })); ix.add(model); }
    await op(fsp.rename(join(SHARE_ROOT, from), join(SHARE_ROOT, want))); ix.drop(from); ix.add(want);
    setFolder(iss, want, by, "옮김", from); return { no: iss.no, result: "옮김", path: want };
  } catch (e: any) {
    if (e instanceof Slow) throw e;
    if (iss.folder !== from) setFolder(iss, from, by, "연결 (옮기기 실패)");
    return { no: iss.no, result: "옮기기 실패", path: from, to: want, why: String(e?.code || e?.message || e) };
  }
}
function setFolder(iss: any, rel: string, by: number | null, how: string, from = "") {
  run("UPDATE issues SET folder=? WHERE id=?", rel, iss.id); iss.folder = rel;
  audit(by, "이슈 폴더", iss.no, from ? { 처리: how, 전: from, 후: rel } : { 처리: how, 경로: rel });
}

let busy = false;
// 숨기지 않은 모든 이슈 (완료 포함). 연결이 안 돼 있거나 다른 작업 중이면 아무것도 하지 않음.
export async function syncFolders(by: number | null = null, ids?: number[], force = false): Promise<{ ok: boolean; why: string; results: FolderResult[] }> {
  if (busy) return { ok: false, why: "다른 폴더 작업이 진행 중입니다. 잠시 뒤 다시", results: [] };
  busy = true;
  try {
    if (force) restUntil = 0;
    const st = await shareStatus(); if (!st.ok) return { ...st, results: [] };
    const list = ids?.length ? q(`SELECT * FROM issues WHERE hidden=0 AND id IN (${ids.map(() => "?").join(",")})`, ...ids) : q("SELECT * FROM issues WHERE hidden=0 ORDER BY no");
    const ix = new Index(); const results: FolderResult[] = [];
    try {
      await ix.load();
      for (const i of list) results.push(await ensureOne(ix, i, by));
    } catch (e: any) {
      if (!(e instanceof Slow)) throw e;
      lastWhy = e.message; restUntil = Date.now() + REST_MS;
      return { ok: false, why: `${e.message} — 이번 회차는 멈췄습니다 (${results.length}/${list.length}건 처리). 10분 뒤 다시 시도`, results };
    }
    return { ok: true, why: "", results };
  } finally { busy = false; }
}

// 관리 화면 '연결 시험': _연결시험 폴더 하나 만들기 (지우는 것은 사람이)
export async function testShare(by: number | null) {
  restUntil = 0;
  const st = await shareStatus(); if (!st.ok) return st;
  try { await op(fsp.mkdir(join(SHARE_ROOT, "_연결시험"), { recursive: true })); audit(by, "이슈 폴더", "연결 시험", { 경로: "_연결시험" }); return { ok: true, why: "" }; }
  catch (e: any) { if (e instanceof Slow) { lastWhy = e.message; restUntil = Date.now() + REST_MS; return { ok: false, why: e.message }; } return { ok: false, why: "폴더를 만들 수 없습니다 (권한 확인): " + (e?.code || e?.message || e) }; }
}

// 관리 화면 표: 옮기기가 필요한 폴더 · 폴더가 없는 이슈 (DB 기록만 봄 — 파일 서버 상태는 shareStatus)
export async function shareView() {
  const st = busy ? { ok: true, why: "" } : await shareStatus();
  const list = q("SELECT * FROM issues WHERE hidden=0 ORDER BY no");
  const pending = list.filter(i => i.folder && !String(i.folder).includes("/")).map(i => ({ no: i.no, from: i.folder, to: folderFor(i) }));
  const none = list.filter(i => !i.folder).map(i => i.no);
  return { ...st, busy, unc: shareUnc(), root: SHARE_ROOT, total: list.length, linked: list.length - none.length, pending, none };
}
