// 회로팀 업무관리 웹 - 사내 서버(NAS)에서 실행하는 프로그램
//   실행: 업무관리.exe [--port 8000] [--data <폴더>]   (기본 데이터 폴더 = 프로그램 옆 '데이터')
//   HTTPS 직접: --cert cert.pem --key key.pem [--http-port 8000]  (--port 는 HTTPS 포트, --http-port 로 들어오면 HTTPS로 넘김)
//   HTTPS 자체 서명: --self-signed [--cert-hosts 192.168.0.10]  (인증서를 열쇠 폴더에 한 번 만들어 계속 씀)
//   HTTPS 프록시 뒤 (시놀로지 역방향 프록시 등): --behind-proxy [--https-only]
//   비밀값 열쇠: 환경변수 WL_SECRET_KEY 또는 --key-file <파일> (기본: 프로그램 옆 '비밀키\secret.key')
//   같은 설정을 환경변수로도: WL_PORT WL_DATA WL_TLS_CERT WL_TLS_KEY WL_HTTP_PORT WL_BEHIND_PROXY=1 WL_HTTPS_ONLY=1 WL_KEY_FILE
import { openDb, q, q1, backup, getSetting, setSetting, notify, db } from "./db";
import { importSeed, mergeSeed, ensureFixedRows } from "./seed";
import { handle, HttpError, NET, setupNeeded, acctFiles } from "./api";
import { initSecret, enc, isEnc, randCode } from "./secret";
import { ensureSelfSigned } from "./selfsign";
import { missReminder } from "./remind";
import { networkInterfaces } from "node:os";
import { join, dirname } from "node:path";
import { existsSync, readFileSync } from "node:fs";
import INDEX from "../public/index.html" with { type: "text" };
import APPJS from "../public/app.js" with { type: "text" };
import CSS from "../public/style.css" with { type: "text" };
import { GUIDE } from "./guide_img";
import { createHash } from "node:crypto";

export const VERSION = "업무관리 0.6.0";
const args = process.argv.slice(2);
const ENVK: Record<string, string> = { "--port": "WL_PORT", "--data": "WL_DATA", "--cert": "WL_TLS_CERT", "--key": "WL_TLS_KEY", "--http-port": "WL_HTTP_PORT", "--key-file": "WL_KEY_FILE", "--seed": "WL_SEED" };
const arg = (k: string, d: string) => { const i = args.indexOf(k); if (i >= 0 && args[i + 1]) return args[i + 1]; const e = ENVK[k] && process.env[ENVK[k]]; return e || d; };
const flag = (k: string, env: string) => args.includes(k) || process.env[env] === "1";
const exeDir = dirname(process.execPath.endsWith("bun") || process.execPath.endsWith("bun.exe") ? join(process.cwd(), "x") : process.execPath);
const DATA = arg("--data", join(exeDir, "데이터"));
let CERT = arg("--cert", ""), TKEY = arg("--key", ""), CA_CERT = "";
// 자체 서명 인증서로 HTTPS (사내 인증서가 없을 때): --self-signed [--cert-hosts 192.168.0.10,nas이름]  /  WL_SELF_SIGNED=1 WL_CERT_HOSTS=…
if (!CERT && flag("--self-signed", "WL_SELF_SIGNED")) {
  const ips = Object.values(networkInterfaces()).flat().filter((x: any) => x && x.family === "IPv4" && !x.internal).map((x: any) => x.address);
  const hosts = Array.from(new Set([...(arg("--cert-hosts", process.env.WL_CERT_HOSTS || "").split(",").map(x => x.trim()).filter(Boolean)), ...ips, "localhost", "127.0.0.1"]));
  const r = ensureSelfSigned(dirname(arg("--key-file", join(exeDir, "비밀키", "secret.key"))), hosts);
  CERT = r.cert; TKEY = r.key; CA_CERT = r.ca;
}
const TLS = CERT && TKEY ? { cert: Bun.file(CERT), key: Bun.file(TKEY) } : undefined;
if ((CERT || TKEY) && !TLS) { console.log("HTTPS는 --cert 와 --key 를 같이 지정합니다"); process.exit(1); }
if (TLS && (!existsSync(CERT) || !existsSync(TKEY))) { console.log(`인증서 파일이 없습니다: ${CERT} / ${TKEY}`); process.exit(1); }
const HTTP_PORT = Number(arg("--http-port", "0"));
NET.trustProxy = flag("--behind-proxy", "WL_BEHIND_PROXY");
NET.httpsOnly = flag("--https-only", "WL_HTTPS_ONLY");
const PORT0 = Number(arg("--port", TLS ? "8443" : "8000"));
const TRY_NEXT = args.includes("--try-next");   // 1_실행: 8000이 다른 프로그램에 쓰이면 8001~8010 차례로 시도
const OPEN = args.includes("--open");           // 1_실행: 실행되면 브라우저 열기
function openBrowser(port: number) {
  if (!OPEN || process.platform !== "win32") return;
  try { Bun.spawn(["cmd", "/c", "start", "", `${TLS ? "https" : "http"}://localhost:${port}`]); } catch {}
}
async function ours(port: number) {
  for (const proto of TLS ? ["https", "http"] : ["http"]) {
    try { const r = await fetch(`${proto}://127.0.0.1:${port}/version`, { signal: AbortSignal.timeout(1500), tls: { rejectUnauthorized: false } } as any); const t = await r.text(); if (t.startsWith("웹 시범판") || t.startsWith("업무관리 ")) return t; } catch {}
  }
  return "";
}
// 이미 업무관리가 켜져 있으면 (창을 두 번 열었거나 서버 자동 시작이 돌고 있으면) 그대로 안내하고 끝냄
{
  const v = await ours(PORT0);
  if (v) {
    console.log(`업무관리가 이미 실행 중입니다 (${v}) · http://localhost:${PORT0}`);
    console.log("다른 검은 창이 열려 있거나 '서버 자동 시작'이 등록되어 있는 경우입니다. 브라우저에서 위 주소를 여세요.");
    openBrowser(PORT0);
    process.exit(0);
  }
}

