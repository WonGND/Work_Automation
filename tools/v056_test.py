# 0.5.6 시험: 웹 기준 시작일(웹 우선) 가져오기 · 입사 · 퇴사
# 사용: python3 -I v056_test.py <주소> <계정표> <seed.json> <DB>   (seed 로 처음 설정한 빈 서버, 오늘 = 웹 기준 시작일 이후)
import sys, json, copy, urllib.request, http.cookiejar, sqlite3, datetime as dt
BASE, ACC, SEED, DB = sys.argv[1:5]
ok = bad = 0
def check(n, c, i=""):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("  ✗", n, i)
class S:
    def __init__(s): s.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def req(s, m, p, b=None):
        r = urllib.request.Request(BASE + p, data=None if b is None else json.dumps(b, ensure_ascii=False).encode(), method=m, headers={"content-type": "application/json", "x-req": "1"})
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
master = seed.get("master") or "홍길동"
adm = login(master)
people = [p["name"] for p in seed["people"] if p["role"] == "member"]
A_name = people[0]; A = A_name.split(" ")[0]; mem = login(A)
mine = [t for t in seed["tasks"] if t["user"] == A_name and t["kind"] == "통상"]
web = {t["title"]: t for t in mem.req("GET", "/api/tasks")[1]}
t1, t2, t3 = (web[mine[k]["title"]]["id"] for k in range(3))
W = "2026-11-16"
db = sqlite3.connect(DB)
def hours(tid, d):
    r = db.execute("SELECT hours FROM task_hours WHERE task_id=? AND date=?", (tid, d)).fetchone(); return r[0] if r else None

# ── 웹 우선 ──
mem.req("PUT", "/api/hours", {"type": "task", "id": t1, "date": W, "hours": 3})          # 웹에 이미 있음
mem.req("PUT", "/api/hours", {"type": "task", "id": t1, "date": "2026-11-13", "hours": 9})   # 기준일 전 → 엑셀로 바뀌어야 함
mem.req("PUT", f"/api/tasks/{t3}", {**{k: web[mine[2]["title"]][k] for k in ("kind", "model_id", "progress", "start", "target", "done", "importance", "category", "note")}, "title": "웹에서 바꾼 업무명"})
s2 = copy.deepcopy(seed)
for t in s2["tasks"]:
    if t["user"] == A_name and t["title"] == mine[0]["title"]: t["hours"][W] = 5; t["hours"]["2026-11-13"] = 4
    if t["user"] == A_name and t["title"] == mine[1]["title"]: t["hours"][W] = 2
    if t["user"] == A_name and t["title"] == mine[2]["title"]: t["title"] = "엑셀 업무명"
st, r = adm.req("POST", "/api/admin/import", {"seed": s2, "from": "2026-10-12", "to": W, "web_start": W})
check("가져오기 성공", st == 200, r)
check("웹 기준일: 웹에 있던 시간은 그대로 (엑셀 5 → 웹 3 유지)", hours(t1, W) == 3, hours(t1, W))
check("웹 기준일: 웹에 없으면 엑셀 값 (2)", hours(t2, W) == 2, hours(t2, W))
check("기준일 전은 엑셀 값 (웹 9 → 엑셀 4)", hours(t1, "2026-11-13") == 4, hours(t1, "2026-11-13"))
check("웹 우선으로 둔 칸 수 알려 줌", r.get("webKeptHours", 0) >= 1 and r.get("webStart") == W, r)
check("기준일 이후 웹에서 고친 업무명은 그대로", db.execute("SELECT title FROM tasks WHERE id=?", (t3,)).fetchone()[0] == "웹에서 바꾼 업무명" and any("웹에서 바꾼" in x for x in r.get("webKeptTasks", [])), r.get("webKeptTasks"))
mem.req("PUT", "/api/hours", {"type": "task", "id": t2, "date": W, "hours": 0})
st, r2 = adm.req("POST", "/api/admin/import", {"seed": s2, "from": "2026-10-12", "to": W, "web_start": W})
check("다시 가져와도 웹 3 그대로", hours(t1, W) == 3)
# 이슈: 웹에서 담당을 고친 이슈는 엑셀 담당으로 되돌리지 않음
iss = [i for i in seed["issues"] if i["members"]][0]
ii = next(x for x in adm.req("GET", "/api/issues")[1] if x["no"] == iss["no"])
det = adm.req("GET", f"/api/issues/{ii['id']}")[1]
uid = {u["login"]: u["id"] for u in adm.req("GET", "/api/meta")[1]["users"]}
newm = [{"role": "정", "user_id": uid[A]}]
st, d = adm.req("PUT", f"/api/issues/{ii['id']}", {**{k: det[k] for k in ("model_id", "title", "source", "occurred", "target", "stage", "status_text", "note", "cause", "plan", "importance", "done") if k in det}, "members": newm, "confirmPl": True})
check("웹에서 이슈 담당 고침", st == 200, d)
st, r3 = adm.req("POST", "/api/admin/import", {"seed": s2, "from": "2026-10-12", "to": W, "web_start": W})
det2 = adm.req("GET", f"/api/issues/{ii['id']}")[1]
check("기준일 이후 웹에서 고친 이슈 담당은 엑셀로 안 바뀜", [(m["role"], m["user_id"]) for m in det2["members"]] == [("정", uid[A])] and any(iss["no"] in x for x in r3.get("webKeptIssues", [])), (det2["members"], r3.get("webKeptIssues")))
wl = {x["no"]: x for x in adm.req("GET", "/api/issues")[1]}
other = [i for i in seed["issues"] if i["members"] and i["no"] != iss["no"] and i["no"] in wl][0]
oo = wl[other["no"]]
od = adm.req("GET", f"/api/issues/{oo['id']}")[1]
check("웹에서 안 고친 이슈 담당은 엑셀 이슈 정리와 같음", sorted((m["role"], m["name"]) for m in od["members"]) == sorted((m["role"], m["name"]) for m in other["members"]), (od["members"], other["members"]))

