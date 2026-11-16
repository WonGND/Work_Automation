# 0.6.0 시험: 진행 현황 4칸 · 첨부 이미지 · 담당 순서 · 발생일 · 월간 시간 표 · 모델 여러 줄 추가/숨김
# 사용: python3 -I v060_test.py <주소> <계정표> <seed.json> <DB>   (seed 로 처음 설정한 빈 서버)
import sys, json, os, struct, zlib, urllib.request, http.cookiejar, sqlite3
BASE, ACC, SEED, DB = sys.argv[1:5]
ok = bad = 0
def check(n, c, i=""):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("  ✗", n, i)
class S:
    def __init__(s): s.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def req(s, m, p, b=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else (None if b is None else json.dumps(b, ensure_ascii=False).encode())
        r = urllib.request.Request(BASE + urllib.request.quote(p, safe="/?=&"), data=data, method=m, headers={"content-type": ctype, "x-req": "1"})
        try:
            with s.op.open(r) as res:
                body = res.read(); ct = res.headers.get("content-type", "")
                return res.status, (json.loads(body) if "json" in ct else body)
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read())
            except Exception: return e.code, {}
acc = {l.split("\t")[0]: l.split("\t")[1] for l in open(ACC, encoding="utf-8-sig").read().splitlines()[1:]}
def login(n):
    s = S(); st, d = s.req("POST", "/api/login", {"login": n, "pw": acc[n]})
    if d.get("must_change"): s.req("POST", "/api/password", {"old": acc[n], "new": "Test!2345"}); acc[n] = "Test!2345"
    return s
