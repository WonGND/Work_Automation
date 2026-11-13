// 메일 보내기 (비밀번호 찾기 인증번호). 사내 메일 서버(SMTP) 설정은 관리 > 메일 설정
import nodemailer from "nodemailer";
import { getSetting } from "./db";
import { dec } from "./secret";

export function mailReady() {
  if (!getSetting("smtp_host", "") || !getSetting("mail_from", "")) return false;
  if (getSetting("smtp_user", "")) { try { dec(getSetting("smtp_pass", "")); } catch { return false; } }   // 열쇠가 바뀌어 비밀번호를 못 풀면 사용 안 함
  return true;
}
export async function sendMail(to: string, subject: string, text: string) {
  const host = getSetting("smtp_host", ""); if (!host) throw new Error("메일 서버(SMTP)가 설정되지 않았습니다");
  const port = Number(getSetting("smtp_port", "25")) || 25;
  const user = getSetting("smtp_user", "");
  const tr = nodemailer.createTransport({
    host, port, secure: getSetting("smtp_secure", "0") === "1",
    auth: user ? { user, pass: dec(getSetting("smtp_pass", "")) } : undefined,
    tls: { rejectUnauthorized: getSetting("smtp_tls_check", "1") === "1" },
    connectionTimeout: 10000, greetingTimeout: 10000, socketTimeout: 15000,
  });
  await tr.sendMail({ from: getSetting("mail_from", ""), to, subject, text });
}