openDb(DATA);
initSecret(arg("--key-file", join(exeDir, "비밀키", "secret.key")));
// 0.3.0 이전에 평문으로 저장된 메일 비밀번호 → 암호화
{ const sp = getSetting("smtp_pass", ""); if (sp && !isEnc(sp)) { setSetting("smtp_pass", enc(sp)); db.exec("PRAGMA wal_checkpoint(TRUNCATE)"); db.exec("VACUUM"); console.log("[보안] 저장된 메일 비밀번호를 암호화했습니다 (DB 안 예전 평문 흔적도 정리)"); } }
if (!q1("SELECT 1 FROM users LIMIT 1")) {
  const seedFile = [arg("--seed", ""), join(exeDir, "seed.json"), join(DATA, "seed.json")].find(f => f && existsSync(f));
  if (seedFile) {
    const msg = await importSeed(JSON.parse(readFileSync(seedFile, "utf-8")));
    console.log("[처음 실행] 데이터 가져오기 완료:", seedFile);
    if (msg) console.log(msg);
    backup("처음");
  } else {
    console.log("seed.json 이 없어 빈 데이터로 시작할 수 없습니다. 프로그램 옆에 seed.json 을 두고 다시 실행하세요.");
    process.exit(1);
  }
} else {
  // 기본 행 확인 (없으면 만들고, 0.2.0 이전 기본 행에 fixed_key를 붙임 · 있는 행은 그대로)
  for (const u of q("SELECT id FROM users WHERE role<>'lead'")) await ensureFixedRows(u.id);
  // 이미 쓰던 데이터: 새 seed.json 에 있는 새 사람(다른 파트)만 더함 (한 번만)
  const seedFile = [arg("--seed", ""), join(exeDir, "seed.json")].find(f => f && existsSync(f));
  if (seedFile) {
    try { const msg = await mergeSeed(JSON.parse(readFileSync(seedFile, "utf-8"))); if (msg) console.log("[추가 반영]\n" + msg); }
    catch (e) { console.error("seed 추가 반영 실패 (있는 데이터는 그대로):", e); }
  }
}

