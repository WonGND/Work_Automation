// 0.7.3: 이슈 → PPT 한 장 (연구소 표준용지 양식 + DESIGN 규격)
// 양식 파일(.pptx)을 열어 1장의 제목 상자(TextBox 1)만 고쳐 쓰고, 안내 문구(TextBox 2)는 지운다.
// 단위: cm (EMU = cm × 360000). 콘텐츠 영역 좌 0.99 ~ 33.35, 위 1.47 ~ 17.99.
import { unzipSync, zipSync, strToU8, strFromU8 } from "fflate";

export type PptItem = { code: string; label: string; text: string };
export type PptBox = { title: string; items: PptItem[]; old?: string };
export type PptIssue = {
  no: string; model: string; title: string;
  info?: { label: string; value: string }[];      // 기본 정보 (없으면 표를 그리지 않음)
  delay?: string;                                   // 지연 사유 (있으면 표 아래 줄)
  boxes: PptBox[];                                  // 현상 진단 · 원인 규명 · 대책 수립 · 검증 적용 (순서 고정, 4개)
  image?: { data: Uint8Array; ext: string } | null;
};

const EMU = 360000, X0 = 0.99, X1 = 33.35, Y0 = 1.47, Y1 = 17.99, GAP = 0.25, H = Y1 - Y0;
let FONT = "맑은 고딕";   // 양식 제목 상자(TextBox 1)의 글꼴을 그대로 씀 (buildPptx 에서 읽음)
const SUB_H = 0.71, PAD = 0.15, LS = 1.2;
const e = (cm: number) => Math.round(cm * EMU);
const esc = (s: string) => String(s ?? "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// ── 글자 폭 추정 (DESIGN 4.2: 한글 1자 = pt × 0.035 cm, 영문 · 숫자 = 그 0.55배) ──
const cw = (ch: string, pt: number) => (/[ᄀ-ᇿ　-鿿가-힯＀-￯]/.test(ch) ? 1 : 0.55) * pt * 0.035;
function wrapCount(text: string, pt: number, width: number) {
  let lines = 0;
  for (const raw of String(text).split("\n")) {
    let w = 0, n = 1;
    for (const ch of raw) { const c = cw(ch, pt); if (w + c > width && w > 0) { n++; w = c; } else w += c; }
    lines += n;
  }
  return lines;
}
// 줄 높이: 글꼴 기본 줄 높이(약 1.2em) × 줄 간격 1.2 — 넘치지 않게 넉넉히 잡음
const lineH = (pt: number) => pt * 0.03528 * 1.2 * LS;
const textW = (s: string, pt: number) => [...s].reduce((a, ch) => a + cw(ch, pt), 0);

// ── 칸 안의 문단 (제목 줄 12pt + " - 내용" 10.5pt) ──
type Para = { kind: "label" | "body" | "dash" | "note"; text: string; pt: number; h: number; gap?: boolean };
const IND = 0.4;   // " - " 내어쓰기
// 이미 "-", "•", "1.", "(1)", "①" 등으로 시작하는 줄은 그대로 둔다
const OWN = /^\s*([-•·*▶▷■□○●※→]|\(?\d{1,2}[).]|[①-⑳]|[가-하][.)])\s*/;
// 0.7.4: "-" · "." 처럼 기호만 적힌 내용은 빈 것으로 봄 (항목 · 줄째 뺌)
export const blank = (t: string) => !String(t ?? "").replace(/[-–—_·•.,~\s]/g, "");
function boxParas(b: PptBox, lpt: number, bpt: number, width: number): Para[] {
  const out: Para[] = [];
  const add = (kind: Para["kind"], text: string, pt: number, w: number, extra = 0) => out.push({ kind, text, pt, h: wrapCount(text, pt, w) * lineH(pt) + extra, gap: extra > 0 });
  for (const it of b.items) {
    if (blank(it.text)) continue;                                // 빈 항목("-"만 적은 것 포함)은 줄째 뺀다
    add("label", [it.code, it.label].filter(Boolean).join(" "), lpt, width, out.length ? 0.1 : 0);
    for (const ln of String(it.text).replace(/\r/g, "").split("\n").filter(x => !blank(x))) add("body", ln.trim(), bpt, width - IND);
  }
  if (b.old && !blank(b.old)) {
    add("label", "이전 기록", lpt, width, out.length ? 0.1 : 0);
    for (const ln of b.old.replace(/\r/g, "").split("\n").filter(x => !blank(x))) add("body", ln.trim(), bpt, width - IND);
  }
  if (!out.length) add("dash", "-", bpt, width);                 // 칸 전체가 비면 "-"
  return out;
}
const sumH = (ps: Para[]) => ps.reduce((a, p) => a + p.h, 0);

