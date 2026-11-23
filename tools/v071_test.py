# 0.7.1 시험: 완료 최신순 · PL 관리 이슈 행(시간 입력) · PL 이슈 등록
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
pl_u = pls[0]; pl = login(pl_u["login"])
opl_u = next(u for u in pls if u["part"] != pl_u["part"]); opl = login(opl_u["login"])
mem_u = next(u for u in meta["users"] if u["role"] == "member" and u["part"] == pl_u["part"]); mem = login(mem_u["login"])
model = next(m for m in meta["models"] if m["part"] == pl_u["part"] and m["active"])
omodel = next(m for m in meta["models"] if m["part"] != pl_u["part"] and m["active"])
import datetime as _dt
_t = _dt.date.today(); W = str(_t - _dt.timedelta(days=_t.weekday()))   # 이번 주 월요일 (날짜에 따라 결과가 바뀌지 않게)
week = lambda s, extra="": s.req("GET", f"/api/week?from={W}{extra}")[1]

# ── PL 관리 행 ──
st, iss = adm.req("POST", "/api/issues", {"model_id": model["id"], "title": "PL 관리 시험 이슈", "target": "2026-12-10", "occurred": "2026-11-10", "members": [{"role": "정", "user_id": mem_u["id"]}]})
check("마스터가 PL 파트 이슈 등록 (PL은 담당 아님)", st == 200, iss); iid = iss["id"]
st, oiss = adm.req("POST", "/api/issues", {"model_id": omodel["id"], "title": "다른 파트 이슈", "members": [{"role": "정", "user_id": mem_u["id"]}]})
w = week(pl)
r = next((x for x in w["rows"] if x["type"] == "issue" and x["id"] == iid), None)
check("PL 내 업무에 담당 아닌 우리 파트 이슈가 'PL 관리'로 보임", r and r["role"] == "PL 관리" and r.get("plManage") is True and not r["done"], r)
check("다른 파트 이슈는 안 보임", not any(x["type"] == "issue" and x["id"] == oiss["id"] for x in w["rows"]))
open_part = {i[0] for i in db.execute("SELECT i.id FROM issues i JOIN models m ON m.id=i.model_id WHERE m.part=? AND i.hidden=0 AND i.done IS NULL AND i.stage<6 AND (i.occurred IS NULL OR i.occurred<=?)", (pl_u["part"], "2026-11-22"))}
shown = {x["id"] for x in w["rows"] if x["type"] == "issue"}
check("우리 파트 진행 중 이슈가 모두 보임", open_part <= shown, (len(open_part), len(shown & open_part)))
check("같은 이슈가 두 번 나오지 않음", len([x for x in w["rows"] if x["type"] == "issue"]) == len(shown))
st, d = pl.req("PUT", "/api/hours", {"type": "issue", "id": iid, "date": W, "hours": 1.5, "text": "원인 검토 회의"})
check("PL이 담당 아닌 우리 파트 이슈에 시간 입력", st == 200, d)
check("기록이 PL 이름으로 저장", db.execute("SELECT hours,text FROM issue_logs WHERE issue_id=? AND user_id=? AND date=?", (iid, pl_u["id"], W)).fetchone() == (1.5, "원인 검토 회의"))
check("PL 내 업무 표에 그 시간이 보임", next(x for x in week(pl)["rows"] if x["type"] == "issue" and x["id"] == iid)["hours"].get(W) == 1.5)
st, d = opl.req("PUT", "/api/hours", {"type": "issue", "id": iid, "date": W, "hours": 1})
check("다른 파트 PL은 시간 입력 못 함", st == 403, d)
st, d = login(next(u for u in meta["users"] if u["role"] == "member" and u["part"] == pl_u["part"] and u["id"] != mem_u["id"])["login"]).req("PUT", "/api/hours", {"type": "issue", "id": iid, "date": W, "hours": 1})
check("담당 아닌 팀원은 여전히 시간 입력 못 함", st == 403, d)
di = adm.req("GET", f"/api/issues/{iid}")[1]
check("이슈 투입 시간에 PL 시간이 들어감", any(l["user_id"] == pl_u["id"] and l["hours"] == 1.5 for l in di["logs"]), di.get("logs"))
dash = adm.req("GET", f"/api/dashboard?mode=custom&from={W}&to={W}")[1]
pr = next(p for p in dash["people"] if p["user_id"] == pl_u["id"])
check("PL 업무로드 집계에 들어감", pr["input"] >= 1.5, pr["input"])
st, d = pl.req("PUT", f"/api/issues/{iid}", {"cause": "PL이 내 업무에서 열어 씀"})
check("PL이 그 이슈 4칸 수정 가능", st == 200 and d["cause"] == "PL이 내 업무에서 열어 씀")
check("팀원 내 업무에는 PL 관리 행이 없음", not any(x.get("plManage") for x in week(mem)["rows"]))
# 담당이 되면 담당 행으로, 빠지면 다시 PL 관리 행
pl.req("PUT", f"/api/issues/{iid}", {"members": [{"role": "정", "user_id": mem_u["id"]}, {"role": "부1", "user_id": pl_u["id"]}], "confirm_pl": True})
r = next(x for x in week(pl)["rows"] if x["type"] == "issue" and x["id"] == iid)
check("PL이 담당이 되면 담당 행 (부1)", r["role"] == "부1" and not r.get("plManage") and r["hours"].get(W) == 1.5, r)
pl.req("PUT", f"/api/issues/{iid}", {"members": [{"role": "정", "user_id": mem_u["id"]}]})
r = next(x for x in week(pl)["rows"] if x["type"] == "issue" and x["id"] == iid)
check("담당에서 빠지면 '담당 해제'가 아니라 'PL 관리'", r["role"] == "PL 관리" and r["hours"].get(W) == 1.5, r)
# 완료 이슈: 기록 없으면 안 보임, 기록 있으면 완료로
st, iss2 = pl.req("POST", "/api/issues", {"model_id": model["id"], "title": "완료 시험 이슈", "members": []})
pl.req("PUT", f"/api/issues/{iss2['id']}", {"stage": 6, "done": "2026-11-12"})
check("기록 없는 완료 이슈는 안 보임", not any(x["type"] == "issue" and x["id"] == iss2["id"] for x in week(pl)["rows"]))
pl.req("PUT", f"/api/issues/{iid}", {"stage": 6, "done": "2026-11-18"})
r = next((x for x in week(pl)["rows"] if x["type"] == "issue" and x["id"] == iid), None)
check("기록 있는 완료 이슈는 완료로 보임 (완료일 포함)", r and r["done"] and r["doneAt"] == "2026-11-18", r)
st, mi = pl.req("GET", "/api/issues?scope=mine")
check("PL 관리 이슈는 '내 이슈'(담당)에는 안 나옴", not any(i["id"] == iid for i in mi))

