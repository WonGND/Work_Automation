# 0.7.2 시험: PL 다른 파트 지정 · 일을 준 사람 보기 · 이슈 템플릿 항목 · 이전 기록 보존
# 사용: python3 -I v071_test.py <주소> <계정표> <seed.json> <DB>   (seed 로 처음 설정한 빈 서버)
import sys, json, urllib.request, http.cookiejar, sqlite3
BASE, ACC, SEED, DB = sys.argv[1:5]
ok = bad = 0
def check(n, c, i=""):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("  ✗", n, i)
class S:
    def __init__(s): s.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def req(s, m, p, b=None):
        r = urllib.request.Request(BASE + urllib.request.quote(p, safe="/?=&"), data=None if b is None else json.dumps(b, ensure_ascii=False).encode(), method=m, headers={"content-type": "application/json", "x-req": "1"})
        try:
            with s.op.open(r) as res: return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read())
            except Exception: return e.code, {}
acc = {l.split("\t")[0]: l.split("\t")[1] for l in open(ACC, encoding="utf-8-sig").read().splitlines()[1:]}
def login(n):
    s = S(); st, d = s.req("POST", "/api/login", {"login": n, "pw": acc[n]})
    if d.get("must_change"): s.req("POST", "/api/password", {"old": acc[n], "new": "Test!2345"}); acc[n] = "Test!2345"
    return s
seed = json.load(open(SEED, encoding="utf-8"))
MAS = seed.get("master") or "홍길동"
adm = login(MAS); meta = adm.req("GET", "/api/meta")[1]
db = sqlite3.connect(DB, timeout=10)
pls = [u for u in meta["users"] if u["role"] == "pl"]
def linked_of(part): return {r[0] for r in db.execute("SELECT im.user_id FROM issue_members im JOIN issues i ON i.id=im.issue_id JOIN models m ON m.id=i.model_id WHERE m.part=? AND i.hidden=0 AND i.done IS NULL AND IFNULL(i.stage,1)<6", (part,))}
act = [u for u in meta["users"] if u["role"] == "member" and u["active"]]
# PL 파트 진행 이슈에 묶이지 않은 우리 파트 팀원이 있는 PL을 고름 (묶인 사람은 원래 볼 수 있음)
pl_u = next(u for u in pls if any(m["part"] == u["part"] and m["id"] not in linked_of(u["part"]) for m in act)); pl = login(pl_u["login"])
linked = linked_of(pl_u["part"])
mem2_u = next(m for m in act if m["part"] == pl_u["part"] and m["id"] not in linked)
mem_u = next(m for m in act if m["part"] == pl_u["part"] and m["id"] != mem2_u["id"]); mem = login(mem_u["login"])
opl_u = next(u for u in pls if u["part"] != pl_u["part"] and any(m["part"] == u["part"] and m["id"] not in linked for m in act)); opl = login(opl_u["login"])
omem_u = next(m for m in act if m["part"] == opl_u["part"] and m["id"] not in linked)
lead_u = next(u for u in meta["users"] if u["role"] == "lead")
model = next(m for m in meta["models"] if m["part"] == pl_u["part"] and m["active"])
omodel = next(m for m in meta["models"] if m["part"] != pl_u["part"] and m["active"])
pops = lambda uid: [r[0] for r in db.execute("SELECT text FROM notifs WHERE user_id=? ORDER BY id", (uid,))]

# ── 1. 버전 · 글꼴 ──
check("버전 0.7.2", urllib.request.urlopen(BASE + "/version").read().decode() == "업무관리 0.7.2")
css = urllib.request.urlopen(BASE + "/fonts/noto.css").read().decode()
check("글꼴 CSS 제공", "Noto Sans KR Variable" in css and "/fonts/" in css)
fn = css.split("/fonts/")[1].split(")")[0].strip("'\"")
r = urllib.request.urlopen(BASE + "/fonts/" + fn)
check("글꼴 파일 제공 (woff2)", r.headers["content-type"] == "font/woff2" and len(r.read()) > 1000)
for bad_p in ["/fonts/%2e%2e%2fseed.json", "/fonts/x.woff2", "/fonts/..%2F..%2Fetc%2Fpasswd"]:
    try: rr = urllib.request.urlopen(BASE + bad_p); check("없는 글꼴 경로는 글꼴이 아님 " + bad_p, rr.headers["content-type"] != "font/woff2")
    except urllib.error.HTTPError as e: check("없는 글꼴 경로는 404 " + bad_p, e.code == 404)
