// 회로팀 업무관리 웹 - 사내 서버(NAS)에서 실행하는 프로그램
//   실행: 업무관리.exe [--port 8000] [--data <폴더>]   (기본 데이터 폴더 = 프로그램 옆 '데이터')
//   HTTPS 직접: --cert cert.pem --key key.pem [--http-port 8000]  (--port 는 HTTPS 포트, --http-port 로 들어오면 HTTPS로 넘김)
//   HTTPS 자체 서명: --self-signed [--cert-hosts 192.168.0.10]  (인증서를 열쇠 폴더에 한 번 만들어 계속 씀)
//   HTTPS 프록시 뒤 (시놀로지 역방향 프록시 등): --behind-proxy [--https-only]
//   비밀값 열쇠: 환경변수 WL_SECRET_KEY 또는 --key-file <파일> (기본: 프로그램 옆 '비밀키\secret.key')
//   같은 설정을 환경변수로도: WL_PORT WL_DATA WL_TLS_CERT WL_TLS_KEY WL_HTTP_PORT WL_BEHIND_PROXY=1 WL_HTTPS_ONLY=1 WL_KEY_FILE
import { openDb, q, q1, run, backup, getSetting, setSetting, notify, db } from "./db";
import { importSeed, mergeSeed, ensureFixedRows } from "./seed";
import { handle, HttpError, NET, setupNeeded, acctFiles } from "./api";
import { syncFolders } from "./share";
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
import { FONT_CSS, FONTS } from "./fonts_kr";   // 0.7.2: Noto Sans KR (tools/mk_fonts.py 가 만듦)
import { createHash } from "node:crypto";

export const VERSION = "업무관리 0.8.0";
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
  // 0.7.8: 접속 주소(WL_CERT_HOSTS)를 정해 두면 컨테이너 내부 주소는 넣지 않음 — 다시 빌드해 내부 주소가 바뀌어도 서버 인증서를 새로 만들지 않게
  const fixed = arg("--cert-hosts", process.env.WL_CERT_HOSTS || "").split(",").map(x => x.trim()).filter(Boolean);
  const hosts = Array.from(new Set([...fixed, ...(fixed.length ? [] : ips), "localhost", "127.0.0.1"]));
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
// 0.7.6: 이슈 폴더 맞추기 — 시작 10초 뒤 · 30분마다 (연결 안 돼 있으면 아무것도 안 함 · 손으로 옮긴 폴더도 다시 찾음)
let lastSkip = "";
const folders = async () => { try { const r = await syncFolders(null); const ch = r.results.filter(x => x.result !== "있음"); if (ch.length) console.log("[이슈 폴더]", ch.map(x => `${x.no} ${x.result}`).join(" · ")); if (!r.ok && r.why && r.why !== lastSkip) console.log("[이슈 폴더] 건너뜀:", r.why); lastSkip = r.ok ? "" : r.why; } catch (e) { console.error("이슈 폴더 맞추기 실패", e); } };
setTimeout(folders, 10e3); setInterval(folders, 30 * 60e3);

