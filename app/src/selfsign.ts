// 사내 인증서가 없을 때 HTTPS용 인증서 — 외부 프로그램(openssl) 없이 node:crypto 로 만듦
// 내부 인증 기관(CA) 1개 + 그 CA가 서명한 서버 인증서 (ECDSA P-256 · SHA-256 · SAN · serverAuth)
import { generateKeyPairSync, sign, randomBytes, createHash, createPrivateKey, createPublicKey, X509Certificate, KeyObject } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";

const len = (n: number) => n < 128 ? Buffer.from([n]) : n < 256 ? Buffer.from([0x81, n]) : Buffer.from([0x82, n >> 8, n & 255]);
const tlv = (tag: number, body: Buffer) => Buffer.concat([Buffer.from([tag]), len(body.length), body]);
const seq = (...x: Buffer[]) => tlv(0x30, Buffer.concat(x));
const set = (...x: Buffer[]) => tlv(0x31, Buffer.concat(x));
const oid = (s: string) => { const p = s.split(".").map(Number); const out = [40 * p[0] + p[1]];
  for (const v of p.slice(2)) { const b: number[] = []; let n = v; do { b.unshift(n & 127); n = Math.floor(n / 128); } while (n); for (let i = 0; i < b.length - 1; i++) b[i] |= 128; out.push(...b); }
  return tlv(0x06, Buffer.from(out)); };
const int = (b: Buffer) => tlv(0x02, b[0] & 0x80 ? Buffer.concat([Buffer.from([0]), b]) : b);
const utf8 = (s: string) => tlv(0x0c, Buffer.from(s, "utf8"));
const octet = (b: Buffer) => tlv(0x04, b);
const bits = (b: Buffer) => tlv(0x03, Buffer.concat([Buffer.from([0]), b]));
const gtime = (d: Date) => tlv(0x18, Buffer.from(d.toISOString().replace(/[-:T]/g, "").slice(0, 14) + "Z"));
const explicit = (n: number, b: Buffer) => tlv(0xa0 + n, b);
const name = (cn: string) => seq(set(seq(oid("2.5.4.3"), utf8(cn))), set(seq(oid("2.5.4.10"), utf8("회로팀 업무관리 (자체 서명)"))));

