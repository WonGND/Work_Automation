# 0.7.0 시험: 가운데 팝업 알림 · 공지 · 버전 공지 초안 · 업무 지정 요약 · 빨간 점
# 사용: python3 -I v070_test.py <주소> <계정표> <seed.json> <DB>   (seed 로 처음 설정한 빈 서버)
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
mas_u = next(u for u in meta["users"] if u["login"] == MAS)
db = sqlite3.connect(DB, timeout=10)
lead = login("팀장"); lead_u = next(u for u in meta["users"] if u["role"] == "lead")
pls = [u for u in meta["users"] if u["role"] == "pl"]
pl_u = pls[0]; pl = login(pl_u["login"])
mems = [u for u in meta["users"] if u["role"] == "member" and u["part"] == pl_u["part"]]
mem_u, mem2_u = mems[0], mems[1]; mem = login(mem_u["login"]); mem2 = login(mem2_u["login"])
oth_u = next(u for u in meta["users"] if u["role"] == "member" and u["part"] != pl_u["part"]); oth = login(oth_u["login"])
model = next(m for m in meta["models"] if m["part"] == pl_u["part"] and m["active"])
pops = lambda s: s.req("GET", "/api/notifs")[1]["pops"]
dots = lambda s: s.req("GET", "/api/notifs")[1]["dots"]

# ── 버전: 자동 전체 알림 대신 마스터에게 공지 초안 ──
check("팀원에게는 버전 알림이 자동으로 가지 않음", db.execute("SELECT COUNT(*) FROM notifs WHERE kind='버전' AND user_id=?", (mem_u["id"],)).fetchone()[0] == 0)
check("팀원에게 처음에는 팝업 없음", pops(mem) == [])
mp = pops(adm)
check("마스터에게 버전 공지 초안 팝업", len(mp) == 1 and mp[0]["data"]["what"] == "버전 공지 초안" and mp[0]["link"] == "#/notices", mp)
check("팀장(마스터 아님)에게는 초안 팝업 없음", pops(lead) == [])
st, nl = adm.req("GET", "/api/notices")
check("마스터 공지 화면에 초안 1개", st == 200 and len(nl["drafts"]) == 1 and nl["drafts"][0]["kind"] == "버전" and nl["canSend"] is True, nl)
draft = nl["drafts"][0]
check("초안 글은 짧은 줄 목록", draft["body"].startswith("· ") and len(draft["body"]) < 700 and "빨간 점" in draft["body"], draft["body"])
check("팀장 · 팀원에게는 초안이 안 보임", lead.req("GET", "/api/notices")[1]["drafts"] == [] and mem.req("GET", "/api/notices")[1]["drafts"] == [] and mem.req("GET", "/api/notices")[1]["list"] == [])
st, d = lead.req("POST", "/api/notices", {"title": "x", "body": "y", "target": {"all": True}, "draft_id": draft["id"]})
check("버전 초안 배포는 마스터만", st == 403, d)
st, d = adm.req("POST", "/api/notifs/ack", {"ids": [mp[0]["id"]]})
check("팝업 확인 → 다시 안 뜸 · 읽음 처리", st == 200 and pops(adm) == [] and db.execute("SELECT read,ack FROM notifs WHERE id=?", (mp[0]["id"],)).fetchone() == (1, 1))
st, d = mem.req("POST", "/api/notifs/ack", {"ids": [mp[0]["id"]]})
check("남의 알림은 확인 못 함 (영향 없음)", st == 200)
n_act = db.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
st, d = adm.req("POST", "/api/notices", {"title": "업무관리 업데이트 안내 (고침)", "body": "· 팝업 알림\n· 빨간 점", "target": {"all": True}, "draft_id": draft["id"]})
check("마스터가 고쳐서 전체 배포", st == 200 and d["sent"] == n_act and d["label"] == "전체", d)
mp2 = pops(mem)
check("팀원에게 업데이트 안내 팝업 (고친 문구)", len(mp2) == 1 and mp2[0]["data"]["what"] == "업데이트 안내" and mp2[0]["data"]["제목"] == "업무관리 업데이트 안내 (고침)" and mp2[0]["data"]["본문"] == "· 팝업 알림\n· 빨간 점" and mp2[0]["data"]["by"] == mas_u["name"], mp2)
check("보낸 사람에게는 팝업 안 뜸", pops(adm) == [])
check("배포 뒤 초안 없음 · 지난 공지에 남음", adm.req("GET", "/api/notices")[1]["drafts"] == [] and mem.req("GET", "/api/notices")[1]["list"][0]["title"] == "업무관리 업데이트 안내 (고침)")
st, d = adm.req("POST", "/api/notices", {"title": "다시", "target": {"all": True}, "draft_id": draft["id"]})
check("같은 초안 두 번 배포 불가", st == 404, d)
for s in (mem, mem2, oth, pl, lead): s.req("POST", "/api/notifs/ack", {"ids": [x["id"] for x in pops(s)]})