// ── 기본 정보 표 ──
type Table = { cols: number[]; rows: { h: number; cells: { text: string; head?: boolean; span?: number }[] }[]; pt: number };
function infoTable(iss: PptIssue, width: number, pt: number): Table | null {
  if (!iss.info?.length) return null;
  const n = iss.info.length;
  const wts = iss.info.map(c => Math.max(textW(c.label, pt) + 0.3, Math.min(textW(c.value || "-", pt) + 0.3, 5)));
  const sw = wts.reduce((a, b) => a + b, 0);
  const cols = wts.map(w => width * w / sw);
  const rowH = (texts: string[], spans?: number[]) => {
    let lines = 1; let ci = 0;
    texts.forEach((t, k) => { const span = spans?.[k] || 1; const w = cols.slice(ci, ci + span).reduce((a, b) => a + b, 0) - 0.2; ci += span; lines = Math.max(lines, wrapCount(t || "-", pt, Math.max(0.5, w))); });
    return Math.max(0.45, lines * lineH(pt) + 0.12);
  };
  const rows: Table["rows"] = [
    { h: rowH(iss.info.map(c => c.label)), cells: iss.info.map(c => ({ text: c.label, head: true })) },
    { h: rowH(iss.info.map(c => c.value || "-")), cells: iss.info.map(c => ({ text: c.value || "-" })) },
  ];
  if (iss.delay && iss.delay.trim() && n >= 2) rows.push({ h: rowH(["지연 사유", iss.delay], [1, n - 1]), cells: [{ text: "지연 사유", head: true }, { text: iss.delay, span: n - 1 }] });
  return { cols, rows, pt };
}
const tableH = (t: Table | null) => t ? t.rows.reduce((a, r) => a + r.h, 0) : 0;

// ── 이미지 크기 (PNG · JPEG 머리에서 읽음) ──
function imgSize(d: Uint8Array): [number, number] | null {
  if (d[0] === 0x89 && d[1] === 0x50) return [(d[16] << 24 | d[17] << 16 | d[18] << 8 | d[19]) >>> 0, (d[20] << 24 | d[21] << 16 | d[22] << 8 | d[23]) >>> 0];
  if (d[0] === 0xff && d[1] === 0xd8) {
    let i = 2;
    while (i < d.length - 9) {
      if (d[i] !== 0xff) { i++; continue; }
      const m = d[i + 1], len = d[i + 2] << 8 | d[i + 3];
      if (m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc) return [d[i + 7] << 8 | d[i + 8], d[i + 5] << 8 | d[i + 6]];
      i += 2 + len;
    }
  }
  return null;
}

// ── 배치 계산 ──
type Section = { box: number; x: number; y: number; w: number; h: number; paras: Para[]; table?: Table | null; img?: { w: number; h: number } | null; more?: Para[] };
export type Layout = { wL: number; scale: { label: number; body: number; table: number }; sections: Section[]; overflow: boolean; split: [number, number] };

function sectionNeed(s: { paras: Para[]; table?: Table | null; img?: { w: number; h: number } | null }) {
  let h = SUB_H + 0.1 + PAD;                        // 소제목 박스 + 여백
  if (s.table) h += tableH(s.table) + 0.15;
  h += sumH(s.paras);
  if (s.img) h += 0.15 + s.img.h;
  return h;
}

