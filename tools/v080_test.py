# 0.8.0 시험: 다중 모델 · 모델별 나누기 · 외근 · 요청 복사 · 폴더 열기 C#
# 사용: python3 -I v080_test.py <주소> <계정표> <seed.json> <DB>
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
import json
import datetime, io, zipfile
check("버전 0.8.0 이상", urllib.request.urlopen(BASE + "/version").read().decode() >= "업무관리 0.8.0")
meta_m = mem.req("GET", "/api/meta")[1]
ms = [m for m in meta_m["models"] if m.get("active") and not m.get("hidden")]
gw = {g["name"]: g["pct"] for g in meta_m.get("grades", [])}
# 날짜: 이번 주 월요일 (시간 기록 시작일 이후)
D = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
def w_of(m):
    k = "양산" if m.get("phase") == "양산" else "선행검토" if m.get("phase") == "선행검토" else (m["part"] if m["part"] in gw else m.get("grade"))
    return gw.get(k, 0)
a, b, c = ms[0], ms[1], ms[2]
# 1) 다중 모델 업무 만들기
st, t = mem.req("POST", "/api/tasks", {"kind": "통상", "title": "다중 모델 시험 업무", "models": [a["id"], b["id"], c["id"], a["id"]]})
check("다중 모델 업무 등록", st == 200 and t.get("model_id") == a["id"], t)
check("models 에 3개 (중복 뺌)", json.loads(t.get("models") or "[]") == [a["id"], b["id"], c["id"]], t.get("models"))
st, t1 = mem.req("POST", "/api/tasks", {"kind": "통상", "title": "단일 모델 시험", "models": [b["id"]]})
check("모델 하나면 models 비움", st == 200 and t1.get("models") == "" and t1.get("model_id") == b["id"], t1)
check("없는 모델 거절", mem.req("POST", "/api/tasks", {"kind": "통상", "title": "x", "models": [999999]})[0] == 400)
def stats():
    return mem.req("GET", f"/api/stats?mode=week&base={D}")[1]
