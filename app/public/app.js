// 회로팀 업무관리 웹 - 화면
"use strict";
let M = null; // meta
const $ = (s, el = document) => el.querySelector(s);
const app = () => $("#app");

// ── 도우미 ──
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "value") el.value = v;
    else if (k === "checked" || k === "disabled" || k === "readOnly" || k === "selected") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}
async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { "content-type": "application/json", "x-req": "1" }, body: body === undefined ? undefined : JSON.stringify(body) });
  let d = {}; try { d = await r.json(); } catch {}
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error(d.error || "로그인이 필요합니다"); }
  if (!r.ok) throw new Error(d.error || `오류 ${r.status}`);
  return d;
}
function toast(msg, isErr) { const t = h("div", { class: isErr ? "e" : "" }, msg); $("#toast").append(t); setTimeout(() => t.remove(), isErr ? 6000 : 2500); }
const fmtPct = v => (v == null ? "-" : Math.round(v * 100) + "%");
const fmtH = v => (v == null ? "" : (Math.round(v * 10) / 10).toString());
const WD = ["일", "월", "화", "수", "목", "금", "토"];
const dd = s => { const d = new Date(s + "T00:00:00"); return `${d.getMonth() + 1}/${d.getDate()}(${WD[d.getDay()]})`; };
const addDays = (s, n) => { const d = new Date(s + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const monday = s => { const d = new Date(s + "T00:00:00Z"); const w = (d.getUTCDay() + 6) % 7; return addDays(s, -w); };
const userName = id => M.users.find(u => u.id === id)?.name || "";
const modelName = id => M.models.find(m => m.id === id)?.name || "";
const badge = (cls, txt) => (txt ? h("span", { class: "badge " + (cls || "") }, txt) : "");
const roleKo = { member: "팀원", pl: "PL", lead: "팀장", master: "마스터" };
function sel(options, value, attrs = {}) {
  return h("select", attrs, options.map(o => { const [v, t] = Array.isArray(o) ? o : [o, o]; return h("option", { value: v, selected: String(v) === String(value ?? "") }, t); }));
}
function modal(title, body, buttons) {
  const bg = h("div", { class: "modal-bg" });
  const close = () => bg.remove();
  const ft = h("div", { class: "ft" });
  for (const b of buttons || []) ft.append(h("button", { class: "btn " + (b.cls || ""), onclick: async () => { try { const r = await b.fn?.(); if (r !== false) close(); } catch (e) { toast(e.message, true); } } }, b.text));
  ft.append(h("button", { class: "btn", onclick: close }, "닫기"));
  bg.append(h("div", { class: "modal" }, h("div", { class: "hd" }, title), h("div", { class: "bd" }, body), ft));
  bg.addEventListener("mousedown", e => { if (e.target === bg) close(); });
  document.body.append(bg);
  return close;
}
function confirmBox(msg) {
  return new Promise(res => { let ok = false; const body = h("div", { class: "pre" }, msg);
    modal("확인", body, [{ text: "확인", cls: "pri", fn: () => { ok = true; res(true); } }]);
    const obs = new MutationObserver(() => { if (!body.isConnected) { obs.disconnect(); if (!ok) res(false); } }); obs.observe(document.body, { childList: true }); });
}
function field(label, el, full) { return [h("label", {}, label), full ? h("div", { class: "full" }, el) : el]; }
const modelsFor = part => M.models.filter(m => m.active && (!part || m.part === part));
const assignable = () => M.users.filter(u => u.active && u.role !== "lead");
const isPLUser = id => M.users.find(u => u.id === id)?.role === "pl";
// 이름 "홍길동 책임" → 이름은 줄바꿈 없이, 직급은 작게
const nameTag = full => { if (!full) return ""; const [n, ...r] = String(full).split(" "); return h("span", { class: "nm" }, h("b", {}, n), r.length ? h("small", {}, " " + r.join(" ")) : ""); };

// ── 날짜 입력: 연(4) · 월(2) · 일(2) 칸, 다 채우면 다음 칸으로, Tab이면 0을 채워 넘어감 ──
function dateInput(value, attrs = {}) {
  const [y0, m0, d0] = (value || "").split("-");
  const mk = (cls, len, ph, v) => h("input", { class: "dp " + cls, inputmode: "numeric", maxlength: len, placeholder: ph, value: v || "", disabled: attrs.disabled, autocomplete: "off" });
  const y = mk("y", 4, "연도", y0), m = mk("m", 2, "월", m0), d = mk("d", 2, "일", d0);
  const pick = h("input", { type: "date", class: "dp-native", tabindex: -1, disabled: attrs.disabled });
  const cal = h("button", { type: "button", class: "dp-cal", tabindex: -1, title: "달력에서 고르기", disabled: attrs.disabled }, "📅");
  const wrap = h("span", { class: "dt" + (attrs.disabled ? " dis" : "") }, y, h("i", {}, "-"), m, h("i", {}, "-"), d, cal, pick);
  const pad = el => { if (el.value.length === 1) el.value = "0" + el.value; };
  const setAll = s => { const mm = String(s).match(/(\d{4})\D?(\d{1,2})\D?(\d{1,2})/); if (!mm) return false; y.value = mm[1]; m.value = mm[2].padStart(2, "0"); d.value = mm[3].padStart(2, "0"); wrap.dispatchEvent(new Event("change", { bubbles: true })); return true; };
  const digits = el => { const v = el.value.replace(/\D/g, ""); if (v !== el.value) el.value = v; };
  y.addEventListener("input", () => { digits(y); if (y.value.length === 4) { m.focus(); m.select(); } });
  m.addEventListener("input", () => { digits(m); if (m.value.length === 2) { d.focus(); d.select(); } });
  d.addEventListener("input", () => digits(d));
  for (const el of [m, d]) el.addEventListener("blur", () => pad(el));
  for (const [el, prev] of [[m, y], [d, m]]) el.addEventListener("keydown", e => { if (e.key === "Backspace" && !el.value) { e.preventDefault(); prev.focus(); } });
  for (const el of [y, m, d]) {
    el.addEventListener("paste", e => { const t = e.clipboardData.getData("text"); if (setAll(t)) e.preventDefault(); });
    el.addEventListener("focus", () => el.select());
    el.addEventListener("change", e => { e.stopPropagation(); wrap.dispatchEvent(new Event("change", { bubbles: true })); });
  }
  // 빈 칸일 때 달력 값을 오늘로 미리 넣으면, 오늘을 눌러도 값이 그대로라 '바뀜'이 안 생겨 입력되지 않았음 → 빈 값으로 열기
  cal.addEventListener("click", () => { pick.value = wrap.value || ""; try { pick.showPicker(); } catch { pick.click(); } });
  for (const ev of ["change", "input"]) pick.addEventListener(ev, () => pick.value && pick.value !== wrap.value && setAll(pick.value));
  Object.defineProperty(wrap, "value", {
    get() { pad(m); pad(d); if (!y.value && !m.value && !d.value) return ""; return `${y.value}-${m.value}-${d.value}`; },
    set(v) { const [a, b, c] = (v || "").split("-"); y.value = a || ""; m.value = b || ""; d.value = c || ""; },
  });
  Object.defineProperty(wrap, "disabled", { set(v) { for (const el of [y, m, d, cal]) el.disabled = !!v; wrap.classList.toggle("dis", !!v); } });
  return wrap;
}

// ── 개인 설정 (열 너비 · 행 높이 · 접기) : 서버에 사람별로 저장 ──
const prefTimers = {};
function getPref(k, def) { const v = M?.prefs?.[k]; if (v == null) return def; try { return JSON.parse(v); } catch { return v; } }
function setPref(k, v) {
  M.prefs = M.prefs || {}; if (v == null) delete M.prefs[k]; else M.prefs[k] = JSON.stringify(v);
  clearTimeout(prefTimers[k]); prefTimers[k] = setTimeout(() => api("PUT", "/api/prefs", { [k]: v == null ? null : JSON.stringify(v) }).catch(() => {}), 500);
}

// 표 열 너비 · 행 높이 조절 (머리글 오른쪽 끝 / 첫 칸 아래쪽 끝을 끌기, 두 번 누르면 원래대로)
function resizable(table, key) {
  const widths = getPref("cw:" + key, {}) || {};
  const rowH = getPref("rh:" + key, 0);
  if (rowH) table.style.setProperty("--rowh", rowH + "px");
  table.classList.add("rsz");
  const ths = table.tHead ? [...table.tHead.rows[0].cells] : [];
  ths.forEach((th, i) => {
    if (widths[i]) { th.style.width = th.style.minWidth = th.style.maxWidth = widths[i] + "px"; }
    const g = h("span", { class: "col-grip", title: "끌어서 열 너비 조절 · 두 번 누르면 원래대로" });
    g.addEventListener("mousedown", e => {
      e.preventDefault(); e.stopPropagation();
      const x0 = e.clientX, w0 = th.getBoundingClientRect().width;
      document.body.classList.add("resizing");
      const mv = ev => { const w = Math.max(40, Math.round(w0 + ev.clientX - x0)); th.style.width = th.style.minWidth = th.style.maxWidth = w + "px"; widths[i] = w; };
      const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); document.body.classList.remove("resizing"); setPref("cw:" + key, widths); };
      document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up);
    });
    g.addEventListener("dblclick", e => { e.stopPropagation(); delete widths[i]; th.style.width = th.style.minWidth = th.style.maxWidth = ""; setPref("cw:" + key, widths); });
    g.addEventListener("click", e => e.stopPropagation());
    th.append(g);
  });
  // 행 높이: 아무 행의 첫 칸 아래 끝을 끌면 그 표의 모든 행 높이가 바뀜
  table.addEventListener("mousedown", e => {
    const td = e.target.closest("tbody td:first-child"); if (!td) return;
    const r = td.getBoundingClientRect(); if (e.clientY < r.bottom - 5) return;
    e.preventDefault();
    const y0 = e.clientY, h0 = r.height; document.body.classList.add("resizing-r");
    const mv = ev => { const v = Math.max(22, Math.round(h0 + ev.clientY - y0)); table.style.setProperty("--rowh", v + "px"); table.dataset.rh = v; };
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); document.body.classList.remove("resizing-r"); if (table.dataset.rh) setPref("rh:" + key, Number(table.dataset.rh)); };
    document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up);
  });
  table.addEventListener("mousemove", e => {
    const td = e.target.closest("tbody td:first-child");
    table.classList.toggle("rh-hover", !!td && e.clientY >= td.getBoundingClientRect().bottom - 5);
  });
  table.addEventListener("dblclick", e => {
    const td = e.target.closest("tbody td:first-child"); if (!td || e.clientY < td.getBoundingClientRect().bottom - 5) return;
    table.style.removeProperty("--rowh"); setPref("rh:" + key, null);
  });
  return table;
}