// 처음 설정: 비밀번호가 있는 관리자가 없으면 설정 코드를 이 창(로그)에만 보여 줌 (파일로 남기지 않음)
if (setupNeeded()) {
  const code = randCode(8);
  setSetting("setup_code_hash", await Bun.password.hash(code));
  console.log("");
  console.log("┌──────────────────────────────────────────────┐");
  console.log(`│ 처음 설정 코드: ${code}                       │`);
  console.log("│ 브라우저로 접속 → '처음 설정'에 이 코드와       │");
  console.log("│ 마스터(또는 팀장) 아이디 · 새 비밀번호를 넣으세요 │");
  console.log("│ (설정을 마치면 코드는 더 이상 쓸 수 없습니다)   │");
  console.log("└──────────────────────────────────────────────┘");
  console.log("");
}
if (acctFiles().length) console.log(`[보안] 데이터 폴더에 예전 계정표 파일이 있습니다 (${acctFiles().join(", ")}) → 관리 > 계정 화면에서 삭제하세요`);

// 매일 자동 백업 (그날 첫 백업이 없으면) + 시작할 때
function dailyBackup() {
  const d = new Date(); const key = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
  if (getSetting("daily_backup", "") !== key) { try { backup("자동"); setSetting("daily_backup", key); } catch (e) { console.error("백업 실패", e); } }
}
dailyBackup();
setInterval(dailyBackup, 30 * 60e3);
// 미입력 알림: 근무일 아침 8시 이후 첫 확인 때 한 번 (10분마다 확인)
const remind = () => { try { missReminder(); } catch (e) { console.error("미입력 알림 실패", e); } };
remind(); setInterval(remind, 10 * 60e3);

const CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'";
// 버전이 바뀌면 모든 사람에게 알림 (우상단 🔔)
const NOTES: Record<string, string> = {
  "업무관리 0.6.0": "이슈 진행 현황을 4칸으로 (현상 · 원인 분석 · 개선검토 · 검증 및 적용) — 이슈를 누르면 왼쪽에 이슈 정보, 오른쪽에 4칸 · PL · 팀장 · 마스터가 씀 · 예전 진행현황은 '현상', 원인은 '원인 분석', 대응 계획은 '개선검토' 칸에 그대로 · 이슈 첨부 이미지 한 장 (붙여넣기 Ctrl+V · 끌어다 놓기 · 파일 고르기, 이슈 정리의 🖼 버튼으로 보기) · 이슈 요약에 발생일 · 현재 진행 칸 · 담당은 정 · 부1 · 부2 순서로 이름만 · 모든 표 머리글 가운데 정렬 · 업무로드 · 요약 기간에 이전 / 다음 버튼 (주 · 월 · 연) · 내 업무 시간 입력 표 월간 보기 · 기준정보 모델 여러 줄 한 번에 추가 · 모델 삭제(숨김) · 되살리기 · 업무 추가 창에서 모델 · 업무 분류 검색",
  "업무관리 0.5.8": "엑셀 가져오기: 이슈 정리의 지연 사유도 가져옴 (엑셀 이슈 정리의 담당 · 맡은 일 · 진행현황 · 단계를 다시 맞춤)",
  "업무관리 0.5.7": "미입력 알림 (전 근무일에 시간이 없으면 아침에 🔔 · 팀장 · PL에게는 주 첫날 지난주 요약) · 다른 사람이 바꾼 계정 · 모델 · 이슈 담당이 열려 있는 화면에도 몇 분 안에 반영 · 엑셀 가져오기는 마스터만",
  "업무관리 0.5.6": "입사 · 퇴사 (관리 > 계정에 입사일 · 퇴사일, 퇴사 다음 날부터 로그인 막힘 · 목록에서 숨김, 기록은 남음) · 사람별을 파트마다 한 열로 · 엑셀 가져오기에 '웹 기준 시작일' (그날부터는 웹 값 우선, 웹에서 고친 업무 · 이슈 · 담당은 덮어쓰지 않음)",
  "업무관리 0.5.5": "다크 모드 — 오른쪽 위 화면 A · B · C 옆 🌙 버튼 (화면마다 어두운 색 따로 · 사람별 저장)",
  "업무관리 0.5.4": "'시범판' 표시 없앰 · 업무 추가 창에서 날짜별 시간 · 그날 한 일 같이 넣기 · 달력에서 오늘 날짜가 안 눌리던 문제 고침 · 시간을 넣으면 근무 시간율 등 요약이 바로 바뀜 · 이슈 정리에 모델 고르기 · 업무 목록 구분 · 머리글 가운데 정렬 · 업무 로드 칸의 '배율 반영 시간' 없앰 · 변경 기록에서 시간 입력 내용 뺌 · 엑셀 내보내기 없앰",
  "웹 시범판 0.5.3": "인증서 설치 안내를 그림으로 — 로그인 화면 노란 상자를 누르면 실제 창 모양 그림 11장을 넘기며 따라 하기 · 보안 경고 창의 지문 확인 값 표시",
  "웹 시범판 0.5.2": "내 업무: 요청하기 · 업무 추가 버튼을 시간 입력 표 바로 위(주 이동 줄 오른쪽)로 옮김 (화면 A · B · C 모두)",
  "웹 시범판 0.5.1": "HTTPS '주의 요함' 경고 없애기 — 로그인 화면 아래 '인증서 설치'로 PC에 한 번 설치",
  "웹 시범판 0.5.0": "엑셀 → 웹 전환 (관리 > 엑셀 가져오기)",
  "웹 시범판 0.4.1": "회로팀 NAS(도커) 운영 시작 · HTTPS(자체 서명 인증서) 접속",
  "웹 시범판 0.4.0": "보안 보강 — 계정표 파일 없앰(처음 비밀번호는 관리 > 계정 '초기화'로 받음) · PL은 우리 파트 · 내 담당 이슈만 열람 · 메일 비밀번호 암호화 · HTTPS 지원",
  "웹 시범판 0.3.0": "우상단 🔔 알림 · 비밀번호 찾기(회사 메일) · 화면 A/B/C 크기 통일 · 업무로드 '모델별 시간 표' 칸 정리",
};
if (getSetting("last_version", "") !== VERSION) {
  notify(q("SELECT id FROM users WHERE active=1").map((x: any) => x.id), "버전", `${VERSION} 로 업데이트됐습니다${NOTES[VERSION] ? ": " + NOTES[VERSION] : ""}`, "");
  setSetting("last_version", VERSION);
}
// 모든 응답에 붙이는 보안 헤더
function secure(res: Response, req: Request) {
  const h = res.headers;
  h.set("x-content-type-options", "nosniff");
  h.set("referrer-policy", "no-referrer");
  h.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  h.set("cross-origin-opener-policy", "same-origin");
  if (isHttpsReq(req)) h.set("strict-transport-security", "max-age=31536000");
  return res;
}
function isHttpsReq(req: Request) { return !!TLS || (NET.trustProxy && (req.headers.get("x-forwarded-proto") || "").startsWith("https")); }
const handler = {
  async fetch(req: Request) { return secure(await route(req), req); },
};
async function route(req: Request): Promise<Response> {
    const url = new URL(req.url);
    // 내부 인증 기관(CA) 인증서 내려받기 (로그인 전 · 공개해도 되는 파일) → PC에 설치하면 '주의 요함' 경고가 사라짐
    if (url.pathname === "/ca.crt" && CA_CERT) {
      const pemTxt = readFileSync(CA_CERT, "utf-8");
      const derB = Buffer.from(pemTxt.replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""), "base64");
      return new Response(derB, { headers: { "content-type": "application/x-x509-ca-cert", "content-disposition": "attachment; filename=\"workmgmt-ca.crt\"", "cache-control": "no-store" } });
    }
    // 인증서 지문 (설치 안내의 '보안 경고' 창과 비교) · 안내 그림
    if (url.pathname === "/ca-info") {
      let sha1 = "";
      if (CA_CERT) { const der = Buffer.from(readFileSync(CA_CERT, "utf-8").replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""), "base64"); sha1 = (createHash("sha1").update(der).digest("hex").toUpperCase().match(/.{8}/g) || []).join(" "); }
      return new Response(JSON.stringify({ sha1 }), { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
    }
    if (url.pathname.startsWith("/guide/") && GUIDE[url.pathname.slice(7)]) return new Response(Buffer.from(GUIDE[url.pathname.slice(7)], "base64"), { headers: { "content-type": "image/png", "cache-control": "max-age=86400" } });
    // 프록시 뒤에서 HTTP로 들어오면 HTTPS로 넘김
    if (NET.trustProxy && NET.httpsOnly && !isHttpsReq(req)) {
      const host = req.headers.get("x-forwarded-host") || req.headers.get("host") || url.host;
      return new Response(null, { status: 308, headers: { location: `https://${host}${url.pathname}${url.search}` } });
    }
    try {
      if (url.pathname.startsWith("/api/")) return await handle(req, url);
      if (url.pathname === "/app.js") return new Response(APPJS, { headers: { "content-type": "text/javascript; charset=utf-8", "cache-control": "no-cache" } });
      if (url.pathname === "/style.css") return new Response(CSS, { headers: { "content-type": "text/css; charset=utf-8", "cache-control": "no-cache" } });
      if (url.pathname === "/version") return new Response(VERSION);
      return new Response(INDEX, { headers: { "content-type": "text/html; charset=utf-8", "content-security-policy": CSP, "x-frame-options": "DENY", "cache-control": "no-cache" } });
    } catch (e: any) {
      if (e instanceof HttpError) return new Response(JSON.stringify({ error: e.message }), { status: e.status, headers: { "content-type": "application/json; charset=utf-8" } });
      console.error(new Date().toISOString(), url.pathname, e);
      return new Response(JSON.stringify({ error: "서버 오류 (관리자에게 문의)" }), { status: 500, headers: { "content-type": "application/json; charset=utf-8" } });
    }
}
let PORT = 0;
for (let p = PORT0; p <= (TRY_NEXT ? PORT0 + 10 : PORT0); p++) {
  try { Bun.serve({ ...handler, port: p, hostname: "0.0.0.0", ...(TLS ? { tls: TLS } : {}) }); PORT = p; break; }
  catch (e: any) {
    if (e?.code !== "EADDRINUSE") throw e;
    console.log(`포트 ${p} 를 다른 프로그램이 쓰고 있습니다.` + (TRY_NEXT && p < PORT0 + 10 ? ` → ${p + 1} 로 다시 시도` : ""));
  }
}
if (!PORT) {
  console.log("");
  console.log(`포트 ${PORT0} 를 다른 프로그램이 쓰고 있어 시작하지 못했습니다.`);
  console.log(`  누가 쓰는지 확인: 명령 프롬프트에서  netstat -ano | findstr :${PORT0}  → 맨 끝 숫자(PID)로  tasklist /fi "pid eq 숫자"`);
  console.log(`  다른 포트로 실행: 업무관리.exe --port 8080   (방화벽 규칙 · 바로가기 주소도 같은 번호로)`);
  process.exit(1);
}
if (PORT !== PORT0) console.log(`※ ${PORT0} 대신 ${PORT} 로 열었습니다. 주소를 확인하세요.`);
if (CA_CERT) console.log(`[HTTPS] 경고를 없애려면 각 PC에서 https://<주소>:${PORT}/ca.crt 를 내려받아 '신뢰할 수 있는 루트 인증 기관'에 설치`);
// HTTPS 직접 실행일 때: HTTP 포트로 들어오면 HTTPS로 넘김
if (TLS && HTTP_PORT) {
  try { Bun.serve({ port: HTTP_PORT, hostname: "0.0.0.0", fetch(req) { const u = new URL(req.url); return new Response(null, { status: 308, headers: { location: `https://${u.hostname}:${PORT}${u.pathname}${u.search}` } }); } }); console.log(`http://…:${HTTP_PORT} → https 로 넘김`); }
  catch { console.log(`HTTP 넘김용 포트 ${HTTP_PORT} 를 열지 못했습니다 (HTTPS는 정상)`); }
}
openBrowser(PORT);
console.log(`회로팀 업무관리 (${VERSION}) 실행 중 · ${TLS ? "https" : "http"}://localhost:${PORT} · 데이터: ${DATA}${NET.trustProxy ? " · 프록시 뒤 (X-Forwarded-Proto 신뢰)" : ""}`);
console.log("이 창을 닫으면 사이트가 멈춥니다.");