const CSP = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'";
// 버전이 바뀌면 모든 사람에게 알림 (우상단 🔔)
const NOTES: Record<string, string> = {
  "업무관리 0.8.0": "한 업무에 모델 여러 개 (업무 추가 · 수정 · 업무 지정) · 다중 모델 업무와 새 기본 행 '외근'은 시간을 넣으면 모델별 시간 · 한 일을 나눠 적음 (합계 = 칸 시간 · Esc 면 다중 모델은 똑같이, 외근은 공통) · 업무 로드와 모델별 시간 표는 모델별로 나눈 시간 × 각 모델 배율 · 주간 · 월간 한 일 보기 새 디자인 (요약 · 이슈 / 업무 / 기본 행 구역 · 시간 많은 순 · 비중 막대) · 모든 창 크기 조절 (오른쪽 아래 모서리 · 창마다 기억 · 제목 줄 더블클릭 = 원래 크기 · 공지 · 알림 제외) · 요청 내용 복사 버튼 · 폴더 바로 열기 빠르게 (PowerShell 대신 설치할 때 만드는 작은 실행 파일 · 다시 설치 필요)",
  "업무관리 0.7.9": "이슈 폴더 바로 열기: 내 정보 > '폴더 바로 열기'에서 설치 파일을 받아 PC에 한 번 설치하면 이슈 번호 옆 📁 를 누를 때 탐색기에서 그 폴더가 바로 열림 (workfolder: 링크 · 내 계정에만 설치 · 이슈 폴더 아래만 열고 그 밖은 거부) · 설치 여부는 PC · 브라우저마다 체크 · 설치하지 않은 PC는 지금처럼 경로 복사",
  "업무관리 0.7.8": "HTTPS 인증서: 서버 인증서를 새로 만들 때 발급자 이름을 내부 인증 기관(CA) 인증서에서 그대로 가져옴 (예전 CA 이름과 달라 PC가 '신뢰할 수 없음'으로 보던 문제 고침) · 켤 때 CA와 이어지지 않는 서버 인증서는 자동으로 다시 만듦 · 접속 주소를 정해 두면 컨테이너 내부 주소는 인증서에 넣지 않아, 다시 빌드해도 서버 인증서가 바뀌지 않음",
  "업무관리 0.7.7": "이슈 폴더: 파일 서버가 느리거나 답하지 않을 때 사이트 전체가 멈추던 문제 고침 (파일 서버 작업을 기다리지 않고 따로 처리 · 작업마다 8초 제한 · 넘으면 그 회차를 멈추고 10분 뒤 다시) · 폴더 목록은 회차마다 한 번만 읽음 · 이슈 등록은 폴더를 기다리지 않고 바로 끝남",
  "업무관리 0.7.6": "이슈 폴더: 이슈를 등록하면 파일 서버(이슈 자료 폴더)에 '모델 \\ 번호 이슈명' 폴더를 자동으로 만듦 · 이미 있는 이슈도 모두 만듦 · 번호만으로 만들어 둔 예전 폴더(예: 26-012)는 모델 폴더 안으로 옮기며 이름을 바꿈 (권한이 없으면 관리 > 이슈 폴더에 옮길 목록) · 이슈 번호를 누르면 폴더 경로 복사 (Win + R → Ctrl + V → Enter 로 열기) · 관리 > 이슈 폴더 (연결 상태 · 연결 시험 · 지금 맞추기 · 경로) · 시작할 때와 30분마다 자동으로 맞춤 · 파일 서버 연결이 끊기면 아무것도 만들지 않음",
  "업무관리 0.7.5": "시간 입력 표 날짜 머리글 · 하루 합계를 누르면 그날 한 일 팝업 (업무 · 이슈별 시간 + ✎ 내용, 안 적은 줄은 업무 제목 · ◀ ▶ · ← →) · [주간 한 일 보기] / [월간 한 일 보기] 팝업 (업무 · 이슈마다 합계 + 날짜별 시간 · 한 일, 전체 / 이슈 / 업무 거르기, 앞뒤 주 · 달) — 내 업무 · 사람별 · PL 일을 준 사람 화면 모두 · 시간을 넣고 칸을 나가면 바로 '한 일 한 줄' 입력 칸 (Enter 저장 · Esc 건너뛰기 · 내 정보에서 끄기) · 시간은 있는데 한 일이 없으면 ✎ 주황 · ✎ 창에 '팀장 · PL이 봅니다' 안내 · 공지 · 알림 팝업을 뺀 모든 창을 Esc 로 닫음 (쓴 내용이 있으면 '저장하지 않고 닫을까요?')",
  "업무관리 0.7.4": "PPT 내보내기: 항목 제목(1-1 등)과 그 내용의 글자 크기를 항상 1pt 차이로 (11.5/10.5 → 최소 9.5/8.5) · '-'처럼 기호만 적힌 항목 · 줄은 빠짐 (내보내기 창에도 '비어 있음') · 배포하지 않은 버전 공지 초안이 있으면 새 버전 내용을 그 초안 뒤에 이어 붙임 (고친 문구 유지)",
  "업무관리 0.7.3": "이슈 창 [PPT 내보내기]: 연구소 표준용지 한 장에 4칸 내용(+ 기본 정보 · 첨부 이미지 · 이전 기록)을 넣고 글자 수에 맞춰 배치 · 글자 크기를 바꿈 (최소 9pt, 그래도 넘치면 유첨 장), 넣을 항목을 고르고 사람마다 기억 · 기준정보 '이슈 템플릿' 탭(마스터 · 팀장): 4칸 제목 · 항목 이름 · 설명 · 순서를 고치고 항목 추가 · 지우기 · 살리기 (지운 항목에 써 둔 글은 '삭제된 항목'으로 남음) · 모든 창을 제목 줄로 끌어 옮김 · 이슈 등록 · 수정 창과 업무 창은 띄운 채로 뒤 목록을 보고 다른 이슈를 열 수 있음",
  "업무관리 0.7.2": "이슈 4칸 이름을 현상 진단 · 원인 규명 · 대책 수립 · 검증 적용으로, 칸 안을 템플릿 항목(1-1 불량 증상 … 4-5 기준서 개정)으로 나눔 (예전 글은 각 칸 '이전 기록'에 그대로) · 이슈 창 크게 열고 크기 조절 · 이슈 요약 탭을 이슈 정리 맨 위 카드로 (누르면 그 조건만) · 완료 이슈 회색 · PL이 일을 준 사람의 '내 업무' 읽기 전용 보기 · PL이 다른 파트 사람에게도 업무 지정 (그 파트 PL에게 알림) · 하루 합계는 일한 시간만, 아래에 연차 · 반차 · 조퇴 · 이슈 등록 · 수정 창에서도 이미지 붙여넣기 · 글꼴 Noto Sans KR",
  "업무관리 0.7.1": "완료된 업무 · 이슈는 최신 완료일이 위로 (시간 입력 표 '완료' 묶음 · 업무 목록 · 내 이슈) · PL은 담당이 아니어도 우리 파트 진행 중 이슈가 '내 업무' 시간 입력 표에 'PL 관리'로 보임 (시간 입력 가능 · 누르면 이슈 창에서 4칸 · 정보 수정) · PL만 '내 업무'에 '+ 이슈 등록' 버튼 · 비밀번호 칸에서 Caps Lock 이 켜져 있으면 안내",
  "업무관리 0.7.0": "알림을 화면 가운데 팝업으로 (공지 · 업무 지정/변경 · 이슈 담당 지정/변경 · 요청 도착/답변 · 업데이트 안내, '확인'을 눌러야 닫힘 · 🔔 숫자도 같이 · 미입력 알림은 🔔만) · 공지 메뉴 (마스터 · 팀장이 전체 · 파트 · 개인에게 보냄 · 지난 공지 보기) · 버전이 바뀌면 마스터에게 공지 초안 → 고쳐서 배포 (자동 버전 알림 없앰) · 업무 지정에 '요약' 칸 · 새로 지정되거나 바뀐 업무 · 이슈에 빨간 점 (탭의 점은 탭을 열면, 행의 점은 행을 누르면 꺼짐)",
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
// 0.7.0: 버전이 바뀌면 전원에게 바로 알리지 않고, 마스터에게 '공지 초안'을 띄움 → 마스터가 고쳐서 [배포]하면 전원에게 팝업
// 공지용 글: 핵심만 짧게 (한 줄에 하나). 여러 버전을 건너뛰어 올리면 그 사이 것을 모두 넣음
const NOTICE: [string, string[]][] = [
  ["업무관리 0.6.0", ["이슈를 누르면 진행 현황 4칸 (현상 · 원인 분석 · 개선검토 · 검증 및 적용) — PL · 팀장이 작성", "이슈 첨부 이미지 한 장 (Ctrl+V · 끌어다 놓기), 이슈 정리 🖼 버튼으로 보기", "이슈 요약에 발생일 · 현재 진행 추가", "내 업무 월간 보기, 업무로드 이전 / 다음 버튼", "업무 추가 창에서 모델 · 업무 분류 검색"]],
  ["업무관리 0.7.0", ["업무 · 이슈가 지정되거나 바뀌면 화면 가운데 팝업 ('확인'을 눌러야 닫힘)", "새로 지정된 업무 · 이슈에 빨간 점 표시", "공지 메뉴 추가 (지난 공지 보기)"]],
  ["업무관리 0.7.1", ["완료된 업무 · 이슈는 최신 완료일이 위로", "PL은 우리 파트 이슈가 '내 업무'에 'PL 관리'로 보임 (시간 입력 · 누르면 수정), '+ 이슈 등록' 버튼", "비밀번호 입력 시 Caps Lock 안내"]],
  ["업무관리 0.7.2", ["이슈 4칸 이름 변경 (현상 진단 · 원인 규명 · 대책 수립 · 검증 적용), 칸 안에 템플릿 항목 — 예전 글은 '이전 기록'에 그대로", "이슈 창을 크게 열고 모서리를 끌어 크기 조절 (크기 기억)", "이슈 요약 탭 → 이슈 정리 맨 위 카드 (누르면 그 조건만 보기), 완료 이슈는 회색", "PL: 일을 준 사람의 '내 업무' 읽기 전용 보기, 다른 파트 사람에게도 업무 지정", "하루 합계는 일한 시간만 + 연차 · 반차 · 조퇴 표시", "이슈 등록 · 수정 창에서도 이미지 Ctrl+V", "글꼴 Noto Sans KR"]],
  ["업무관리 0.7.3", ["이슈 창 [PPT 내보내기] — 연구소 표준용지 한 장 (글이 많으면 글자를 줄이고, 그래도 넘치면 유첨 장)", "넣을 내용(기본 정보 · 이미지 · 칸 · 항목)을 고를 수 있고 고른 것은 기억", "기준정보 '이슈 템플릿' — 4칸 제목 · 항목을 마스터 · 팀장이 고침 (지운 항목의 글은 남음)", "모든 창을 제목 줄로 끌어 옮기기", "이슈 등록 · 수정 · 업무 창을 띄운 채로 뒤 목록 보기 · 다른 이슈 열어 보기"]],
  ["업무관리 0.7.4", ["PPT 항목 제목과 내용 글자 크기를 1pt 차이로 맞춤", "'-'만 적힌 항목은 PPT에서 자동으로 빠짐"]],
  ["업무관리 0.7.5", ["시간 입력 표의 날짜(또는 하루 합계)를 누르면 그날 한 일이 팝업으로", "[주간 한 일 보기] — 이번 주 업무 · 이슈별 시간과 한 일을 한 창에 (월간 보기에서는 월간)", "시간을 넣으면 바로 '한 일 한 줄' 입력 칸 (Enter 저장 · Esc 건너뛰기, 내 정보에서 끄기)", "시간은 있는데 한 일을 안 적은 칸은 ✎가 주황", "모든 창을 Esc 로 닫기 (공지 · 알림 제외, 쓴 내용이 있으면 확인)"]],
  ["업무관리 0.7.6", ["이슈마다 파일 서버(이슈 자료 폴더)에 '모델 \\ 번호 이슈명' 폴더가 자동으로 생김 (새 이슈는 등록할 때)", "이슈 번호를 누르면 폴더 경로가 복사됨 → Win + R → Ctrl + V → Enter 로 폴더 열기"]],
  ["업무관리 0.7.7", ["파일 서버가 느릴 때 사이트가 잠시 멈추던 문제를 고쳤습니다"]],
  ["업무관리 0.7.8", ["'연결이 비공개로 설정되어 있지 않습니다' 경고가 다시 뜨던 문제를 고쳤습니다 (인증서를 다시 설치할 필요 없음)"]],
  ["업무관리 0.7.9", ["내 정보 > '폴더 바로 열기'를 한 번 설치하면 이슈 번호 옆 📁 를 누를 때 폴더가 바로 열립니다"]],
  ["업무관리 0.8.0", ["한 업무에 모델을 여러 개 고를 수 있고, 시간을 넣으면 모델별로 시간 · 한 일을 나눕니다", "기본 행에 '외근'이 생겼습니다 (시간을 넣고 모델별로 나누기)", "주간 · 월간 한 일 보기가 보기 쉽게 바뀌었습니다", "창 오른쪽 아래 모서리를 끌어 크기를 바꿀 수 있습니다", "받은 요청에 [복사] 버튼이 생겼습니다", "폴더 바로 열기를 쓰는 분은 내 정보에서 다시 설치하면 훨씬 빨라집니다"]],
];
{
  const last = getSetting("last_version", "");
  if (last !== VERSION) {
    const at = NOTICE.findIndex(([v]) => v === last);
    const news = NOTICE.slice(at + 1).slice(-3);   // 지난 버전 다음부터 (0.5.8에서 바로 올리면 0.6.0 + 0.7.0) · 많아도 최근 3개 버전
    const lines = news.flatMap(([, ls]) => ls);
    if (lines.length && q1("SELECT 1 FROM users WHERE active=1")) {
      const ver = VERSION.replace("업무관리 ", "");
      // 0.7.4: 배포하지 않은 예전 초안이 있으면 그 글(마스터가 고친 문구 포함) 뒤에 새 버전 내용을 이어 붙여 한 번에 공지
      const olds = q("SELECT id, body FROM notices WHERE status='draft' AND kind='버전' ORDER BY id");
      const body = [...olds.map((d: any) => String(d.body || "").trim()).filter(Boolean), lines.map(l => "· " + l).join("\n")].join("\n");
      for (const d of olds) run("DELETE FROM notices WHERE id=?", d.id);
      run("UPDATE notifs SET ack=1 WHERE pop=1 AND ack=0 AND kind='버전' AND data LIKE '%draft_id%'");
      const r = run("INSERT INTO notices(kind,title,body,status,version) VALUES('버전',?,?,'draft',?)", `업무관리 ${ver} 업데이트 안내`, body, VERSION);
      const id = Number(r.lastInsertRowid);
      notify(q("SELECT id FROM users WHERE active=1 AND role='master'").map((x: any) => x.id), "버전", `${VERSION} 로 업데이트됐습니다 · 공지 초안을 확인하고 배포해 주세요`, "#/notices",
        { pop: true, data: { what: "버전 공지 초안", 제목: `업무관리 ${ver} 업데이트 안내`, 본문: body, 안내: "공지 메뉴에서 문구를 고쳐 [배포]하면 팀원에게 팝업으로 갑니다. 배포 전에는 마스터에게만 보입니다.", draft_id: id } });
    }
    setSetting("last_version", VERSION);
  }
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
    if (url.pathname === "/fonts/noto.css") return new Response(FONT_CSS, { headers: { "content-type": "text/css; charset=utf-8", "cache-control": "max-age=604800" } });
    if (url.pathname.startsWith("/fonts/") && FONTS[url.pathname.slice(7)]) return new Response(Buffer.from(FONTS[url.pathname.slice(7)], "base64"), { headers: { "content-type": "font/woff2", "cache-control": "public, max-age=31536000, immutable" } });
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