// 끌어서 순서 바꾸기: 행에 마우스를 올리면 ⠿ 손잡이가 보이고, 그걸 잡고 옮김
function dragHandle() { return h("span", { class: "grip", title: "잡고 끌어서 순서 바꾸기", onclick: e => e.stopPropagation() }, "⠿"); }
function sortable(tbody, rowSel, onDrop) {
  let drag = null;
  tbody.addEventListener("mousedown", e => { const g = e.target.closest(".grip"); if (!g) return; const tr = g.closest(rowSel); if (tr) tr.draggable = true; });
  tbody.addEventListener("dragstart", e => { drag = e.target.closest(rowSel); if (!drag) return; drag.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", drag.dataset.id || ""); });
  tbody.addEventListener("dragover", e => {
    if (!drag) return; e.preventDefault();
    const over = e.target.closest(rowSel); if (!over || over === drag || over.parentNode !== drag.parentNode) return;
    const r = over.getBoundingClientRect(); over.parentNode.insertBefore(drag, e.clientY < r.top + r.height / 2 ? over : over.nextSibling);
  });
  const end = async () => {
    if (!drag) return; const d = drag; drag = null; d.classList.remove("dragging"); d.draggable = false;
    const ids = [...tbody.querySelectorAll(rowSel)].map(tr => Number(tr.dataset.id)).filter(Boolean);
    try { await onDrop(ids); } catch (e) { toast(e.message, true); }
  };
  tbody.addEventListener("dragend", end);
  document.addEventListener("mouseup", () => { if (!drag) for (const tr of tbody.querySelectorAll("[draggable=true]")) tr.draggable = false; });
  tbody.addEventListener("drop", e => e.preventDefault());
}
async function saveOrder(ids) { await api("PUT", "/api/tasks/order", { ids }); toast("순서를 저장했습니다"); }

// 접기 · 펴기 (사람별로 기억)
function foldable(key, title, body, defOpen = false) {
  const open = getPref("fold:" + key, defOpen);
  const head = h("button", { class: "fold-hd" + (open ? " open" : ""), type: "button" }, h("span", { class: "car" }, "▸"), title);
  const box = h("div", { class: "fold-bd" }, body); box.hidden = !open;
  head.addEventListener("click", () => { box.hidden = !box.hidden; head.classList.toggle("open", !box.hidden); setPref("fold:" + key, !box.hidden); });
  return h("div", { class: "fold" }, head, box);
}

// ── 로그인 · 시작 ──
// 처음 설정 (관리자 비밀번호가 하나도 없을 때): 프로그램 창 · 로그에 나온 설정 코드 + 마스터/팀장 아이디 + 새 비밀번호
function showSetup() {
  $("#top").hidden = true;
  const code = h("input", { placeholder: "설정 코드 (프로그램 창 · 로그에 나온 8자리)", inputmode: "numeric" }), id = h("input", { placeholder: "마스터 또는 팀장 아이디 (예: 홍길동, 팀장)" });
  const n1 = h("input", { type: "password", placeholder: "새 비밀번호 (8자 이상)" }), n2 = h("input", { type: "password", placeholder: "새 비밀번호 확인" });
  const er = h("div", { class: "err small" });
  app().replaceChildren(h("div", { class: "login" }, h("h1", {}, "처음 설정"),
    h("div", { class: "help" }, "아직 관리자 비밀번호가 없습니다. 프로그램을 실행한 창(도커는 컨테이너 로그)에 나온 설정 코드로 관리자 비밀번호를 정합니다. 다른 사람의 처음 비밀번호는 로그인 후 관리 > 계정 > '비밀번호 초기화'로 만듭니다."),
    code, id, n1, n2, h("button", { class: "btn pri", onclick: async () => {
      if (n1.value !== n2.value) { er.textContent = "새 비밀번호 두 칸이 다릅니다"; return; }
      try { await api("POST", "/api/setup", { code: code.value.trim(), login: id.value.trim(), pw: n1.value }); toast("관리자 비밀번호를 정했습니다. 로그인하세요."); showLogin(); } catch (e) { er.textContent = e.message; }
    } }, "설정하기"), er));
  code.focus();
}
async function showLogin(msg) {
  try { const r = await fetch("/api/setup").then(x => x.json()); if (r.needed) return showSetup(); } catch {}
  $("#top").hidden = true;
  const id = h("input", { placeholder: "아이디 (이름)", autocomplete: "username" });
  const pw = h("input", { type: "password", placeholder: "비밀번호", autocomplete: "current-password" });
  const er = h("div", { class: "err small" }, msg || "");
  const go = async () => {
    try { const r = await api("POST", "/api/login", { login: id.value.trim(), pw: pw.value }); await boot(r.must_change); }
    catch (e) { er.textContent = e.message; }
  };
  pw.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  app().replaceChildren(h("div", { class: "login" }, h("h1", {}, "회로팀 업무관리"), h("div", { style: "margin-bottom:14px" }),
    id, pw, h("button", { class: "btn pri", onclick: go }, "로그인"), er,
    h("div", { style: "text-align:center;margin-top:14px" }, h("button", { class: "link2", onclick: () => showForgot(id.value.trim()) }, "비밀번호를 잊었나요?")),
    location.protocol === "https:" ? certBox() : ""));
  id.focus();
}
// 내부 인증서 설치 안내 (PC마다 한 번) — 그림 따라 하기
const CERT_DONE = "wl_cert_done";
function certBox() {
  let done = false; try { done = localStorage.getItem(CERT_DONE) === "1"; } catch {}
  if (done) return h("div", { style: "text-align:center;margin-top:6px" }, h("button", { class: "link2", onclick: certHelp }, "🔒 인증서 설치 안내 다시 보기"));
  return h("button", { class: "cert-box", onclick: certHelp },
    h("div", { class: "cb-t" }, "🔒 주소창에 '주의 요함'이 보이나요?"),
    h("div", { class: "cb-s" }, "인증서 설치 (PC마다 한 번 · 1분) — 그림 보고 따라 하기 ▶"));
}
const CERT_STEPS = [
  "인증서 내려받기 → 받은 파일 열기", "'열기 - 보안 경고'가 뜨면 [열기]", "[인증서 설치] 누르기", "[현재 사용자] 그대로 → [다음]",
  "[모든 인증서를 다음 저장소에 저장] → [찾아보기]", "[신뢰할 수 있는 루트 인증 기관] → [확인]", "칸 확인 → [다음]", "[마침]",
  "보안 경고 → [예]", "'가져오기를 완료했습니다' → [확인]", "크롬 · 엣지를 모두 닫고 다시 접속"];
async function certHelp() {
  let i = 0, fp = "";
  try { fp = (await fetch("/ca-info").then(r => r.json())).sha1 || ""; } catch {}
  const img = h("img", { class: "cert-img", alt: "" });
  const cap = h("div", { class: "cert-cap" }), extra = h("div"), dots = h("div", { class: "cert-dots" });
  const prev = h("button", { class: "btn", onclick: () => go(i - 1) }, "◀ 이전"), next = h("button", { class: "btn pri", onclick: () => go(i + 1) }, "다음 ▶");
  const dl = h("a", { class: "btn pri cert-dl", href: "/ca.crt", download: "workmgmt-ca.crt", onclick: () => setTimeout(() => go(1), 600) }, "⬇ 인증서 내려받기");
  const finish = h("button", { class: "btn pri", onclick: () => { try { localStorage.setItem(CERT_DONE, "1"); } catch {} close(); toast("브라우저 창을 모두 닫고 다시 열면 '주의 요함'이 없어집니다"); if ($("#top").hidden) showLogin(); } }, "설치 끝 (이 안내 접기)");
  const go = n => {
    i = Math.max(0, Math.min(CERT_STEPS.length - 1, n));
    img.src = `/guide/c${i + 1}.png`;
    cap.replaceChildren(h("b", {}, `${i + 2} / ${CERT_STEPS.length + 1}`), "  ", CERT_STEPS[i]);
    extra.replaceChildren(
      i === 0 ? h("div", { class: "row", style: "margin:4px 0 10px" }, dl, h("span", { class: "muted small" }, "다운로드 목록이 안 보이면 Ctrl + J")) : "",
      i === 8 && fp ? h("div", { class: "cert-fp" }, "창의 지문(sha1)이 이 값과 같으면 [예]: ", h("code", {}, fp)) : "");
    dots.replaceChildren(...CERT_STEPS.map((_, k) => h("span", { class: k === i ? "on" : "", onclick: () => go(k) })));
    prev.disabled = i === 0; next.hidden = i === CERT_STEPS.length - 1; finish.hidden = i !== CERT_STEPS.length - 1;
  };
  const key = e => { if (e.key === "ArrowRight") go(i + 1); if (e.key === "ArrowLeft") go(i - 1); };
  document.addEventListener("keydown", key);
  const close = modal("주소창 '주의 요함' 없애기 · 그림대로 따라 하기", h("div", {}, cap, extra, img, dots,
    h("div", { class: "row", style: "justify-content:center;gap:10px;margin-top:8px" }, prev, next, finish),
    h("div", { class: "help", style: "margin-top:10px" }, "회사 PC 정책으로 설치가 막히면 IT팀에 '업무관리 인증서 배포'를 요청하세요 (그룹 정책으로 한 번에 설치). 인증서 이름: 회로팀 업무관리 내부 인증 기관")), []);
  const obs = new MutationObserver(() => { if (!document.body.contains(img)) { document.removeEventListener("keydown", key); obs.disconnect(); } });
  obs.observe(document.body, { childList: true });
  go(0);
}
// 비밀번호 찾기: 아이디 + 회사 메일 → 인증번호 메일 → 인증번호 + 새 비밀번호
function showForgot(login0) {
  $("#top").hidden = true;
  const id = h("input", { placeholder: "아이디 (이름)", value: login0 || "" }), em = h("input", { placeholder: "등록한 회사 메일" });
  const code = h("input", { placeholder: "메일로 받은 인증번호 6자리", inputmode: "numeric", maxlength: 6 });
  const n1 = h("input", { type: "password", placeholder: "새 비밀번호 (6자 이상)" }), n2 = h("input", { type: "password", placeholder: "새 비밀번호 확인" });
  const msg = h("div", { class: "small", style: "margin:4px 0 10px;min-height:18px" });
  const step2 = h("div", {}, h("div", { class: "muted small", style: "margin-top:6px" }, "2. 인증번호와 새 비밀번호"), code, n1, n2,
    h("button", { class: "btn pri", onclick: async () => {
      if (n1.value !== n2.value) { msg.className = "err small"; msg.textContent = "새 비밀번호 두 칸이 다릅니다"; return; }
      try { await api("POST", "/api/reset/confirm", { login: id.value.trim(), code: code.value.trim(), new: n1.value }); toast("비밀번호를 바꿨습니다. 새 비밀번호로 로그인하세요."); showLogin(); }
      catch (e) { msg.className = "err small"; msg.textContent = e.message; }
    } }, "새 비밀번호로 바꾸기"));
  step2.hidden = true;
  app().replaceChildren(h("div", { class: "login" }, h("h1", {}, "비밀번호 찾기"),
    h("div", { class: "muted small" }, "1. 아이디와 '내 정보'에 등록한 회사 메일"), id, em,
    h("button", { class: "btn pri", onclick: async () => {
      try { const r = await api("POST", "/api/reset/request", { login: id.value.trim(), email: em.value.trim() }); msg.className = "small"; msg.textContent = r.msg; step2.hidden = false; code.focus(); }
      catch (e) { msg.className = "err small"; msg.textContent = e.message; }
    } }, "인증번호 받기"), msg, step2,
    h("div", { class: "help", style: "margin-top:14px" }, "메일을 등록하지 않았거나 메일이 오지 않으면:", h("br"),
      h("button", { class: "btn sm", style: "margin-top:6px", onclick: async () => { if (!id.value.trim()) { msg.className = "err small"; msg.textContent = "아이디를 적어 주세요"; return; } const r = await api("POST", "/api/reset/askadmin", { login: id.value.trim() }); msg.className = "small"; msg.textContent = r.msg; } }, "팀장 · 마스터에게 초기화 요청")),
    h("div", { style: "text-align:center;margin-top:10px" }, h("button", { class: "link2", onclick: () => showLogin() }, "← 로그인으로"))));
  (login0 ? em : id).focus();
}

async function boot(forcePw) {
  try { M = await api("GET", "/api/meta"); } catch { return; }
  $("#top").hidden = false;
  applyTheme(getPref("theme", (() => { try { return localStorage.getItem("theme") || ""; } catch { return ""; } })()));
  applyDark(getPref("dark", (() => { try { return localStorage.getItem("dark") || "0"; } catch { return "0"; } })()));
  $("#who").textContent = `${M.user.name} · ${roleKo[M.user.role]}${M.user.part ? " · " + M.user.part : ""}`;
  if (forcePw || M.user.must_change) { location.hash = "#/pw"; }
  buildNav(); route(); setBell(M.notifUnread);
  if (!M.myEmail && !M.user.must_change) { try { if (!sessionStorage.getItem("emailTip")) { sessionStorage.setItem("emailTip", "1"); setTimeout(() => toast("비밀번호를 잊었을 때를 위해 오른쪽 위 '내 정보'에서 회사 메일을 등록해 주세요"), 1200); } } catch {} }
}
// ── 알림 (우상단 🔔) ──
function setBell(n) { const b = $("#bellN"); b.hidden = !n; b.textContent = n > 99 ? "99+" : n; }
const NK = { 업무: "📋", 이슈: "⚠", 요청: "✉", 버전: "⬆", 계정: "🔑" };
async function openBell() {
  const pn = $("#bellPanel");
  if (!pn.hidden) { pn.hidden = true; return; }
  const d = await api("GET", "/api/notifs"); setBell(d.unread);
  const item = n => h("div", { class: "bn-it" + (n.read ? "" : " new"), onclick: async () => { if (!n.read) await api("POST", "/api/notifs/read", { id: n.id }); pn.hidden = true; const r = await api("GET", "/api/notifs"); setBell(r.unread); if (n.link) { if (location.hash === n.link) route(); else location.hash = n.link; } } },
    h("span", { class: "bn-k" }, NK[n.kind] || "•"), h("div", {}, h("div", { class: "bn-t" }, n.text), h("div", { class: "bn-d" }, `${n.kind} · ${n.created.slice(5, 16)}`)));
  pn.replaceChildren(h("div", { class: "bn-hd" }, h("b", {}, "알림"), h("span", { class: "muted small" }, d.unread ? ` 새 알림 ${d.unread}` : ""), h("div", { class: "spacer" }),
    d.unread ? h("button", { class: "link2", onclick: async e => { e.stopPropagation(); await api("POST", "/api/notifs/read", { all: true }); pn.hidden = true; setBell(0); openBell(); } }, "모두 읽음") : ""),
    h("div", { class: "bn-list" }, d.list.length ? d.list.map(item) : h("div", { class: "muted small", style: "padding:18px;text-align:center" }, "알림이 없습니다")));
  pn.hidden = false;
}
$("#btnBell").addEventListener("click", e => { e.stopPropagation(); openBell().catch(er => toast(er.message, true)); });
document.addEventListener("click", e => { const pn = $("#bellPanel"); if (!pn.hidden && !e.target.closest(".bell-wrap")) pn.hidden = true; });
setInterval(async () => { if (!M || document.hidden) return; try { const d = await api("GET", "/api/notifs"); setBell(d.unread); } catch {} }, 60000);
function buildNav() {
  const P = M.perms, items = [];
  if (P.sheet) items.push(["#/me", "내 업무"], ["#/myissues", "내 이슈"]);
  if (P.pl) items.push(["#/part", "우리 파트 이슈"]);
  if (P.assign) items.push(["#/assign", "업무 지정"]);
  if (P.admin) items.push(["#/dash", "업무로드"], ["#/summary", "이슈 요약"], ["#/registry", "이슈 정리"], ["#/people", "사람별"]);
  if (P.std) items.push(["#/master", "기준정보"]);
  if (P.admin) items.push(["#/admin", "관리"]);
  items.push(["#/requests", "요청"]);
  $("#nav").replaceChildren(...items.map(([href, t]) => h("a", { href }, t, href === "#/requests" && M.reqPending ? h("span", { class: "nbadge" }, M.reqPending) : "")));
}
$("#btnOut").addEventListener("click", async () => { try { await api("POST", "/api/logout", {}); } catch {} M = null; showLogin(); });
$("#btnPw").addEventListener("click", () => { location.hash = "#/pw"; });
// 화면 모양 A · B · C (사람별 저장 · 로그인 화면에서도 이 PC에서 마지막에 쓴 것)
function applyTheme(t) {
  t = ["a", "b", "c"].includes(t) ? t : "b";   // 기본은 화면 B
  document.documentElement.dataset.theme = t;
  $("#selTheme").value = t; try { localStorage.setItem("theme", t); } catch {}
}
try { applyTheme(localStorage.getItem("theme") || ""); } catch {}
// 다크 모드 (화면 A · B · C 모두 · 사람별 저장 · 로그인 화면에서도 이 PC에서 마지막에 쓴 것)
function applyDark(on) {
  on = on === true || on === "1";
  if (on) document.documentElement.dataset.dark = "1"; else delete document.documentElement.dataset.dark;
  $("#btnDark").textContent = on ? "☀️" : "🌙"; $("#btnDark").title = on ? "밝은 화면으로" : "다크 모드로";
  try { localStorage.setItem("dark", on ? "1" : "0"); } catch {}
}
try { applyDark(localStorage.getItem("dark") || "0"); } catch {}
$("#btnDark").addEventListener("click", () => { const on = document.documentElement.dataset.dark !== "1"; applyDark(on); setPref("dark", on ? "1" : "0"); if (location.hash.startsWith("#/dash")) route(); });
$("#selTheme").addEventListener("change", e => { applyTheme(e.target.value); setPref("theme", e.target.value); });
window.addEventListener("hashchange", route);

async function route() {
  if (!M) return;
  const hs = location.hash || (M.perms.sheet ? "#/me" : "#/dash");
  for (const a of document.querySelectorAll("nav a")) a.classList.toggle("on", hs.startsWith(a.getAttribute("href")));
  app().replaceChildren(h("div", { class: "loading" }, "불러오는 중…"));
  try {
    if (M.user.must_change && hs !== "#/pw") { location.hash = "#/pw"; return; }
    let m;
    if (hs === "#/pw") return pagePw();
    if (hs === "#/me") return pageMe(M.user.id, false);
    if (hs === "#/myissues") return pageMyIssues();
    if (hs === "#/part") return pageIssues("part");
    if (hs === "#/assign") return pageAssign();
    if (hs === "#/dash") return pageDash();
    if (hs === "#/summary") return pageSummary();
    if (hs === "#/registry") return pageIssues("all");
    if ((m = hs.match(/^#\/people(?:\/(\d+))?$/))) return pagePeople(m[1] ? Number(m[1]) : 0);
    if (hs === "#/master") return pageMaster();
    if (hs === "#/admin") return pageAdmin();
    if (hs === "#/requests") return pageRequests();
    location.hash = M.perms.sheet ? "#/me" : "#/dash";
  } catch (e) { app().replaceChildren(h("div", { class: "card err" }, e.message)); }
}

// ── 비밀번호 ──
function pagePw() {
  const o = h("input", { type: "password" }), n1 = h("input", { type: "password" }), n2 = h("input", { type: "password" });
  const em = h("input", { value: M.myEmail || "", placeholder: M.mailDomain ? `이름@${M.mailDomain.replace(/^@/, "")}` : "회사 메일 주소" });
  app().replaceChildren(h("h1", {}, "내 정보"),
    M.user.must_change ? "" : h("div", { class: "card", style: "max-width:460px;margin-bottom:18px" }, h("h2", { style: "margin-top:0" }, "회사 메일 (비밀번호 찾기용)"),
      h("div", { class: "form" }, ...field("메일", em)),
      h("div", { class: "muted small", style: "margin-top:8px" }, M.mailReady ? "비밀번호를 잊으면 로그인 화면 > '비밀번호를 잊었나요?'에서 이 메일로 인증번호를 받습니다." : "메일 보내기는 서버 설정 후 쓸 수 있습니다. 그전에는 '팀장 · 마스터에게 초기화 요청'을 씁니다."),
      h("div", { class: "row", style: "margin-top:10px" }, h("button", { class: "btn pri", onclick: async () => { try { await api("PUT", "/api/me/email", { email: em.value.trim() }); M.myEmail = em.value.trim().toLowerCase(); toast("메일을 저장했습니다"); } catch (e) { toast(e.message, true); } } }, "메일 저장"))),
    h("h2", {}, "비밀번호 바꾸기"),
    M.user.must_change ? h("div", { class: "help" }, "처음 로그인입니다. 받은 비밀번호를 새 비밀번호(6자 이상)로 바꾼 뒤 사용합니다.") : "",
    h("div", { class: "card", style: "max-width:460px" }, h("div", { class: "form" }, ...field("지금 비밀번호", o), ...field("새 비밀번호", n1), ...field("새 비밀번호 확인", n2)),
      h("div", { class: "row", style: "margin-top:14px" }, h("button", { class: "btn pri", onclick: async () => {
        if (n1.value !== n2.value) return toast("새 비밀번호 두 칸이 다릅니다", true);
        try { await api("POST", "/api/password", { old: o.value, new: n1.value }); toast("바꿨습니다"); M.user.must_change = 0; location.hash = M.perms.sheet ? "#/me" : "#/dash"; } catch (e) { toast(e.message, true); }
      } }, "바꾸기"))));
}

// ── 요약 기간 (주간 · 월간 · 연간 · 직접) + 기준일 ──
const PER = { mode: "week", base: null, from: "", to: "" };
function perQs() { return `mode=${PER.mode}&base=${PER.base || M.today}${PER.mode === "custom" ? `&from=${PER.from}&to=${PER.to}` : ""}`; }
function periodBar(onChange) {
  const seg = h("div", { class: "seg" }, [["week", "주간"], ["month", "월간"], ["year", "연간"], ["custom", "직접"]].map(([k, t]) =>
    h("button", { class: PER.mode === k ? "on" : "", onclick: () => { PER.mode = k; if (k === "custom" && !PER.from) { PER.from = monday(PER.base || M.today); PER.to = PER.base || M.today; } onChange(); } }, t)));
  const box = h("div", { class: "row per" }, seg);
  if (PER.mode === "custom") {
    const f = dateInput(PER.from), t = dateInput(PER.to);
    const go = () => { if (/^\d{4}-\d{2}-\d{2}$/.test(f.value) && /^\d{4}-\d{2}-\d{2}$/.test(t.value)) { PER.from = f.value; PER.to = t.value; onChange(); } };
    f.addEventListener("change", go); t.addEventListener("change", go);
    box.append(f, h("span", { class: "muted" }, "~"), t);
  } else {
    const b = dateInput(PER.base || M.today);
    b.addEventListener("change", () => { if (/^\d{4}-\d{2}-\d{2}$/.test(b.value)) { PER.base = b.value; onChange(); } });
    box.append(h("span", { class: "muted small" }, "기준일"), b, (PER.base && PER.base !== M.today) ? h("button", { class: "btn sm", onclick: () => { PER.base = null; onChange(); } }, "오늘로") : "");
  }
  return box;
}
function statCards(s) {
  const rc = s.rateCls === "과부하" ? "over" : s.rateCls === "적정" ? "fit" : s.rateCls === "여유" ? "spare" : "";
  const bar = v => h("div", { class: "bar" + (v > 1.2 ? " over" : "") }, h("i", { style: `width:${Math.min(100, Math.round((v || 0) * 100 / 1.5))}%` }));
  return h("div", { class: "cards stat6" },
    h("div", { class: "card stat" }, h("div", { class: "k" }, "근무 시간율"), h("div", { class: "v" }, fmtPct(s.rate)), bar(s.rate), h("div", { class: "s" }, `투입 ${fmtH(s.input)}h ÷ 기준 ${fmtH(s.base)}h`)),
    h("div", { class: "card stat" }, h("div", { class: "k" }, "업무 로드 (등급 반영)"), h("div", { class: "v" }, fmtPct(s.load)), bar(s.load)),
    h("div", { class: "card stat" }, h("div", { class: "k" }, "판정"), h("div", { class: "v jd" }, badge(rc, s.rateCls), " ", s.judge), h("div", { class: "s" }, s.action || "")),
    h("div", { class: "card stat" }, h("div", { class: "k" }, "미입력"), h("div", { class: "v" }, s.missing + "일"), h("div", { class: "s" }, `${s.from} ~ ${s.to} · 근무일 ${s.workdays}일`)),
    h("div", { class: "card stat" }, h("div", { class: "k" }, "내 이슈"), h("div", { class: "v" }, s.issuesOpen + "건"), h("div", { class: "s" }, `지연 ${s.issuesLate} · 임박 ${s.issuesSoon} · 완료 ${s.issuesDone}`)),
    h("div", { class: "card stat" }, h("div", { class: "k" }, "통상 업무"), h("div", { class: "v" }, s.tasksOpen + "건"), h("div", { class: "s" }, `지연 ${s.tasksLate}`)));
}

// ── 내 업무 (사람별 보기에서도 씀) ──
let weekFrom = null;
async function pageMe(uid, readonly) {
  const root = h("div");
  app().replaceChildren(root);
  const u = M.users.find(x => x.id === uid);
  const statBox = h("div"), weekBox = h("div"), taskBox = h("div");
  let statT = 0; weekBox.addEventListener("hours-saved", () => { clearTimeout(statT); statT = setTimeout(() => loadStats().catch(() => {}), 600); });
  const refresh = async () => { await Promise.all([loadStats(), renderWeek(weekBox, uid, readonly, refresh), renderTasks(taskBox, uid, readonly, refresh)]); };
  const head = h("div", { class: "row page-hd" }, h("h1", {}, readonly ? `${u.name}` : "내 업무", h("span", { class: "sub" }, `${u.part} · ${roleKo[u.role]}`)), h("div", { class: "spacer" }));
  const loadStats = async () => {
    const s = await api("GET", `/api/stats?user=${uid}&${perQs()}`);
    statBox.replaceChildren(h("div", { class: "row", style: "margin-bottom:8px" }, h("b", {}, "요약 기간"), periodBar(loadStats)), statCards(s));
  };
  root.append(head, statBox, h("h2", {}, "시간 입력", h("span", { class: "sub" }, readonly ? "보기 전용" : "칸에 시간을 넣으면 바로 저장 · 0.5시간 단위 · ✎ = 그날 한 일 · 방향키 · Enter로 칸 이동")), weekBox,
    h("h2", {}, "업무 목록", h("span", { class: "sub" }, "행을 누르면 내용 보기 · 고치기 · ⠿를 잡고 끌면 순서 바꾸기")), taskBox);
  weekFrom = weekFrom || monday(M.today);
  await refresh();
}

async function renderWeek(box, uid, readonly, refreshAll) {
  const w = await api("GET", `/api/week?user=${uid}&from=${weekFrom}`);
  const again = () => renderWeek(box, uid, readonly, refreshAll);
  const nav = h("div", { class: "row", style: "margin-bottom:8px" },
    h("button", { class: "btn sm", onclick: () => { weekFrom = addDays(weekFrom, -7); again(); } }, "◀ 이전 주"),
    h("b", { class: "wk-range" }, `${dd(w.from)} ~ ${dd(w.to)}`),
    h("button", { class: "btn sm", onclick: () => { weekFrom = addDays(weekFrom, 7); again(); } }, "다음 주 ▶"),
    h("button", { class: "btn sm", onclick: () => { weekFrom = monday(M.today); again(); } }, "이번 주"),
    h("div", { class: "spacer" }),
    readonly ? "" : h("button", { class: "btn", onclick: () => requestModal() }, "✉ 요청하기"),
    readonly ? "" : h("button", { class: "btn pri", onclick: () => taskModal(null, false, refreshAll) }, "+ 업무 추가"));
  const thead = h("thead", {}, h("tr", {}, h("th", { class: "name" }, "업무 · 이슈"), w.days.map(d => h("th", { class: "c " + (d.workday ? "" : "we ") + (d.holiday ? "hol " : "") + (d.today ? "today" : ""), title: d.holiday || "" }, dd(d.date), d.holiday ? h("div", { class: "small" }, d.holiday) : "")), h("th", { class: "c" }, "합계")));
  const tbody = h("tbody");
  const totals = {}; const leave = {}; const early = {};
  const sumRow = h("tr", { class: "sum" });
  thead.append(sumRow);   // 하루 합계는 맨 위 (머리글과 같이 고정)
  const recalc = () => {
    for (const d of w.days) { totals[d.date] = 0; leave[d.date] = 0; early[d.date] = 0; }
    for (const r of w.rows) for (const [d, v] of Object.entries(r.hours)) {
      if (!(d in totals)) continue;
      if (r.kind === "휴가") leave[d] += v; else if (r.kind === "조퇴") early[d] += v; else totals[d] += v;
    }
    sumRow.replaceChildren(h("td", { class: "name" }, "하루 합계"), ...w.days.map(d => {
      let cls = "", tip = "";
      const need = w.dayHours - (early[d.date] > 0 ? w.earlyHours : 0);
      if (d.leave) { cls = "lv"; tip = "휴직"; }
      else if (d.workday && d.past && !d.beforeStart) {
        if (totals[d.date] === 0 && leave[d.date] === 0) { cls = "miss"; tip = "미입력"; }
        else if (totals[d.date] + leave[d.date] < need && !d.today) { cls = "short"; tip = "부족"; }
        else if (leave[d.date] >= w.dayHours) { cls = "leave"; tip = "휴가"; }
        else cls = "okd";
      }
      if (totals[d.date] > w.dayHours) { cls = "overd"; tip = `${w.dayHours}h 초과`; }
      const v = totals[d.date] + leave[d.date];
      return h("td", { class: "c " + cls, title: tip }, h("b", {}, v ? fmtH(v) : (d.past && d.workday ? "0" : "")), tip ? h("div", { class: "small" }, tip) : "");
    }), h("td", { class: "c tot" }, h("b", {}, fmtH(Object.values(totals).reduce((a, b) => a + b, 0)))));
  };
  const allInputs = [];
  const moveFocus = (inp, dr, dc) => {
    const r = Number(inp.dataset.r), c = Number(inp.dataset.c);
    let nr = r + dr, nc = c + dc;
    while (nr >= 0 && nr < allInputs.length) {
      const row = allInputs[nr]; if (row && row[nc] && !row[nc].disabled) { row[nc].focus(); return; }
      if (dc) break; nr += dr;
    }
    if (dc) { const row = allInputs[r]; while ((nc += dc) >= 0 && nc < 7) if (row[nc] && !row[nc].disabled) { row[nc].focus(); return; } }
  };
  const cell = (r, d, ri, ci) => {
    const dis = readonly || d.beforeStart || d.leave;
    const inp = h("input", { class: "h", inputmode: "decimal", value: r.hours[d.date] ? String(r.hours[d.date]) : "", disabled: dis, title: d.date, "data-r": ri, "data-c": ci, autocomplete: "off" });
    (allInputs[ri] = allInputs[ri] || [])[ci] = inp;
    let last = inp.value;
    inp.addEventListener("focus", () => inp.select());
    inp.addEventListener("keydown", e => {
      const atStart = inp.selectionStart === 0 && inp.selectionEnd === 0, atEnd = inp.selectionStart === inp.value.length, all = inp.selectionStart === 0 && inp.selectionEnd === inp.value.length;
      if (e.key === "ArrowDown" || e.key === "Enter") { e.preventDefault(); moveFocus(inp, 1, 0); }
      else if (e.key === "ArrowUp") { e.preventDefault(); moveFocus(inp, -1, 0); }
      else if (e.key === "ArrowRight" && (atEnd || all)) { e.preventDefault(); moveFocus(inp, 0, 1); }
      else if (e.key === "ArrowLeft" && (atStart || all)) { e.preventDefault(); moveFocus(inp, 0, -1); }
      else if (e.key === "Escape") { inp.value = last; inp.blur(); }
    });
    inp.addEventListener("change", async () => {
      const v = inp.value.trim();
      const n = v === "" ? 0 : Number(v);
      if (v !== "" && (!isFinite(n) || n < 0 || n > 24 || Math.abs(n / w.unit - Math.round(n / w.unit)) > 1e-9)) {
        inp.classList.add("bad"); toast(`시간은 0 ~ 24 사이, ${w.unit}시간 단위로 넣습니다 (30분 = 0.5)`, true); inp.value = last; setTimeout(() => inp.classList.remove("bad"), 1500); return;
      }
      try {
        await api("PUT", "/api/hours", { type: r.type, id: r.id, date: d.date, hours: n });
        last = inp.value; if (n) r.hours[d.date] = n; else delete r.hours[d.date];
        inp.classList.remove("saved"); void inp.offsetWidth; inp.classList.add("saved"); recalc(); rowTot(); box.dispatchEvent(new Event("hours-saved"));
      } catch (e) { toast(e.message, true); inp.value = last; }
    });
    let rowTot = () => {};
    const wrap = h("div", { class: "cell" }, inp);
    if (r.type === "issue" || (r.kind !== "휴가" && r.kind !== "조퇴")) {
      const has = !!r.texts?.[d.date];
      const nb = h("button", { class: "note-btn" + (has ? " has" : ""), title: has ? r.texts[d.date] : "그날 한 일 쓰기", disabled: dis && !has, tabindex: -1 }, "✎");
      nb.addEventListener("click", () => logModal(r, d.date, readonly || dis, again));
      wrap.append(nb);
    }
    return { td: h("td", { class: "c " + (d.workday ? "" : "we ") + (d.today ? "today" : "") }, wrap), setTot: f => (rowTot = f) };
  };
  let ri = 0;
  const addRow = (r, target, drag) => {
    const tot = h("td", { class: "c tot" });
    const upd = () => (tot.textContent = fmtH(Object.values(r.hours).reduce((a, b) => a + b, 0)));
    const my = ri++;
    const tds = w.days.map((d, ci) => { const c = cell(r, d, my, ci); c.setTot(upd); return c.td; });
    upd();
    const open = () => r.type === "issue" ? issueModal({ id: r.id }, again) : taskModal({ id: r.id }, readonly, refreshAll);
    const name = h("td", { class: "name" },
      drag && !readonly ? dragHandle() : "",
      h("span", { class: "t lnk", role: "button", title: (r.duty ? `할 일 (PL): ${r.duty}\n` : "") + "눌러서 내용 보기", onclick: open }, r.type === "issue" ? [h("b", {}, r.no + " "), r.title] : r.title),
      h("span", { class: "m" }, r.type === "issue" ? [badge(r.released ? "warn" : "role", r.role), " ", r.model || "공통"] : [r.kind, r.model ? " · " + r.model : r.fixed ? " · 기본 행" : " · 공통"],
        r.assigned ? [" ", badge("pl", "PL 지정")] : "", r.hidden ? [" ", badge("warn", "삭제됨")] : "", r.done ? [" ", badge("done", "완료")] : ""));
    target.append(h("tr", { "data-id": r.id }, name, tds, tot));
  };
  const iss = w.rows.filter(r => r.type === "issue"), fixed = w.rows.filter(r => r.type === "task" && r.fixed), rest = w.rows.filter(r => r.type === "task" && !r.fixed);
  const grp = (label, key, list, opts = {}) => {
    if (!list.length && !opts.always) return;
    const open = getPref("wk:" + key, !opts.closed);
    const tr = h("tr", { class: "grp" + (open ? " open" : "") }, h("td", { colspan: 9 }, h("span", { class: "car" }, "▸"), ` ${label} (${list.length})`));
    const body = h("tbody", { class: "gbody" }); body.hidden = !open;
    tr.addEventListener("click", () => { body.hidden = !body.hidden; tr.classList.toggle("open", !body.hidden); setPref("wk:" + key, !body.hidden); });
    const head = h("tbody", {}, tr);
    tables.push(head, body);
    list.forEach(r => addRow(r, body, opts.drag));
    if (opts.drag && !readonly) sortable(body, "tr[data-id]", async ids => { const all = [...ids, ...w.rows.filter(x => x.type === "task" && !x.fixed && !ids.includes(x.id)).map(x => x.id)]; await saveOrder(all); });
  };
  const tables = [];
  grp("이슈", "iss", iss.filter(r => !r.done));
  grp("업무", "task", rest.filter(r => !r.done), { always: true, drag: true });
  grp("기본 행 (회의 · 교육 · 휴가 · 조퇴)", "fix", fixed, { always: true });
  grp("완료 · 삭제한 것 (이번 주 기록 있음)", "done", [...iss.filter(r => r.done), ...rest.filter(r => r.done)], { closed: true });
  recalc();
  const table = h("table", {}, thead, ...tables);
  resizable(table, "week");
  box.replaceChildren(nav, h("div", { class: "week" }, table),
    h("div", { class: "legend" }, h("span", {}, h("i", { style: "background:var(--warn)" }), "미입력 · 부족"), h("span", {}, h("i", { style: "background:var(--bad)" }), `${w.dayHours}h 초과`),
      h("span", {}, h("i", { style: "background:var(--ok)" }), "휴가"), h("span", {}, h("i", { style: "background:var(--violet)" }), "휴직"), h("span", {}, h("b", { class: "note-btn has" }, "✎"), " = 그날 한 일 있음"),
      h("span", {}, `조퇴 행에는 ${w.earlyHours}을 넣으면 그날 기준 시간이 ${w.dayHours - w.earlyHours}h가 됩니다`)));
}

function logModal(r, date, readonly, after) {
  const hrs = h("input", { class: "inp", inputmode: "decimal", value: r.hours[date] ? String(r.hours[date]) : "", disabled: readonly, style: "width:100px" });
  const isIssue = r.type === "issue";
  const txt = h("textarea", { class: "inp", rows: 5, disabled: readonly, placeholder: isIssue ? "이 이슈에서 오늘 한 일 (예: 불량품 3EA 재현 시험, 원인 후보 2건 확인)" : "이 업무에서 그날 한 일 (예: 전원부 회로도 1차 검토, 부품 2종 변경 검토)" }, r.texts?.[date] || "");
  modal(`${isIssue ? r.no + " " : ""}${r.title} · ${dd(date)}`, h("div", { class: "form" }, r.duty ? field("할 일 (PL 지정)", h("div", { class: "pre small" }, r.duty)) : "", ...field("투입 시간(h)", hrs), ...field("한 일", txt, false)),
    readonly ? [] : [{ text: "저장", cls: "pri", fn: async () => { await api("PUT", "/api/hours", { type: isIssue ? "issue" : "task", id: r.id, date, hours: hrs.value.trim() === "" ? 0 : Number(hrs.value), text: txt.value }); toast("저장했습니다"); await after(); } }]);
  setTimeout(() => txt.focus(), 50);
}

async function renderTasks(box, uid, readonly, refreshAll) {
  let filter = box.dataset.f || "open";
  const list = await api("GET", `/api/tasks?user=${uid}${filter === "hidden" ? "&hidden=1" : ""}`);
  const fin = t => t.done || t.progress === 100;
  const shown = list.filter(t => filter === "all" ? true : filter === "done" ? fin(t) : filter === "hidden" ? t.hidden : !fin(t) && !t.hidden);
  const nDone = list.filter(t => fin(t) && !t.hidden).length;
  const seg = h("div", { class: "seg" }, [["open", "진행 중"], ["done", `완료 (${nDone})`], ["all", "전체"], ["hidden", "삭제한 업무"]].map(([k, t]) =>
    h("button", { class: filter === k ? "on" : "", onclick: () => { box.dataset.f = k; renderTasks(box, uid, readonly, refreshAll); } }, t)));
  const canDrag = !readonly && filter === "open";
  const rows = shown.map(t => h("tr", { class: "click" + (t.hidden ? " muted" : ""), "data-id": t.fixed ? "" : t.id, onclick: () => taskModal(t, readonly, refreshAll) },
    h("td", { class: "nowrap c" }, canDrag && !t.fixed ? dragHandle() : "", t.kind), h("td", {}, modelName(t.model_id) || "공통"),
    h("td", {}, t.title, t.fixed ? [" ", badge("", "기본 행")] : "", t.assigned_name ? [" ", badge("pl", `PL 지정 · ${t.assigned_name.split(" ")[0]}`)] : "", t.notes ? [" ", h("span", { class: "muted small" }, `✎${t.notes}`)] : ""),
    h("td", { class: "num" }, t.kind === "통상" ? (t.progress ?? 0) + "%" : ""), h("td", {}, t.start || ""), h("td", {}, t.target || ""),
    h("td", {}, badge(t.sched.cls, t.sched.text)), h("td", {}, t.done || ""), h("td", { class: "c" }, t.importance), h("td", { class: "small" }, t.category),
    h("td", { class: "small pre" }, t.note), h("td", { class: "num" }, fmtH(t.total))));
  const tb = h("tbody", {}, rows.length ? rows : h("tr", {}, h("td", { colspan: 12, class: "muted c" }, filter === "open" ? "진행 중인 업무가 없습니다" : "업무가 없습니다")));
  if (canDrag) sortable(tb, "tr[data-id]:not([data-id=''])", async ids => { const rest = list.filter(t => !t.fixed && !ids.includes(t.id)).map(t => t.id); await saveOrder([...ids, ...rest]); await renderWeekAgain(); });
  const renderWeekAgain = async () => { await refreshAll(); };
  const table = h("table", { class: "task-list" }, h("thead", {}, h("tr", {}, ["구분", "모델", "업무명", "진행률", "시작일", "목표 마감일", "일정", "실제 마감일", "중요도", "업무 분류", "비고", "투입(h)"].map(x => h("th", {}, x)))), tb);
  resizable(table, "tasks");
  box.replaceChildren(h("div", { class: "row", style: "margin-bottom:8px" }, seg, h("div", { class: "spacer" }),
    readonly ? "" : h("button", { class: "btn", onclick: () => taskModal(null, false, refreshAll) }, "+ 업무 추가")),
    h("div", { class: "tbl" }, table),
    readonly ? "" : h("div", { class: "help" }, "이슈는 PL이 등록하면 '내 이슈'와 시간 입력 표에 자동으로 생깁니다. 끝난 업무는 지우지 말고 실제 마감일을 넣거나 진행률 100%로 완료하세요. 완료된 업무는 '완료' 탭에 모입니다."));
}

async function taskModal(t0, readonly, after) {
  const isNew = !t0;
  const t = isNew ? { kind: "통상", progress: 0, notes_list: [], hours_list: [], canEdit: true } : await api("GET", `/api/tasks/${t0.id}`);
  readonly = readonly || !t.canEdit;
  const dis = readonly;
  const kind = sel(t.fixed ? [t.kind] : ["통상", "기타", "휴가", "조퇴"], t.kind, { disabled: readonly || t.fixed });
  const model = sel([["", "공통 (모델 없음)"], ...modelsFor("").map(m => [m.id, `${m.name} (${m.part} · ${m.phase || "-"})`])], t.model_id, { disabled: dis });
  const title = h("input", { value: t.title || "", disabled: readonly });
  const prog = sel([["", "-"], ...Array.from({ length: 11 }, (_, i) => [i * 10, i * 10 + "%"])], t.progress, { disabled: dis });
  const st = dateInput(t.start, { disabled: dis }), tg = dateInput(t.target, { disabled: dis }), dn = dateInput(t.done, { disabled: dis });
  const imp = sel(["", "상", "중", "하"], t.importance, { disabled: dis });
  const cat = sel([["", "-"], ...M.categories.map(c => [c.name, c.name])], t.category, { disabled: dis });
  const note = h("textarea", { disabled: dis }, t.note || "");
  const form = h("div", { class: "form" }, t.fixed && !readonly ? h("div", { class: "full help" }, "기본 행입니다. 이름 · 모델 · 분류 · 비고는 고칠 수 있고, 구분(기타 · 휴가 · 조퇴)은 계산에 쓰여 바꿀 수 없습니다.") : "", t.assigned_name ? h("div", { class: "full help" }, `${t.assigned_name} 이(가) 지정한 업무입니다.`) : "",
    ...field("구분", kind), ...field("모델", model), ...field("업무명", title), ...field("진행률 (통상)", prog),
    ...field("시작일", st), ...field("목표 마감일", tg), ...field("실제 마감일", dn), ...field("중요도", imp), ...field("업무 분류", cat), ...field("비고", note));
  let body = form;
  // 새 업무: 날짜별 시간 · 그날 한 일을 같이 넣기 (이미 끝난 업무를 넣을 때 완료 탭을 다시 찾지 않도록)
  const hrows = [];
  if (isNew) {
    const list = h("div", { class: "hrs-list" });
    const addRow = (date = "") => {
      const d = dateInput(date), hh = h("input", { class: "hrs-h", inputmode: "decimal", placeholder: "시간" }), tx = h("input", { class: "hrs-t", placeholder: "그날 한 일 (선택)" });
      const row = h("div", { class: "hrs-row" }, d, hh, tx, h("button", { type: "button", class: "btn sm", title: "이 줄 지우기", onclick: () => { row.remove(); hrows.splice(hrows.indexOf(o), 1); } }, "✕"));
      const o = { d, hh, tx }; hrows.push(o); list.append(row);
    };
    addRow(M.today);
    body = h("div", {}, form, h("div", { class: "hrs-box" }, h("div", { class: "row" }, h("b", {}, "시간 입력"), h("span", { class: "muted small" }, `선택 · ${M.unit || 0.5}시간 단위 · 시간을 비운 줄은 넣지 않음`), h("div", { class: "spacer" }),
      h("button", { type: "button", class: "btn sm", onclick: () => addRow("") }, "+ 날짜 추가")), list));
  }
  if (!isNew) {
    const log = h("div", {},
      h("div", { class: "muted small", style: "margin-bottom:8px" }, `투입 합계 ${fmtH(t.total)}h · 기록 ${t.notes_list.length}건 · 시간 입력 표의 ✎에서 그날 한 일을 씁니다`),
      t.notes_list.length ? h("div", { class: "timeline" }, t.notes_list.map(n => h("div", { class: "it" }, h("div", { class: "d" }, `${n.date} · ${fmtH(n.hours)}h`), h("div", { class: "pre" }, n.text)))) : h("div", { class: "muted" }, "아직 기록이 없습니다."),
      t.hours_list.length ? h("details", { style: "margin-top:12px" }, h("summary", { class: "small muted" }, "날짜별 시간"), h("div", { class: "small" }, t.hours_list.map(x => `${x.date} ${fmtH(x.hours)}h`).join(" · "))) : "");
    body = tabbed([["f", "업무 내용", form], ["l", `진행 기록 (${t.notes_list.length})`, log]]);
  }
  const btns = readonly ? [] : [{ text: "저장", cls: "pri", fn: async () => {
    const b = { kind: kind.value, model_id: model.value ? Number(model.value) : null, title: title.value, progress: kind.value === "통상" ? (prog.value === "" ? null : Number(prog.value)) : null,
      start: st.value, target: tg.value, done: dn.value, importance: imp.value, category: cat.value, note: note.value };
    if (isNew) {
      b.hours = [];
      for (const o of hrows) {
        const hv = o.hh.value.trim(); if (hv === "" || Number(hv) === 0) { if (o.tx.value.trim()) throw new Error("그날 한 일을 쓴 줄에 시간을 넣어 주세요"); continue; }
        if (!o.d.value) throw new Error("시간을 넣은 줄에 날짜를 넣어 주세요");
        b.hours.push({ date: o.d.value, hours: Number(hv), text: o.tx.value.trim() });
      }
      if (new Set(b.hours.map(x => x.date)).size !== b.hours.length) throw new Error("같은 날짜가 두 줄 있습니다");
      await api("POST", "/api/tasks", b);
    } else await api("PUT", `/api/tasks/${t.id}`, b);
    toast("저장했습니다"); await after();
  } }];
  if (!readonly && !isNew && !t.fixed) btns.unshift(t.hidden
    ? { text: "되살리기", fn: async () => { await api("POST", `/api/tasks/${t.id}/hide`, { hidden: false }); toast("되살렸습니다"); await after(); } }
    : { text: "삭제 (숨김)", cls: "danger", fn: async () => { if (!(await confirmBox("이 업무를 목록에서 숨깁니다.\n넣은 시간은 그대로 남아 집계에 들어가고, '삭제한 업무'에서 되살릴 수 있습니다."))) return false; await api("POST", `/api/tasks/${t.id}/hide`, { hidden: true }); toast("숨겼습니다"); await after(); } });
  modal(isNew ? "업무 추가" : (readonly ? "업무 보기" : "업무"), body, btns);
  if (isNew) setTimeout(() => title.focus(), 50);
}
function tabbed(list) {
  const bar = h("div", { class: "tabs" }); const panes = [];
  list.forEach(([k, t, el], i) => {
    const pane = h("div", { class: "pane" }, el); pane.hidden = i > 0; panes.push(pane);
    bar.append(h("button", { class: i === 0 ? "on" : "", type: "button", onclick: e => { for (const b of bar.children) b.classList.remove("on"); e.currentTarget.classList.add("on"); panes.forEach((p, j) => (p.hidden = j !== i)); } }, t));
  });
  return h("div", {}, bar, panes);
}

// ── 내 이슈 (접고 펴기) ──
async function pageMyIssues() {
  const list = await api("GET", "/api/issues?scope=mine");
  const full = await Promise.all(list.map(i => api("GET", `/api/issues/${i.id}`)));
  const open = full.filter(i => !(i.done || i.stage === 6)), done = full.filter(i => i.done || i.stage === 6);
  const root = h("div", {}, h("div", { class: "row page-hd" }, h("h1", {}, "내 이슈", h("span", { class: "sub" }, `진행 ${open.length} · 완료 ${done.length}`)), h("div", { class: "spacer" }),
    h("button", { class: "btn sm", onclick: () => { for (const c of root.querySelectorAll(".issue-card")) c.classList.add("open"); } }, "모두 펴기"),
    h("button", { class: "btn sm", onclick: () => { for (const c of root.querySelectorAll(".issue-card")) c.classList.remove("open"); } }, "모두 접기")),
    h("div", { class: "help" }, "제목 줄을 누르면 펴지고 접힙니다. 시간과 '오늘 한 일'은 내 업무 > 시간 입력 표의 ✎에서도 넣을 수 있습니다."));
  if (!full.length) root.append(h("div", { class: "card muted" }, "담당 이슈가 없습니다."));
  for (const i of open) root.append(issueCard(i));
  if (done.length) root.append(foldable("myissues-done", `완료된 이슈 (${done.length})`, done.map(issueCard), false));
  app().replaceChildren(root);
}
function issueCard(i) {
  const my = i.members.find(m => m.user_id === M.user.id);
  const isLead = my?.role === "정";
  const can = i.canManage;
  const stage = sel(M.stages.map((s, k) => [k + 1, s]), i.stage, { disabled: !can });
  const cause = h("textarea", { class: "inp", disabled: !isLead && !can }, i.cause || ""), plan = h("textarea", { class: "inp", disabled: !isLead && !can }, i.plan || "");
  const cat = sel([["", "-"], ...M.categories.map(c => [c.name, c.name])], my?.category);
  const delay = h("textarea", { class: "inp", readOnly: true, rows: 2 }, i.delay_reason || "");
  delay.addEventListener("focus", () => { if (!can) toast("입력 권한이 없습니다 (지연 사유는 PL이 입력)", true); });
  stage.addEventListener("mousedown", () => { if (!can) toast("입력 권한이 없습니다 (단계는 PL이 고칩니다)", true); });
  const mine = i.logs.filter(l => l.user_id === M.user.id);
  const logToday = e => { e.stopPropagation(); logModal({ type: "issue", id: i.id, no: i.no, title: i.title, duty: my?.duty, hours: Object.fromEntries(mine.map(l => [l.date, l.hours])), texts: Object.fromEntries(mine.map(l => [l.date, l.text])) }, M.today, false, () => route()); };
  const card = h("div", { class: "issue-card" });
  const top = h("div", { class: "top" }, h("span", { class: "car" }, "▸"), h("span", { class: "no" }, i.no), h("span", { class: "ttl" }, i.title), badge("role", my?.role), badge(i.sched.cls, i.sched.text), h("span", { class: "muted small" }, M.stages[(i.stage || 1) - 1] || ""),
    i.needDelay ? badge("late", "지연 사유 미입력 (PL)") : "", h("div", { class: "spacer" }), h("span", { class: "muted small" }, `내 투입 ${fmtH(i.hours.find(x => x.user_id === M.user.id)?.h || 0)}h`),
    h("button", { class: "btn sm pri", onclick: logToday }, "오늘 한 일"));
  top.addEventListener("click", () => card.classList.toggle("open"));
  const body = h("div", { class: "ic-body" },
    h("div", { class: "duty" }, h("b", {}, "할 일 (PL 지정)"), h("div", { class: "pre" }, my?.duty || h("span", { class: "muted" }, "PL이 아직 적지 않았습니다"))),
    h("div", { class: "kv" }, h("div", {}, h("b", {}, "모델"), `${i.model} (${i.part})`), h("div", {}, h("b", {}, "발생처"), i.source || "-"), h("div", {}, h("b", {}, "발생일"), i.occurred || "-"),
      h("div", {}, h("b", {}, "Target (PL)"), i.target || "-"), h("div", {}, h("b", {}, "담당"), i.members.map(m => `${m.role} ${m.name}`).join(" · ")), h("div", {}, h("b", {}, "진척"), Math.round(i.progress * 100) + "%")),
    h("div", { class: "form" }, ...field("단계 (PL)", stage), ...field("진행현황 (PL)", h("div", { class: "pre small" }, i.status_text || "-")),
      ...field("지연 사유 (PL)", h("div", {}, delay, h("div", { class: "lock" }, "🔒 PL만 입력합니다"))),
      ...field("원인 (정)", cause), ...field("대응 계획 (정)", plan), ...field("내 업무 분류", cat)),
    h("div", { class: "row", style: "margin-top:10px" }, h("button", { class: "btn pri", onclick: async () => {
      try {
        const b = { cause: cause.value, plan: plan.value }; if (can) b.stage = Number(stage.value);
        if (isLead || can) await api("PUT", `/api/issues/${i.id}`, b);
        await api("PUT", `/api/issues/${i.id}/me`, { category: cat.value });
        toast("저장했습니다");
      } catch (e) { toast(e.message, true); }
    } }, "저장")),
    mine.length ? h("div", { style: "margin-top:10px" }, h("div", { class: "muted small" }, "내 최근 기록"), h("div", { class: "timeline" }, mine.slice(0, 5).map(l => h("div", { class: "it" }, h("div", { class: "d" }, `${l.date} · ${fmtH(l.hours)}h`), h("div", { class: "pre" }, l.text || h("span", { class: "muted" }, "(내용 없음)")))))) : "");
  card.append(top, body);
  return card;
}

// ── 이슈 목록 (PL: 우리 파트 / 팀장: 전체) ──
async function pageIssues(scope) {
  const root = h("div"); app().replaceChildren(root);
  const st = { done: false, hidden: false, part: "", model: "" };
  const load = async () => {
    const qs = scope === "all" ? `scope=all${st.hidden ? "&hidden=1" : ""}` : `scope=part`;
    const all = await api("GET", `/api/issues?${qs}`);
    const nDone = all.filter(i => i.done || i.stage === 6).length;
    const byPart = all.filter(i => st.done || !(i.done || i.stage === 6)).filter(i => !st.part || i.part === st.part);
    const mNames = [...new Set(byPart.map(i => i.model || ""))].sort((a, b) => !a ? 1 : !b ? -1 : a.localeCompare(b, "ko"));
    if (st.model && !mNames.includes(st.model === "-" ? "" : st.model)) st.model = "";
    const list = byPart.filter(i => !st.model || (i.model || "") === (st.model === "-" ? "" : st.model));
    const head = h("div", { class: "row page-hd" }, h("h1", {}, scope === "all" ? "이슈 정리" : `우리 파트 이슈 (${M.perms.plPart})`, h("span", { class: "sub" }, `${list.length}건`)), h("div", { class: "spacer" }),
      scope === "all" ? sel([["", "모든 파트"], ...M.parts.map(p => [p, p])], st.part, { onchange: e => { st.part = e.target.value; load(); } }) : "",
      sel([["", `모든 모델 (${byPart.length})`], ...mNames.map(n => [n || "-", `${n || "모델 없음"} (${byPart.filter(i => (i.model || "") === n).length})`])], st.model, { onchange: e => { st.model = e.target.value; load(); } }),
      h("label", { class: "small chk" }, h("input", { type: "checkbox", checked: st.done, onchange: e => { st.done = e.target.checked; load(); } }), ` 완료 포함 (${nDone})`),
      scope === "all" ? h("label", { class: "small chk" }, h("input", { type: "checkbox", checked: st.hidden, onchange: e => { st.hidden = e.target.checked; load(); } }), " 삭제한 이슈 포함") : "",
      h("button", { class: "btn pri", onclick: () => issueModal(null, load) }, "+ 새 이슈"));
    const rows = list.map(i => {
      const mem = r => nameTag(i.members.find(m => m.role === r)?.name || "");
      return h("tr", { class: "click" + (i.hidden ? " muted" : "") + (i.done || i.stage === 6 ? " is-done" : ""), onclick: () => issueModal(i, load) },
        h("td", { class: "nowrap" }, h("b", {}, i.no)), h("td", {}, i.model, h("div", { class: "small muted" }, i.part)), h("td", { class: "small" }, i.source), h("td", { class: "ttl" }, i.title, i.hidden ? [" ", badge("warn", "삭제됨")] : "", i.plAssigned.length ? [" ", badge("warn", "PL 담당 → 재지정")] : ""),
        h("td", {}, mem("정")), h("td", {}, mem("부1")), h("td", {}, mem("부2")), h("td", { class: "nowrap small" }, i.occurred || ""), h("td", { class: "nowrap small" }, i.target || ""),
        h("td", {}, badge(i.sched.cls, i.sched.text)), h("td", { class: "nowrap small" }, M.stages[(i.stage || 1) - 1] || ""), h("td", { class: "small pre status" }, i.status_text || ""),
        h("td", { class: "small pre" }, i.needDelay ? badge("late", "지연 사유 필요") : (i.delay_reason || "")));
    });
    const table = h("table", { class: "issues" }, h("thead", {}, h("tr", {}, ["번호", "모델", "발생처", "이슈명", "정", "부1", "부2", "발생일", "Target", "일정", "단계", "진행현황", "지연 사유"].map(x => h("th", {}, x)))),
      h("tbody", {}, rows.length ? rows : h("tr", {}, h("td", { colspan: 13, class: "c muted" }, "이슈가 없습니다"))));
    resizable(table, "issues-" + scope);
    root.replaceChildren(head,
      h("div", { class: "help" }, "이슈는 PL이 등록하고 정 · 부1 · 부2와 각자의 할 일을 지정합니다. 지정된 사람의 '내 이슈'와 시간 입력 표에 바로 생깁니다. 담당별 투입 · 오늘 한 일은 이슈를 누르면 보입니다. 목표일이 지났는데 끝나지 않았으면 지연 사유를 적어 주세요."),
      h("div", { class: "tbl" }, table));
  };
  await load();
}

async function issueModal(i0, after) {
  const isNew = !i0;
  const i = isNew ? { stage: 1, members: [], logs: [], hours: [], canManage: true, source: "내부", occurred: M.today } : await api("GET", `/api/issues/${i0.id}`);
  const can = i.canManage;
  const part = M.perms.admin ? "" : M.perms.plPart;
  const model = sel([["", "모델 선택"], ...modelsFor(part).concat(i.model_id && !modelsFor(part).some(m => m.id === i.model_id) ? M.models.filter(m => m.id === i.model_id) : []).map(m => [m.id, `${m.name} (${m.part})`])], i.model_id, { disabled: !can });
  const title = h("input", { value: i.title || "", disabled: !can });
  const source = sel(["", "내부", "고객", "기타"], i.source, { disabled: !can });
  const occ = dateInput(i.occurred, { disabled: !can }), tgt = dateInput(i.target, { disabled: !can });
  const stage = sel(M.stages.map((s, k) => [k + 1, s]), i.stage, { disabled: !can });
  const status = h("textarea", { disabled: !can, placeholder: "현상 · 원인 · 진행 · Action plan", rows: 5 }, i.status_text || "");
  const delay = h("textarea", { disabled: !can, placeholder: "목표일이 지났는데 끝나지 않은 이유" }, i.delay_reason || "");
  const note = h("textarea", { disabled: !can }, i.note || "");
  const imp = sel(["", "상", "중", "하"], i.importance, { disabled: !can });
  const people = assignable();
  const memRows = ["정", "부1", "부2"].map(role => {
    const m = i.members.find(x => x.role === role) || {};
    const s = sel([["", "-"], ...people.map(u => [u.id, `${u.name} (${u.part}${u.role === "pl" ? " · PL" : ""})`])], m.user_id, { disabled: !can });
    const duty = h("textarea", { class: "inp", rows: 2, placeholder: `${role} 담당이 할 일 (담당자 '내 이슈'에 그대로 보임)`, disabled: !can }, m.duty || "");
    const cat = sel([["", "업무 분류"], ...M.categories.map(c => [c.name, c.name])], m.category, { disabled: !can, class: "inp" });
    return { role, s, duty, cat, el: h("div", { class: "mem" }, h("b", {}, role), s, duty, cat) };
  });
  const form = h("div", { class: "form" }, ...field("번호", h("b", {}, i.no || "(저장하면 자동)")), ...field("모델", model), ...field("이슈명", title), ...field("발생처", source), ...field("발생일", occ), ...field("Target", tgt),
    ...field("단계 (PL)", stage), ...field("중요도", imp),
    h("label", { class: "full" }, "담당 · 할 일 (PL이 지정 → 각 담당자의 '내 이슈'에 할 일이 보임)"), h("div", { class: "full" }, memRows.map(r => r.el)),
    ...field("진행현황", status), ...field("지연 사유" + (i.sched?.cls === "late" ? " ⚠" : ""), delay), ...field("비고", note),
    i.plAssigned?.length ? h("div", { class: "full help warn" }, `PL(${i.plAssigned.join(", ")})이 담당으로 되어 있습니다. 재지정이 필요한지 확인해 주세요.`) : "",
    !isNew ? h("div", { class: "full small muted" }, `원인 (정): ${i.cause || "-"}  /  대응 계획 (정): ${i.plan || "-"}`) : "");
  let body = form;
  if (!isNew) {
    const byUser = {};
    for (const l of i.logs) (byUser[l.user_id] = byUser[l.user_id] || []).push(l);
    const ids = Array.from(new Set([...i.members.map(m => m.user_id), ...Object.keys(byUser).map(Number)]));
    const act = h("div", {}, ids.length ? ids.map(uid => {
      const m = i.members.find(x => x.user_id === uid);
      const logs = byUser[uid] || [];
      return h("div", { class: "card", style: "margin-bottom:10px" },
        h("div", { class: "row" }, h("b", {}, userName(uid)), badge("role", m?.role || "담당 해제"), h("span", { class: "muted small" }, `투입 ${fmtH(logs.reduce((a, l) => a + l.hours, 0))}h · 기록 ${logs.filter(l => l.text).length}건`)),
        h("div", { class: "small", style: "margin:6px 0" }, `할 일: ${m?.duty || "-"}  ·  분류: ${m?.category || "-"}`),
        logs.length ? h("div", { class: "timeline" }, logs.slice(0, 30).map(l => h("div", { class: "it" }, h("div", { class: "d" }, `${l.date} · ${fmtH(l.hours)}h`), h("div", { class: "pre" }, l.text || h("span", { class: "muted" }, "(시간만)"))))) : h("div", { class: "muted small" }, "기록 없음"));
    }) : h("div", { class: "muted" }, "담당자가 없습니다."));
    body = tabbed([["f", "이슈 내용", form], ["a", `담당별 투입 · 오늘 한 일 (${fmtH(i.hours.reduce((a, x) => a + x.h, 0))}h)`, act]]);
  }
  const btns = [];
  if (can) btns.push({ text: "저장", cls: "pri", fn: async () => {
    const members = memRows.map(r => ({ role: r.role, user_id: r.s.value ? Number(r.s.value) : null, duty: r.duty.value, category: r.cat.value })).filter(x => x.user_id);
    const pls = members.filter(x => isPLUser(x.user_id));
    let confirm_pl = false;
    if (pls.length) {
      const wasSame = pls.every(x => i.members.some(o => o.user_id === x.user_id && o.role === x.role));
      if (!wasSame) { if (!(await confirmBox(pls.map(x => `${x.role}이(가) PL입니다 (${userName(x.user_id)}).`).join("\n") + "\n정말 입력하시겠습니까?"))) return false; }
      confirm_pl = true;
    }
    const b = { model_id: Number(model.value) || null, title: title.value, source: source.value, occurred: occ.value, target: tgt.value, stage: Number(stage.value), status_text: status.value, delay_reason: delay.value, note: note.value, importance: imp.value, members, confirm_pl };
    if (isNew) { const r = await api("POST", "/api/issues", b); toast(`${r.no} 등록했습니다`); }
    else { await api("PUT", `/api/issues/${i.id}`, b); toast("저장했습니다"); }
    await after();
  } });
  if (can && !isNew) btns.unshift(i.hidden
    ? { text: "되살리기", fn: async () => { await api("POST", `/api/issues/${i.id}/hide`, { hidden: false }); toast("되살렸습니다"); await after(); } }
    : { text: "삭제 (숨김)", cls: "danger", fn: async () => {
      const reason = await promptBox("삭제 사유", "예: 중복 등록, 잘못 만든 이슈"); if (!reason) return false;
      await api("POST", `/api/issues/${i.id}/hide`, { hidden: true, reason }); toast("숨겼습니다 (기록과 시간은 남음)"); await after(); } });
  modal(isNew ? "새 이슈 등록" : `${i.no} ${i.title}`, body, btns);
}
function promptBox(title, ph) {
  return new Promise(res => { const inp = h("input", { class: "inp", placeholder: ph }); let ok = false;
    const close = modal(title, inp, [{ text: "확인", cls: "pri", fn: () => { if (!inp.value.trim()) { toast("내용을 적어 주세요", true); return false; } ok = true; res(inp.value.trim()); } }]);
    const obs = new MutationObserver(() => { if (!inp.isConnected) { obs.disconnect(); if (!ok) res(""); } }); obs.observe(document.body, { childList: true });
    setTimeout(() => inp.focus(), 50); });
}

// ── 요청하기 · 받은 요청 ──
function requestModal(toId) {
  const T = M.reqTargets || [];
  if (!T.length) return toast("요청을 보낼 사람이 없습니다", true);
  const rk = { pl: "PL", master: "마스터", lead: "팀장" };
  let pick = toId || T[0].id;
  const btns = h("div", { class: "seg req-to" });
  const draw = () => btns.replaceChildren(...T.map(u => h("button", { type: "button", class: u.id === pick ? "on" : "", onclick: () => { pick = u.id; draw(); } }, `${rk[u.role]} · ${u.name.split(" ")[0]}`)));
  draw();
  const txt = h("textarea", { class: "inp", rows: 6, placeholder: "요청 내용 (예: 11/12 이슈 26-017 회의 일정 조율 부탁드립니다 / 모델 목록에 ○○ 추가 요청)" });
  modal("요청하기", h("div", { class: "form" }, ...field("받는 사람", btns), ...field("요청 내용", txt)),
    [{ text: "보내기", cls: "pri", fn: async () => { await api("POST", "/api/requests", { to_id: pick, text: txt.value }); toast("요청을 보냈습니다 · '요청' 메뉴에서 처리 상태를 볼 수 있습니다"); } }]);
  setTimeout(() => txt.focus(), 50);
}
async function pageRequests() {
  const box = sessionStorage.getItem("rbox") || "in";
  const list = await api("GET", `/api/requests?box=${box}`);
  M.reqPending = box === "in" ? list.filter(r => r.status === "대기").length : M.reqPending; buildNav();
  const tab = (k, t) => h("button", { class: box === k ? "on" : "", onclick: () => { sessionStorage.setItem("rbox", k); pageRequests(); } }, t);
  const stCls = { 대기: "soon", 확인: "role", 완료: "done" };
  const card = r => {
    const mineIn = box === "in";
    const reply = h("textarea", { class: "inp", rows: 2, placeholder: "답변 (선택)" }, r.reply || "");
    const act = st => async () => { try { await api("PUT", `/api/requests/${r.id}`, { status: st, reply: reply.value }); toast(`'${st}'(으)로 바꿨습니다`); pageRequests(); } catch (e) { toast(e.message, true); } };
    return h("div", { class: "card req" + (r.status === "완료" ? " done" : "") },
      h("div", { class: "row" }, badge(stCls[r.status], r.status), h("b", {}, mineIn ? `${r.from_name} → 나` : `나 → ${r.to_name}`), h("span", { class: "muted small" }, r.created.slice(0, 16)), h("div", { class: "spacer" }),
        h("button", { class: "btn sm", onclick: async () => { await api("PUT", `/api/requests/${r.id}`, { hide: true }); pageRequests(); } }, "목록에서 숨기기")),
      h("div", { class: "pre", style: "margin:8px 0" }, r.text),
      mineIn ? h("div", {}, reply, h("div", { class: "row", style: "margin-top:6px" }, h("button", { class: "btn sm", onclick: act("확인") }, "확인함"), h("button", { class: "btn sm pri", onclick: act("완료") }, "완료"), r.status !== "대기" ? h("button", { class: "btn sm", onclick: act("대기") }, "대기로 되돌리기") : ""))
        : (r.reply ? h("div", { class: "duty" }, h("b", {}, `답변 · ${r.updated.slice(0, 16)}`), h("div", { class: "pre" }, r.reply)) : ""));
  };
  const open = list.filter(r => r.status !== "완료"), done = list.filter(r => r.status === "완료");
  app().replaceChildren(h("div", { class: "row page-hd" }, h("h1", {}, "요청"), h("div", { class: "spacer" }), (M.reqTargets || []).length ? h("button", { class: "btn pri", onclick: () => requestModal() }, "✉ 요청하기") : ""),
    h("div", { class: "tabs" }, tab("in", `받은 요청${M.reqPending ? ` (${M.reqPending})` : ""}`), tab("out", "보낸 요청")),
    ...(open.length ? open.map(card) : [h("div", { class: "card muted" }, box === "in" ? "처리할 요청이 없습니다." : "보낸 요청이 없습니다.")]),
    done.length ? foldable("req-done-" + box, `완료 (${done.length})`, done.map(card), false) : "");
}

// ── 업무 지정 (PL → 팀원 통상 업무) ──
async function pageAssign() {
  const list = await api("GET", "/api/assign");
  const part = M.perms.admin ? "" : M.perms.plPart;
  const people = M.users.filter(u => u.active && u.role !== "lead" && (!part || u.part === part));
  const title = h("input", { class: "inp", placeholder: "업무명 (예: B모델 EMC 대책 회로 검토)" });
  const model = sel([["", "공통 (모델 없음)"], ...modelsFor(part).map(m => [m.id, `${m.name} (${m.part} · ${m.phase || "-"})`])], "", { class: "inp" });
  const st = dateInput(M.today), tg = dateInput("");
  const imp = sel(["", "상", "중", "하"], "", { class: "inp" }), cat = sel([["", "-"], ...M.categories.map(c => [c.name, c.name])], "", { class: "inp" });
  const note = h("textarea", { class: "inp", rows: 3, placeholder: "할 일 · 참고 내용 (받는 사람 업무의 비고에 들어감)" });
  const checks = people.map(u => ({ u, el: h("input", { type: "checkbox" }) }));
  const form = h("div", { class: "card" }, h("div", { class: "form" }, ...field("업무명", title), ...field("모델", model), ...field("시작일", st), ...field("목표 마감일", tg), ...field("중요도", imp), ...field("업무 분류", cat), ...field("할 일 · 비고", note),
    ...field("받는 사람", h("div", { class: "picks" }, checks.map(c => h("label", { class: "pick" }, c.el, " ", c.u.name, part ? "" : h("small", { class: "muted" }, ` ${c.u.part}`)))))),
    h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "btn pri", onclick: async () => {
      const ids = checks.filter(c => c.el.checked).map(c => c.u.id);
      try { const r = await api("POST", "/api/assign", { user_ids: ids, title: title.value, model_id: Number(model.value) || null, start: st.value, target: tg.value, importance: imp.value, category: cat.value, note: note.value });
        toast(`${r.to.join(", ")} 에게 지정했습니다`); pageAssign(); } catch (e) { toast(e.message, true); }
    } }, "지정하기"), h("span", { class: "muted small" }, "받은 사람의 '내 업무'에 통상 업무로 생깁니다. 받은 사람도 내용을 고칠 수 있습니다.")));
  const groups = {};
  for (const t of list) (groups[t.assign_group || t.id] = groups[t.assign_group || t.id] || []).push(t);
  const fin = t => t.done || t.progress === 100;
  const gl = Object.values(groups);
  const card = g => h("div", { class: "card", style: "margin-bottom:10px" },
    h("div", { class: "row" }, h("b", {}, g[0].title), h("span", { class: "muted small" }, `${modelName(g[0].model_id) || "공통"} · 목표 ${g[0].target || "-"} · ${g[0].created?.slice(0, 10) || ""} 지정`)),
    h("table", { style: "margin-top:8px" }, h("tbody", {}, g.map(t => h("tr", { class: "click", onclick: () => taskModal(t, false, pageAssign) }, h("td", { style: "width:140px" }, nameTag(t.uname)), h("td", { style: "width:110px" }, h("div", { class: "row" }, (t.progress ?? 0) + "%", h("div", { class: "bar" }, h("i", { style: `width:${t.progress || 0}%` })))),
      h("td", { style: "width:110px" }, badge(t.sched.cls, t.sched.text)), h("td", { class: "num", style: "width:80px" }, fmtH(t.total) + "h"), h("td", { class: "small muted" }, t.hidden ? "받은 사람이 삭제함" : t.notes ? `기록 ${t.notes}건` : ""))))));
  const openG = gl.filter(g => !g.every(fin)), doneG = gl.filter(g => g.every(fin));
  app().replaceChildren(h("h1", {}, "업무 지정", h("span", { class: "sub" }, part ? `${part} 사람에게 통상 업무를 내려줍니다` : "모든 사람에게 통상 업무를 내려줍니다")),
    foldable("assign-form", "새 업무 지정", form, true),
    h("h2", {}, "내가 지정한 업무", h("span", { class: "sub" }, `진행 ${openG.length} · 완료 ${doneG.length} · 사람을 누르면 그 업무 보기 · 고치기`)),
    ...(openG.length ? openG.map(card) : [h("div", { class: "card muted" }, "진행 중인 지정 업무가 없습니다.")]),
    doneG.length ? foldable("assign-done", `완료된 지정 업무 (${doneG.length})`, doneG.map(card), false) : "");
}

// ── 업무로드 (팀장) ──
async function pageDash() {
  const root = h("div"); app().replaceChildren(root);
  const load = async () => {
    const d = await api("GET", `/api/dashboard?${perQs()}`);
    const t = d.team;
    const bar = (v, over) => h("div", { class: "bar" + (over ? " over" : "") }, h("i", { style: `width:${Math.min(100, Math.round((v || 0) * 100 / 1.5))}%` }));
    const tiles = h("div", { class: "cards" },
      h("div", { class: "card stat" }, h("div", { class: "k" }, "팀 근무 시간율"), h("div", { class: "v" }, fmtPct(t.rate)), h("div", { class: "s" }, `${fmtH(t.input)}h ÷ ${fmtH(t.base)}h`)),
      h("div", { class: "card stat" }, h("div", { class: "k" }, "팀 업무 로드"), h("div", { class: "v" }, fmtPct(t.load))),
      h("div", { class: "card stat" }, h("div", { class: "k" }, "과부하 인원"), h("div", { class: "v" }, t.over + "명")),
      h("div", { class: "card stat" }, h("div", { class: "k" }, "주 52h 초과"), h("div", { class: "v" }, t.w52 + "명")),
      h("div", { class: "card stat" }, h("div", { class: "k" }, "로드 높음"), h("div", { class: "v" }, t.high + "명")),
      h("div", { class: "card stat" }, h("div", { class: "k" }, "적정 · 여유"), h("div", { class: "v" }, `${t.fit} · ${t.spare}명`)));
    const parts = h("div", { class: "tbl" }, h("table", { class: "center" }, h("thead", {}, h("tr", {}, ["파트", "인원", "담당 모델", "cross join", "진행 이슈", "지연 이슈", "근무 시간율", "업무 로드", "과부하"].map(x => h("th", {}, x)))),
      h("tbody", {}, d.parts.map(p => h("tr", {}, h("td", {}, h("b", {}, p.part)), h("td", { class: "num" }, p.n), h("td", { class: "num" }, p.models), h("td", { class: "num" }, p.cross), h("td", { class: "num" }, p.issuesOpen), h("td", { class: "num" }, p.issuesLate),
        h("td", {}, h("div", { class: "row" }, fmtPct(p.rate), bar(p.rate, p.rate > 1.2))), h("td", {}, h("div", { class: "row" }, fmtPct(p.load), bar(p.load))), h("td", { class: "num" }, p.over))))));
    const cols = d.modelCols.filter(mc => d.people.some(p => p.models[mc.name]));
    const judgeB = p => badge(p.rateCls === "과부하" ? "over" : p.rateCls === "적정" ? "fit" : "spare", p.judge);
    const rc = p => p.rate > 1.2 ? "over" : "";
    const layout = getPref("dashLayout", "1");
    let people;
    if (layout === "2") {
      // 안 2: 모델 열을 촘촘하게 (세로 글씨 머리글 · 좁은 칸) → 한 화면에
      people = h("div", { class: "tbl" }, h("table", { class: "dash-people dl2" }, h("thead", {}, h("tr", {}, [["이름", "w-nm"], ["파트", "w-pt"], ["근무 시간율", "w-rt"], ["업무 로드", "w-rt"], ["판정", "w-jd"], ["미입력", "w-ms"]].map(([x, c]) => h("th", { class: c }, x)),
        [{ name: "공통·기타" }, ...cols].map(mc => h("th", { class: "mh", title: mc.part ? `${mc.part} · ${mc.phase} · 배율 ${Math.round(mc.weight * 100)}%` : "모델 없는 업무" }, mc.name)))),
        h("tbody", {}, d.people.map(p => h("tr", { class: "click", onclick: () => (location.hash = `#/people/${p.user_id}`) },
          h("td", {}, nameTag(p.name)), h("td", { class: "small" }, p.part), h("td", { class: "c" }, fmtPct(p.rate)), h("td", { class: "c" }, fmtPct(p.load)),
          h("td", { class: "c", title: p.judge + (p.action ? " · " + p.action : "") }, badge(p.rateCls === "과부하" ? "over" : p.rateCls === "적정" ? "fit" : "spare", p.rateCls || p.judge)), h("td", { class: "c" + (p.missing ? " err" : "") }, p.missing),
          [{ name: "공통·기타" }, ...cols].map(mc => { const v = p.models[mc.name] || 0; const r = p.input ? v / p.input : 0; return h("td", { class: "heat c", title: `${mc.name} ${fmtH(v)}h`, style: v ? (document.documentElement.dataset.dark === "1" ? `background:rgba(91,141,239,${0.10 + r * 0.55})${r > 0.45 ? ";color:#fff" : ""}` : `background:rgba(47,85,151,${0.08 + r * 0.6})${r > 0.45 ? ";color:#fff" : ""}`) : "" }, v ? fmtH(v) : ""); }))))));
    } else {
      // 안 1: 파트 합계 행 + 사람 행을 한 표에 · 모델은 '모델별 투입' 막대 한 칸 (많은 순 3개 이름)
      const palette = ["#2f5597", "#4f81bd", "#7fa7d9", "#9bbb59", "#f79646", "#8064a2", "#4bacc6", "#c0504d", "#a5a5a5"];
      const mcolor = {}; [{ name: "공통·기타" }, ...cols].forEach((mc, i) => (mcolor[mc.name] = mc.name === "공통·기타" ? "#c9ced6" : palette[i % palette.length]));
      const stack = p => { const ent = Object.entries(p.models).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]); const tot = ent.reduce((a, [, v]) => a + v, 0) || 1;
        return h("div", { class: "mstack" }, h("div", { class: "sbar" }, ent.map(([n, v]) => h("i", { title: `${n} ${fmtH(v)}h (${Math.round(v * 100 / tot)}%)`, style: `width:${v * 100 / tot}%;background:${mcolor[n] || "#999"}` }))),
          h("div", { class: "small muted" }, ent.slice(0, 3).map(([n, v]) => `${n} ${fmtH(v)}h`).join(" · ") + (ent.length > 3 ? ` 외 ${ent.length - 3}` : ""))); };
      const rows = [];
      for (const pr of d.parts) {
        const ps = d.people.filter(p => p.part === pr.part); if (!ps.length) continue;
        rows.push(h("tr", { class: "part-row" }, h("td", {}, h("b", {}, pr.part)), h("td", { class: "c" }, pr.n + "명"), h("td", {}, h("div", { class: "row" }, fmtPct(pr.rate), bar(pr.rate, pr.rate > 1.2))), h("td", {}, h("div", { class: "row" }, fmtPct(pr.load), bar(pr.load))),
          h("td", { class: "small" }, pr.over ? `과부하 ${pr.over}명` : ""), h("td", { class: "c" }, ps.reduce((a, p) => a + p.missing, 0) || ""), h("td", { class: "small muted" }, `모델 ${pr.models} · cross ${pr.cross}`)));
        for (const p of ps) rows.push(h("tr", { class: "click", onclick: () => (location.hash = `#/people/${p.user_id}`) },
          h("td", { class: "ind" }, nameTag(p.name)), h("td", { class: "c small muted" }, roleKo[p.role] || ""), h("td", {}, h("div", { class: "row" }, fmtPct(p.rate), bar(p.rate, p.rate > 1.2))), h("td", {}, h("div", { class: "row" }, fmtPct(p.load), bar(p.load))),
          h("td", {}, judgeB(p)), h("td", { class: "c" + (p.missing ? " err" : "") }, p.missing || ""), h("td", {}, stack(p))));
      }
      people = h("div", { class: "tbl" }, h("table", { class: "dash-people dl1" }, h("thead", {}, h("tr", {}, ["파트 / 이름", "인원", "근무 시간율", "업무 로드", "판정", "미입력", "모델별 투입 (많은 순)"].map(x => h("th", {}, x)))), h("tbody", {}, rows)));
    }
    root.replaceChildren(h("div", { class: "row" }, h("h1", {}, "업무로드", h("span", { class: "sub" }, `${d.from} ~ ${d.to} · 오늘 ${d.today}`)), h("div", { class: "spacer" }), periodBar(load)),
      tiles, ...(getPref("dashLayout", "1") === "1" ? [] : [h("h2", {}, "파트별"), parts]), h("div", { class: "row" }, h("h2", {}, getPref("dashLayout", "1") === "1" ? "파트 · 개인별" : "개인별", h("span", { class: "sub" }, "이름을 누르면 그 사람 화면")), h("div", { class: "spacer" }),
        h("div", { class: "seg lay-sw" }, [["1", "파트 묶음 · 모델 막대"], ["2", "모델별 시간 표"]].map(([k, t]) => h("button", { class: getPref("dashLayout", "1") === k ? "on" : "", onclick: () => { setPref("dashLayout", k); load(); } }, t)))), people,
      h("div", { class: "help" }, "근무 시간율 = 투입 ÷ 기준 시간 (주 40h = 100%) · 업무 로드 = Σ(배율 × 시간) ÷ 기준 시간 · 배율: 단계 양산 · 선행검토면 그 배율, 회로플랫폼 · 아트웍 모델은 그 파트 배율, 그 외 등급 배율"));
  };
  await load();
}