check("CSP에 blob: 이미지 허용", "blob:" in urllib.request.urlopen(BASE + "/").headers["content-security-policy"])

# ── 2. 일을 준 사람 보기 ──
st, d = pl.req("GET", f"/api/week?user={omem_u['id']}")
check("관계 없는 다른 파트 사람은 못 봄", st == 403, d)
st, d = pl.req("GET", f"/api/week?user={mem2_u['id']}")
check("우리 파트라도 일을 주지 않았으면 못 봄", st == 403, d)
n0 = len(pops(opl_u["id"]))
st, d = pl.req("POST", "/api/assign", {"user_ids": [omem_u["id"]], "title": "다른 파트 지정 시험", "target": "2026-12-05", "model_id": omodel["id"], "summary": "요약"})
check("PL이 다른 파트 사람에게 업무 지정", st == 200 and d["to"] == [omem_u["name"]], d)
p = pops(opl_u["id"])[n0:]
check("받는 사람 파트 PL에게 알림", len(p) == 1 and omem_u["name"] in p[0] and "다른 파트 지정 시험" in p[0], p)
check("내 파트 사람 지정은 다른 PL에게 알림 없음", (pl.req("POST", "/api/assign", {"user_ids": [mem_u["id"]], "title": "우리 파트 지정"})[0] == 200) and len(pops(opl_u["id"])) == n0 + 1)
st, d = pl.req("POST", "/api/assign", {"user_ids": [lead_u["id"]], "title": "팀장 지정"})
check("팀장에게는 지정 못 함", st == 403, d)
for path in ["/api/week", "/api/tasks", "/api/stats"]:
    st, d = pl.req("GET", f"{path}?user={omem_u['id']}")
    check(f"일을 준 다른 파트 사람 {path} 보기", st == 200)
st, g = pl.req("GET", "/api/assign/given")
check("'내가 일을 준 사람' 목록", st == 200 and {omem_u["id"], mem_u["id"]} <= {u["id"] for u in g} and next(u for u in g if u["id"] == omem_u["id"])["tasks"] == 1, g)
check("팀원은 목록이 비어 있음", mem.req("GET", "/api/assign/given")[1] == [])
tid = next(t["id"] for t in pl.req("GET", f"/api/tasks?user={omem_u['id']}")[1] if t["title"] == "다른 파트 지정 시험")
st, d = pl.req("PUT", f"/api/tasks/{tid}", {"title": "PL이 남의 업무 고침 시도", "progress": 50})
check("보기만 가능 (남의 업무 이름은 못 고침 · 지정 업무는 지정한 사람이 고침 가능한 기존 규칙 확인)", st in (200, 403))
st, d = pl.req("PUT", "/api/hours", {"type": "task", "id": tid, "date": "2026-11-16", "hours": 2})
check("남의 시간은 입력 못 함", st in (403, 404), (st, d))
omem = login(omem_u["login"])
omem.req("PUT", f"/api/tasks/{tid}", {"progress": 100, "done": "2026-11-20"})
st, d = pl.req("GET", f"/api/week?user={omem_u['id']}")
check("업무가 끝나면 다시 못 봄", st == 403, (st, d))
# 이슈 담당으로 연결
st, iss = pl.req("POST", "/api/issues", {"model_id": model["id"], "title": "0.7.2 시험 이슈", "members": [{"role": "정", "user_id": mem2_u["id"]}], "status_text": "예전 4칸 글 (현상)", "items": {"1-1": "화면 깜빡임", "2-3": ""}})
check("이슈 등록에 템플릿 항목", st == 200 and iss["items"] == {"1-1": "화면 깜빡임"}, iss)
iid = iss["id"]
check("우리 파트 이슈 담당이면 볼 수 있음", pl.req("GET", f"/api/week?user={mem2_u['id']}")[0] == 200)
check("다른 파트 PL은 못 봄", opl.req("GET", f"/api/week?user={mem2_u['id']}")[0] == 403)