export function layoutIssue(iss: PptIssue): Layout {
  const sz = iss.image ? imgSize(iss.image.data) : null;
  // [항목 제목, 내용, 기본 정보 표] — 0.7.4: 제목과 내용은 항상 1pt 차이 (11.5/10.5 → 9.5/8.5)
  const SCALES = [[11.5, 10.5, 10], [11, 10, 9.5], [10.5, 9.5, 9], [10, 9, 8.5], [9.5, 8.5, 8]];
  const DEF_WL = 14.0;
  const wLs = [DEF_WL]; for (let w = 9.5; w <= 15.001; w += 0.25) if (Math.abs(w - DEF_WL) > 0.01) wLs.push(+w.toFixed(2));
  wLs.sort((a, b) => Math.abs(a - DEF_WL) - Math.abs(b - DEF_WL));
  const build = (wL: number, sc: number[]) => {
    const wR = X1 - X0 - GAP - wL;
    const inner = (w: number) => w - 2 * PAD;
    const [lpt, bpt, tpt] = sc;
    const table = infoTable(iss, inner(wL), tpt);
    let img: { w: number; h: number } | null = null;
    if (sz && sz[0] && sz[1]) { const mh = 3.2, mw = inner(wL); let ih = mh, iw = ih * sz[0] / sz[1]; if (iw > mw) { iw = mw; ih = iw * sz[1] / sz[0]; } img = { w: iw, h: ih }; }
    const sec = [0, 1, 2, 3].map(k => ({ paras: boxParas(iss.boxes[k], lpt, bpt, inner(k < 2 ? wL : wR)), table: k === 0 ? table : null, img: k === 0 ? img : null }));
    return { wR, sec, need: sec.map(sectionNeed) };
  };
  // 1) 기본 크기 → 2) 위아래 경계 이동 → 3) 좌우 폭 → 4) 글자 축소 순으로 들어가는 첫 배치를 고른다
  for (const sc of SCALES) for (const wL of wLs) {
    const b = build(wL, sc);
    const fitSide = (t: number, btm: number) => b.need[t] + b.need[btm] <= H;
    if (fitSide(0, 1) && fitSide(2, 3)) return place(iss, wL, b, sc, false);
  }
  // 9pt까지 줄여도 넘치면: 가장 적게 넘치는 폭을 고르고, 넘친 줄은 유첨 장으로
  const sc = SCALES[SCALES.length - 1];
  let best = wLs[0], bestOver = Infinity;
  for (const wL of wLs) { const b = build(wL, sc); const o = Math.max(0, b.need[0] + b.need[1] - H) + Math.max(0, b.need[2] + b.need[3] - H); if (o < bestOver) { bestOver = o; best = wL; } }
  return place(iss, best, build(best, sc), sc, true);
}

function place(iss: PptIssue, wL: number, b: any, sc: number[], over: boolean): Layout {
  const xs = [X0, X0, X0 + wL + GAP, X0 + wL + GAP], ws = [wL, wL, b.wR, b.wR];
  const split = (t: number, btm: number) => {
    const nt = b.need[t], nb = b.need[btm];
    if (nt <= H / 2 && nb <= H / 2) return H / 2;                         // 기본: 반씩
    if (nt + nb <= H) return nt > H / 2 ? Math.min(nt + 0.3, H - Math.max(nb, 2.5)) : H - nb;   // 위가 많으면 위 내용 끝 + 0.3, 아래가 많으면 아래에 필요한 만큼
    return Math.max(4, Math.min(H - 4, H * nt / (nt + nb)));             // 넘칠 때: 필요량 비율
  };
  const sL = split(0, 1), sR = split(2, 3);
  const sections: Section[] = [0, 1, 2, 3].map(k => {
    const top = k % 2 === 0, s = k < 2 ? sL : sR;
    const y = top ? Y0 : Y0 + s, h = top ? s : H - s;
    const sec: Section = { box: k, x: xs[k], y, w: ws[k], h, paras: b.sec[k].paras, table: b.sec[k].table, img: b.sec[k].img };
    if (over) {   // 넘치는 문단은 유첨으로 (이미지가 있으면 이미지는 남기고 글을 넘김)
      let room = h - (SUB_H + 0.1 + PAD) - (sec.table ? tableH(sec.table) + 0.15 : 0) - (sec.img ? sec.img.h + 0.15 : 0);
      const fit: Para[] = [], more: Para[] = [];
      const noteH = lineH(sc[1]);
      for (const p of sec.paras) { if (!more.length && room - p.h >= noteH) { fit.push(p); room -= p.h; } else more.push(p); }
      while (more.length && fit.length && fit[fit.length - 1].kind === "label") more.unshift(fit.pop()!);   // 항목 제목만 남기지 않음
      if (more.length && more[0].kind === "body") { const lb = [...fit].reverse().find(p => p.kind === "label"); if (lb) more.unshift({ ...lb, text: lb.text + " (이어서)" }); }
      if (more.length) { sec.paras = [...fit, { kind: "note", text: "→ 유첨 p.2 에서 이어짐", pt: sc[1], h: noteH }]; sec.more = more; }
    }
    return sec;
  });
  return { wL, scale: { label: sc[0], body: sc[1], table: sc[2] }, sections, overflow: sections.some(s => s.more?.length), split: [sL, sR] };
}