// ── 이슈 요약 ──
async function pageSummary() {
  const s = await api("GET", "/api/summary");
  const c = s.count;
  const open = s.issues.filter(i => !(i.done || i.stage === 6));
  const grp = (title, list, k) => [h("h2", { class: k ? "h-" + k : "" }, title, h("span", { class: "sub" }, list.length + "건")), h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["번호", "파트", "모델", "이슈명", "담당", "Target", "일정", "단계", "지연 사유"].map(x => h("th", {}, x)))),
    h("tbody", {}, list.map(i => h("tr", { class: "click" + (k ? " r-" + k : ""), onclick: () => issueModal(i, pageSummary) }, h("td", {}, h("b", {}, i.no)), h("td", {}, i.part), h("td", {}, i.model), h("td", {}, i.title), h("td", { class: "small" }, i.members.map(m => `${m.role} ${m.name}`).join(" · ")),
      h("td", {}, i.target || ""), h("td", {}, badge(i.sched.cls, i.sched.text)), h("td", {}, M.stages[(i.stage || 1) - 1]), h("td", { class: "small pre" }, i.needDelay ? badge("late", "필요") : i.delay_reason))))))];
  app().replaceChildren(h("h1", {}, "이슈 요약"),
    h("div", { class: "cards" }, [["진행", c.open], ["지연", c.late, "late"], ["임박", c.soon, "soon"], ["완료", c.done], ["지연 사유 미입력", c.needDelay, "late"]].map(([k, v, cl]) => h("div", { class: "card stat" + (cl && v ? " k-" + cl : "") }, h("div", { class: "k" }, k), h("div", { class: "v" }, v + "건")))),
    ...grp("지연", open.filter(i => i.sched.cls === "late"), "late"), ...grp("임박", open.filter(i => i.sched.cls === "soon"), "soon"), ...grp("진행", open.filter(i => !["late", "soon"].includes(i.sched.cls))));
}