# ── 공지: 마스터 · 팀장만, 전체 · 파트 · 개인 ──
for s, nm in ((pl, "PL"), (mem, "팀원")):
    st, d = s.req("POST", "/api/notices", {"title": "x", "target": {"all": True}})
    check(f"{nm}은 공지 못 보냄", st == 403, d)
st, d = lead.req("POST", "/api/notices", {"title": "", "body": "b", "target": {"all": True}})
check("제목 없으면 거절", st == 400)
st, d = lead.req("POST", "/api/notices", {"title": "t", "target": {}})
check("받는 사람 없으면 거절", st == 400)
st, d = lead.req("POST", "/api/notices", {"title": "t", "target": {"parts": []}})
check("빈 파트 목록 거절", st == 400)
n_part = db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND part=?", (pl_u["part"],)).fetchone()[0]
st, d = lead.req("POST", "/api/notices", {"title": "파트 공지", "body": "금요일까지 입력", "target": {"parts": [pl_u["part"]]}})
check("팀장 파트별 공지", st == 200 and d["sent"] == n_part and d["label"] == "파트: " + pl_u["part"], d)
p1 = pops(mem)
check("그 파트 사람에게 공지 팝업 (보낸 사람 표시)", len(p1) == 1 and p1[0]["kind"] == "공지" and p1[0]["data"]["what"] == "공지" and p1[0]["data"]["by"] == lead_u["name"] and p1[0]["data"]["제목"] == "파트 공지" and p1[0]["data"]["본문"] == "금요일까지 입력", p1)
check("다른 파트 사람에게는 안 감", pops(oth) == [] and all(n["title"] != "파트 공지" for n in oth.req("GET", "/api/notices")[1]["list"]))
check("🔔 숫자도 같이 올라감", mem.req("GET", "/api/notifs")[1]["unread"] >= 1)
st, d = adm.req("POST", "/api/notices", {"title": "개인 공지", "body": "두 분만", "target": {"users": [mem_u["id"], oth_u["id"], 999999]}})
check("마스터 개인별 공지 (없는 사람은 뺌)", st == 200 and d["sent"] == 2, d)
check("개인 공지: 고른 사람만", len(pops(oth)) == 1 and len(pops(mem)) == 2 and pops(mem2) == pops(mem2) and all(x["data"].get("제목") != "개인 공지" for x in pops(mem2)))
check("확인 전에는 계속 뜸", len(pops(mem)) == 2 and len(pops(mem)) == 2)
ml = mem.req("GET", "/api/notices")[1]
check("팀원 지난 공지 = 받은 것만 (받는 사람 목록은 안 보임)", [n["title"] for n in ml["list"]][:2] == ["개인 공지", "파트 공지"] and ml["canSend"] is False and all(not n.get("target_label") for n in ml["list"]), [n["title"] for n in ml["list"]])
al = lead.req("GET", "/api/notices")[1]
check("팀장 지난 공지 = 전체 + 받는 사람 표시", len(al["list"]) == 3 and al["list"][0]["target_label"].startswith("개인: ") and al["list"][0]["recv_n"] == 2, [(n["title"], n.get("target_label")) for n in al["list"]])
check("공지 본문 2000자 제한", lead.req("POST", "/api/notices", {"title": "긴", "body": "가" * 3000, "target": {"users": [oth_u["id"]]}})[0] == 200 and len(db.execute("SELECT body FROM notices WHERE title='긴'").fetchone()[0]) == 2000)
st, d = adm.req("DELETE", f"/api/notices/{al['list'][0]['id']}")
check("보낸 공지는 지울 수 없음", st == 400, d)
check("공지가 변경 기록에 남음", db.execute("SELECT COUNT(*) FROM audit WHERE action='공지 보냄'").fetchone()[0] == 3)
for s in (mem, mem2, oth, pl, lead, adm): s.req("POST", "/api/notifs/ack", {"ids": [x["id"] for x in pops(s)]})
check("확인하면 안 뜸", pops(mem) == [] and pops(oth) == [])

