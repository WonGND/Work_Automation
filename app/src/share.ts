// 0.7.6: 이슈 폴더 — 파일 서버(SMB) 폴더를 NAS가 연결해 컨테이너의 /share 로 넘겨 줌.
//   이슈마다 <모델>/<번호> <이슈명> 폴더를 만든다. 파일은 읽지 · 쓰지 · 지우지 않는다.
//   예전에 손으로 만든 '<번호>' 폴더가 맨 위에 있으면 위 이름으로 옮겨 본다 (권한이 없으면 그대로 두고 목록으로 알림).
import { existsSync, statSync, mkdirSync, readdirSync, renameSync, accessSync, constants } from "fs";
import { join } from "path";
import { q, q1, run, getSetting, audit, DATA_DIR } from "./db";

export const SHARE_ROOT = process.env.WL_SHARE_DIR || "/share";

export function shareUnc(): string {
  return (getSetting("share_unc", "") || process.env.WL_SHARE_UNC || "").trim().replace(/[\\/]+$/, "");
}

// 연결 상태: 폴더가 있고 · 쓸 수 있고 · 실제로 다른 서버가 연결된 폴더인지 (연결이 끊겨 NAS의 빈 폴더만 남으면 만들지 않음)
export function shareStatus(): { ok: boolean; why: string } {
  try {
    if (!existsSync(SHARE_ROOT) || !statSync(SHARE_ROOT).isDirectory()) return { ok: false, why: `${SHARE_ROOT} 폴더가 없습니다 (YAML의 share 연결 확인)` };
    if (process.env.WL_SHARE_LOCAL !== "1" && DATA_DIR && statSync(SHARE_ROOT).dev === statSync(DATA_DIR).dev)
      return { ok: false, why: "파일 서버가 연결되어 있지 않습니다 (NAS의 원격 폴더 마운트가 끊겼거나, 마운트 뒤에 업무관리를 다시 시작하지 않음)" };
    accessSync(SHARE_ROOT, constants.W_OK);
    readdirSync(SHARE_ROOT);
    return { ok: true, why: "" };
  } catch (e: any) { return { ok: false, why: "파일 서버 폴더를 열 수 없습니다: " + (e?.code || e?.message || e) }; }
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

const dirs = (p: string) => { try { return readdirSync(p, { withFileTypes: true }).filter(d => d.isDirectory()).map(d => d.name); } catch { return []; } };
const isNo = (name: string, no: string) => name === no || (name.startsWith(no) && /^[ _\-(]/.test(name.slice(no.length)));

// 번호로 이미 있는 폴더 찾기: 맨 위('26-012') 또는 모델 폴더 안('G8/26-012 ...')
function findExisting(no: string): { rel: string; top: boolean } | null {
  const top = dirs(SHARE_ROOT);
  const t = top.find(n => isNo(n, no)); if (t) return { rel: t, top: true };
  for (const d of top) { if (d.startsWith("_")) continue; const s = dirs(join(SHARE_ROOT, d)).find(n => isNo(n, no)); if (s) return { rel: `${d}/${s}`, top: false }; }
  return null;
}

export type FolderResult = { no: string; result: "있음" | "만듦" | "연결" | "옮김" | "옮기기 실패" | "실패"; path: string; to?: string; why?: string };

function ensureOne(iss: any, by: number | null): FolderResult {
  const want = folderFor(iss);
  if (iss.folder && existsSync(join(SHARE_ROOT, iss.folder))) {
    // 맨 위에 남아 있는 예전 폴더(옮기기 실패)는 매번 다시 옮겨 본다
    if (!iss.folder.includes("/")) return tryMove(iss, iss.folder, want, by);
    return { no: iss.no, result: "있음", path: iss.folder };
  }
  const ex = findExisting(iss.no);
  if (ex && ex.top) return tryMove(iss, ex.rel, want, by);
  if (ex) { setFolder(iss, ex.rel, by, "연결"); return { no: iss.no, result: "연결", path: ex.rel }; }
  try {
    mkdirSync(join(SHARE_ROOT, want), { recursive: true });
    setFolder(iss, want, by, "만듦"); return { no: iss.no, result: "만듦", path: want };
  } catch (e: any) { return { no: iss.no, result: "실패", path: want, why: String(e?.code || e?.message || e) }; }
}
function tryMove(iss: any, from: string, want: string, by: number | null): FolderResult {
  try {
    if (existsSync(join(SHARE_ROOT, want))) throw Object.assign(new Error("옮길 자리에 같은 이름 폴더가 있음"), { code: "같은 이름 있음" });
    mkdirSync(join(SHARE_ROOT, want.split("/")[0]), { recursive: true });
    renameSync(join(SHARE_ROOT, from), join(SHARE_ROOT, want));
    setFolder(iss, want, by, "옮김", from); return { no: iss.no, result: "옮김", path: want };
  } catch (e: any) {
    if (iss.folder !== from) setFolder(iss, from, by, "연결 (옮기기 실패)");
    return { no: iss.no, result: "옮기기 실패", path: from, to: want, why: String(e?.code || e?.message || e) };
  }
}
function setFolder(iss: any, rel: string, by: number | null, how: string, from = "") {
  run("UPDATE issues SET folder=? WHERE id=?", rel, iss.id); iss.folder = rel;
  audit(by, "이슈 폴더", iss.no, from ? { 처리: how, 전: from, 후: rel } : { 처리: how, 경로: rel });
}

let busy = false;
// 숨기지 않은 모든 이슈 (완료 포함). 연결이 안 돼 있으면 아무것도 하지 않음.
export function syncFolders(by: number | null = null, ids?: number[]): { ok: boolean; why: string; results: FolderResult[] } {
  const st = shareStatus(); if (!st.ok) return { ...st, results: [] };
  if (busy) return { ok: false, why: "다른 폴더 작업이 진행 중입니다. 잠시 뒤 다시", results: [] };
  busy = true;
  try {
    const list = ids?.length ? q(`SELECT * FROM issues WHERE hidden=0 AND id IN (${ids.map(() => "?").join(",")})`, ...ids) : q("SELECT * FROM issues WHERE hidden=0 ORDER BY no");
    return { ok: true, why: "", results: list.map(i => ensureOne(i, by)) };
  } finally { busy = false; }
}

// 관리 화면 '연결 시험': _연결시험 폴더 하나 만들기 (지우는 것은 사람이)
export function testShare(by: number | null) {
  const st = shareStatus(); if (!st.ok) return st;
  try { mkdirSync(join(SHARE_ROOT, "_연결시험"), { recursive: true }); audit(by, "이슈 폴더", "연결 시험", { 경로: "_연결시험" }); return { ok: true, why: "" }; }
  catch (e: any) { return { ok: false, why: "폴더를 만들 수 없습니다 (권한 확인): " + (e?.code || e?.message || e) }; }
}

// 관리 화면 표: 옮기기가 필요한 폴더 · 폴더가 없는 이슈
export function shareView() {
  const st = shareStatus();
  const list = q("SELECT * FROM issues WHERE hidden=0 ORDER BY no");
  const pending = list.filter(i => i.folder && !String(i.folder).includes("/")).map(i => ({ no: i.no, from: i.folder, to: folderFor(i) }));
  const none = list.filter(i => !i.folder).map(i => i.no);
  return { ...st, unc: shareUnc(), root: SHARE_ROOT, total: list.length, linked: list.length - none.length, pending, none };
}