// ── 사람별 ──
async function pagePeople(uid) {
  if (uid) return pageMe(uid, M.user.id !== uid);
  const list = M.users.filter(u => u.role !== "lead" && u.active);
  app().replaceChildren(h("h1", {}, "사람별"), h("div", { class: "cards" }, list.map(u => h("a", { class: "card", href: `#/people/${u.id}`, style: "text-decoration:none;color:inherit" }, h("b", {}, u.name), h("div", { class: "muted small" }, `${u.part} · ${roleKo[u.role]}`)))));
}

// ── 기준정보 ──
async function pageMaster() {
  M = await api("GET", "/api/meta");
  const tab = sessionStorage.getItem("mtab") || "g";
  const T = (k, t) => h("button", { class: tab === k ? "on" : "", onclick: () => { sessionStorage.setItem("mtab", k); pageMaster(); } }, t);
  const body = h("div");
  app().replaceChildren(h("h1", {}, "기준정보", h("span", { class: "sub" }, "여기서 고친 값은 바로 모든 화면 계산에 반영됩니다 · 마스터 · 팀장 · PL이 고칩니다" + (M.perms.pl ? ` (모델은 ${M.perms.plPart}만)` : ""))), h("div", { class: "tabs" }, T("g", "등급 배율"), T("m", "모델"), T("h", "공휴일"), T("l", "휴직"), T("s", "기준값"), T("j", "판정 문구"), T("c", "업무 분류")), body);
  if (tab === "g") {
    const ins = M.grades.map(g => ({ g, el: h("input", { class: "inp", style: "width:90px", value: Math.round(g.pct * 1000) / 10 }) }));
    const oth = h("input", { class: "inp", style: "width:90px", value: Math.round(Number(M.settings.other_pct || 0) * 1000) / 10 });
    const nn = h("input", { class: "inp", placeholder: "새 등급 · 파트 이름" }), np = h("input", { class: "inp", style: "width:90px", placeholder: "%" });
    body.append(h("div", { class: "card", style: "max-width:560px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "등급 / 파트"), h("th", {}, "배율 (%)"))), h("tbody", {}, ins.map(x => h("tr", {}, h("td", {}, x.g.name), h("td", {}, x.el, " %"))), h("tr", {}, h("td", {}, "공통·기타 (모델 없음)"), h("td", {}, oth, " %")))),
      h("div", { class: "help" }, "단계가 양산 · 선행검토인 모델은 등급과 관계없이 그 배율, 모델의 파트 이름(회로플랫폼 · 아트웍)이 이 표에 있으면 그 파트 배율을 씁니다 (단계 우선)."),
      h("div", { class: "row" }, h("button", { class: "btn pri", onclick: async () => { try { await api("PUT", "/api/master/grades", { items: ins.map(x => ({ name: x.g.name, pct: Number(x.el.value) / 100 })), other_pct: Number(oth.value) / 100 }); toast("저장했습니다"); } catch (e) { toast(e.message, true); } } }, "저장"),
        h("div", { class: "spacer" }), nn, np, h("button", { class: "btn", onclick: async () => { try { await api("POST", "/api/master/grades", { name: nn.value, pct: Number(np.value) / 100 }); pageMaster(); } catch (e) { toast(e.message, true); } } }, "추가"))));
  }
  if (tab === "m") {
    const myPart = M.perms.pl ? M.perms.plPart : "";
    const mk = m => {
      const ro = !!myPart && !!m.id && m.part !== myPart;   // PL: 다른 파트 모델은 보기만
      const r = { name: h("input", { class: "mini-in", value: m.name || "", disabled: ro }), part: sel(myPart ? [myPart] : ["", ...M.parts], m.id ? m.part : myPart, { class: "mini-in", disabled: ro || !!myPart }), grade: sel(["", ...M.grades.map(g => g.name)], m.grade, { class: "mini-in", disabled: ro }),
        phase: sel(["", ...M.phases], m.phase, { class: "mini-in", disabled: ro }), customer: h("input", { class: "mini-in", value: m.customer || "", style: "width:90px", disabled: ro }), sop: dateInput(m.sop, { disabled: ro }),
        active: h("input", { type: "checkbox", checked: m.id ? m.active : true, disabled: ro }) };
      if (ro) return h("tr", { class: "muted" }, h("td", {}, r.name), h("td", {}, m.part), h("td", {}, r.grade), h("td", {}, r.phase), h("td", {}, r.customer), h("td", {}, r.sop), h("td", { class: "c" }, r.active), h("td", { class: "small" }, "🔒"));
      const save = h("button", { class: "btn sm" + (m.id ? "" : " pri"), onclick: async () => { try { await api(m.id ? "PUT" : "POST", "/api/master/models", { id: m.id, name: r.name.value, part: r.part.value, grade: r.grade.value, phase: r.phase.value, customer: r.customer.value, sop: r.sop.value, active: r.active.checked }); toast("저장했습니다"); pageMaster(); } catch (e) { toast(e.message, true); } } }, m.id ? "저장" : "추가");
      return h("tr", {}, h("td", {}, r.name), h("td", {}, r.part), h("td", {}, r.grade), h("td", {}, r.phase), h("td", {}, r.customer), h("td", {}, r.sop), h("td", { class: "c" }, r.active), h("td", {}, save));
    };
    body.append(h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["모델명", "파트", "등급", "단계", "고객사", "양산 목표", "관리 (사용)", ""].map(x => h("th", {}, x)))), h("tbody", {}, M.models.map(mk), mk({})))),
      h("div", { class: "help" }, "관리를 끄면 드롭다운과 업무로드 모델 칸에서 빠집니다 (기록은 남음). 모델은 지우지 않고 관리를 끕니다."));
  }
  if (tab === "h") {
    const list = await api("GET", "/api/master/holidays");
    const d = dateInput(""), n = h("input", { class: "inp", placeholder: "명칭", style: "max-width:220px" });
    body.append(h("div", { class: "row", style: "margin-bottom:8px" }, d, n, h("button", { class: "btn pri", onclick: async () => { try { await api("POST", "/api/master/holidays", { date: d.value, name: n.value }); pageMaster(); } catch (e) { toast(e.message, true); } } }, "추가")),
      h("div", { class: "tbl", style: "max-width:520px" }, h("table", {}, h("tbody", {}, list.map(x => h("tr", {}, h("td", {}, x.date), h("td", {}, x.name), h("td", {}, h("button", { class: "btn sm danger", onclick: async () => { await api("DELETE", "/api/master/holidays", { date: x.date }); pageMaster(); } }, "빼기"))))))));
  }
  if (tab === "l") {
    const list = await api("GET", "/api/master/leaves");
    const u = sel(M.users.filter(x => x.role !== "lead").map(x => [x.id, x.name])), s = dateInput(""), e = dateInput("");
    body.append(h("div", { class: "help" }, "휴직 기간은 기준 시간 0 · 미입력에서 빠집니다. 복직일 = 다시 출근하는 첫날 (비우면 휴직 중)."),
      h("div", { class: "row", style: "margin-bottom:8px" }, u, s, e, h("button", { class: "btn pri", onclick: async () => { try { await api("POST", "/api/master/leaves", { user_id: Number(u.value), start: s.value, end: e.value }); pageMaster(); } catch (er) { toast(er.message, true); } } }, "추가")),
      h("div", { class: "tbl", style: "max-width:640px" }, h("table", {}, h("thead", {}, h("tr", {}, ["이름", "시작일", "복직일", ""].map(x => h("th", {}, x)))), h("tbody", {}, list.map(x => {
        const ss = dateInput(x.start), ee = dateInput(x.end);
        return h("tr", {}, h("td", {}, x.name), h("td", {}, ss), h("td", {}, ee), h("td", {}, h("button", { class: "btn sm", onclick: async () => { await api("PUT", "/api/master/leaves", { id: x.id, start: ss.value, end: ee.value }); toast("저장했습니다"); } }, "저장")));
      })))));
  }
  if (tab === "s") {
    const S = M.settings;
    const items = [["hstart", "시간 기록 시작일", "date"], ["day_hours", "하루 기준 시간 (h)"], ["early_hours", "조퇴 차감 시간 (h)"], ["unit", "입력 단위 (h)"], ["over", "과부하 기준 (근무 시간율 초과, 1.2 = 120%)"], ["fit", "적정 기준 (이상)"], ["lhi", "업무 로드 높음 (이상)"], ["llo", "업무 로드 낮음 (미만)"], ["soon_days", "임박 (D-일 이내)"], ["done_keep_days", "완료 이슈를 PL 화면에 보이는 일수"], ["today_fix", "기준 날짜 고정 (비우면 오늘)", "date"]];
    const ins = items.map(([k, t, ty]) => ({ k, el: ty === "date" ? dateInput(S[k] || "") : h("input", { value: S[k] || "" }), t }));
    body.append(h("div", { class: "card", style: "max-width:640px" }, h("div", { class: "form" }, ins.flatMap(x => field(x.t, x.el))),
      h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "btn pri", onclick: async () => { try { await api("PUT", "/api/master/settings", Object.fromEntries(ins.map(x => [x.k, x.el.value]))); toast("저장했습니다"); M = await api("GET", "/api/meta"); } catch (e) { toast(e.message, true); } } }, "저장"))));
  }
  if (tab === "j") {
    const ins = M.judge.map((j, i) => ({ i, t: h("input", { class: "mini-in", value: j.text || "", style: "width:100%" }), a: h("input", { class: "mini-in", value: j.action || "", style: "width:100%" }) }));
    body.append(h("div", { class: "help" }, "근무 시간율 구분(과부하 · 적정 · 여유)과 업무 로드 구분(높음 · 중간 · 낮음)에 따라 보이는 판정 문구와 권장 조치입니다. 구분 기준값은 '기준값' 탭에서 고칩니다."),
      h("div", { class: "tbl", style: "max-width:980px" }, h("table", {}, h("thead", {}, h("tr", {}, ["근무 시간율", "업무 로드", "판정 문구", "권장 조치"].map(x => h("th", {}, x)))),
        h("tbody", {}, ins.map(x => h("tr", {}, h("td", { class: "nowrap" }, M.judge[x.i].rate), h("td", { class: "nowrap" }, M.judge[x.i].load), h("td", { style: "width:220px" }, x.t), h("td", {}, x.a)))))),
      h("div", { class: "row", style: "margin-top:10px" }, h("button", { class: "btn pri", onclick: async () => { try { await api("PUT", "/api/master/judge", { items: ins.map(x => ({ i: x.i, text: x.t.value, action: x.a.value })) }); toast("저장했습니다"); } catch (e) { toast(e.message, true); } } }, "저장")));
  }
  if (tab === "c") {
    const b = h("input", { class: "inp", placeholder: "대분류" }), m = h("input", { class: "inp", placeholder: "중분류" }), n = h("input", { class: "inp", placeholder: "소분류 (선택 목록에 보이는 이름)" });
    body.append(h("div", { class: "row", style: "margin-bottom:8px" }, b, m, n, h("button", { class: "btn pri", onclick: async () => { try { await api("POST", "/api/master/categories", { big: b.value, mid: m.value, name: n.value }); pageMaster(); } catch (e) { toast(e.message, true); } } }, "추가")),
      h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["대분류", "중분류", "업무 분류"].map(x => h("th", {}, x)))), h("tbody", {}, M.categories.map(c => h("tr", {}, h("td", {}, c.big), h("td", {}, c.mid), h("td", {}, c.name)))))));
  }
}