# ── 업무 지정: 요약 · 팝업 · 빨간 점 ──
check("처음에는 빨간 점 없음", dots(mem) == {"me": 0, "myissues": 0}, dots(mem))
st, d = pl.req("POST", "/api/assign", {"user_ids": [mem_u["id"], mem2_u["id"], pl_u["id"]], "title": "EMC 대책 회로 검토", "summary": "CE 30MHz 초과 대책안 3개 비교", "model_id": model["id"], "target": "2026-12-04", "start": "2026-11-17"})
check("PL 업무 지정", st == 200, d)
p = pops(mem)
check("받은 사람 팝업: 업무명 · 요약 · 목표일 · 지정한 사람", len(p) == 1 and p[0]["data"] == {"what": "업무 지정", "by": pl_u["name"], "제목": "EMC 대책 회로 검토", "요약": "CE 30MHz 초과 대책안 3개 비교", "목표일": "2026-12-04", "모델": model["name"]} and p[0]["link"] == "#/me", p)
check("본인에게 지정한 것은 팝업 · 점 없음", pops(pl) == [] and dots(pl)["me"] == 0)
check("탭 빨간 점 (내 업무)", dots(mem) == {"me": 1, "myissues": 0}, dots(mem))
tid = db.execute("SELECT id FROM tasks WHERE user_id=? AND title='EMC 대책 회로 검토'", (mem_u["id"],)).fetchone()[0]
w = mem.req("GET", "/api/week?from=2026-11-17")[1]
check("시간 표 행에 점", next(r for r in w["rows"] if r["type"] == "task" and r["id"] == tid)["flag"] == 1 and sum(r.get("flag", 0) for r in w["rows"]) == 1)
check("업무 목록 · 업무 창에 요약", mem.req("GET", f"/api/tasks/{tid}")[1]["summary"] == "CE 30MHz 초과 대책안 3개 비교")
st, d = mem.req("POST", "/api/dots/seen", {"tab": "me"})
check("탭을 열면 탭의 점은 꺼지고 행의 점은 남음", d["dots"]["me"] == 0 and next(r for r in mem.req("GET", "/api/week?from=2026-11-17")[1]["rows"] if r["type"] == "task" and r["id"] == tid)["flag"] == 1, d)
st, d = mem2.req("POST", "/api/dots/clear", {"type": "task", "id": tid})
check("남의 행 점은 못 끔", db.execute("SELECT flag FROM tasks WHERE id=?", (tid,)).fetchone()[0] == 2)
st, d = mem.req("POST", "/api/dots/clear", {"type": "task", "id": tid})
check("행을 누르면 행의 점 꺼짐", st == 200 and db.execute("SELECT flag FROM tasks WHERE id=?", (tid,)).fetchone()[0] == 0)
mem.req("POST", "/api/notifs/ack", {"ids": [x["id"] for x in pops(mem)]})
st, d = mem.req("PUT", f"/api/tasks/{tid}", {"progress": 30, "note": "내가 고침"})
check("받은 사람이 스스로 고치면 팝업 · 점 없음", st == 200 and pops(mem) == [] and dots(mem)["me"] == 0)
st, d = pl.req("PUT", f"/api/tasks/{tid}", {"target": "2026-12-11", "summary": "대책안 2개로 줄임"})
check("지정한 PL이 목표일 · 요약을 바꿈", st == 200 and d["target"] == "2026-12-11" and d["summary"] == "대책안 2개로 줄임", d)
p = pops(mem)
check("바뀌면 팝업 + 점 다시", len(p) == 1 and p[0]["data"]["what"] == "업무 변경" and p[0]["data"]["목표일"] == "2026-12-11" and p[0]["data"]["요약"] == "대책안 2개로 줄임" and dots(mem)["me"] == 1, (p, dots(mem)))
st, d = pl.req("PUT", f"/api/tasks/{tid}", {"target": "2026-12-11"})
check("같은 값으로 저장하면 알림 없음", len(pops(mem)) == 1)
st, d = mem.req("PUT", f"/api/tasks/{tid}", {"summary": "받은 사람이 요약을 바꾸려 함"})
check("요약은 지정한 사람만 고침", mem.req("GET", f"/api/tasks/{tid}")[1]["summary"] == "대책안 2개로 줄임")
st, d = mem.req("POST", "/api/tasks", {"kind": "통상", "title": "내가 만든 업무"})
check("본인이 추가한 업무는 팝업 · 점 없음", st == 200 and len(pops(mem)) == 1 and d.get("flag", 0) == 0)
mem.req("POST", "/api/notifs/ack", {"ids": [x["id"] for x in pops(mem)]}); mem.req("POST", "/api/dots/clear", {"type": "task", "id": tid})
check("같이 받은 다른 사람도 팝업 · 점", len(pops(mem2)) == 1 and dots(mem2)["me"] == 1)
mem2.req("POST", "/api/notifs/ack", {"ids": [x["id"] for x in pops(mem2)]}); mem2.req("POST", "/api/dots/seen", {"tab": "me"})

