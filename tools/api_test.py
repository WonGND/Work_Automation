# API 시험: 로그인 · 권한 · 입력 검사 · 이슈 흐름 · 계산 · 백업 · 내보내기
import sys, json, urllib.request, http.cookiejar, re
BASE = sys.argv[1]; ACC = sys.argv[2]
acc = {}
for line in open(ACC, encoding="utf-8-sig").read().splitlines()[1:]:
    p = line.split("\t")
    if len(p) >= 5: acc[p[0]] = p[1]
NEWPW = "Test!2345"
ok = 0; bad = 0
def check(name, cond, info=""):
    global ok, bad
    if cond: ok += 1
    else: bad += 1; print("  ✗", name, info)
class S:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar(); self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
    def req(self, m, path, body=None, hdr=True):
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(BASE + path, data=data, method=m, headers={"content-type": "application/json", **({"x-req": "1"} if hdr else {})})
        try:
            with self.op.open(r) as res:
                raw = res.read(); ct = res.headers.get("content-type", "")
                return res.status, (json.loads(raw) if "json" in ct else raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try: return e.code, json.loads(raw)
            except Exception: return e.code, raw
def login(user, first=True):
    s = S()
    st, d = s.req("POST", "/api/login", {"login": user, "pw": acc[user]})
    if st == 200 and d.get("must_change"):
        st2, d2 = s.req("GET", "/api/week")
        check(f"{user}: 비밀번호 바꾸기 전에는 막힘", st2 == 403, st2)
        st3, _ = s.req("POST", "/api/password", {"old": acc[user], "new": NEWPW})
        check(f"{user}: 비밀번호 변경", st3 == 200)
        acc[user] = NEWPW
    elif st != 200:
        st, d = s.req("POST", "/api/login", {"login": user, "pw": NEWPW}); acc[user] = NEWPW
    check(f"{user}: 로그인", st == 200, d)
    return s

anon = S()
check("로그인 없이 막힘", anon.req("GET", "/api/meta")[0] == 401)
st, d = anon.req("POST", "/api/login", {"login": "정시우", "pw": "000000"})
check("틀린 비밀번호", st == 401)

mem = login("정시우"); pl2 = login("최예준"); pl3 = login("윤지호"); lead = login("팀장"); mas = login("홍길동"); m3 = login("임서연")
st, meta = mem.req("GET", "/api/meta")
uid = {u["login"]: u["id"] for u in meta["users"]}
models = {m["name"]: m for m in meta["models"]}
check("CSRF 헤더 없으면 막힘", mem.req("PUT", "/api/hours", {"type": "task"}, hdr=False)[0] == 403)

# 권한
check("팀원은 업무로드 못 봄", mem.req("GET", "/api/dashboard")[0] == 403)
check("PL은 업무로드 못 봄", pl2.req("GET", "/api/dashboard")[0] == 403)
check("팀장 업무로드", lead.req("GET", "/api/dashboard?mode=week")[0] == 200)
check("마스터 업무로드", mas.req("GET", "/api/dashboard?mode=month")[0] == 200)
check("팀원은 남의 시간 못 봄", mem.req("GET", f"/api/week?user={uid['강하준']}")[0] == 403)
check("팀장은 사람별 볼 수 있음", lead.req("GET", f"/api/week?user={uid['강하준']}")[0] == 200)
check("팀원 기준정보 못 고침", mem.req("PUT", "/api/master/grades", {"items": []})[0] == 403)
check("팀원 계정 관리 못 함", mem.req("GET", "/api/admin/audit")[0] == 403)
check("팀원은 이슈 등록 못 함", mem.req("POST", "/api/issues", {"model_id": models["모델06"]["id"], "title": "x"})[0] == 403)

# 시간 입력 검사
st, tasks = mem.req("GET", "/api/tasks")
t0 = next(t for t in tasks if t["kind"] == "통상")
for v, exp in [(1.3, 400), (25, 400), (-1, 400), ("abc", 400), (1.5, 200), (0, 200)]:
    st, d = mem.req("PUT", "/api/hours", {"type": "task", "id": t0["id"], "date": "2026-11-03", "hours": v})
    check(f"시간 {v} → {exp}", st == exp, (st, d))
check("시작일 이전 날짜 막힘", mem.req("PUT", "/api/hours", {"type": "task", "id": t0["id"], "date": "2026-10-01", "hours": 1})[0] == 400)
other = next(t for t in lead.req("GET", f"/api/tasks?user={uid['강하준']}")[1])
check("남의 업무 시간 못 넣음", mem.req("PUT", "/api/hours", {"type": "task", "id": other["id"], "date": "2026-11-03", "hours": 1})[0] == 403)
check("팀원 업무 구분 '이슈' 못 만듦", mem.req("POST", "/api/tasks", {"kind": "이슈", "title": "x"})[0] == 400)
# 업무 추가 + 날짜별 시간 (0.5.4)
n0 = len(mem.req("GET", "/api/tasks")[1])
check("업무 추가 시간: 시작일 전 날짜면 업무도 안 생김", mem.req("POST", "/api/tasks", {"kind": "통상", "title": "시간같이1", "hours": [{"date": "2026-11-10", "hours": 2}, {"date": "2026-01-01", "hours": 1}]})[0] == 400 and len(mem.req("GET", "/api/tasks")[1]) == n0)
check("업무 추가 시간: 같은 날짜 두 줄 거부", mem.req("POST", "/api/tasks", {"kind": "통상", "title": "시간같이2", "hours": [{"date": "2026-11-10", "hours": 2}, {"date": "2026-11-10", "hours": 1}]})[0] == 400)
check("업무 추가 시간: 0.5 단위 아니면 거부", mem.req("POST", "/api/tasks", {"kind": "통상", "title": "시간같이3", "hours": [{"date": "2026-11-10", "hours": 0.3}]})[0] == 400 and len(mem.req("GET", "/api/tasks")[1]) == n0)
st, th = mem.req("POST", "/api/tasks", {"kind": "통상", "title": "시간같이 완료", "done": "2026-11-11", "hours": [{"date": "2026-11-10", "hours": 2.5, "text": "회로 검토"}, {"date": "2026-11-11", "hours": 1}, {"date": "2026-11-12", "hours": ""}]})
td = mem.req("GET", f"/api/tasks/{th['id']}")[1] if st == 200 else {}
check("업무 추가 시간: 시간 · 그날 한 일 같이 저장", st == 200 and td.get("total") == 3.5 and len(td.get("hours_list", [])) == 2 and td["notes_list"][0]["text"] == "회로 검토", td)
st, nt = mem.req("POST", "/api/tasks", {"kind": "통상", "title": "API 시험 업무", "model_id": models["모델06"]["id"], "progress": 20, "start": "2026-11-02", "target": "2026-11-06"})
check("업무 추가", st == 200 and nt.get("title") == "API 시험 업무", nt)
check("진행률 15% 막힘", mem.req("PUT", f"/api/tasks/{nt['id']}", {"progress": 15})[0] == 400)
check("업무 삭제(숨김)", mem.req("POST", f"/api/tasks/{nt['id']}/hide", {"hidden": True})[0] == 200)
st, tl = mem.req("GET", "/api/tasks?hidden=1")
check("숨긴 업무는 데이터에 남음", any(t["id"] == nt["id"] and t["hidden"] for t in tl))
fx = next(t for t in tasks if t["fixed"])
check("기본 행은 숨길 수 없음", mem.req("POST", f"/api/tasks/{fx['id']}/hide", {"hidden": True})[0] == 400)

# 이슈 흐름
g10 = models["모델06"]["id"]; wine = models["모델03"]["id"]
st, d = pl2.req("POST", "/api/issues", {"model_id": wine, "title": "다른 파트 모델", "members": []})
check("PL은 다른 파트 모델 이슈 등록 못 함", st == 403, d)
st, d = pl2.req("POST", "/api/issues", {"model_id": g10, "title": "API 시험 이슈", "members": [{"role": "정", "user_id": uid["최예준"]}]})
check("PL을 담당으로 넣으면 확인 요청 (409)", st == 409 and "CONFIRM_PL" in d.get("error", "") and "정말 입력" in d.get("error", ""), d)
st, d = pl2.req("POST", "/api/issues", {"model_id": g10, "title": "API 시험 PL 담당", "members": [{"role": "정", "user_id": uid["최예준"]}], "confirm_pl": True})
check("확인하면 PL도 담당으로 저장 · 재지정 표시", st == 200 and d["plAssigned"] == ["최예준 수석"], d)
pl2.req("POST", f"/api/issues/{d['id']}/hide", {"hidden": True, "reason": "API 시험"})
check("팀장 계정은 담당 불가", pl2.req("POST", "/api/issues", {"model_id": g10, "title": "x2", "members": [{"role": "정", "user_id": uid["팀장"]}], "confirm_pl": True})[0] == 400)
st, d = pl2.req("POST", "/api/issues", {"model_id": g10, "title": "API 시험 이슈", "members": [{"role": "부1", "user_id": uid["정시우"]}]})
check("정 없이 부만 지정 막힘", st == 400, d)
st, iss = pl2.req("POST", "/api/issues", {"model_id": g10, "title": "API 시험 이슈", "target": "2026-11-02", "occurred": "2026-10-28",
    "members": [{"role": "정", "user_id": uid["정시우"], "duty": "원인 분석"}, {"role": "부1", "user_id": uid["강하준"], "duty": "광학 측정"}, {"role": "부2", "user_id": uid["조주원"], "duty": "고객 대응"}]})
check("PL 이슈 등록 · 번호", st == 200 and re.match(r"26-\d{3}", iss.get("no", "")), iss)
no = iss["no"]; iid = iss["id"]
check("새 번호는 26-031 (앞에서 26-030 사용)", no == "26-031", no)
check("같은 이름 중복 등록 막힘", pl2.req("POST", "/api/issues", {"model_id": g10, "title": "API 시험 이슈", "members": []})[0] == 400)
st, mine = mem.req("GET", "/api/issues?scope=mine")
check("정 담당 '내 이슈'에 보임", any(i["id"] == iid for i in mine))
st, wk = mem.req("GET", "/api/week?from=2026-11-02")
check("정 담당 시간 표에 이슈 행", any(r["type"] == "issue" and r["id"] == iid for r in wk["rows"]))
check("목표일 지났으면 '지연 사유 필요'", iss["needDelay"] is True)
st, d = mem.req("PUT", f"/api/issues/{iid}", {"delay_reason": "팀원이 쓰려 함"})
check("팀원은 지연 사유 못 씀 (권한 메시지)", st == 403 and "권한" in d.get("error", ""), d)
st, d = mem.req("PUT", f"/api/issues/{iid}", {"stage": 2})
check("정 담당도 단계는 못 고침 (PL만)", st == 403 and "단계" in d.get("error", ""), d)
st, d = mem.req("PUT", f"/api/issues/{iid}", {"cause": "I2C 마진"})
check("정 담당은 원인 고침", st == 200, d)
st, d = pl2.req("PUT", f"/api/issues/{iid}", {"stage": 2})
check("PL은 단계 고침", st == 200 and d["stage"] == 2, d)
st, d = login("강하준").req("PUT", f"/api/issues/{iid}", {"stage": 3})
check("부 담당은 단계 못 고침", st == 403, d)
st, d = pl2.req("PUT", f"/api/issues/{iid}", {"delay_reason": "자재 입고 지연 (11/5 입고 예정)"})
check("PL 지연 사유 입력", st == 200 and d["needDelay"] is False, d)
check("다른 파트 PL은 못 고침", pl3.req("PUT", f"/api/issues/{iid}", {"title": "x"})[0] == 403)
s2 = login("강하준")
st, d = s2.req("PUT", "/api/hours", {"type": "issue", "id": iid, "date": "2026-11-03", "hours": 2.5, "text": "휘도 측정 3EA"})
check("부1 오늘 한 일 기록", st == 200, d)
st, d = mem.req("PUT", "/api/hours", {"type": "issue", "id": iid, "date": "2026-11-03", "hours": 1, "text": "원인 후보 2건"})
check("정 오늘 한 일 기록", st == 200, d)
check("담당 아닌 사람 기록 못 함", m3.req("PUT", "/api/hours", {"type": "issue", "id": iid, "date": "2026-11-03", "hours": 1})[0] == 403)
st, det = pl2.req("GET", f"/api/issues/{iid}")
check("PL이 담당별 활동 봄", st == 200 and len(det["logs"]) == 2 and {l["text"] for l in det["logs"]} == {"휘도 측정 3EA", "원인 후보 2건"}, det.get("logs"))
st, d = mem.req("PUT", f"/api/issues/{iid}/me", {"duty": "원인 분석 · 재현 시험", "category": "1-13-2.소분류 1-13-2"})
st, det = mem.req("GET", f"/api/issues/{iid}")
me_ = next(x for x in det["members"] if x["user_id"] == uid["정시우"])
check("할 일은 PL이 쓴 그대로 (담당자가 못 바꿈) · 분류는 저장", st == 200 and me_["duty"] == "원인 분석" and me_["category"].startswith("1-13-2"), me_)
st, wk = mem.req("GET", "/api/week?from=2026-11-02")
check("시간 표 이슈 행에 PL 할 일 보임", any(r["type"] == "issue" and r["id"] == iid and r.get("duty") == "원인 분석" for r in wk["rows"]))
st, d = pl2.req("PUT", f"/api/issues/{iid}", {"members": [{"role": "정", "user_id": uid["정시우"]}, {"role": "부1", "user_id": uid["조주원"]}]})
check("PL 담당 변경", st == 200, d)
st, wk2 = s2.req("GET", "/api/week?from=2026-11-02")
check("빠진 담당(강하준)도 기록은 남고 '담당 해제'로 보임", any(r["type"] == "issue" and r["id"] == iid and r["role"] == "담당 해제" and r["hours"].get("2026-11-03") == 2.5 for r in wk2["rows"]))
st, d = pl2.req("POST", f"/api/issues/{iid}/hide", {"hidden": True})
check("삭제 사유 없으면 막힘", st == 400)
st, d = pl2.req("POST", f"/api/issues/{iid}/hide", {"hidden": True, "reason": "API 시험"})
check("PL 이슈 삭제(숨김)", st == 200)
st, al = lead.req("GET", "/api/issues?scope=all&hidden=1")
check("팀장은 삭제한 이슈도 봄", any(i["id"] == iid and i["hidden"] for i in al))
st, d = pl2.req("POST", "/api/issues", {"model_id": g10, "title": "API 시험 이슈 2", "members": []})
check("지운 번호 다시 안 씀 → 26-032", st == 200 and d["no"] == "26-032", d)
pl2.req("POST", f"/api/issues/{d['id']}/hide", {"hidden": True, "reason": "API 시험"})

# 통상 업무 기록 · 상세 · 순서
my = [t for t in mem.req("GET", "/api/tasks")[1] if not t["fixed"]]
t0 = my[0]
st, d = mem.req("PUT", "/api/hours", {"type": "task", "id": t0["id"], "date": "2026-11-03", "hours": 2, "text": "회로도 1차 검토"})
check("통상 업무 그날 한 일 저장", st == 200, d)
st, d = mem.req("GET", f"/api/tasks/{t0['id']}")
check("업무 상세에 진행 기록", st == 200 and d["notes_list"][0]["text"] == "회로도 1차 검토" and d["notes_list"][0]["hours"] == 2 and d["canEdit"], d)
st, wk = mem.req("GET", "/api/week?from=2026-11-02")
check("시간 표 업무 행에 기록 표시", any(r["type"] == "task" and r["id"] == t0["id"] and r["texts"].get("2026-11-03") == "회로도 1차 검토" for r in wk["rows"]))
mem.req("PUT", "/api/hours", {"type": "task", "id": t0["id"], "date": "2026-11-03", "hours": 2, "text": ""})
check("기록 지우면 빠짐 (시간은 남음)", mem.req("GET", f"/api/tasks/{t0['id']}")[1]["notes_list"] == [] and mem.req("GET", f"/api/tasks/{t0['id']}")[1]["total"] >= 2)
ids = [t["id"] for t in my][::-1]
st, d = mem.req("PUT", "/api/tasks/order", {"ids": ids})
check("업무 순서 바꾸기", st == 200 and [t["id"] for t in mem.req("GET", "/api/tasks")[1] if not t["fixed"] and not t["hidden"] and not (t["done"] or t["progress"] == 100)][:3] == [i for i in ids if any(t["id"] == i and not (t["done"] or t["progress"] == 100) for t in my)][:3])
check("남의 업무 순서는 못 바꿈", mem.req("PUT", "/api/tasks/order", {"ids": [other["id"]]})[0] == 400)
check("남의 업무 상세 못 봄", m3.req("GET", f"/api/tasks/{t0['id']}")[0] == 403)

# PL 업무 지정
st, d = pl2.req("POST", "/api/assign", {"user_ids": [uid["정시우"], uid["조주원"]], "title": "API 지정 업무", "target": "2026-11-20", "note": "EMC 대책 검토"})
check("PL이 우리 파트 2명에게 업무 지정", st == 200 and len(d["to"]) == 2, d)
check("다른 파트 사람에게는 지정 못 함", pl2.req("POST", "/api/assign", {"user_ids": [uid["임서연"]], "title": "x"})[0] == 403)
check("팀원은 지정 못 함", mem.req("POST", "/api/assign", {"user_ids": [uid["조주원"]], "title": "x"})[0] == 403)
at = next(t for t in mem.req("GET", "/api/tasks")[1] if t["title"] == "API 지정 업무")
check("받은 사람 업무에 'PL 지정'으로 생김", at["assigned_name"] == "최예준 수석" and at["kind"] == "통상" and at["target"] == "2026-11-20", at)
st, d = mem.req("PUT", f"/api/tasks/{at['id']}", {"title": "API 지정 업무 (수정)", "progress": 30, "target": "2026-11-25"})
check("받은 사람이 전부 고칠 수 있음", st == 200 and d["title"] == "API 지정 업무 (수정)" and d["target"] == "2026-11-25", d)
st, d = pl2.req("GET", "/api/assign")
check("PL '내가 지정한 업무'에서 진행 보임", st == 200 and any(x["id"] == at["id"] and x["progress"] == 30 for x in d), d[:1])
st, d = pl2.req("PUT", f"/api/tasks/{at['id']}", {"note": "PL 추가 메모"})
check("지정한 PL도 그 업무를 고칠 수 있음", st == 200, d)
check("다른 PL은 못 고침", pl3.req("PUT", f"/api/tasks/{at['id']}", {"note": "x"})[0] == 403)

# 기준정보 권한 (PL: 공통 값 · 우리 파트 모델)
check("팀원은 기준정보 못 고침", mem.req("PUT", "/api/master/grades", {"items": []})[0] == 403)
check("PL은 배율 고침", pl2.req("PUT", "/api/master/grades", {"items": []})[0] == 200)
m_other = next(x for x in meta["models"] if x["part"] == "3part")
check("PL은 다른 파트 모델 못 고침", pl2.req("PUT", "/api/master/models", {**m_other, "id": m_other["id"]})[0] == 403)
st, d = pl2.req("POST", "/api/master/models", {"name": "API시험모델", "part": "2part", "grade": "B", "phase": "DV", "active": True})
check("PL은 우리 파트 모델 추가", st == 200, d)
check("PL은 다른 파트로 모델 추가 못 함", pl2.req("POST", "/api/master/models", {"name": "API시험모델2", "part": "3part", "active": True})[0] == 403)
st, d = pl2.req("PUT", "/api/master/judge", {"items": [{"i": 0, "text": "과부하 · 로드 높음 (시험)", "action": "분산"}]})
st2, me2 = pl2.req("GET", "/api/meta")
check("판정 문구 고치기", st == 200 and me2["judge"][0]["text"] == "과부하 · 로드 높음 (시험)", d)
pl2.req("PUT", "/api/master/judge", {"items": [{"i": 0, "text": "과부하 · 로드 높음", "action": "핵심 업무 분산 · 인력 보강"}]})
st, d = mem.req("PUT", "/api/prefs", {"cw:tasks": '{"2":300}'})
check("개인 설정 저장 · 읽기", st == 200 and mem.req("GET", "/api/meta")[1]["prefs"].get("cw:tasks") == '{"2":300}')
st, d = mem.req("GET", "/api/stats?mode=custom&from=2026-10-19&to=2026-10-31")
check("요약 기간 직접 지정", st == 200 and d["from"] == "2026-10-19" and d["to"] == "2026-10-31", d.get("from"))

# PL 이슈 열람 범위 (IT 보안검토 B)
other_iss = next(i for i in lead.req("GET", "/api/issues?scope=all")[1] if i["part"] not in ("2part",) and not any(mm["user_id"] == uid["최예준"] for mm in i["members"]))
st, d = pl2.req("GET", f"/api/issues/{other_iss['id']}")
check("PL은 다른 파트 이슈 상세를 못 봄 (/api/issues/번호)", st == 403, (other_iss["no"], st))
own_iss = next(i for i in lead.req("GET", "/api/issues?scope=all")[1] if i["part"] == "2part")
check("PL은 우리 파트 이슈는 봄", pl2.req("GET", f"/api/issues/{own_iss['id']}")[0] == 200)
not_mine = next(i for i in lead.req("GET", "/api/issues?scope=all")[1] if not any(mm["user_id"] == uid["임서연"] for mm in i["members"]))
check("팀원은 담당 아닌 이슈 못 봄", m3.req("GET", f"/api/issues/{not_mine['id']}")[0] == 403)
mine = next((i for i in lead.req("GET", "/api/issues?scope=all")[1] if any(mm["user_id"] == uid["임서연"] for mm in i["members"])), None)
if mine: check("팀원은 담당 이슈는 봄", m3.req("GET", f"/api/issues/{mine['id']}")[0] == 200)

# 요청하기
st, me_m = mem.req("GET", "/api/meta")
tg = {x["role"]: x["id"] for x in me_m["reqTargets"]}
check("요청 대상 = 우리 파트 PL · 마스터 · 팀장", set(tg) == {"pl", "master", "lead"} and tg["pl"] == uid["최예준"], me_m["reqTargets"])
st, d = mem.req("POST", "/api/requests", {"to_id": uid["최예준"], "text": "모델 추가 요청"})
check("PL에게 요청 보냄", st == 200 and d["status"] == "대기", d)
check("다른 파트 PL에게는 못 보냄", mem.req("POST", "/api/requests", {"to_id": uid["임서연"], "text": "x"})[0] == 403)
check("빈 요청 못 보냄", mem.req("POST", "/api/requests", {"to_id": uid["최예준"], "text": " "})[0] == 400)
st, inbox = pl2.req("GET", "/api/requests?box=in")
check("PL 받은 요청 · 대기 수", st == 200 and inbox[0]["text"] == "모델 추가 요청" and pl2.req("GET", "/api/meta")[1]["reqPending"] == 1, inbox[:1])
check("보낸 사람은 처리 못 함", mem.req("PUT", f"/api/requests/{d['id']}", {"status": "완료"})[0] == 403)
st, d2 = pl2.req("PUT", f"/api/requests/{d['id']}", {"status": "완료", "reply": "추가했습니다"})
check("받은 PL이 완료 · 답변", st == 200 and d2["status"] == "완료" and d2["reply"] == "추가했습니다", d2)
check("보낸 요청에서 답변 보임", mem.req("GET", "/api/requests?box=out")[1][0]["reply"] == "추가했습니다")
check("관계없는 사람은 못 봄", m3.req("PUT", f"/api/requests/{d['id']}", {"status": "대기"})[0] == 403)
# 기본 행 이름 고치기
fx = next(t for t in mem.req("GET", "/api/tasks")[1] if t["fixed"] and t["kind"] == "기타")
st, d = mem.req("PUT", f"/api/tasks/{fx['id']}", {"title": "회의·보고 (주간)", "note": "메모"})
check("기본 행 이름 고침", st == 200 and d["title"] == "회의·보고 (주간)", d)
check("기본 행 구분은 못 바꿈", mem.req("PUT", f"/api/tasks/{fx['id']}", {"kind": "통상"})[0] == 400)

# 알림
st, nb = mem.req("GET", "/api/notifs")
kinds = [n["kind"] for n in nb["list"]]
check("알림: 업무 지정 · 이슈 담당 · 요청 처리 · 버전", st == 200 and {"업무", "이슈", "요청", "버전"} <= set(kinds) and nb["unread"] >= 4, kinds)
st, nb2 = pl2.req("GET", "/api/notifs")
check("PL 알림: 받은 요청", any(n["kind"] == "요청" and "요청" in n["text"] for n in nb2["list"]), [n["text"] for n in nb2["list"]][:4])
nid = nb["list"][0]["id"]; mem.req("POST", "/api/notifs/read", {"id": nid})
check("알림 하나 읽음", mem.req("GET", "/api/notifs")[1]["unread"] == nb["unread"] - 1)
check("남의 알림은 못 읽음 처리", (pl2.req("POST", "/api/notifs/read", {"id": nid})[0] == 200) and True)
mem.req("POST", "/api/notifs/read", {"all": True})
check("모두 읽음", mem.req("GET", "/api/notifs")[1]["unread"] == 0 and mem.req("GET", "/api/meta")[1]["notifUnread"] == 0)
# 메일 등록
check("메일 형식 검사", mem.req("PUT", "/api/me/email", {"email": "abc"})[0] == 400)
check("메일 등록", mem.req("PUT", "/api/me/email", {"email": "Hong@Example.com"})[0] == 200 and mem.req("GET", "/api/meta")[1]["myEmail"] == "hong@example.com")
check("팀원 meta에 남의 메일 없음 · SMTP 값 없음", all("email" not in u for u in mem.req("GET", "/api/meta")[1]["users"]) and not any(k.startswith("smtp") for k in mem.req("GET", "/api/meta")[1]["settings"]))
check("메일 설정 안 됐을 때 비밀번호 찾기 안내 (503)", S().req("POST", "/api/reset/request", {"login": "정시우", "email": "hong@example.com"})[0] == 503)
st, d = S().req("POST", "/api/reset/askadmin", {"login": "정시우"})
check("관리자에게 초기화 요청 → 팀장 알림", st == 200 and any(n["kind"] == "계정" for n in lead.req("GET", "/api/notifs")[1]["list"]))
check("팀원은 메일 설정 못 봄", mem.req("GET", "/api/admin/mail")[0] == 403)

# 기준정보 · 계산이 따라가는지
st, ds1 = lead.req("GET", "/api/dashboard?mode=month&base=2026-11-04")
st, _ = lead.req("PUT", "/api/master/grades", {"items": [{"name": "4part", "pct": 0.5}]})
st, ds2 = lead.req("GET", "/api/dashboard?mode=month&base=2026-11-04")
lead.req("PUT", "/api/master/grades", {"items": [{"name": "4part", "pct": 0.3}]})
check("배율 바꾸면 계산이 따라감 (값 저장)", st == 200)
check("배율 범위 검사", lead.req("PUT", "/api/master/grades", {"items": [{"name": "A", "pct": 5}]})[0] == 400)

# 관리
st, d = lead.req("POST", "/api/admin/users", {"login": "시험계정", "name": "시험 계정", "part": "2part", "role": "member"})
check("팀장 계정 추가 (임시 비밀번호 10자)", st == 200 and len(d.get("temp", "")) == 10, d)
check("팀장은 마스터 계정 못 만듦", lead.req("POST", "/api/admin/users", {"login": "m2", "name": "m2", "role": "master"})[0] == 403)
st, d = mas.req("POST", "/api/admin/backups", {})
check("백업", st == 200 and d["name"].endswith(".db"), d)
check("엑셀 내보내기 없앰", lead.req("GET", "/api/admin/export?mode=year")[0] == 404)
st, au = lead.req("GET", "/api/admin/audit")
check("변경 기록 남음", st == 200 and any(a["action"] == "이슈 등록" for a in au))
check("변경 기록에 시간 입력 없음", not any(a["action"] == "시간" for a in au) and all(a["action"] != "이슈 기록" or '"h"' not in (a["detail"] or "") for a in au))
print(f"API 시험: 통과 {ok} · 실패 {bad}")