// ── 관리 ──
async function pageAdmin() {
  const tab = sessionStorage.getItem("atab") || "u";
  const T = (k, t) => h("button", { class: tab === k ? "on" : "", onclick: () => { sessionStorage.setItem("atab", k); pageAdmin(); } }, t);
  const body = h("div");
  app().replaceChildren(h("h1", {}, "관리"), h("div", { class: "tabs" }, T("u", "계정"), T("imp", "엑셀 가져오기"), T("mail", "메일 설정"), T("b", "백업"), T("a", "변경 기록")), body);
  if (tab === "imp") {
    const f = h("input", { type: "file", accept: ".json,application/json" });
    const fromI = dateInput(""), toI = dateInput("");
    const info = h("div"), out = h("div");
    let seed = null;
    f.addEventListener("change", async () => {
      try { seed = JSON.parse(await f.files[0].text()); } catch { seed = null; return toast("가져오기 파일(seed.json)이 아닙니다", true); }
      // 파일 안의 날짜 범위 · 사람별 마지막 입력일
      const last = {}; let lo = "9999", hi = "";
      const see = (u, d) => { if (d < lo) lo = d; if (d > hi) hi = d; if (!last[u] || d > last[u]) last[u] = d; };
      for (const t of seed.tasks || []) for (const d of Object.keys(t.hours)) see(t.user, d);
      for (const i of seed.issues || []) for (const lg of i.logs || []) for (const d of Object.keys(lg.hours)) see(lg.user, d);
      fromI.value = lo === "9999" ? "" : lo; toI.value = hi;
      info.replaceChildren(h("div", { class: "help" }, `파일: ${seed.source || "-"} (${(seed.extracted || "").slice(0, 16)}) · 사람 ${seed.people?.length} · 업무 ${seed.tasks?.length} · 이슈 ${seed.issues?.length} · 시간이 있는 날짜 ${lo} ~ ${hi}`),
        h("div", { class: "small muted", style: "margin:4px 0 8px" }, "사람별 마지막 입력일: " + (seed.people || []).map(p => `${p.name.split(" ")[0]} ${(last[p.name] || "-").slice(5)}`).join(" · ")));
    });
    const show = (r, dry) => out.append(h("div", { class: "card", style: "margin-top:10px" }, h("b", {}, dry ? `미리보기 (${fromI.value} ~ ${toI.value} · 아직 바뀐 것 없음)` : "가져오기 완료"),
      h("div", { class: "small", style: "margin-top:6px" }, `새 계정 ${r.users} · 업무 새로 ${r.tasksNew} / 고침 ${r.tasksUpd} · 엑셀에서 없어져 숨김 ${r.hidden} · 기간 안 시간 ${r.hoursSet}칸 엑셀 값으로 · 이슈 새로 ${r.issuesNew} / 고침 ${r.issuesUpd} · 모델 추가 ${r.models} · 휴직 추가 ${r.leaves}`),
      r.renamed.length ? h("div", { class: "small", style: "margin-top:4px" }, "업무명이 바뀐 행 (같은 업무로 맞춤): " + r.renamed.slice(0, 15).join(" / ")) : "",
      r.issuesHidden.length ? h("div", { class: "small", style: "margin-top:4px" }, "엑셀 이슈 정리에서 없어져 숨긴 이슈 (기록은 남음): " + r.issuesHidden.join(" / ")) : "",
      r.skipped.length ? h("div", { class: "small err" }, "건너뜀: " + r.skipped.slice(0, 10).join(" / ")) : ""));
    const go = async dry => {
      if (!seed) return toast("먼저 파일을 고르세요", true);
      if (!dry && !(await confirmBox(`${fromI.value} ~ ${toI.value} 기간의 시간을 엑셀 값으로 맞추고, 업무 · 이슈 내용을 엑셀대로 고치거나 추가합니다.\n기간 밖 시간, 웹에서 만든 업무 · 이슈, 계정 · 비밀번호는 그대로입니다.\n시작 전에 자동 백업을 만듭니다.`))) return;
      try { const r = await api("POST", "/api/admin/import", { seed, from: fromI.value, to: toI.value, dry }); show(r, dry); if (!dry) toast("가져왔습니다"); } catch (e) { toast(e.message, true); }
    };
    body.append(h("div", { class: "help" }, "엑셀(팀장 파일)에서 만든 가져오기 파일(seed.json)로 웹 데이터를 엑셀에 맞춥니다. 파일을 고르면 들어 있는 날짜 범위가 기간에 자동으로 들어갑니다. 기간을 줄이면 그 날짜의 시간만 엑셀 값으로 바뀝니다 (업무 · 이슈 내용과 새 이슈는 기간과 상관없이 반영)."),
      h("div", { class: "card", style: "max-width:760px" }, h("div", { class: "form" }, ...field("가져오기 파일", f), ...field("반영할 기간", h("div", { class: "row" }, fromI, h("span", { class: "muted" }, "~"), toI))), info,
        h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "btn", onclick: () => go(true) }, "미리보기"), h("button", { class: "btn pri", onclick: () => go(false) }, "가져오기"))), out);
  }
  if (tab === "mail") {
    const c = await api("GET", "/api/admin/mail");
    const f = { smtp_host: h("input", { value: c.smtp_host, placeholder: "예: mail.회사.co.kr 또는 IP" }), smtp_port: h("input", { value: c.smtp_port, style: "max-width:120px" }),
      smtp_secure: sel([["0", "보통 (25 · 587, STARTTLS 자동)"], ["1", "SSL (465)"]], c.smtp_secure), smtp_user: h("input", { value: c.smtp_user, placeholder: "로그인이 필요 없으면 비움" }),
      smtp_pass: h("input", { type: "password", placeholder: c.smtp_pass_set ? "(저장됨 · 바꿀 때만 입력)" : "" }), smtp_tls_check: sel([["1", "확인함 (기본)"], ["0", "확인 안 함 (사내 인증서일 때)"]], c.smtp_tls_check),
      mail_from: h("input", { value: c.mail_from, placeholder: "예: 업무관리 <noreply@회사.co.kr>" }), mail_domain: h("input", { value: c.mail_domain, placeholder: "예: company.co.kr (이 도메인 메일만 등록 허용 · 비우면 제한 없음)" }) };
    const to = h("input", { class: "inp", placeholder: "시험 메일 받을 주소", style: "max-width:300px" });
    body.append(h("div", { class: "help" }, "비밀번호 찾기 인증번호를 보낼 사내 메일 서버(SMTP)입니다. 값은 IT팀에 받습니다 (서버 주소 · 포트 · 보내는 계정). 비밀번호는 데이터 파일에 저장되므로 보내기 전용 계정을 권합니다."),
      h("div", { class: "card", style: "max-width:720px" }, h("div", { class: "form" }, ...field("SMTP 서버", f.smtp_host), ...field("포트", f.smtp_port), ...field("보안", f.smtp_secure), ...field("계정", f.smtp_user), ...field("계정 비밀번호", f.smtp_pass), ...field("인증서 확인", f.smtp_tls_check), ...field("보내는 사람", f.mail_from), ...field("회사 메일 도메인", f.mail_domain)),
        h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "btn pri", onclick: async () => { const b = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value])); if (!b.smtp_pass) delete b.smtp_pass; try { await api("PUT", "/api/admin/mail", b); toast("저장했습니다"); } catch (e) { toast(e.message, true); } } }, "저장"),
          to, h("button", { class: "btn", onclick: async () => { try { await api("POST", "/api/admin/mail/test", { to: to.value.trim() }); toast("시험 메일을 보냈습니다"); } catch (e) { toast(e.message, true); } } }, "시험 메일 보내기"))));
  }
  if (tab === "u") {
    M = await api("GET", "/api/meta");
    const showTemp = (who, pw) => modal("처음 비밀번호", h("div", {}, h("p", {}, `${who} 의 처음 비밀번호:`), h("div", { style: "font-size:26px;font-weight:700;letter-spacing:3px;font-family:Consolas,monospace" }, pw), h("p", { class: "muted small" }, "본인에게 직접 전달하세요 (메신저 · 메일에 남기지 않기를 권합니다). 처음 로그인할 때 새 비밀번호로 바꿉니다. 이 창을 닫으면 다시 볼 수 없고, 파일로도 남지 않습니다.")), []);
    const files = M.acctFiles ? await api("GET", "/api/admin/acctfiles") : [];
    if (files.length) body.append(h("div", { class: "help warn" }, h("b", {}, "보안: 예전 버전에서 만든 계정표 파일이 데이터 폴더에 남아 있습니다 "), `(${files.join(", ")}). 처음 비밀번호가 적혀 있으니 계정을 나눠 줬다면 지우세요. `,
      h("button", { class: "btn sm danger", onclick: async () => { if (!(await confirmBox("계정표 파일을 지웁니다. (아직 로그인 안 한 사람은 '비밀번호 초기화'로 새로 받으면 됩니다)"))) return; const r = await api("DELETE", "/api/admin/acctfiles"); toast(`${r.deleted.length}개 지웠습니다`); M.acctFiles = 0; pageAdmin(); } }, "지금 지우기")));
    const noPw = M.users.filter(u => u.active && !u.has_pw).length;
    if (noPw) body.append(h("div", { class: "help" }, `처음 비밀번호가 아직 없는 계정 ${noPw}개 → '처음 비밀번호 만들기'를 눌러 나온 비밀번호를 본인에게 전달하세요.`));
    const rows = M.users.map(u => {
      const role = sel([["member", "팀원"], ["pl", "PL"], ["lead", "팀장"], ["master", "마스터"]], u.role, { class: "mini-in" });
      const part = sel(["", ...M.parts], u.part, { class: "mini-in" }); const title = h("input", { class: "mini-in", value: u.title || "", style: "width:70px" });
      const name = h("input", { class: "mini-in", value: u.name, style: "width:110px" });
      const act = h("input", { type: "checkbox", checked: !!u.active });
      const email = h("input", { class: "mini-in", value: u.email || "", style: "width:190px", placeholder: "회사 메일" });
      return h("tr", {}, h("td", {}, u.login, !u.has_pw ? [" ", badge("warn", "비밀번호 없음")] : u.must_change ? [" ", badge("", "처음 로그인 전")] : ""), h("td", {}, name), h("td", {}, title), h("td", {}, part), h("td", {}, role), h("td", {}, email), h("td", { class: "c" }, act),
        h("td", {}, h("button", { class: "btn sm", onclick: async () => { try { await api("PUT", `/api/admin/users/${u.id}`, { name: name.value, title: title.value, part: part.value, role: role.value, active: act.checked, email: email.value.trim() }); toast("저장했습니다"); M = await api("GET", "/api/meta"); } catch (e) { toast(e.message, true); } } }, "저장"), " ",
          h("button", { class: "btn sm", onclick: async () => { if (u.has_pw && !(await confirmBox(`${u.name} 비밀번호를 초기화할까요?`))) return; try { const r = await api("POST", `/api/admin/users/${u.id}/reset`, {}); showTemp(u.name, r.temp); pageAdmin(); } catch (e) { toast(e.message, true); } } }, u.has_pw ? "비밀번호 초기화" : "처음 비밀번호 만들기")));
    });
    const nl = h("input", { class: "inp", placeholder: "아이디 (예: 홍길동)" }), nn = h("input", { class: "inp", placeholder: "이름 (예: 홍길동 선임)" }), nt = h("input", { class: "inp", placeholder: "직급" }), np = sel(["", ...M.parts], ""), nr = sel([["member", "팀원"], ["pl", "PL"], ["lead", "팀장"], ["master", "마스터"]], "member");
    body.append(h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["아이디", "이름", "직급", "파트", "권한", "회사 메일", "사용", ""].map(x => h("th", {}, x)))), h("tbody", {}, rows))),
      h("h2", {}, "계정 추가"), h("div", { class: "row" }, nl, nn, nt, np, nr, h("button", { class: "btn pri", onclick: async () => { try { const r = await api("POST", "/api/admin/users", { login: nl.value, name: nn.value, title: nt.value, part: np.value, role: nr.value }); showTemp(nn.value, r.temp); pageAdmin(); } catch (e) { toast(e.message, true); } } }, "추가")),
      h("div", { class: "help" }, "PL = 그 파트 모델의 이슈를 등록 · 관리 · 업무 지정 · 팀장 = 모든 화면 (개인 업무 화면 없음) · 마스터 = 팀장과 같은 권한 + 본인 업무 화면. 퇴사자는 '사용'을 끕니다 (기록은 남음)."));
  }
  if (tab === "b") {
    const b = await api("GET", "/api/admin/backups");
    body.append(h("div", { class: "help" }, "서버는 매일 처음 켜질 때와 30분마다 확인해서 하루 한 번 자동 백업합니다 (최근 90개 보관). 백업 파일(.db)은 데이터 전체입니다."),
      h("div", { class: "row", style: "margin-bottom:10px" }, h("button", { class: "btn pri", onclick: async () => { const r = await api("POST", "/api/admin/backups", {}); toast(`백업: ${r.name}`); pageAdmin(); } }, "지금 백업")),
      h("div", { class: "tbl", style: "max-width:700px" }, h("table", {}, h("thead", {}, h("tr", {}, ["백업 파일", "크기", ""].map(x => h("th", {}, x)))), h("tbody", {}, b.list.map(x => h("tr", {}, h("td", {}, x.name), h("td", { class: "num" }, Math.round(x.size / 1024) + " KB"), h("td", {}, h("a", { href: `/api/admin/backups/${encodeURIComponent(x.name)}` }, "내려받기"))))))));
  }
  if (tab === "a") {
    const list = await api("GET", "/api/admin/audit?limit=400");
    body.append(h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["시각", "누가", "작업", "대상", "내용"].map(x => h("th", {}, x)))), h("tbody", {}, list.map(a => h("tr", {}, h("td", { class: "small" }, a.at), h("td", {}, a.name || "-"), h("td", {}, a.action), h("td", { class: "small" }, a.target), h("td", { class: "small" }, (a.detail || "").slice(0, 300))))))));
  }
}

boot().catch(() => showLogin());

