# 0.7.7 시험 (0.7.6 이슈 폴더를 비동기로): 이슈 폴더 (만들기 · 예전 폴더 옮기기 · 다시 찾기 · 권한)
# 사용: python3 -I v076_test.py <주소> <계정표> <seed.json> <DB> <share 폴더>   (서버는 WL_SHARE_DIR=<share> WL_SHARE_LOCAL=1, 켜기 전 share 에 맨 위 번호 폴더 하나)
import sys, json, urllib.request, http.cookiejar, sqlite3
BASE, ACC, SEED, DB, SHARE = sys.argv[1:6]
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
import os; PRE = os.environ.get("PRE", "")
import os, time, shutil
from os.path import join, isdir, exists
check("버전 0.7.7 이상", urllib.request.urlopen(BASE + "/version").read().decode() >= "업무관리 0.7.7")
# 권한: 관리 > 이슈 폴더는 팀장 · 마스터만
check("팀원은 이슈 폴더 관리 못 봄", mem.req("GET", "/api/master/share")[0] == 403)
check("PL은 이슈 폴더 관리 못 봄", pl.req("GET", "/api/master/share")[0] == 403)
st, v = adm.req("GET", "/api/master/share"); check("마스터: 연결 상태", st == 200 and v.get("ok"), v)
# 경로 저장 (형식 확인)
check("잘못된 경로 거절", adm.req("PUT", "/api/master/share", {"unc": "C:/abc"})[0] == 400)
st, v = adm.req("PUT", "/api/master/share", {"unc": "//srv/team/이슈자료/"}); check("경로 저장 (/ → \\ · 끝 \\ 뺌)", v.get("unc") == "\\\\srv\\team\\이슈자료", v.get("unc"))
check("meta 에 경로", adm.req("GET", "/api/meta")[1].get("shareUnc") == "\\\\srv\\team\\이슈자료")
# 시작할 때 맞추기 → 숨기지 않은 이슈마다 모델 폴더 안에 '번호 이슈명'
time.sleep(1)
iss = [r for r in db.execute("SELECT i.no, m.name, i.title, i.hidden, i.folder FROM issues i LEFT JOIN models m ON m.id=i.model_id")]
vis = [r for r in iss if not r[3]]
check("보이는 이슈 모두 폴더 있음", all(r[4] and isdir(join(SHARE, r[4])) for r in vis), [r[0] for r in vis if not r[4]][:5])
check("숨긴 이슈는 폴더 안 만듦", all(not r[4] for r in iss if r[3]))
check("폴더 이름 = 모델/번호 이슈명", all(r[4].split("/")[1].startswith(r[0] + " ") for r in vis if r[4]))
# 예전 폴더 옮기기 (시험 전에 맨 위에 '번호'만으로 만들어 둔 것)
moved = [r for r in vis if r[0] == PRE]
check("맨 위 번호 폴더 → 모델 폴더로 옮김", moved and "/" in moved[0][4] and not exists(join(SHARE, PRE)), moved)
check("옮긴 폴더 안 파일 그대로", moved and exists(join(SHARE, moved[0][4], "자료.txt")))
# 새 이슈 등록 → 바로 폴더 (이름에 / : 같은 글자는 _)
mdl = next(m for m in meta["models"] if m["part"] == pl_u["part"] and not m.get("hidden"))
st, r = pl.req("POST", "/api/issues", {"model_id": mdl["id"], "title": "C/G 시험: 폴더 이름?"})
check("PL 이슈 등록", st == 200, r)
want = f"{mdl['name']}/{r.get('no')} C_G 시험_ 폴더 이름_"
for _ in range(30):   # 0.7.7: 등록은 폴더를 기다리지 않음 → 곧 생김
    if isdir(join(SHARE, want)) and db.execute("SELECT folder FROM issues WHERE id=?", (r["id"],)).fetchone()[0] == want: break
    time.sleep(0.2)
check("등록하면 곧 폴더", isdir(join(SHARE, want)) and db.execute("SELECT folder FROM issues WHERE id=?", (r["id"],)).fetchone()[0] == want, want)
check("이슈 목록에도 folder", any(i.get("folder") == want for i in pl.req("GET", "/api/issues?scope=part")[1]))
# 이슈명을 바꿔도 폴더는 그대로
pl.req("PUT", f"/api/issues/{r['id']}", {"title": "이름 바꿈"})
adm.req("POST", "/api/master/share/sync")
check("이슈명 바꿔도 폴더 그대로", db.execute("SELECT folder FROM issues WHERE id=?", (r["id"],)).fetchone()[0] == want)
# 사람이 폴더를 다른 이름으로 옮기면 다시 찾아 연결 (번호로)
os.rename(join(SHARE, want), join(SHARE, mdl["name"], f"{r['no']} 손으로 바꾼 이름"))
st, s2 = adm.req("POST", "/api/master/share/sync")
check("손으로 바꾼 폴더 다시 연결", any(x["no"] == r["no"] and x["result"] == "연결" for x in s2["results"]), s2.get("results"))
check("새로 만들지 않음", not isdir(join(SHARE, want)))
# 연결 시험
check("연결 시험", adm.req("POST", "/api/master/share/test")[1].get("ok") and isdir(join(SHARE, "_연결시험")))
# 변경 기록
check("변경 기록에 남음", db.execute("SELECT COUNT(*) FROM audit WHERE action='이슈 폴더'").fetchone()[0] >= len(vis))
print(f"0.7.7 시험: 통과 {ok} · 실패 {bad}")
