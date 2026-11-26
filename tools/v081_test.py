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
import datetime, io, zipfile, re, subprocess, os, tempfile
check("버전 0.8.1", urllib.request.urlopen(BASE + "/version").read().decode() >= "업무관리 0.8.1")
meta_m = mem.req("GET", "/api/meta")[1]
ms = [m for m in meta_m["models"] if m.get("active") and not m.get("hidden")]
a, b, c = ms[0], ms[1], ms[2]
mon = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
D, D2, D3 = mon.isoformat(), (mon + datetime.timedelta(days=1)).isoformat(), (mon + datetime.timedelta(days=2)).isoformat()
def hrs(tid, d): r = db.execute("SELECT hours FROM task_hours WHERE task_id=? AND date=?", (tid, d)).fetchone(); return r[0] if r else 0
def note(tid, d): r = db.execute("SELECT text FROM task_notes WHERE task_id=? AND date=?", (tid, d)).fetchone(); return r[0] if r else ""
def spl(tid, d): return sorted(db.execute("SELECT model_id, hours FROM task_splits WHERE task_id=? AND date=?", (tid, d)).fetchall())
rows = mem.req("GET", "/api/week?from=" + D)[1]["rows"]
o = next(r for r in rows if r.get("fixedKey") == "5")
O = o["id"]
# 1) 검사 먼저: 합계가 틀리면 시간도 안 바뀜 (0.8.0 은 시간만 바뀌었음)
mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D, "hours": 2})
st, _ = mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D, "hours": 5, "splits": [{"model_id": a["id"], "hours": 3}, {"model_id": b["id"], "hours": 1}]})
check("합계 틀림 → 400", st == 400)
check("합계 틀림 → 시간 그대로 2h", hrs(O, D) == 2, hrs(O, D))
st, _ = mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D, "hours": 5, "splits": [{"model_id": 0, "hours": 3}, {"model_id": 0, "hours": 2}]})
check("같은 모델 두 줄 → 400 · 시간 그대로", st == 400 and hrs(O, D) == 2)
# 2) 나누기 저장 → 칸 시간만 바꾸면 나누기는 풀리고 한 일은 [모델] 로 남음
st, r = mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D, "hours": 5, "splits": [{"model_id": a["id"], "hours": 3, "text": "출장 A"}, {"model_id": 0, "hours": 2, "text": "이동"}]})
check("외근 나누기 저장", st == 200 and spl(O, D) == sorted([(a["id"], 3), (0, 2)]), r)
check("한 일 = 이어 붙임", note(O, D) == f"[{a['name']} 3h] 출장 A / [공통 2h] 이동", note(O, D))
check("응답에 한 일", r.get("text") == note(O, D))
st, r = mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D, "hours": 6})
check("시간만 바꿈 → 나누기 풀림", st == 200 and spl(O, D) == [] and hrs(O, D) == 6)
check("한 일은 남고 시간 표시만 뗌", note(O, D) == f"[{a['name']}] 출장 A / [공통] 이동", note(O, D))
check("응답 한 일도 같음", r.get("text") == note(O, D))
# 3) 한 일 칸을 모두 비워 저장(text 없이) → 기존 한 일 유지
mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D2, "hours": 4, "text": "고객사 방문 회의"})
st, _ = mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D2, "hours": 4, "splits": [{"model_id": a["id"], "hours": 4}]})
check("빈 한 일로 나누기 → 기존 글 유지", st == 200 and note(O, D2) == "고객사 방문 회의", note(O, D2))
st, _ = mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D2, "hours": 4, "splits": [{"model_id": a["id"], "hours": 4}], "text": ""})
check("사람이 직접 비우면(text='') 지움", st == 200 and note(O, D2) == "")
# 4) 다중 모델 업무: 모델을 바꾸면 빠진 모델의 나누기만 풀림
st, t = mem.req("POST", "/api/tasks", {"kind": "통상", "title": "0.8.1 다중 모델", "models": [a["id"], b["id"], c["id"]]})
T = t["id"]
for d, sp in ((D, [(a, 1, "가"), (b, 1, "나")]), (D2, [(a, 2, "다"), (c, 1, "")])):
    st, _ = mem.req("PUT", "/api/hours", {"type": "task", "id": T, "date": d, "hours": sum(x[1] for x in sp), "splits": [{"model_id": m["id"], "hours": hh, "text": tx} for m, hh, tx in sp]})
    check("다중 모델 나누기 " + d, st == 200)