// ── XML 조각 ──
const rpr = (pt: number, extra = "") => `<a:rPr lang="ko-KR" altLang="en-US" sz="${Math.round(pt * 100)}" dirty="0"${extra}><a:solidFill><a:srgbClr val="000000"/></a:solidFill><a:latin typeface="${FONT}"/><a:ea typeface="${FONT}"/></a:rPr>`;
const ln = (w: number, c: string) => `<a:ln w="${w}"><a:solidFill><a:srgbClr val="${c}"/></a:solidFill><a:prstDash val="solid"/></a:ln>`;
const xfrm = (x: number, y: number, w: number, h: number) => `<a:xfrm><a:off x="${e(x)}" y="${e(y)}"/><a:ext cx="${e(w)}" cy="${e(h)}"/></a:xfrm>`;
let SID = 10;
const rect = (name: string, x: number, y: number, w: number, h: number, fill: string, line: string, text = "", pt = 12) =>
  `<p:sp><p:nvSpPr><p:cNvPr id="${SID++}" name="${name}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>${xfrm(x, y, w, h)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>${fill}${line}</p:spPr>` +
  `<p:txBody><a:bodyPr wrap="none" lIns="${e(0.1)}" rIns="${e(0.1)}" tIns="0" bIns="0" rtlCol="0" anchor="ctr"><a:noAutofit/></a:bodyPr><a:lstStyle/><a:p><a:pPr algn="ctr"/>${text ? `<a:r>${rpr(pt)}<a:t>${esc(text)}</a:t></a:r>` : `<a:endParaRPr lang="ko-KR" sz="${pt * 100}"/>`}</a:p></p:txBody></p:sp>`;
const line = (x1: number, y: number, x2: number) =>
  `<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="${SID++}" name="구분선"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr>${xfrm(x1, y, x2 - x1, 0)}<a:prstGeom prst="line"><a:avLst/></a:prstGeom>${ln(6350, "000000")}</p:spPr></p:cxnSp>`;
function paraXml(p: Para) {
  const sp = `<a:lnSpc><a:spcPct val="${LS * 100000}"/></a:lnSpc>`;
  if (p.kind === "label") return `<a:p><a:pPr>${sp}${p.gap ? `<a:spcBef><a:spcPts val="283"/></a:spcBef>` : ""}</a:pPr><a:r>${rpr(p.pt)}<a:t>${esc(p.text)}</a:t></a:r></a:p>`;
  if (p.kind === "body") { const own = OWN.test(p.text); return `<a:p><a:pPr marL="${e(own ? 0.15 : IND)}" indent="${own ? 0 : -e(0.25)}">${sp}</a:pPr><a:r>${rpr(p.pt)}<a:t>${esc(own ? p.text : "- " + p.text)}</a:t></a:r></a:p>`; }
  if (p.kind === "note") return `<a:p><a:pPr algn="r">${sp}</a:pPr><a:r>${rpr(p.pt)}<a:t>${esc(p.text)}</a:t></a:r></a:p>`;
  return `<a:p><a:pPr>${sp}</a:pPr><a:r>${rpr(p.pt)}<a:t>-</a:t></a:r></a:p>`;
}
const textBox = (x: number, y: number, w: number, h: number, paras: Para[]) =>
  `<p:sp><p:nvSpPr><p:cNvPr id="${SID++}" name="본문"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>${xfrm(x, y, w, h)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>` +
  `<p:txBody><a:bodyPr wrap="square" lIns="0" rIns="0" tIns="0" bIns="0" rtlCol="0" anchor="t"><a:noAutofit/></a:bodyPr><a:lstStyle/>${paras.map(paraXml).join("")}</p:txBody></p:sp>`;