# ── 이슈 담당: 팝업 · 빨간 점 ──
st, iss = pl.req("POST", "/api/issues", {"model_id": model["id"], "title": "0.7.0 시험 이슈", "target": "2026-12-01", "members": [{"role": "정", "user_id": mem_u["id"], "duty": "재현 시험"}, {"role": "부1", "user_id": pl_u["id"]}], "confirm_pl": True})
check("이슈 등록 + 담당 지정", st == 200, iss); iid = iss["id"]
p = pops(mem)
check("담당 지정 팝업: 이슈 · 역할 · 할 일 · 목표일", len(p) == 1 and p[0]["data"] == {"what": "이슈 담당 지정", "by": pl_u["name"], "제목": f"{iss['no']} 0.7.0 시험 이슈", "역할": "정", "할 일": "재현 시험", "목표일": "2026-12-01"} and p[0]["link"] == "#/myissues", p)
check("PL 본인을 넣은 것은 팝업 · 점 없음", pops(pl) == [] and dots(pl)["myissues"] == 0)
check("탭 빨간 점 (내 이슈)", dots(mem) == {"me": 0, "myissues": 1}, dots(mem))
mi = next(i for i in mem.req("GET", "/api/issues?scope=mine")[1] if i["id"] == iid)
check("내 이슈 목록 · 시간 표 이슈 행에 점", mi["mflag"] == 1 and next(r for r in mem.req("GET", "/api/week?from=2026-11-17")[1]["rows"] if r["type"] == "issue" and r["id"] == iid)["flag"] == 1)
mem.req("POST", "/api/dots/seen", {"tab": "myissues"}); mem.req("POST", "/api/notifs/ack", {"ids": [x["id"] for x in pops(mem)]})
check("탭 점 꺼짐 · 행 점 남음", dots(mem)["myissues"] == 0 and db.execute("SELECT flag FROM issue_members WHERE issue_id=? AND user_id=?", (iid, mem_u["id"])).fetchone()[0] == 2)
st, d = pl.req("PUT", f"/api/issues/{iid}", {"status_text": "현상 적음"})
check("담당이 안 바뀌는 수정은 점 · 팝업 그대로", pops(mem) == [] and db.execute("SELECT flag FROM issue_members WHERE issue_id=? AND user_id=?", (iid, mem_u["id"])).fetchone()[0] == 2)
st, d = pl.req("PUT", f"/api/issues/{iid}", {"members": [{"role": "정", "user_id": mem_u["id"], "duty": "재현 시험"}, {"role": "부1", "user_id": pl_u["id"]}, {"role": "부2", "user_id": mem2_u["id"]}], "confirm_pl": True})
check("부2 추가: 새 사람만 팝업 · 점, 기존 사람 표시는 유지", st == 200 and len(pops(mem2)) == 1 and pops(mem2)[0]["data"]["역할"] == "부2" and dots(mem2)["myissues"] == 1 and pops(mem) == [] and db.execute("SELECT flag FROM issue_members WHERE issue_id=? AND user_id=?", (iid, mem_u["id"])).fetchone()[0] == 2, (pops(mem2), pops(mem)))
mem.req("POST", "/api/dots/clear", {"type": "issue", "id": iid})
check("행을 누르면 이슈 행 점 꺼짐", db.execute("SELECT flag FROM issue_members WHERE issue_id=? AND user_id=?", (iid, mem_u["id"])).fetchone()[0] == 0)
st, d = pl.req("PUT", f"/api/issues/{iid}", {"members": [{"role": "정", "user_id": mem2_u["id"]}, {"role": "부1", "user_id": mem_u["id"], "duty": "측정 지원"}]})
p = pops(mem)
check("역할 · 할 일이 바뀌면 '담당 변경' 팝업 + 점", st == 200 and len(p) == 1 and p[0]["data"]["what"] == "이슈 담당 변경" and p[0]["data"]["역할"] == "부1" and p[0]["data"]["할 일"] == "측정 지원" and dots(mem)["myissues"] == 1, p)
st, d = pl.req("PUT", f"/api/issues/{iid}", {"members": [{"role": "정", "user_id": mem2_u["id"]}]})
check("담당에서 빠지면 '담당 해제' 팝업", any(x["data"]["what"] == "이슈 담당 해제" for x in pops(mem)) and dots(mem)["myissues"] == 0, pops(mem))
for s in (mem, mem2): s.req("POST", "/api/notifs/ack", {"ids": [x["id"] for x in pops(s)]})

