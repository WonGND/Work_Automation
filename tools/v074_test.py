# 0.7.4 시험: PPT 글자 크기 1pt 차이 · "-"만 적힌 항목 빼기
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
import urllib.parse
import io, zipfile, re, struct, zlib
def raw(s, m, p, body=None, ctype="application/json"):
    data = body if isinstance(body, (bytes, bytearray)) else (None if body is None else json.dumps(body, ensure_ascii=False).encode())
    r = urllib.request.Request(BASE + urllib.request.quote(p, safe="/?=&"), data=data, method=m, headers={"content-type": ctype, "x-req": "1"})
    try:
        with s.op.open(r) as res: return res.status, res.headers, res.read()
    except urllib.error.HTTPError as e: return e.code, e.headers, e.read()
def png(w, h):
    rows = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(rows)) + ch(b"IEND", b"")
check("버전 0.7.4", urllib.request.urlopen(BASE + "/version").read().decode() == "업무관리 0.7.4")
st, iss = pl.req("POST", "/api/issues", {"model_id": model["id"], "title": "0.7.4 대시 시험", "members": [{"role": "정", "user_id": mem2_u["id"]}],
  "items": {"1-1": "-", "1-2": "첫 줄\n-\n둘째 줄", "1-3": " - ", "2-1": "–", "3-1": "개선안", "4-1": "."}, "status_text": "-", "cause": "예전 원인 글"})
iid = iss["id"]
st, hd, body = raw(pl, "POST", f"/api/issues/{iid}/pptx", {})
s1 = zipfile.ZipFile(io.BytesIO(body)).read("ppt/slides/slide1.xml").decode()
texts = re.findall(r"<a:t>([^<]*)</a:t>", s1)
check("'-'만 적은 항목은 빠짐 (1-1 · 1-3 · 2-1 · 4-1)", not any(t.startswith(("1-1 ", "1-3 ", "2-1 ", "4-1 ")) for t in texts), texts)
check("글 있는 항목은 들어감 (1-2 · 3-1)", "1-2 불량 재현" in texts and "3-1 원인별 개선안" in texts)
check("항목 안 '-' 줄도 빠짐", "- 첫 줄" in texts and "- 둘째 줄" in texts and texts.count("- -") == 0 and "- " not in texts)
check("이전 기록 '-'도 빠짐 · 다른 칸 이전 기록은 들어감", texts.count("이전 기록") == 1 and "- 예전 원인 글" in texts)
check("검증 적용 칸은 '-' 한 개 (빈 칸 표시)", texts.count("-") >= 1)
# 글자 크기: 본문 상자 안에서 항목 제목 = 내용 + 1pt
bodies = re.findall(r'name="본문".*?</p:sp>', s1, re.S)
pairs = []
for b in bodies:
    for p in re.findall(r"<a:p>.*?</a:p>", b, re.S):
        m = re.search(r'sz="(\d+)".*?<a:t>([^<]*)</a:t>', p, re.S)
        if m: pairs.append((int(m.group(1)), m.group(2)))
lab = {sz for sz, t in pairs if re.match(r"^\d-\d |^이전 기록", t)}; bod = {sz for sz, t in pairs if t.startswith("- ") or t == "-"}
check("기본 크기 11.5 / 10.5", lab == {1150} and bod == {1050}, (lab, bod))
long = "\n".join(f"긴 내용 {k}번째 줄 — 시험 조건과 결과 수치, 담당 확인 일자를 적습니다" for k in range(6))
pl.req("PUT", f"/api/issues/{iid}", {"items": {i["id"]: long for b2 in adm.req("GET", "/api/meta")[1]["issueTpl"] for i in b2["items"]}})
s1 = zipfile.ZipFile(io.BytesIO(raw(pl, "POST", f"/api/issues/{iid}/pptx", {})[2])).read("ppt/slides/slide1.xml").decode()
bodies = re.findall(r'name="본문".*?</p:sp>', s1, re.S); pairs = []
for b in bodies:
    for p in re.findall(r"<a:p>.*?</a:p>", b, re.S):
        m = re.search(r'sz="(\d+)".*?<a:t>([^<]*)</a:t>', p, re.S)
        if m: pairs.append((int(m.group(1)), m.group(2)))
lab = {sz for sz, t in pairs if re.match(r"^\d-\d ", t)}; bod = {sz for sz, t in pairs if t.startswith("- ")}
check("줄여도 1pt 차이 (최소 9.5 / 8.5)", len(lab) == 1 and len(bod) == 1 and min(lab) - min(bod) == 100 and min(bod) >= 850, (lab, bod))
print(f"0.7.4 시험: 통과 {ok} · 실패 {bad}")