function tableXml(t: Table, x: number, y: number) {
  const bd = ["lnL", "lnR", "lnT", "lnB"].map(k => `<a:${k} w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:srgbClr val="000000"/></a:solidFill><a:prstDash val="solid"/></a:${k}>`).join("");
  const W = t.cols.reduce((a, b) => a + b, 0);
  const rows = t.rows.map(r => {
    const cells: string[] = [];
    for (const c of r.cells) {
      cells.push(`<a:tc${c.span && c.span > 1 ? ` gridSpan="${c.span}"` : ""}><a:txBody><a:bodyPr/><a:lstStyle/>${String(c.text).split("\n").map(x => `<a:p><a:pPr algn="ctr"/><a:r>${rpr(t.pt)}<a:t>${esc(x)}</a:t></a:r></a:p>`).join("")}</a:txBody>` +
        `<a:tcPr marL="${e(0.08)}" marR="${e(0.08)}" marT="${e(0.04)}" marB="${e(0.04)}" anchor="ctr">${bd}${c.head ? `<a:solidFill><a:srgbClr val="D9D9D9"/></a:solidFill>` : "<a:noFill/>"}</a:tcPr></a:tc>`);
      for (let k = 1; k < (c.span || 1); k++) cells.push(`<a:tc hMerge="1"><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="ko-KR"/></a:p></a:txBody><a:tcPr>${bd}<a:noFill/></a:tcPr></a:tc>`);
    }
    return `<a:tr h="${e(r.h)}">${cells.join("")}</a:tr>`;
  }).join("");
  return `<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="${SID++}" name="기본 정보"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>` +
    `<p:xfrm><a:off x="${e(x)}" y="${e(y)}"/><a:ext cx="${e(W)}" cy="${e(tableH(t))}"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">` +
    `<a:tbl><a:tblPr firstRow="1"/><a:tblGrid>${t.cols.map(c => `<a:gridCol w="${e(c)}"/>`).join("")}</a:tblGrid>${rows}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>`;
}
const picXml = (rid: string, x: number, y: number, w: number, h: number) =>
  `<p:pic><p:nvPicPr><p:cNvPr id="${SID++}" name="첨부 이미지"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="${rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr>${xfrm(x, y, w, h)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>`;

// 소제목 박스: 글자 폭 + 0.5, 최소 3.44
const subBox = (x: number, y: number, title: string) => rect("소제목", x, y, Math.max(3.44, textW(title, 12) + 0.5), SUB_H, `<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>`, ln(9525, "808080"), title, 12);

function sectionXml(s: Section, title: string, imgRid: string) {
  let out = subBox(s.x, s.y, title);
  let y = s.y + SUB_H + 0.1;
  const x = s.x + PAD, w = s.w - 2 * PAD;
  if (s.table) { out += tableXml(s.table, x, y); y += tableH(s.table) + 0.15; }
  const th = sumH(s.paras);
  const bottom = s.y + s.h - PAD - (s.img ? s.img.h + 0.15 : 0);
  out += textBox(x, y, w, Math.max(0.5, bottom - y), s.paras);
  if (s.img && imgRid) { const iy = Math.min(y + th + 0.2, s.y + s.h - PAD - s.img.h); out += picXml(imgRid, x + (w - s.img.w) / 2, iy, s.img.w, s.img.h); }
  return out;
}