# ── 요청: 팝업 ──
st, rq = mem.req("POST", "/api/requests", {"to_id": pl_u["id"], "text": "모델 추가 부탁드립니다"})
check("요청 보냄", st == 200, rq)
p = pops(pl)
check("받은 사람(PL)에게 요청 팝업", len(p) == 1 and p[0]["data"]["what"] == "요청 도착" and p[0]["data"]["by"] == mem_u["name"] and p[0]["data"]["내용"] == "모델 추가 부탁드립니다" and p[0]["link"] == "#/requests", p)
st, d = pl.req("PUT", f"/api/requests/{rq['id']}", {"status": "완료", "reply": "추가했습니다"})
p = pops(mem)
check("처리하면 보낸 사람에게 팝업 (상태 · 답변)", st == 200 and len(p) == 1 and p[0]["data"]["what"] == "요청 완료" and p[0]["data"]["답변"] == "추가했습니다" and p[0]["data"]["보낸 요청"] == "모델 추가 부탁드립니다", p)

# ── 팝업으로 안 뜨는 것 ──
db.execute("INSERT INTO notifs(user_id,kind,text,link) VALUES(?,?,?,?)", (mem2_u["id"], "미입력", "11/16 시간이 입력되지 않았습니다", "#/me")); db.commit()
check("미입력 알림은 🔔만 (팝업 아님)", pops(mem2) == [] and mem2.req("GET", "/api/notifs")[1]["unread"] >= 1)
st, d = mem.req("POST", "/api/dots/seen", {"tab": "x"}); check("잘못된 탭", st == 400)
st, d = mem.req("POST", "/api/dots/clear", {"type": "x", "id": 1}); check("잘못된 종류", st == 400)
check("버전 0.7.0", urllib.request.urlopen(BASE + "/version").read().decode() == "업무관리 0.7.0")
print(f"0.7.0 시험: 통과 {ok} · 실패 {bad}")
sys.exit(1 if bad else 0)
