# 0.7.9 시험: 폴더 바로 열기 설치 묶음 · 일괄 배포 설정
# 사용: python3 -I v079_test.py <주소> <계정표> <seed.json> <DB>
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
import io, zipfile
check("버전 0.7.9 이상", urllib.request.urlopen(BASE + "/version").read().decode() >= "업무관리 0.7.9")
def raw(s, path):
    r = urllib.request.Request(BASE + path, headers={"x-req": "1"})
    try:
        with s.op.open(r) as x: return x.status, x.headers.get("content-type", ""), x.read()
    except urllib.error.HTTPError as e: return e.code, "", e.read()
# 경로가 없으면 받을 수 없음
adm.req("PUT", "/api/master/share", {"unc": ""})
st, _, _ = raw(mem, "/api/folder-tool"); check("경로 없으면 404", st == 404, st)
# 경로를 정하면 팀원도 받음
adm.req("PUT", "/api/master/share", {"unc": "\\\\srv\\team\\이슈자료"})
st, ct, data = raw(mem, "/api/folder-tool"); check("팀원 설치 묶음 받기", st == 200 and "zip" in ct, (st, ct))
z = zipfile.ZipFile(io.BytesIO(data)); names = sorted(z.namelist())
check("묶음 구성", names == ["README.txt", "install.cmd", "open-folder.ps1", "uninstall.cmd"], names)
ps = z.read("open-folder.ps1").decode("utf-8-sig")
check("스크립트에 지금 경로", "$Root = '\\\\srv\\team\\이슈자료'" in ps, ps[:300])
check("스크립트: 상위 경로 거부", "\\.\\." in ps and "Fail" in ps)
ins = z.read("install.cmd").decode("utf-8")
check("설치: 내 계정(HKCU)에만", "HKCU\\Software\\Classes\\workfolder" in ins and "HKLM" not in ins)
check("줄바꿈 CRLF", b"\r\n" in z.read("install.cmd"))
check("로그인 안 하면 못 받음", raw(S(), "/api/folder-tool")[0] in (401, 403))
# IT 일괄 배포 설정
st, v = adm.req("PUT", "/api/master/share", {"unc": "\\\\srv\\team\\이슈자료", "direct_all": True})
check("일괄 배포 켜기", adm.req("GET", "/api/meta")[1]["settings"].get("folder_direct_all") == "1")
check("팀원 meta 에도 보임", mem.req("GET", "/api/meta")[1]["settings"].get("folder_direct_all") == "1")
check("팀원은 바꿀 수 없음", mem.req("PUT", "/api/master/share", {"unc": "", "direct_all": False})[0] == 403)
adm.req("PUT", "/api/master/share", {"unc": "", "direct_all": False})
js = urllib.request.urlopen(BASE + "/app.js").read().decode()
for k in ("workfolder:", "function folderDirect", "설치 파일 받기", "모든 PC에 배포함"): check("화면 코드: " + k, k in js)
print(f"0.7.9 시험: 통과 {ok} · 실패 {bad}")