const pem = (label: string, b: Buffer) => `-----BEGIN ${label}-----\n${b.toString("base64").match(/.{1,64}/g)!.join("\n")}\n-----END ${label}-----\n`;
const der = (p: string) => Buffer.from(p.replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""), "base64");
const ski = (spki: Buffer) => createHash("sha1").update(spki).digest();
const crit = tlv(0x01, Buffer.from([0xff]));
// 0.7.8: DER 에서 TLV 하나 읽기 (태그 1바이트 · 길이 최대 4바이트)
function tlvAt(b: Buffer, off: number) {
  let l = b[off + 1], h = 2;
  if (l & 0x80) { const n = l & 0x7f; l = 0; for (let i = 0; i < n; i++) l = l * 256 + b[off + 2 + i]; h = 2 + n; }
  return { tag: b[off], start: off, body: off + h, end: off + h + l };
}
// 0.7.8: CA 인증서의 '주체(subject)' 원본 바이트 — 서버 인증서의 '발급자'는 이것과 바이트까지 같아야 PC가 둘을 잇는다
//   (예전 CA는 조직 이름이 지금 코드와 달라 이름을 다시 만들면 어긋남)
export function caSubject(caCertPem: string): Buffer {
  const d = der(caCertPem.split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----");
  const tbs = tlvAt(d, tlvAt(d, 0).body);
  let o = tbs.body;
  if (d[o] === 0xa0) o = tlvAt(d, o).end;         // version
  o = tlvAt(d, o).end;                             // serial
  o = tlvAt(d, o).end;                             // signature algorithm
  o = tlvAt(d, o).end;                             // issuer
  o = tlvAt(d, o).end;                             // validity
  const sub = tlvAt(d, o);                         // subject
  return d.subarray(sub.start, sub.end);
}
function cert(subject: Buffer, issuer: Buffer, spki: Buffer, signKey: KeyObject, days: number, exts: Buffer[]) {
  const sigAlg = seq(oid("1.2.840.10045.4.3.2"));
  const now = new Date(Date.now() - 3600e3), end = new Date(now.getTime() + days * 864e5);
  const serial = randomBytes(16); serial[0] &= 0x7f;
  const tbs = seq(explicit(0, int(Buffer.from([2]))), int(serial), sigAlg, issuer, seq(gtime(now), gtime(end)), subject, spki, explicit(3, seq(...exts)));
  return seq(tbs, sigAlg, bits(sign("sha256", tbs, { key: signKey, dsaEncoding: "der" })));
}
const CA_NAME = "회로팀 업무관리 내부 인증 기관";
// 내부 인증 기관(CA) — 한 번 만들어 10년 사용. 이 CA 인증서를 PC에 '신뢰'로 설치하면 경고가 사라짐
export function makeCA() {
  const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  const spki = publicKey.export({ type: "spki", format: "der" }) as Buffer;
  const nm = name(CA_NAME), k = ski(spki);
  const c = cert(nm, nm, spki, privateKey, 3650, [
    seq(oid("2.5.29.19"), crit, octet(seq(tlv(0x01, Buffer.from([0xff]))))),                 // basicConstraints CA:TRUE
    seq(oid("2.5.29.15"), crit, octet(tlv(0x03, Buffer.from([0x01, 0x06])))),               // keyUsage keyCertSign · cRLSign
    seq(oid("2.5.29.14"), octet(octet(k))),                                                   // subjectKeyIdentifier
  ]);
  return { cert: pem("CERTIFICATE", c), key: privateKey.export({ type: "pkcs8", format: "pem" }) as string };
}
// 서버 인증서 — 내부 CA가 서명 · SAN(IP · 이름) · 825일
export function makeServer(hosts: string[], caCertPem: string, caKeyPem: string) {
  const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  const spki = publicKey.export({ type: "spki", format: "der" }) as Buffer;
  const caKey = createPrivateKey(caKeyPem);
  const caSpki = createPublicKey(caKey).export({ type: "spki", format: "der" }) as Buffer;
  const san = hosts.map(h => /^\d+\.\d+\.\d+\.\d+$/.test(h) ? tlv(0x87, Buffer.from(h.split(".").map(Number))) : tlv(0x82, Buffer.from(h)));
  const c = cert(name(hosts[0]), caSubject(caCertPem), spki, caKey, 825, [
    seq(oid("2.5.29.17"), octet(seq(...san))),
    seq(oid("2.5.29.19"), crit, octet(seq())),
    seq(oid("2.5.29.15"), crit, octet(tlv(0x03, Buffer.from([0x07, 0x80])))),
    seq(oid("2.5.29.37"), octet(seq(oid("1.3.6.1.5.5.7.3.1")))),
    seq(oid("2.5.29.14"), octet(octet(ski(spki)))),
    seq(oid("2.5.29.35"), octet(seq(tlv(0x80, ski(caSpki))))),                                // authorityKeyIdentifier
  ]);
  return { cert: pem("CERTIFICATE", c) + caCertPem, key: privateKey.export({ type: "pkcs8", format: "pem" }) as string };
}
// 열쇠 폴더에 CA · 서버 인증서가 없으면 만들고, 접속 주소(hosts)가 바뀌었거나 만료가 가까우면 서버 인증서만 새로 만듦
export function ensureSelfSigned(dir: string, hosts: string[]) {
  mkdirSync(dir, { recursive: true });
  const caC = join(dir, "ca-cert.pem"), caK = join(dir, "ca-key.pem"), sc = join(dir, "server-cert.pem"), sk = join(dir, "server-key.pem"), sh = join(dir, "server-hosts.txt");
  if (!existsSync(caC) || !existsSync(caK)) {
    const ca = makeCA(); writeFileSync(caC, ca.cert); writeFileSync(caK, ca.key, { mode: 0o600 });
    console.log(`[HTTPS] 내부 인증 기관(CA)을 만들었습니다: ${caC} — 이 인증서를 PC에 설치하면 '주의 요함' 경고가 사라집니다`);
    for (const f of [sc, sk]) if (existsSync(f)) writeFileSync(f, "");
  }
  const want = hosts.join(",");
  let renew = !existsSync(sc) || !existsSync(sk) || !readFileSync(sc, "utf-8").trim() || (existsSync(sh) ? readFileSync(sh, "utf-8") : "") !== want;
  if (!renew) { try {
    const x = new X509Certificate(readFileSync(sc, "utf-8")), ca = new X509Certificate(readFileSync(caC, "utf-8"));
    renew = new Date(x.validTo).getTime() - Date.now() < 30 * 864e5
      || x.issuer !== ca.subject || !x.checkIssued(ca) || !x.verify(ca.publicKey);   // 0.7.8: CA와 안 이어지는 서버 인증서는 새로 만듦
  } catch { renew = true; } }
  if (renew) {
    const r = makeServer(hosts, readFileSync(caC, "utf-8"), readFileSync(caK, "utf-8"));
    writeFileSync(sc, r.cert); writeFileSync(sk, r.key, { mode: 0o600 }); writeFileSync(sh, want);
    console.log(`[HTTPS] 서버 인증서를 만들었습니다 (${hosts.join(", ")})`);
  }
  return { cert: sc, key: sk, ca: caC };
}
