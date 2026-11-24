# 0.7.5 시험: 그날 · 주간 한 일 보기, 한 일 한 줄, Esc
# 사용: python3 -I v075_test.py <주소> <계정표> <seed.json> <DB>
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
opl_u = next(u for u in pls if u["part"] != pl_u["part"] and any(m["part"] == u["part"] and m["id"] not in linked for m in act)); opl = login(opl_u["login"])
omem_u = next(m for m in act if m["part"] == opl_u["part"] and m["id"] not in linked)
lead_u = next(u for u in meta["users"] if u["role"] == "lead")
model = next(m for m in meta["models"] if m["part"] == pl_u["part"] and m["active"])
omodel = next(m for m in meta["models"] if m["part"] != pl_u["part"] and m["active"])
import datetime
check("버전 0.7.5 이상", urllib.request.urlopen(BASE + "/version").read().decode() >= "업무관리 0.7.5")
# 한 일 한 줄: 시간 + 한 일을 한 번에 저장
wk = mem.req("GET", "/api/week?from=" + datetime.date.today().isoformat())[1]
task = next((r for r in wk["rows"] if r["type"] == "task" and r.get("kind") not in ("휴가", "조퇴")), None)
check("팀원 업무 줄 있음", task is not None)
D = wk["from"]
st, _ = mem.req("PUT", "/api/hours", {"type": "task", "id": task["id"], "date": D, "hours": 1.5, "text": "0.7.5 한 줄 시험"})
check("시간 + 한 일 저장", st == 200, st)
r2 = next(r for r in mem.req("GET", "/api/week?from=" + D)[1]["rows"] if r["type"] == task["type"] and r["id"] == task["id"])
check("주간 데이터에 시간", r2["hours"].get(D) == 1.5, r2["hours"])
check("주간 데이터에 한 일", r2.get("texts", {}).get(D) == "0.7.5 한 줄 시험", r2.get("texts"))
# 월간 보기 (월간 한 일 보기 팝업이 쓰는 데이터)
mo = mem.req("GET", "/api/week?mode=month&from=" + D)[1]
r3 = next(r for r in mo["rows"] if r["type"] == task["type"] and r["id"] == task["id"])
check("월간 데이터에 한 일", r3.get("texts", {}).get(D) == "0.7.5 한 줄 시험", r3.get("texts"))
# 팀장 · PL 이 사람별로 볼 수 있음
lead = login(lead_u["login"])
st, lw = lead.req("GET", f"/api/week?user={mem_u['id']}&from={D}")
check("팀장이 팀원 한 일 봄", st == 200 and any(r.get("texts", {}).get(D) == "0.7.5 한 줄 시험" for r in lw["rows"]), st)
st, pw = pl.req("GET", f"/api/week?user={mem_u['id']}&from={D}")
check("같은 파트 PL이 한 일 봄", st == 200 and any(r.get("texts", {}).get(D) == "0.7.5 한 줄 시험" for r in pw["rows"]), st)
# 한 일 한 줄 끄기 설정 (본인 저장)
st, _ = mem.req("PUT", "/api/prefs", {"noteInline": "false"})
check("한 줄 설정 저장", st == 200)
check("설정이 내 정보에 남음", mem.req("GET", "/api/meta")[1].get("prefs", {}).get("noteInline") == "false")
mem.req("PUT", "/api/prefs", {"noteInline": None})
check("설정 지우면 기본(켜짐)", "noteInline" not in mem.req("GET", "/api/meta")[1].get("prefs", {}))
# 한 일만 지움 → 시간은 그대로
mem.req("PUT", "/api/hours", {"type": "task", "id": task["id"], "date": D, "hours": 1.5, "text": ""})
r4 = next(r for r in mem.req("GET", "/api/week?from=" + D)[1]["rows"] if r["type"] == task["type"] and r["id"] == task["id"])
check("한 일 지워도 시간 남음", r4["hours"].get(D) == 1.5 and not r4.get("texts", {}).get(D), r4)
mem.req("PUT", "/api/hours", {"type": "task", "id": task["id"], "date": D, "hours": 0})
# 정적 화면 파일에 0.7.5 기능
js = urllib.request.urlopen(BASE + "/app.js").read().decode()
for k in ("function dayLog", "function periodLog", "function noteInline", "저장하지 않고 닫을까요", "팀장 · PL이 사람별 화면에서"):
    check("화면 코드: " + k, k in js)
print(f"0.7.5 시험: 통과 {ok} · 실패 {bad}")