def png(w=4, h=4):
    def ch(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
seed = json.load(open(SEED, encoding="utf-8"))
MAS = seed.get("master") or "홍길동"
adm = login(MAS)
meta = adm.req("GET", "/api/meta")[1]
mas_u = next(u for u in meta["users"] if u["login"] == MAS)
db = sqlite3.connect(DB, timeout=10)
IMG = os.path.join(os.path.dirname(DB), "이미지")
lead = login("팀장")
pls = [u for u in meta["users"] if u["role"] == "pl"]
pl_u = pls[0]; pl = login(pl_u["login"])
other_pl_u = next(u for u in pls if u["part"] != pl_u["part"]); other_pl = login(other_pl_u["login"])
mem_u = next(u for u in meta["users"] if u["role"] == "member" and u["part"] == pl_u["part"]); mem = login(mem_u["login"])
mem2_u = next(u for u in meta["users"] if u["role"] == "member" and u["id"] != mem_u["id"]); mem2 = login(mem2_u["login"])
model = next(m for m in meta["models"] if m["part"] == pl_u["part"] and m["active"])

# ── 기존 데이터: 예전 진행현황 · 원인 · 대응 계획이 그대로 4칸으로 보임 ──
allI = adm.req("GET", "/api/issues?scope=all")[1]
src = {i["no"]: i for i in seed["issues"]}
same = [i for i in allI if i["no"] in src]
check("기존 이슈가 있음", len(same) > 0)
check("예전 진행현황 = 현상 칸 그대로", all((i["status_text"] or "") == (src[i["no"]].get("status_text") or "") for i in same))
check("예전 원인 · 대응 계획 = 원인 분석 · 개선검토 칸 그대로", all((i["cause"] or "") == (src[i["no"]].get("cause") or "") and (i["plan"] or "") == (src[i["no"]].get("plan") or "") for i in same))
check("검증 및 적용 칸은 비어 있음", all((i.get("verify") or "") == "" for i in same))
wt = next((i for i in same if i["status_text"] and not i["cause"] and not i["plan"]), None)
if wt: check("현재 진행 = 내용이 있는 가장 뒤 칸 (현상)", wt["now"] and wt["now"]["label"] == "현상" and wt["now"]["text"] == wt["status_text"], wt.get("now"))
wp = next((i for i in same if i["plan"]), None)
if wp: check("현재 진행 = 개선검토 (대응 계획이 있던 이슈)", wp["now"]["label"] == "개선검토" and wp["now"]["text"] == wp["plan"], wp.get("now"))
emp = next((i for i in same if not i["status_text"] and not i["cause"] and not i["plan"]), None)
if emp: check("네 칸이 다 비면 현재 진행 없음", emp["now"] is None)

# ── 새 이슈 · 담당 순서 ──
st, iss = pl.req("POST", "/api/issues", {"model_id": model["id"], "title": "0.6.0 시험 이슈", "occurred": "2026-10-20", "target": "2026-12-01",
    "members": [{"role": "부2", "user_id": mem2_u["id"]}, {"role": "정", "user_id": mem_u["id"], "duty": "재현"}, {"role": "부1", "user_id": mas_u["id"] if mas_u["id"] not in (mem_u["id"], mem2_u["id"]) else pl_u["id"]}], "confirm_pl": True})
check("이슈 등록", st == 200, iss); iid = iss["id"]
check("담당 순서 정 · 부1 · 부2", [m["role"] for m in iss["members"]] == ["정", "부1", "부2"], [m["role"] for m in iss["members"]])
check("발생일 저장", iss["occurred"] == "2026-10-20")
sm = lead.req("GET", "/api/summary")[1]
si = next(i for i in sm["issues"] if i["id"] == iid)
check("이슈 요약에 발생일 · 담당 순서", si["occurred"] == "2026-10-20" and [m["role"] for m in si["members"]] == ["정", "부1", "부2"])

# ── 4칸 쓰기 권한: PL(우리 파트) · 팀장 · 마스터 ──
for k in ("status_text", "cause", "plan", "verify"):
    st, d = mem.req("PUT", f"/api/issues/{iid}", {k: "정 담당이 씀"})
    check(f"정 담당은 {k} 못 씀", st == 403, d)
st, d = other_pl.req("PUT", f"/api/issues/{iid}", {"verify": "다른 파트 PL"})
check("다른 파트 PL은 못 씀", st == 403, d)
st, d = pl.req("PUT", f"/api/issues/{iid}", {"status_text": "화면 깜박임 3/50EA"})
check("PL 현상 저장", st == 200 and d["status_text"] == "화면 깜박임 3/50EA" and d["now"]["label"] == "현상", d)
check("칸별 마지막 수정 (누가)", d["box_meta"].get("status_text", {}).get("by") == pl_u["name"] and len(d["box_meta"]["status_text"]["at"]) == 16, d.get("box_meta"))
st, d = lead.req("PUT", f"/api/issues/{iid}", {"cause": "T-CON 리셋 마진 부족"})
check("팀장 원인 분석 저장", st == 200 and d["now"]["label"] == "원인 분석", d)
st, d = adm.req("PUT", f"/api/issues/{iid}", {"plan": "리셋 IC 변경 검토", "verify": "DV 20EA 재검증 예정"})
check("마스터 개선검토 · 검증 및 적용 저장", st == 200 and d["plan"] == "리셋 IC 변경 검토" and d["verify"] == "DV 20EA 재검증 예정", d)
check("현재 진행 = 검증 및 적용", d["now"]["label"] == "검증 및 적용" and d["now"]["text"] == "DV 20EA 재검증 예정")
check("다른 칸의 수정 기록은 그대로", d["box_meta"]["status_text"]["by"] == pl_u["name"] and d["box_meta"]["verify"]["by"] == mas_u["name"], d["box_meta"])
st, d = adm.req("PUT", f"/api/issues/{iid}", {"verify": ""})
check("뒤 칸을 비우면 현재 진행이 앞 칸으로", d["now"]["label"] == "개선검토", d.get("now"))
st, d = mem.req("GET", f"/api/issues/{iid}")
check("담당자는 4칸 읽기 가능", st == 200 and d["status_text"] == "화면 깜박임 3/50EA" and d["canManage"] is False)
long = "가" * 5000
st, d = pl.req("PUT", f"/api/issues/{iid}", {"verify": long})
check("한 칸 4000자까지", st == 200 and len(d["verify"]) == 4000, len(d.get("verify", "")))
pl.req("PUT", f"/api/issues/{iid}", {"verify": "DV 20EA 재검증 예정"})
row = db.execute("SELECT status_text,cause,plan,verify FROM issues WHERE id=?", (iid,)).fetchone()
check("DB에 4칸 저장", row == ("화면 깜박임 3/50EA", "T-CON 리셋 마진 부족", "리셋 IC 변경 검토", "DV 20EA 재검증 예정"), row)
aud = db.execute("SELECT COUNT(*) FROM audit WHERE action='이슈 수정' AND target=?", (iss["no"],)).fetchone()[0]
check("4칸 수정이 변경 기록에 남음", aud >= 4, aud)

# ── 첨부 이미지 ──
P = png()
st, d = mem.req("POST", f"/api/issues/{iid}/image", raw=P, ctype="image/png")
check("담당자는 이미지 못 올림", st == 403, d)
st, d = other_pl.req("POST", f"/api/issues/{iid}/image", raw=P, ctype="image/png")
check("다른 파트 PL은 이미지 못 올림", st == 403, d)
st, d = pl.req("POST", f"/api/issues/{iid}/image", raw=b"<html>not image</html>", ctype="image/png")
check("이미지가 아닌 파일 거절", st == 400, d)
st, d = pl.req("POST", f"/api/issues/{iid}/image", raw=b"", ctype="image/png")
check("빈 파일 거절", st == 400, d)
st, d = pl.req("POST", f"/api/issues/{iid}/image", raw=P[:8] + b"\x00" * (8 * 1024 * 1024 + 10), ctype="image/png")
check("8MB 넘으면 거절", st == 413, d)
st, d = pl.req("GET", f"/api/issues/{iid}/image")
check("이미지가 없으면 404", st == 404)
st, d = pl.req("POST", f"/api/issues/{iid}/image", raw=P, ctype="image/png")
check("PL 이미지 올리기", st == 200 and d.get("image_at"), d)
check("이미지 파일이 DB 밖 '이미지' 폴더에", os.path.exists(os.path.join(IMG, f"{iid}.png")), os.listdir(IMG) if os.path.isdir(IMG) else "폴더 없음")
check("DB에는 파일 이름만", db.execute("SELECT image FROM issues WHERE id=?", (iid,)).fetchone()[0] == f"{iid}.png")
check("백업 폴더에는 이미지가 없음", not any(f.endswith((".png", ".jpg")) for f in os.listdir(os.path.join(os.path.dirname(DB), "백업"))))
st, d = mem.req("GET", f"/api/issues/{iid}/image")
check("담당자는 이미지 보기 가능", st == 200 and d == P)
st, d = mem2.req("GET", f"/api/issues/{iid}") ; check("부2도 has_image", d.get("has_image") is True)
out_u = next(u for u in meta["users"] if u["role"] == "member" and u["part"] != pl_u["part"] and u["id"] not in (mem_u["id"], mem2_u["id"], mas_u["id"]))
st, d = login(out_u["login"]).req("GET", f"/api/issues/{iid}/image")
check("담당이 아닌 다른 파트 사람은 이미지 못 봄", st == 403, st)
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
st, d = lead.req("POST", f"/api/issues/{iid}/image", raw=JPG, ctype="image/jpeg")
check("팀장이 새 이미지로 바꿈", st == 200)
check("바꾸면 이전 파일은 지워짐 (한 장만)", sorted(os.listdir(IMG)) == [f"{iid}.jpg"], os.listdir(IMG))
li = next(i for i in adm.req("GET", "/api/issues?scope=all")[1] if i["id"] == iid)
check("이슈 정리 목록에 has_image", li["has_image"] is True and li["image"] == f"{iid}.jpg")
st, d = mem.req("DELETE", f"/api/issues/{iid}/image")
check("담당자는 이미지 못 지움", st == 403)
st, d = adm.req("DELETE", f"/api/issues/{iid}/image")
check("마스터 이미지 지우기", st == 200 and os.listdir(IMG) == [], os.listdir(IMG))
check("지운 뒤 has_image 꺼짐", adm.req("GET", f"/api/issues/{iid}")[1]["has_image"] is False)
check("이미지 작업이 변경 기록에 남음", db.execute("SELECT COUNT(*) FROM audit WHERE action='이슈 이미지' AND target=?", (iss["no"],)).fetchone()[0] == 3)
st, d = pl.req("POST", "/api/issues/999999/image", raw=P, ctype="image/png")
check("없는 이슈", st == 404)

# ── 내 업무 월간 표 ──
st, w = mem.req("GET", "/api/week?from=2026-11-16&mode=month")
check("월간: 11월 30일", st == 200 and w["from"] == "2026-11-01" and w["to"] == "2026-11-30" and len(w["days"]) == 30, (w.get("from"), w.get("to")))
st, w2 = mem.req("GET", "/api/week?from=2026-02-10&mode=month")
check("월간: 2월 28일", len(w2["days"]) == 28 and w2["to"] == "2026-02-28")
st, wk = mem.req("GET", "/api/week?from=2026-11-18")
check("주간은 그대로 7일 (월~일)", len(wk["days"]) == 7 and wk["from"] == "2026-11-16")
tot_m = sum(v for r in w["rows"] for v in r["hours"].values())
tot_db = db.execute("SELECT IFNULL(SUM(h.hours),0) FROM task_hours h JOIN tasks t ON t.id=h.task_id WHERE t.user_id=? AND h.date BETWEEN '2026-11-01' AND '2026-11-30'", (mem_u["id"],)).fetchone()[0] + \
         db.execute("SELECT IFNULL(SUM(hours),0) FROM issue_logs WHERE user_id=? AND date BETWEEN '2026-11-01' AND '2026-11-30'", (mem_u["id"],)).fetchone()[0]
check("월간 표 시간 합계 = DB 합계", abs(tot_m - tot_db) < 1e-9, (tot_m, tot_db))
check("월간 표에 새 이슈 행", any(r["type"] == "issue" and r["id"] == iid for r in w["rows"]))
st, d = mem2.req("GET", f"/api/week?user={mem_u['id']}&from=2026-11-16&mode=month")
check("다른 사람 월간 표는 못 봄", st == 403)

# ── 기준정보 모델: 여러 줄 추가 · 삭제(숨김) · 되살리기 ──
n0 = db.execute("SELECT COUNT(*) FROM models").fetchone()[0]
st, d = adm.req("POST", "/api/master/models/bulk", {"items": [{"name": "시험모델A", "part": pl_u["part"], "grade": "A", "phase": "DV"}, {"name": "시험모델B", "part": other_pl_u["part"], "phase": "ES", "sop": "2027-03-01"}, {"name": "시험모델C", "part": pl_u["part"], "active": False}]})
check("모델 3개 한 번에 추가", st == 200 and d["added"] == ["시험모델A", "시험모델B", "시험모델C"] and db.execute("SELECT COUNT(*) FROM models").fetchone()[0] == n0 + 3, d)
check("꺼서 넣은 모델은 관리 꺼짐", db.execute("SELECT active FROM models WHERE name='시험모델C'").fetchone()[0] == 0)
st, d = adm.req("POST", "/api/master/models/bulk", {"items": [{"name": "시험모델D", "part": pl_u["part"]}, {"name": "시험모델A", "part": pl_u["part"]}]})
check("하나라도 같은 이름이면 전부 안 넣음", st == 400 and db.execute("SELECT COUNT(*) FROM models WHERE name='시험모델D'").fetchone()[0] == 0, d)
st, d = adm.req("POST", "/api/master/models/bulk", {"items": [{"name": "시험모델E", "part": pl_u["part"]}, {"name": "시험모델E", "part": pl_u["part"]}]})
check("같은 이름 두 줄 거절", st == 400)
st, d = adm.req("POST", "/api/master/models/bulk", {"items": []})
check("빈 목록 거절", st == 400)
st, d = pl.req("POST", "/api/master/models/bulk", {"items": [{"name": "시험모델F", "part": other_pl_u["part"]}]})
check("PL은 다른 파트 모델 못 넣음", st == 403, d)
st, d = pl.req("POST", "/api/master/models/bulk", {"items": [{"name": "시험모델F", "part": pl_u["part"]}, {"name": "시험모델G", "part": pl_u["part"]}]})
check("PL 우리 파트 모델 2개 추가", st == 200 and len(d["added"]) == 2, d)
st, d = mem.req("POST", "/api/master/models/bulk", {"items": [{"name": "시험모델H", "part": pl_u["part"]}]})
check("팀원은 모델 못 넣음", st == 403)
mid = lambda nm: db.execute("SELECT id FROM models WHERE name=?", (nm,)).fetchone()[0]
st, d = other_pl.req("POST", "/api/master/models/hide", {"id": mid("시험모델A"), "hidden": True})
check("PL은 다른 파트 모델 삭제 못 함", st == 403)
# 시간이 들어간 모델을 숨겨도 집계는 그대로
before = adm.req("GET", "/api/dashboard?mode=custom&from=2026-10-12&to=2026-11-13")[1]
used = max((m for m in meta["models"]), key=lambda m: db.execute("SELECT IFNULL(SUM(h.hours),0) FROM task_hours h JOIN tasks t ON t.id=h.task_id WHERE t.model_id=?", (m["id"],)).fetchone()[0])
st, d = adm.req("POST", "/api/master/models/hide", {"id": used["id"], "hidden": True})
check("모델 삭제(숨김)", st == 200 and db.execute("SELECT hidden FROM models WHERE id=?", (used["id"],)).fetchone()[0] == 1)
check("숨겨도 모델 행은 남음 (실제 삭제 아님)", db.execute("SELECT COUNT(*) FROM models WHERE id=?", (used["id"],)).fetchone()[0] == 1)
after = adm.req("GET", "/api/dashboard?mode=custom&from=2026-10-12&to=2026-11-13")[1]
check("숨겨도 팀 투입 · 로드 집계는 그대로", abs(before["team"]["input"] - after["team"]["input"]) < 1e-9 and abs(before["team"]["weighted"] - after["team"]["weighted"]) < 1e-9, (before["team"]["input"], after["team"]["input"]))
check("숨겨도 사람별 모델 시간은 그대로", all(b["models"] == a["models"] for b, a in zip(before["people"], after["people"])))
check("숨긴 모델은 업무로드 모델 칸에서 빠짐", used["id"] in [m["id"] for m in before["modelCols"]] and used["id"] not in [m["id"] for m in after["modelCols"]])
m2 = adm.req("GET", "/api/meta")[1]
check("기준 정보에 hidden 표시", next(m for m in m2["models"] if m["id"] == used["id"])["hidden"] == 1)
st, d = adm.req("POST", "/api/master/models/hide", {"id": used["id"], "hidden": False})
check("되살리기", st == 200 and db.execute("SELECT hidden FROM models WHERE id=?", (used["id"],)).fetchone()[0] == 0)
check("삭제 · 되살리기가 변경 기록에 남음", db.execute("SELECT COUNT(*) FROM audit WHERE action IN ('모델 삭제(숨김)','모델 되살리기') AND target=?", (used["name"],)).fetchone()[0] == 2)
r0 = adm.req("GET", "/api/notifs")[1]["rev"]
adm.req("POST", "/api/master/models/hide", {"id": mid("시험모델G"), "hidden": True})
check("모델 삭제가 다른 화면에도 반영 (rev)", adm.req("GET", "/api/notifs")[1]["rev"] > r0)
st, d = adm.req("POST", "/api/master/models/hide", {"id": 999999, "hidden": True})
check("없는 모델", st == 404)

# ── 버전 ──
check("버전 0.6.0 이상", urllib.request.urlopen(BASE + "/version").read().decode() >= "업무관리 0.6.0")
print(f"0.6.0 시험: 통과 {ok} · 실패 {bad}")
sys.exit(1 if bad else 0)