// 제목 상자(TextBox 1)의 글자만 바꾼다 (서식 유지)
function setTitle(sld: string, title: string) {
  return sld.replace(/(<p:sp><p:nvSpPr><p:cNvPr id="\d+" name="TextBox 1">[\s\S]*?<p:txBody>[\s\S]*?<a:p>)([\s\S]*?)(<\/a:p><\/p:txBody><\/p:sp>)/, (_m, a, body, c) => {
    const r = body.match(/<a:rPr[\s\S]*?<\/a:rPr>/)?.[0] || "";
    const end = body.match(/<a:endParaRPr[\s\S]*?<\/a:endParaRPr>/)?.[0] || "";
    a = a.replace(/(<a:ext cx=")\d+(")/, `$1${e(textW(title, 18) + 0.6)}$2`);
    return a + `<a:r>${r.replace(/ err="1"/, "")}<a:t>${esc(title)}</a:t></a:r>` + end + c;
  });
}
const dropBox2 = (sld: string) => sld.replace(/<p:sp><p:nvSpPr><p:cNvPr id="\d+" name="TextBox 2">[\s\S]*?<\/p:sp>/, "");

export function buildPptx(tpl: Uint8Array, iss: PptIssue, L = layoutIssue(iss)): Uint8Array {
  const z = unzipSync(tpl);
  const s1 = "ppt/slides/slide1.xml";
  if (!z[s1] || !/name="TextBox 1"/.test(strFromU8(z[s1]))) throw new Error("PPT 양식에 1장 제목 상자(TextBox 1)가 없습니다");
  const base = dropBox2(strFromU8(z[s1]));
  FONT = base.match(/name="TextBox 1"[\s\S]*?<a:ea typeface="([^"]+)"/)?.[1] || base.match(/name="TextBox 1"[\s\S]*?<a:latin typeface="([^"]+)"/)?.[1] || "맑은 고딕";
  const titleText = `■ [${iss.no}] ${iss.model ? iss.model + " · " : ""}${iss.title}`;
  SID = 10;
  // 이미지
  let rid = "";
  if (iss.image && L.sections[0].img) {
    const ext = iss.image.ext === "jpg" ? "jpeg" : iss.image.ext;
    const name = `ppt/media/issue_img.${ext}`;
    z[name] = iss.image.data;
    rid = "rIdImg1";
    const rels = strFromU8(z["ppt/slides/_rels/slide1.xml.rels"]);
    z["ppt/slides/_rels/slide1.xml.rels"] = strToU8(rels.replace("</Relationships>", `<Relationship Id="${rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/issue_img.${ext}"/></Relationships>`));
    const ct = strFromU8(z["[Content_Types].xml"]);
    if (!new RegExp(`Extension="${ext}"`, "i").test(ct)) z["[Content_Types].xml"] = strToU8(ct.replace("<Default ", `<Default Extension="${ext}" ContentType="image/${ext}"/><Default `));
  }
  const frame = (secs: Section[], titles: string[], rid2: string) => {
    let x = "";
    // 외곽 사각형 (좌 · 우), 위아래 구역 사이 구분선
    const left = secs.filter(s => s.box < 2), right = secs.filter(s => s.box >= 2);
    for (const side of [left, right]) if (side.length) {
      const sx = side[0].x, sw = side[0].w;
      x += rect("외곽", sx, Y0, sw, H, "<a:noFill/>", ln(6350, "000000"));
      if (side.length === 2) x += line(sx, side[1].y, sx + sw);
    }
    secs.forEach((s, k) => { x += sectionXml(s, titles[k], s.box === 0 ? rid2 : ""); });
    return x;
  };
  const titles = (s: Section) => iss.boxes[s.box].title;
  // 유첨 장: 넘친 칸을 위에서부터 이어 씀 (전체 폭 외곽 1개). 한 장에 안 들어가면 p.3, p.4 … 로 이어짐
  const extra = L.sections.filter(s => s.more?.length);
  const W = X1 - X0;
  type Chunk = { box: number; paras: Para[] };
  const pages: Chunk[][] = [];
  if (extra.length) {
    let page: Chunk[] = [], y = Y0;
    const newPage = () => { pages.push(page); page = []; y = Y0; };
    for (const s of extra) {
      const paras = s.more!.map((p, i) => ({ ...p, gap: i > 0 && p.kind === "label", h: wrapCount(p.text, p.pt, W - 2 * PAD - (p.kind === "body" ? IND : 0)) * lineH(p.pt) + (i > 0 && p.kind === "label" ? 0.1 : 0) }));
      const head = SUB_H + 0.1 + PAD;
      if (Y1 - y < head + lineH(paras[0].pt) * 2) newPage();
      // 본문 칸의 안내 문구에 이어지는 쪽 번호
      const note = s.paras.find(p => p.kind === "note"); if (note) note.text = `→ 유첨 p.${pages.length + 2} 에서 이어짐`;
      let ch: Chunk = { box: s.box, paras: [] }; y += head;
      for (const p of paras) {
        if (y + p.h > Y1 - PAD && ch.paras.length) { page.push(ch); newPage(); ch = { box: s.box, paras: [] }; y += head; }
        ch.paras.push(ch.paras.length ? p : { ...p, gap: false, h: p.h - (p.gap ? 0.1 : 0) }); y += ch.paras[ch.paras.length - 1].h;
      }
      page.push(ch); y += 0.1;
    }
    if (page.length) pages.push(page);
  }
  let sld = setTitle(base, titleText).replace("</p:spTree>", frame(L.sections, L.sections.map(titles), rid) + "</p:spTree>");
  z[s1] = strToU8(sld);
  let ct = strFromU8(z["[Content_Types].xml"]), prels = strFromU8(z["ppt/_rels/presentation.xml.rels"]), pres = strFromU8(z["ppt/presentation.xml"]);
  let maxId = Math.max(255, ...[...pres.matchAll(/<p:sldId id="(\d+)"/g)].map(m => +m[1]));
  pages.forEach((pg, n) => {
    const no = n + 2;
    let inner = rect("외곽", X0, Y0, W, H, "<a:noFill/>", ln(6350, "000000")), y = Y0;
    pg.forEach((c, k) => {
      const hh = k === pg.length - 1 ? Y1 - y : SUB_H + 0.1 + PAD + sumH(c.paras) + 0.1;
      if (k) inner += line(X0, y, X1);
      inner += subBox(X0, y, iss.boxes[c.box].title);
      inner += textBox(X0 + PAD, y + SUB_H + 0.1, W - 2 * PAD, Math.max(0.5, hh - SUB_H - 0.1 - PAD), c.paras);
      y += hh;
    });
    z[`ppt/slides/slide${no}.xml`] = strToU8(setTitle(base, titleText + " (유첨)").replace("</p:spTree>", inner + "</p:spTree>"));
    z[`ppt/slides/_rels/slide${no}.xml.rels`] = strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>`);
    ct = ct.replace("</Types>", `<Override PartName="/ppt/slides/slide${no}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>`);
    prels = prels.replace("</Relationships>", `<Relationship Id="rIdSlide${no}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide${no}.xml"/></Relationships>`);
    pres = pres.replace(/(<p:sldIdLst>[\s\S]*?)(<\/p:sldIdLst>)/, `$1<p:sldId id="${++maxId}" r:id="rIdSlide${no}"/>$2`);
  });
  z["[Content_Types].xml"] = strToU8(ct); z["ppt/_rels/presentation.xml.rels"] = strToU8(prels); z["ppt/presentation.xml"] = strToU8(pres);
  return zipSync(z, { level: 6 });
}

// 파일 이름: "{모델명} {이슈명}_{YYMMDD}.pptx" (윈도우에서 못 쓰는 글자는 뺌)
export function pptName(model: string, title: string, d = new Date()) {
  const ymd = `${String(d.getFullYear()).slice(2)}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
  return `${[model, title].filter(Boolean).join(" ")}_${ymd}.pptx`.replace(/[\\/:*?"<>|\r\n]+/g, " ").replace(/\s+/g, " ").trim();
}