s0 = stats()
# 2) 시간만 넣으면 똑같이 나눔
check("시간 6h", mem.req("PUT", "/api/hours", {"type": "task", "id": t["id"], "date": D, "hours": 6})[0] == 200)
s1 = stats()
exp_even = 2 * (w_of(a) + w_of(b) + w_of(c))
check("로드: 똑같이 나눔", abs((s1["weighted"] - s0["weighted"]) - exp_even) < 1e-6, (s1["weighted"] - s0["weighted"], exp_even))
check("모델별 시간: 2h 씩", all(abs(s1["models"].get(m["name"], 0) - s0["models"].get(m["name"], 0) - 2) < 1e-6 for m in (a, b, c)))
# 3) 모델별로 나누기
bres = mem.req("PUT", "/api/hours", {"type": "task", "id": t["id"], "date": D, "hours": 6, "splits": [{"model_id": a["id"], "hours": 1}, {"model_id": b["id"], "hours": 3}]})
check("합계 다르면 거절", bres[0] == 400, bres)
check("이 업무의 모델이 아니면 거절", mem.req("PUT", "/api/hours", {"type": "task", "id": t["id"], "date": D, "hours": 6, "splits": [{"model_id": ms[3]["id"], "hours": 6}]})[0] == 400)
st, _ = mem.req("PUT", "/api/hours", {"type": "task", "id": t["id"], "date": D, "hours": 6, "splits": [{"model_id": a["id"], "hours": 1, "text": "A 일"}, {"model_id": b["id"], "hours": 3, "text": "B 일"}, {"model_id": c["id"], "hours": 2}]})
check("모델별 나누기 저장", st == 200)
s2 = stats()
exp = 1 * w_of(a) + 3 * w_of(b) + 2 * w_of(c)
check("로드: 나눈 시간 × 배율", abs((s2["weighted"] - s0["weighted"]) - exp) < 1e-6, (s2["weighted"] - s0["weighted"], exp))
check("입력 시간은 6h 그대로", abs(s2["input"] - s0["input"] - 6) < 1e-6)
wk = mem.req("GET", "/api/week?from=" + D)[1]
row = next(r for r in wk["rows"] if r["type"] == "task" and r["id"] == t["id"])
check("주간: split 표시", row.get("split") is True and row.get("models") == [a["name"], b["name"], c["name"]], row.get("models"))
check("주간: 나눈 시간", sorted(x["hours"] for x in row["splits"].get(D, [])) == [1, 2, 3])
check("한 일 = 모델별 이어 붙임", row["texts"].get(D) == f"[{b['name']} 3h] B 일 / [{a['name']} 1h] A 일" or row["texts"].get(D) == f"[{a['name']} 1h] A 일 / [{b['name']} 3h] B 일", row["texts"].get(D))
# 4) 시간이 바뀌면 나누기 지우고 똑같이로
mem.req("PUT", "/api/hours", {"type": "task", "id": t["id"], "date": D, "hours": 3})
row = next(r for r in mem.req("GET", "/api/week?from=" + D)[1]["rows"] if r["type"] == "task" and r["id"] == t["id"])
check("시간 바뀌면 나누기 지움", not row["splits"].get(D))
mem.req("PUT", "/api/hours", {"type": "task", "id": t["id"], "date": D, "hours": 0})
# 5) 외근 기본 행
rows = mem.req("GET", "/api/week?from=" + D)[1]["rows"]
fx = [r for r in rows if r["type"] == "task" and r.get("fixed")]
out = [r for r in fx if r.get("fixedKey") == "5"]
check("외근 기본 행 있음", len(out) == 1 and out[0]["title"] == "외근", [r["title"] for r in fx])
check("기본 행 순서: 회의 다음 외근", [r.get("fixedKey") for r in fx][:2] == ["1", "5"], [r.get("fixedKey") for r in fx])
o = out[0]
check("외근은 split", o.get("split") is True)
s3 = stats()
st, _ = mem.req("PUT", "/api/hours", {"type": "task", "id": o["id"], "date": D, "hours": 8, "splits": [{"model_id": b["id"], "hours": 5, "text": "출장"}, {"model_id": 0, "hours": 3}]})
check("외근 모델별 (공통 포함)", st == 200)
s4 = stats()
check("외근 로드: 5h × 배율 + 3h × 공통", abs((s4["weighted"] - s3["weighted"]) - (5 * w_of(b) + 3 * float(meta_m["settings"].get("other_pct", 0) or 0))) < 1e-6)
check("외근은 아무 모델이나", mem.req("PUT", "/api/hours", {"type": "task", "id": o["id"], "date": D, "hours": 8, "splits": [{"model_id": ms[3]["id"], "hours": 8}]})[0] == 200)
mem.req("PUT", "/api/hours", {"type": "task", "id": o["id"], "date": D, "hours": 0})
check("시간 0 이면 나누기도 지움", db.execute("SELECT COUNT(*) FROM task_splits WHERE task_id=?", (o["id"],)).fetchone()[0] == 0)
# 6) 업무 지정도 다중 모델
st, r = pl.req("POST", "/api/assign", {"user_ids": [mem_u["id"]], "title": "지정 다중 모델", "models": [a["id"], b["id"]]})
tk = db.execute("SELECT models FROM tasks WHERE title='지정 다중 모델'").fetchone()
check("업무 지정 다중 모델", st == 200 and tk and json.loads(tk[0]) == [a["id"], b["id"]], (st, tk))
# 7) 요청 알림에 전체 내용 (복사용)
long = "요청 내용 " * 60
tg = mem.req("GET", "/api/meta")[1].get("reqTargets") or []
if tg:
    mem.req("POST", "/api/requests", {"to_id": tg[0]["id"], "text": long})
    d = db.execute("SELECT data FROM notifs WHERE kind='요청' ORDER BY id DESC LIMIT 1").fetchone()
    check("요청 알림에 전체 내용", d and json.loads(d[0]).get("내용") == long.strip()[:2000] or (d and len(json.loads(d[0]).get("내용", "")) > 400), None)
# 8) 폴더 바로 열기 묶음에 C# 소스
adm.req("PUT", "/api/master/share", {"unc": "\\\\srv\\team\\이슈자료"})
req = urllib.request.Request(BASE + "/api/folder-tool", headers={"x-req": "1"})
z = zipfile.ZipFile(io.BytesIO(mem.op.open(req).read()))
cs = z.read("open-folder.cs").decode("utf-8-sig")
check("묶음: C# 소스 + 예비 ps1", {"install.cmd", "uninstall.cmd", "open-folder.cs", "open-folder.ps1", "README.txt"} <= set(z.namelist()))
check("C# 소스에 경로", '@"\\\\srv\\team\\이슈자료"' in cs)
ins = z.read("install.cmd").decode()
check("설치: csc 로 빌드 → exe 등록", "csc.exe" in ins and "open-folder.exe" in ins and "HKCU" in ins)
adm.req("PUT", "/api/master/share", {"unc": ""})
js = urllib.request.urlopen(BASE + "/app.js").read().decode()
for k in ("function splitModal", "function modelMulti", "wl-sum", "rsz", "copyBtn"): check("화면 코드: " + k, k in js)
print(f"0.8.0 시험: 통과 {ok} · 실패 {bad}")
