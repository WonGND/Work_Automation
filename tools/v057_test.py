# 0.5.7 시험: 미입력 알림 · 공통 정보 rev · 엑셀 가져오기 마스터 전용
# 사용: python3 -I v057_test.py <주소> <계정표> <seed.json> <DB>   (seed 로 처음 설정한 빈 서버)
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
master = seed.get("master") or "홍길동"
adm = login(master)
meta = adm.req("GET", "/api/meta")[1]
users = [u for u in meta["users"] if u["role"] != "lead" and u["active"]]
lead = next((u for u in meta["users"] if u["role"] == "lead"), None)
db = sqlite3.connect(DB, timeout=10)
def setting(k, v): db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v)); db.commit()
def notifs(uid, since): return [r[0] for r in db.execute("SELECT text FROM notifs WHERE user_id=? AND kind='미입력' AND id>?", (uid, since))]
def maxid(): return db.execute("SELECT IFNULL(MAX(id),0) FROM notifs").fetchone()[0]
def missing(uid, f, t): return adm.req("GET", f"/api/stats?user={uid}&mode=custom&from={f}&to={t}")[1]["missing"]

# ── 미입력 알림 ──
setting("web_start", "2026-10-12"); setting("today_fix", "2026-11-04")       # 수요일 → 전 근무일 11/3(화)
m0 = maxid(); st, r = adm.req("POST", "/api/admin/remind", {})
exp = {u["id"] for u in users if missing(u["id"], "2026-11-03", "2026-11-03") > 0}
got = {u["id"] for u in users if notifs(u["id"], m0)}
check("전 근무일 미입력인 사람에게만 알림", st == 200 and got == exp and r["daily"] == len(exp) and r["day"] == "2026-11-03", (r, len(exp), len(got)))
check("알림 글에 날짜 · 요일", all("11/3(화)" in notifs(u, m0)[0] for u in got) if got else True)
check("주 중간에는 주간 요약 없음", r["weekly"] == 0 and (not lead or not notifs(lead["id"], m0)))
setting("today_fix", "2026-11-09")                                           # 월요일 → 전 근무일 11/6(금) + 지난주 요약
m1 = maxid(); st, r = adm.req("POST", "/api/admin/remind", {})
wk = {u["id"]: missing(u["id"], "2026-11-02", "2026-11-08") for u in users}
tx = notifs(lead["id"], m1) if lead else notifs(next(u["id"] for u in users if u["role"] == "master"), m1)
summ = [t for t in tx if t.startswith("지난주")]
check("월요일: 팀장에게 지난주 미입력 요약 1건", len(summ) == 1 and r["week"] == "2026-11-02 ~ 2026-11-08", (tx, r))
check("요약에 미입력인 사람 · 일수가 모두 들어감", all(f"{u['name'].split(' ')[0]} {wk[u['id']]}일" in summ[0] for u in users if wk[u["id"]] > 0) and not any(f"{u['name'].split(' ')[0]} " in summ[0] for u in users if wk[u["id"]] == 0), summ)
pl = next(u for u in users if u["role"] == "pl")
mine = [u for u in users if u["part"] == pl["part"] and u["id"] != pl["id"] and wk[u["id"]] > 0]
ps = [t for t in notifs(pl["id"], m1) if t.startswith("지난주")]
check("PL은 자기 파트 것만", (len(ps) == 1 and all(u["name"].split(" ")[0] in ps[0] for u in mine) and pl["part"] in ps[0]) if mine else not ps, ps)
setting("web_start", "2026-11-09"); m2 = maxid(); st, r = adm.req("POST", "/api/admin/remind", {})
check("웹 기준 시작일 이전 날짜는 알리지 않음", r["daily"] == 0 and r["weekly"] == 0 and maxid() == m2, r)
setting("today_fix", "2026-11-08"); st, r = adm.req("POST", "/api/admin/remind", {})
check("주말에는 안 보냄", r["daily"] == 0 and r["weekly"] == 0)
mem = login(next(u["login"] for u in users if u["role"] == "member"))
check("알림 보내기는 마스터만", mem.req("POST", "/api/admin/remind", {})[0] == 403)
setting("today_fix", ""); setting("web_start", "2026-11-16")

# ── 공통 정보 rev ──
r0 = mem.req("GET", "/api/notifs")[1]["rev"]
tid = mem.req("GET", "/api/tasks")[1][0]["id"]
mem.req("PUT", "/api/hours", {"type": "task", "id": tid, "date": "2026-11-03", "hours": 1})
check("시간 입력으로는 rev 안 바뀜", mem.req("GET", "/api/notifs")[1]["rev"] == r0)
adm.req("PUT", f"/api/admin/users/{pl['id']}", {"title": "수석"})
r1 = mem.req("GET", "/api/notifs")[1]["rev"]
check("계정을 고치면 rev 바뀜", r1 > r0, (r0, r1))
mm = meta["models"][0]
adm.req("PUT", "/api/master/models", {**mm, "customer": (mm.get("customer") or "") + " "})
check("모델을 고치면 rev 바뀜", mem.req("GET", "/api/notifs")[1]["rev"] > r1)

# ── 엑셀 가져오기: 마스터만 ──
if lead:
    ld = login(lead["login"])
    check("팀장은 엑셀 가져오기 못 함", ld.req("POST", "/api/admin/import", {"seed": seed, "from": "2026-10-12", "to": "2026-11-04", "dry": True})[0] == 403)
check("마스터는 미리보기 됨", adm.req("POST", "/api/admin/import", {"seed": seed, "from": "2026-10-12", "to": "2026-11-04", "dry": True})[0] == 200)
print(f"0.5.7 시험: 통과 {ok} · 실패 {bad}")