# ── PL 이슈 등록 (내 업무 버튼 = 기존 등록 API) ──
st, d = pl.req("POST", "/api/issues", {"model_id": model["id"], "title": "PL 내 업무에서 등록", "members": []})
check("PL 이슈 등록 (담당 없이)", st == 200, d)
check("등록한 이슈가 PL 내 업무에 PL 관리로", any(x["type"] == "issue" and x["id"] == d["id"] and x["role"] == "PL 관리" for x in week(pl)["rows"]))
st, d = pl.req("POST", "/api/issues", {"model_id": omodel["id"], "title": "다른 파트 모델"})
check("PL은 다른 파트 모델로 등록 못 함", st == 403, d)
st, d = mem.req("POST", "/api/issues", {"model_id": model["id"], "title": "팀원 등록"})
check("팀원은 이슈 등록 못 함", st == 403, d)

# ── 완료일 ──
for k, dt in enumerate(["2026-11-03", "2026-11-17", "2026-11-10"]):
    st, t = mem.req("POST", "/api/tasks", {"kind": "통상", "title": f"완료 정렬 {k}", "start": "2026-11-01"})
    mem.req("PUT", "/api/hours", {"type": "task", "id": t["id"], "date": W, "hours": 0.5})
    mem.req("PUT", f"/api/tasks/{t['id']}", {"done": dt, "progress": 100})
rows = [x for x in week(mem)["rows"] if x["type"] == "task" and x["title"].startswith("완료 정렬")]
check("주간 표 완료 업무에 완료일", sorted(x["doneAt"] for x in rows) == ["2026-11-03", "2026-11-10", "2026-11-17"], [x.get("doneAt") for x in rows])
tl = [t for t in mem.req("GET", "/api/tasks")[1] if t["title"].startswith("완료 정렬")]
check("업무 목록에 완료일", all(t["done"] for t in tl))
check("버전 0.7.1 이상", urllib.request.urlopen(BASE + "/version").read().decode() >= "업무관리 0.7.1")
print(f"0.7.1 시험: 통과 {ok} · 실패 {bad}")
sys.exit(1 if bad else 0)
