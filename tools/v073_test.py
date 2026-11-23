# 0.7.3 시험: 이슈 템플릿 편집 (항목 id 유지 · 지운 항목 글 보존) · PPT 내보내기 · 권한
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
lead = login(lead_u["login"])
check("버전 0.7.3", urllib.request.urlopen(BASE + "/version").read().decode() == "업무관리 0.7.3")
tpl0 = adm.req("GET", "/api/meta")[1]["issueTpl"]
check("기본 템플릿 id = 예전 번호", [i["id"] for i in tpl0[0]["items"]] == ["1-1", "1-2", "1-3"] and tpl0[0]["deleted"] == [])

# 이슈 하나 만들고 항목 쓰기
st, iss = pl.req("POST", "/api/issues", {"model_id": model["id"], "title": "0.7.3 템플릿 시험", "members": [{"role": "정", "user_id": mem2_u["id"]}], "items": {"1-2": "재현 됨", "3-4": "리스크 있음"}})
iid = iss["id"]
def box(t, k): return {"key": t[k]["key"], "title": t[k]["title"], "items": [{"id": i["id"], "label": i["label"], "hint": i["hint"]} for i in t[k]["items"]] + [{"id": d["id"], "label": d["label"], "del": 1} for d in t[k]["deleted"]]}
B = [box(tpl0, k) for k in range(4)]
# 권한
check("PL은 템플릿 못 고침", pl.req("PUT", "/api/master/issue-tpl", {"boxes": B})[0] == 403)
check("팀원은 못 고침", mem.req("PUT", "/api/master/issue-tpl", {"boxes": B})[0] == 403)
check("칸 3개는 거절", adm.req("PUT", "/api/master/issue-tpl", {"boxes": B[:3]})[0] == 400)
bad1 = json.loads(json.dumps(B)); bad1[0]["title"] = ""
check("빈 칸 제목 거절", adm.req("PUT", "/api/master/issue-tpl", {"boxes": bad1})[0] == 400)
bad2 = json.loads(json.dumps(B)); bad2[1]["items"].append({"id": "zz-9", "label": "x"})
check("없는 id 거절", adm.req("PUT", "/api/master/issue-tpl", {"boxes": bad2})[0] == 400)
bad3 = json.loads(json.dumps(B)); bad3[1]["items"].append(dict(bad3[1]["items"][0]))
check("같은 항목 두 번 거절", adm.req("PUT", "/api/master/issue-tpl", {"boxes": bad3})[0] == 400)
# 고치기: 1번 칸 제목 바꾸고, 1-2(글 있음) 지우고, 새 항목 앞에 추가, 3-4(글 있음) 아래로 옮기기
N = json.loads(json.dumps(B))
N[0]["title"] = "현상 파악"
N[0]["items"] = [{"id": "", "label": "고객 요청 사항", "hint": "고객이 요청한 내용"}, N[0]["items"][0], N[0]["items"][2]]   # 1-2 빠짐 (보내지 않음)
p3 = N[2]["items"]; p3.append(p3.pop(3))   # 3-4 Risk → 맨 뒤
st, d = lead.req("PUT", "/api/master/issue-tpl", {"boxes": N})
check("팀장이 템플릿 저장", st == 200, d)
t1 = d["issueTpl"]
check("칸 제목 바뀜", t1[0]["title"] == "현상 파악")
check("새 항목이 1-1 · 예전 1-1이 1-2", t1[0]["items"][0]["label"] == "고객 요청 사항" and t1[0]["items"][0]["code"] == "1-1" and t1[0]["items"][1]["id"] == "1-1" and t1[0]["items"][1]["code"] == "1-2")
newid = t1[0]["items"][0]["id"]
check("새 항목 id는 새로 만들어짐", newid.startswith("n"))
check("보내지 않은 항목(글 있음)은 지운 항목으로 남음", [x["id"] for x in t1[0]["deleted"]] == ["1-2"])
check("옮긴 항목 번호 3-7 · id 그대로", t1[2]["items"][-1]["id"] == "3-4" and t1[2]["items"][-1]["code"] == "3-7" and t1[2]["items"][3]["code"] == "3-4" and t1[2]["items"][3]["id"] == "3-5")
g = pl.req("GET", f"/api/issues/{iid}")[1]
check("이슈의 글은 그대로", g["items"] == {"1-2": "재현 됨", "3-4": "리스크 있음"}, g["items"])
check("현재 진행 = 옮긴 3-4 (새 번호 3-7)", g["now"]["label"] == "3-7 Risk 사항", g["now"])
# 새 항목에 글 쓰기 · 지운 항목 글 비우기
st, d = pl.req("PUT", f"/api/issues/{iid}", {"items": {newid: "A사 요청"}})
check("새 항목에 글 저장", st == 200 and d["items"][newid] == "A사 요청")
check("지운 항목 글도 고칠 수 있음 (비우기)", pl.req("PUT", f"/api/issues/{iid}", {"items": {"1-2": ""}})[1]["items"].get("1-2") is None)
# 글이 없어진 지운 항목은 다음 저장 때 정리됨, 글 있는 항목을 지우면 남음
pl.req("PUT", f"/api/issues/{iid}", {"items": {"3-4": "리스크 있음 2"}})
t2 = adm.req("GET", "/api/meta")[1]["issueTpl"]
N2 = [box(t2, k) for k in range(4)]
N2[2]["items"] = [i for i in N2[2]["items"] if i["id"] != "3-4"]          # 글 있는 3-4 지우기 (목록에서 뺌)
N2[0]["items"] = [i for i in N2[0]["items"] if i["id"] != "1-2"]          # 글 없는 1-2 (지운 항목)도 뺌 → 정리
st, d = adm.req("PUT", "/api/master/issue-tpl", {"boxes": N2}); t3 = d["issueTpl"]
check("글 없는 지운 항목은 정리", [x["id"] for x in t3[0]["deleted"]] == [])
check("글 있는 항목은 지워도 남음", [x["id"] for x in t3[2]["deleted"]] == ["3-4"])
g = pl.req("GET", f"/api/issues/{iid}")[1]
check("지운 항목 글 그대로 · 현재 진행 '삭제된 항목'", g["items"]["3-4"] == "리스크 있음 2" and g["now"]["label"] == "삭제된 항목 · Risk 사항", g["now"])
# 살리기
N3 = [box(t3, k) for k in range(4)]
for it in N3[2]["items"]:
    if it["id"] == "3-4": it.pop("del")