# ── 입사 · 퇴사 ──
B = people[1].split(" ")[0]; Bs = login(B); bid = uid[B]
today = dt.date.today().isoformat(); yday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
check("자기 계정 퇴사 처리 막힘", adm.req("PUT", f"/api/admin/users/{uid[master]}", {"left_on": yday})[0] == 400)
check("퇴사일 < 입사일 막힘", adm.req("PUT", f"/api/admin/users/{bid}", {"joined": "2026-11-10", "left_on": "2026-11-01"})[0] == 400)
st, d = adm.req("PUT", f"/api/admin/users/{bid}", {"left_on": today})
check("퇴사일 = 오늘 → 오늘은 아직 로그인 됨", st == 200 and Bs.req("GET", "/api/meta")[0] == 200)
st, d = adm.req("PUT", f"/api/admin/users/{bid}", {"left_on": yday})
check("퇴사일 지나면 세션 끊김", Bs.req("GET", "/api/meta")[0] == 401)
check("퇴사일 지나면 로그인 막힘", S().req("POST", "/api/login", {"login": B, "pw": acc[B]})[0] == 403)
mu = {u["login"]: u for u in adm.req("GET", "/api/meta")[1]["users"]}
check("목록에는 퇴사 표시 (기록은 남음)", mu[B]["gone"] is True and mu[B]["left_on"] == yday)
dsh = adm.req("GET", f"/api/dashboard?mode=week&base={today}")[1]
names = [p["name"] for p in dsh["people"]]
check("이번 주 업무로드에서 빠짐 (어제 퇴사 → 이번 주 월~어제 기간은 포함될 수 있음)", (people[1] in names) == (yday >= (dt.date.today() - dt.timedelta(days=dt.date.today().weekday())).isoformat()), names)
dsh2 = adm.req("GET", "/api/dashboard?mode=week&base=2026-11-03")[1]
check("퇴사 전 기간 업무로드에는 들어감", people[1] in [p["name"] for p in dsh2["people"]])
adm.req("PUT", f"/api/admin/users/{bid}", {"left_on": "2026-10-20"})
dsh3 = adm.req("GET", "/api/dashboard?mode=week&base=2026-11-03")[1]
check("퇴사 후 기간 업무로드에서 빠짐", people[1] not in [p["name"] for p in dsh3["people"]])
check("퇴사자는 이슈 담당 못 됨", adm.req("POST", "/api/issues", {"model_id": det["model_id"], "title": "퇴사자 담당 시험", "members": [{"role": "정", "user_id": bid}]})[0] == 400)
check("퇴사자에게 업무 지정 못 함", adm.req("POST", "/api/assign", {"user_ids": [bid], "title": "x"})[0] in (400, 403))
adm.req("PUT", f"/api/admin/users/{bid}", {"left_on": ""})
check("퇴사일 지우면 다시 로그인", S().req("POST", "/api/login", {"login": B, "pw": acc[B]})[0] == 200)
# 입사일: 그 전 날짜는 기준 시간에서 빠짐
base0 = adm.req("GET", f"/api/stats?user={bid}&mode=week&base=2026-11-03")[1]["base"]
adm.req("PUT", f"/api/admin/users/{bid}", {"joined": "2026-11-05"})
s1 = adm.req("GET", f"/api/stats?user={bid}&mode=week&base=2026-11-03")[1]
check("입사일 전 날짜는 기준 시간 · 미입력에서 빠짐 (40h → 16h)", base0 == 40 and s1["base"] == 16, (base0, s1["base"], s1["missing"]))
st, d = adm.req("POST", "/api/admin/users", {"login": "새사람", "name": "새사람 연구원", "title": "연구원", "part": "2part", "role": "member", "joined": "2026-12-01"})
check("계정 추가 때 입사일", st == 200 and db.execute("SELECT joined FROM users WHERE login='새사람'").fetchone()[0] == "2026-12-01")
print(f"0.5.6 시험: 통과 {ok} · 실패 {bad}")
