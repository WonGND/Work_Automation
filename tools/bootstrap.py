# 시험용: 처음 설정(설정 코드는 서버 로그에서) → 마스터가 모든 계정 '처음 비밀번호 만들기' → 시험용 계정표(시험 폴더에만) 작성
#   + 0.4.0 처음 설정 · 계정 흐름 점검
import sys, json, re, urllib.request, http.cookiejar
BASE, LOG, OUT = sys.argv[1:4]
import ssl; ssl._create_default_https_context = ssl._create_unverified_context
import os as _o
ADMIN, ADMIN_PW = _o.environ.get("ADMIN", "홍길동"), "Admin!2345"
ok = bad = 0
def check(n, c, i=""):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("  ✗", n, i)
class S:
    def __init__(s): s.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def req(s, m, p, b=None):
        r = urllib.request.Request(BASE + p, data=None if b is None else json.dumps(b).encode(), method=m, headers={"content-type": "application/json", "x-req": "1"})
        try:
            with s.op.open(r) as res: return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read())
            except Exception: return e.code, {}
import os
log = open(LOG, encoding="utf-8").read()
code = re.search(r"처음 설정 코드: (\d+)", log).group(1)
check("계정표 파일을 만들지 않음", not any("계정표" in f for f in os.listdir(os.path.join(os.path.dirname(LOG), "데이터"))))
a = S()
check("처음 설정 필요", a.req("GET", "/api/setup")[1].get("needed") is True)
st, d = a.req("POST", "/api/login", {"login": "정시우", "pw": "123456"})
check("비밀번호 없는 계정 로그인 안내", st == 403 and "비밀번호가 없는" in d.get("error", ""), d)
check("틀린 설정 코드 거부", a.req("POST", "/api/setup", {"code": "00000000", "login": ADMIN, "pw": ADMIN_PW})[0] == 403)
check("팀원 아이디로는 설정 불가", a.req("POST", "/api/setup", {"code": code, "login": "정시우", "pw": ADMIN_PW})[0] == 400)
check("짧은 관리자 비밀번호 거부", a.req("POST", "/api/setup", {"code": code, "login": ADMIN, "pw": "1234"})[0] == 400)
check("처음 설정 성공", a.req("POST", "/api/setup", {"code": code, "login": ADMIN, "pw": ADMIN_PW})[0] == 200)
check("설정 끝나면 다시 못 함", a.req("POST", "/api/setup", {"code": code, "login": "팀장", "pw": ADMIN_PW})[0] == 403 and a.req("GET", "/api/setup")[1]["needed"] is False)
m = S(); check("마스터 로그인", m.req("POST", "/api/login", {"login": ADMIN, "pw": ADMIN_PW})[0] == 200)
st, meta = m.req("GET", "/api/meta")
rows = ["아이디\t처음 비밀번호\t이름\t파트\t권한", f"{ADMIN}\t{ADMIN_PW}\t\t\t마스터"]
for u in meta["users"]:
    if u["login"] == ADMIN: continue
    st, d = m.req("POST", f"/api/admin/users/{u['id']}/reset", {})
    if st == 200: rows.append(f"{u['login']}\t{d['temp']}\t{u['name']}\t{u['part']}\t{u['role']}")
    else: check(f"{u['login']} 처음 비밀번호", False, d)
t = rows[2].split("\t")[1]
check("임시 비밀번호 10자 · 영문숫자", len(t) == 10 and re.fullmatch(r"[A-Za-z0-9]+", t) is not None, t)
open(OUT, "w", encoding="utf-8-sig").write("\n".join(rows) + "\n")
print(f"처음 설정 시험: 통과 {ok} · 실패 {bad} · 계정 {len(rows) - 1}개")
