# 비밀번호 찾기 메일 시험: 가짜 SMTP 서버(aiosmtpd)를 띄우고 인증번호 메일 → 새 비밀번호 → 로그인
import sys, json, re, time, email, urllib.request, http.cookiejar
from email import policy
from aiosmtpd.controller import Controller
BASE, PW = sys.argv[1], sys.argv[2]; LEAD = sys.argv[3] if len(sys.argv) > 3 else "팀장"
box = []
class H:
    async def handle_DATA(self, server, session, env):
        box.append(email.message_from_bytes(env.content, policy=policy.default)); return "250 OK"
ctl = Controller(H(), hostname="127.0.0.1", port=2526); ctl.start()
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
lead = S(); check("팀장 로그인", lead.req("POST", "/api/login", {"login": LEAD, "pw": PW})[0] == 200)
check("메일 설정 저장", lead.req("PUT", "/api/admin/mail", {"smtp_host": "127.0.0.1", "smtp_port": "2526", "smtp_secure": "0", "smtp_user": "", "smtp_tls_check": "0", "mail_from": "업무관리 <noreply@example.com>", "mail_domain": "example.com"})[0] == 200)
st, d = lead.req("POST", "/api/admin/mail/test", {"to": "hong@example.com"}); time.sleep(0.5)
check("시험 메일 도착", st == 200 and len(box) == 1 and "시험" in box[0]["subject"], (st, d))
m = S(); m.req("POST", "/api/login", {"login": "정시우", "pw": PW})
check("회사 도메인 아닌 메일 거부", m.req("PUT", "/api/me/email", {"email": "a@gmail.com"})[0] == 400)
check("회사 메일 등록", m.req("PUT", "/api/me/email", {"email": "hong@example.com"})[0] == 200)
a = S()
st, d = a.req("POST", "/api/reset/request", {"login": "정시우", "email": "wrong@example.com"}); time.sleep(0.5)
check("메일이 다르면 같은 안내 · 메일 안 감", st == 200 and len(box) == 1, d)
st, d = a.req("POST", "/api/reset/request", {"login": "정시우", "email": "hong@example.com"}); time.sleep(0.8)
check("인증번호 메일 도착", st == 200 and len(box) == 2, (st, d))
code = re.search(r"\b(\d{6})\b", box[-1].get_body(("plain",)).get_content()).group(1)
check("1분 안 다시 요청 막힘", a.req("POST", "/api/reset/request", {"login": "정시우", "email": "hong@example.com"})[0] == 429)
wrong = "000000" if code != "000000" else "111111"
st, d = a.req("POST", "/api/reset/confirm", {"login": "정시우", "code": wrong, "new": "NewPw!777"})
check("틀린 인증번호", st == 400 and "남은" in d.get("error", ""), d)
check("짧은 비밀번호 거부", a.req("POST", "/api/reset/confirm", {"login": "정시우", "code": code, "new": "12"})[0] == 400)
st, d = a.req("POST", "/api/reset/confirm", {"login": "정시우", "code": code, "new": "NewPw!777"})
check("인증번호 맞으면 새 비밀번호", st == 200, d)
check("같은 인증번호 다시 못 씀", a.req("POST", "/api/reset/confirm", {"login": "정시우", "code": code, "new": "Again!777"})[0] == 400)
check("기존 로그인 세션 끊김", m.req("GET", "/api/meta")[0] == 401)
check("예전 비밀번호 로그인 안 됨", S().req("POST", "/api/login", {"login": "정시우", "pw": PW})[0] == 401)
check("새 비밀번호 로그인", S().req("POST", "/api/login", {"login": "정시우", "pw": "NewPw!777"})[0] == 200)
ctl.stop()
print(f"메일 시험: 통과 {ok} · 실패 {bad}")