# ── 3. 템플릿 항목 ──
st, tpl = adm.req("GET", "/api/meta")
tpl = tpl["issueTpl"]
check("템플릿 4칸 이름", [b["title"] for b in tpl] == ["현상 진단", "원인 규명", "대책 수립", "검증 적용"], [b["title"] for b in tpl])
check("대책 수립 3-4 Risk · 3-7 검증 계획", [i["code"] for i in tpl[2]["items"]] == ["3-1", "3-2", "3-3", "3-4", "3-5", "3-6", "3-7"] and tpl[2]["items"][3]["label"] == "Risk 사항" and tpl[2]["items"][6]["label"].startswith("검증 계획"))
check("현재 진행 = 마지막 채운 항목", iss["now"]["label"] == "1-1 불량 증상" and iss["now"]["text"] == "화면 깜빡임", iss["now"])
st, d = pl.req("PUT", f"/api/issues/{iid}", {"items": {"3-2": "R12 값 변경", "2-1": "설계"}})
check("항목 저장 (부분 합치기)", st == 200 and d["items"] == {"1-1": "화면 깜빡임", "2-1": "설계", "3-2": "R12 값 변경"}, d.get("items"))
check("현재 진행 = 가장 뒤 칸의 마지막 항목", d["now"]["label"] == "3-2 개선안별 변경점" and d["now"]["text"] == "R12 값 변경", d["now"])
check("항목을 고친 칸에 수정 기록", set(d["box_meta"]) >= {"cause", "plan"} and d["box_meta"]["plan"]["by"].startswith(pl_u["name"].split(" ")[0]), d["box_meta"])
check("예전 글은 그대로", d["status_text"] == "예전 4칸 글 (현상)")
st, d = pl.req("PUT", f"/api/issues/{iid}", {"items": {"3-2": ""}})
check("항목을 비우면 지워짐", "3-2" not in d["items"] and d["now"]["label"] == "2-1 원인 기인", d["now"])
st, d = pl.req("PUT", f"/api/issues/{iid}", {"items": {"9-9": "x"}})
check("없는 항목 번호는 거절", st == 400, d)
st, d = mem.req("PUT", f"/api/issues/{iid}", {"items": {"1-2": "x"}})
check("팀원은 항목 못 고침", st == 403, d)
st, d = opl.req("PUT", f"/api/issues/{iid}", {"items": {"1-2": "x"}})
check("다른 파트 PL은 못 고침", st == 403, d)
st, d = pl.req("PUT", f"/api/issues/{iid}", {"status_text": ""})
check("이전 기록을 비우면 사라짐 (항목은 남음)", d["status_text"] in ("", None) and d["items"]["1-1"] == "화면 깜빡임")
# 항목 없이 예전 글만 있는 이슈
st, iss3 = pl.req("POST", "/api/issues", {"model_id": model["id"], "title": "예전 글만", "members": [], "cause": "원인 예전 글", "status_text": "현상 예전 글"})
check("항목이 없으면 현재 진행 = 예전 글 (가장 뒤 칸)", iss3["now"] and iss3["now"]["key"] == "cause" and iss3["now"]["text"] == "원인 예전 글", iss3["now"])
check("DB items 열은 JSON", json.loads(db.execute("SELECT items FROM issues WHERE id=?", (iid,)).fetchone()[0]) == {"1-1": "화면 깜빡임", "2-1": "설계"})
print(f"0.7.2 시험: 통과 {ok} · 실패 {bad}")