st, g = mem.req("GET", f"/api/tasks/{T}")
check("업무 GET 에 split_dates", [x["date"] for x in g.get("split_dates", [])] == [D, D2], g.get("split_dates"))
st, _ = mem.req("PUT", f"/api/tasks/{T}", {"title": "0.8.1 다중 모델", "models": [a["id"], b["id"], c["id"]]})
check("모델 그대로 → 나누기 그대로", len(spl(T, D)) == 2 and len(spl(T, D2)) == 2)
st, _ = mem.req("PUT", f"/api/tasks/{T}", {"title": "0.8.1 다중 모델", "models": [a["id"], b["id"]]})
check("c 뺌 → c 가 있던 날만 풀림", st == 200 and len(spl(T, D)) == 2 and spl(T, D2) == [])
check("풀린 날 한 일은 [모델] 표시로 남음", note(T, D2) == f"[{a['name']}] 다", note(T, D2))
check("풀린 날 시간 그대로", hrs(T, D2) == 3)
st, _ = mem.req("PUT", f"/api/tasks/{T}", {"title": "0.8.1 다중 모델", "models": [a["id"]]})
check("한 모델로 → 모두 풀림", spl(T, D) == [] and hrs(T, D) == 2 and note(T, D) == f"[{a['name']}] 가 / [{b['name']}] 나", note(T, D))
# 5) 로드: 풀린 뒤 계산 정상 (예외 없음)
check("업무 로드 계산", mem.req("GET", f"/api/stats?mode=week&base={D}")[0] == 200)
# 6) 0시간 → 나누기 지움, 한 일 유지
mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D3, "hours": 3, "splits": [{"model_id": a["id"], "hours": 3, "text": "점검"}]})
mem.req("PUT", "/api/hours", {"type": "task", "id": O, "date": D3, "hours": 0})
check("0시간 → 시간 · 나누기 지움, 한 일 남음", hrs(O, D3) == 0 and spl(O, D3) == [] and note(O, D3) == f"[{a['name']}] 점검", note(O, D3))
# 7) 폴더 묶음: cmd 에 한글 없음 · 안내 txt · C# 폴더 확인 + 셸 열기
adm.req("PUT", "/api/master/share", {"unc": "\\\\srv\\team\\이슈자료"})
req = urllib.request.Request(BASE + "/api/folder-tool", headers={"x-req": "1"})
z = zipfile.ZipFile(io.BytesIO(mem.op.open(req).read()))
for f in ("install.cmd", "uninstall.cmd"):
    check(f + " 에 한글 없음", not re.search("[가-힣]", z.read(f).decode("utf-8")))
check("안내 txt 4개", {"msg_fast.txt", "msg_ps.txt", "msg_fail.txt", "msg_removed.txt"} <= set(z.namelist()))
ins = z.read("install.cmd").decode()
check("설치 안내를 type 으로", 'type "%~dp0msg_%HOW%.txt"' in ins and 'set "HOW=fast"' in ins)
cs = z.read("open-folder.cs").decode("utf-8-sig")
check("C#: 폴더만 (Directory.Exists)", "Directory.Exists(full)" in cs)
check("C#: 셸로 열기 (UseShellExecute)", "UseShellExecute = true" in cs and "explorer.exe" not in cs)
ps = z.read("open-folder.ps1").decode("utf-8-sig")
check("ps1: 폴더만", "-PathType Container" in ps)
if os.path.exists("/usr/bin/mcs"):
    d = tempfile.mkdtemp(); open(d + "/a.cs", "w", encoding="utf-8").write(cs)
    p = subprocess.run(["mcs", "-langversion:5", "-r:System.Windows.Forms.dll", "-out:" + d + "/a.exe", d + "/a.cs"], capture_output=True, text=True)
    check("C# 5 컴파일", p.returncode == 0, p.stdout + p.stderr)
adm.req("PUT", "/api/master/share", {"unc": ""})
js = urllib.request.urlopen(BASE + "/app.js").read().decode()
for k in ("function splitModal", "SPLIT_CLOSE?.()", "NOTE_FIN", "bgEsc", "split_dates", "parseSplitNote"): check("화면 코드: " + k, k in js)
check("옛 splitInline 없음", "function splitInline" not in js)
print(f"0.8.1 시험: 통과 {ok} · 실패 {bad}")
