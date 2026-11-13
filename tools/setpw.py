# 시험용: 계정표의 처음 비밀번호를 한 번에 바꿈
import sys, json, urllib.request, http.cookiejar
BASE, ACC, NEW = sys.argv[1:4]
for l in open(ACC, encoding="utf-8-sig").read().splitlines()[1:]:
    p = l.split("\t")
    if len(p) < 5: continue
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    def req(m, path, b=None):
        r = urllib.request.Request(BASE + path, data=None if b is None else json.dumps(b).encode(), method=m, headers={"content-type": "application/json", "x-req": "1"})
        try: return json.loads(op.open(r).read())
        except Exception as e: return {"error": str(e)}
    req("POST", "/api/login", {"login": p[0], "pw": p[1]}); req("POST", "/api/password", {"old": p[1], "new": NEW})
