// 비밀값 암호화 (SMTP 비밀번호 등) — AES-256-GCM
// 열쇠는 데이터베이스와 다른 곳에 둠: ① 환경변수 WL_SECRET_KEY  ② 열쇠 파일 (--key-file 또는 WL_KEY_FILE, 기본: 프로그램 옆 '비밀키\secret.key')
// 열쇠 파일은 데이터 폴더(자동 백업 대상) 밖에 있으므로 DB나 백업 파일만으로는 비밀번호를 풀 수 없음
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

let KEY: Buffer | null = null;
export let KEY_SOURCE = "";
export function initSecret(keyFile: string) {
  const env = process.env.WL_SECRET_KEY;
  if (env && env.length >= 16) { KEY = createHash("sha256").update(env).digest(); KEY_SOURCE = "환경변수 WL_SECRET_KEY"; return; }
  if (!existsSync(keyFile)) {
    mkdirSync(dirname(keyFile), { recursive: true });
    writeFileSync(keyFile, randomBytes(32).toString("base64"), { mode: 0o600 });
    console.log(`[보안] 비밀값 열쇠 파일을 만들었습니다: ${keyFile} (이 파일이 없으면 저장한 메일 비밀번호를 다시 넣어야 합니다)`);
  }
  KEY = createHash("sha256").update(readFileSync(keyFile, "utf-8").trim()).digest(); KEY_SOURCE = "열쇠 파일";
}
export function enc(plain: string): string {
  if (!plain) return "";
  const iv = randomBytes(12); const c = createCipheriv("aes-256-gcm", KEY!, iv);
  const ct = Buffer.concat([c.update(plain, "utf8"), c.final()]);
  return "enc:v1:" + Buffer.concat([iv, c.getAuthTag(), ct]).toString("base64");
}
export function dec(stored: string): string {
  if (!stored) return "";
  if (!stored.startsWith("enc:v1:")) return stored;   // 0.3.0 이전 평문 (시작할 때 암호화로 바꿈)
  const b = Buffer.from(stored.slice(7), "base64");
  const d = createDecipheriv("aes-256-gcm", KEY!, b.subarray(0, 12)); d.setAuthTag(b.subarray(12, 28));
  return Buffer.concat([d.update(b.subarray(28)), d.final()]).toString("utf8");
}
export function isEnc(s: string) { return s.startsWith("enc:v1:"); }
// 임시 비밀번호 · 인증번호 (암호학적 난수)
export function randCode(n = 6) { const a = new Uint32Array(n); crypto.getRandomValues(a); return Array.from(a, x => String(x % 10)).join("").replace(/^0/, "1"); }
export function tempPw(n = 10) {
  const cs = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"; const a = new Uint32Array(n); crypto.getRandomValues(a);
  return Array.from(a, x => cs[x % cs.length]).join("");
}