st, d = adm.req("PUT", "/api/master/issue-tpl", {"boxes": N3})
check("살리기", any(i["id"] == "3-4" for i in d["issueTpl"][2]["items"]) and not d["issueTpl"][2]["deleted"])
check("없는 항목 id로 이슈 저장은 거절", pl.req("PUT", f"/api/issues/{iid}", {"items": {"x-1": "a"}})[0] == 400)

# ── PPT ──
st, hd, body = raw(pl, "POST", f"/api/issues/{iid}/pptx", {})
check("PL PPT 내려받기", st == 200 and "presentationml" in hd["content-type"], (st, body[:200]))
check("파일 이름 (모델 이슈명_날짜)", "filename*=UTF-8''" in hd["content-disposition"] and urllib.parse.unquote(hd["content-disposition"].split("''")[1]).startswith(f"{model['name']} 0.7.3 템플릿 시험_"), hd["content-disposition"])
z = zipfile.ZipFile(io.BytesIO(body)); s1 = z.read("ppt/slides/slide1.xml").decode()
check("제목 · 칸 제목 · 항목", f"■ [{iss['no']}]" in s1 and "현상 파악" in s1 and "A사 요청" in s1 and "리스크 있음 2" in s1 and "고객 요청 사항" in s1)
check("안내 문구(TextBox 2) 지움", 'name="TextBox 2"' not in s1 and "ctrl + shift + s" not in s1)
check("빈 칸은 '-'", "<a:t>-</a:t>" in s1)
check("담당 이름 · 기본 정보 표", mem2_u["name"] in s1 and "발생처" in s1)
check("팀원(담당)도 내려받기", raw(login(mem2_u["login"]), "POST", f"/api/issues/{iid}/pptx", {})[0] == 200)
check("관계 없는 사람은 못 받음", raw(login(omem_u["login"]), "POST", f"/api/issues/{iid}/pptx", {})[0] == 403)
st, hd, body = raw(pl, "POST", f"/api/issues/{iid}/pptx", {"info": False, "off": ["plan", newid]})
s1 = zipfile.ZipFile(io.BytesIO(body)).read("ppt/slides/slide1.xml").decode()
check("고른 것만 (기본 정보 · 대책 수립 칸 · 새 항목 끔)", "발생처" not in s1 and "리스크 있음 2" not in s1 and "A사 요청" not in s1 and "현상 파악" in s1)
# 이미지 · 넘침
st, hd, b = raw(pl, "POST", f"/api/issues/{iid}/image", png(400, 200), "image/png")
check("이미지 올림", st == 200, b[:200])
long = "\n".join(f"긴 내용 {k}번째 줄 — 시험 조건과 결과 수치, 담당 확인 일자를 적습니다" for k in range(14))
pl.req("PUT", f"/api/issues/{iid}", {"items": {i["id"]: long for b2 in adm.req("GET", "/api/meta")[1]["issueTpl"] for i in b2["items"]}})
st, hd, body = raw(pl, "POST", f"/api/issues/{iid}/pptx", {})
z = zipfile.ZipFile(io.BytesIO(body)); names = z.namelist()
check("이미지 들어감", any(n.startswith("ppt/media/issue_img") for n in names) and "rIdImg1" in z.read("ppt/slides/_rels/slide1.xml.rels").decode())
check("넘치면 유첨 장 (2장 이상)", "ppt/slides/slide2.xml" in names and "rIdSlide2" in z.read("ppt/_rels/presentation.xml.rels").decode() and z.read("ppt/presentation.xml").decode().count("<p:sldId ") >= 2)
s2 = z.read("ppt/slides/slide2.xml").decode()
check("유첨 장 제목 · '(계속)' 없음", "(유첨)" in s2 and "(계속)" not in s2)
check("본문 칸에 유첨 안내", "유첨 p.2" in z.read("ppt/slides/slide1.xml").decode())
st, hd, body = raw(pl, "POST", f"/api/issues/{iid}/pptx", {"image": False})
check("이미지 끔", not any(n.startswith("ppt/media/issue_img") for n in zipfile.ZipFile(io.BytesIO(body)).namelist()))
print(f"0.7.3 시험: 통과 {ok} · 실패 {bad}")
