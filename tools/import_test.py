# 엑셀 가져오기 시험: 11/4 seed 로 시작 → 웹에 입력 → '나중 엑셀'(seed 수정본) 가져오기 → 규칙대로 반영됐는지
import sys, json, copy, urllib.request, http.cookiejar, sqlite3
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
adm = login("홍길동"); mem = login("정시우")
seed = json.load(open(SEED, encoding="utf-8"))
me_tasks = [t for t in seed["tasks"] if t["user"].startswith("정시우") and t["kind"] == "통상"]
T = me_tasks[0]
web = {t["title"]: t for t in mem.req("GET", "/api/tasks")[1]}
wid = web[T["title"]]["id"]
# 웹 입력: 기준일 이전(11/10) 과 이후(11/12) 에 시간 · 기록, 웹에서 새 업무
mem.req("PUT", "/api/hours", {"type": "task", "id": wid, "date": "2026-11-10", "hours": 7, "text": "웹에서 적은 11/10"})
mem.req("PUT", "/api/hours", {"type": "task", "id": wid, "date": "2026-11-12", "hours": 3, "text": "웹 11/12"})
st, nw = mem.req("POST", "/api/tasks", {"kind": "통상", "title": "웹에서 만든 업무", "target": "2026-11-30"})
mem.req("PUT", "/api/hours", {"type": "task", "id": nw["id"], "date": "2026-11-12", "hours": 2})
before_users = {u["login"]: u for u in adm.req("GET", "/api/meta")[1]["users"]}
# '나중 엑셀' 만들기: T 진행률 · 11/10 시간 4h · 11/12 시간 5h(기준일 뒤라 무시돼야) · 새 업무 · 새 이슈 · 이슈 내용 변경
s2 = copy.deepcopy(seed); s2["source"] = "시험_나중엑셀.xlsm"; s2["extracted"] = "2026-11-15T09:00:00"
for t in s2["tasks"]:
    if t["user"] == T["user"] and t["title"] == T["title"]:
        t["progress"] = 80; t["hours"]["2026-11-10"] = 4.0; t["hours"]["2026-11-12"] = 5.0; t["hours"]["2026-11-09"] = 1.5
s2["tasks"].append({**copy.deepcopy(T), "title": "엑셀에서 11/9 추가한 업무", "hours": {"2026-11-09": 6.0}, "progress": 10, "row": 299})
iss0 = s2["issues"][0]; iss0["status_text"] = "엑셀에서 고친 진행현황"
s2["issues"].append({**copy.deepcopy(iss0), "no": "26-031", "title": "엑셀에서 새로 만든 이슈", "logs": [{"user": iss0["members"][0]["name"], "hours": {"2026-11-09": 2.0}}]})
st, pv = adm.req("POST", "/api/admin/import", {"seed": s2, "from": "2026-10-12", "to": "2026-11-11", "dry": True})
check("미리보기", st == 200 and pv["dry"] and pv["tasksNew"] == 1 and pv["issuesNew"] == 1, pv)
check("미리보기는 아무것도 안 바꿈", not any(t["title"] == "엑셀에서 11/9 추가한 업무" for t in mem.req("GET", "/api/tasks")[1]))
check("팀원은 가져오기 못 함", mem.req("POST", "/api/admin/import", {"seed": s2, "from": "2026-10-12", "to": "2026-11-11"})[0] == 403)
st, r = adm.req("POST", "/api/admin/import", {"seed": s2, "from": "2026-10-12", "to": "2026-11-11"})
check("가져오기 실행", st == 200 and not r["dry"], r)
db = sqlite3.connect(DB)
h = dict(db.execute("SELECT date, hours FROM task_hours WHERE task_id=?", (wid,)).fetchall())
check("기준일까지 시간 = 엑셀 (11/10 웹 7h → 엑셀 4h)", h.get("2026-11-10") == 4.0, h)
check("기준일 전 엑셀에만 있던 시간 들어옴 (11/9 1.5h)", h.get("2026-11-09") == 1.5, h)
check("기준일 뒤 시간 = 웹 그대로 (11/12 3h, 엑셀 5h 무시)", h.get("2026-11-12") == 3.0, h)
notes = dict(db.execute("SELECT date, text FROM task_notes WHERE task_id=?", (wid,)).fetchall())
check("웹에 적은 '한 일' 글은 남음", notes.get("2026-11-10") == "웹에서 적은 11/10" and notes.get("2026-11-12") == "웹 11/12", notes)
tasks = {t["title"]: t for t in mem.req("GET", "/api/tasks")[1]}
check("업무 내용 엑셀로 (진행률 80)", tasks[T["title"]]["progress"] == 80, tasks[T["title"]]["progress"])
check("엑셀 새 업무 추가", "엑셀에서 11/9 추가한 업무" in tasks)
check("웹에서 만든 업무 · 시간 그대로", "웹에서 만든 업무" in tasks and tasks["웹에서 만든 업무"]["total"] == 2)
check("같은 업무가 두 번 생기지 않음", sum(1 for t in mem.req("GET", "/api/tasks")[1] if t["title"] == T["title"]) == 1)
iss = {i["no"]: i for i in adm.req("GET", "/api/issues?scope=all")[1]}
check("이슈 내용 엑셀로", iss[iss0["no"]]["status_text"] == "엑셀에서 고친 진행현황")
check("엑셀 새 이슈 추가", "26-031" in iss)
st, nx = adm.req("POST", "/api/issues", {"model_id": iss["26-031"]["model_id"], "title": "가져오기 뒤 새 이슈", "members": []})
check("다음 이슈 번호는 엑셀 번호 다음 (26-032)", st == 200 and nx["no"] == "26-032", nx)
after_users = {u["login"]: u for u in adm.req("GET", "/api/meta")[1]["users"]}
check("계정 · 비밀번호 그대로", set(before_users) == set(after_users) and login("정시우") is not None and S().req("POST", "/api/login", {"login": "정시우", "pw": acc["정시우"]})[0] == 200)
fixed = db.execute("SELECT user_id, COUNT(*) FROM tasks WHERE fixed=1 GROUP BY user_id").fetchall()
check("기본 행 5개씩 그대로 (0.8.0 외근 포함)", all(n == 5 for _, n in fixed), fixed)
st, r2 = adm.req("POST", "/api/admin/import", {"seed": s2, "from": "2026-10-12", "to": "2026-11-11"})
check("같은 파일 두 번 가져와도 늘지 않음", r2["tasksNew"] == 0 and r2["issuesNew"] == 0, r2)
import glob, os
check("가져오기 전 자동 백업", any("엑셀가져오기전" in f for f in os.listdir(os.path.join(os.path.dirname(DB), "백업"))))
print(f"엑셀 가져오기 시험: 통과 {ok} · 실패 {bad}")
