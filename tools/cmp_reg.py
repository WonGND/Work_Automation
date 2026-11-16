import json, sys, urllib.request, http.cookiejar, sqlite3, collections
B, DBP, SEED = sys.argv[1:4]
op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def rq(m,p,b=None):
    r=urllib.request.Request(B+p,data=None if b is None else json.dumps(b,ensure_ascii=False).encode(),method=m,headers={"content-type":"application/json","x-req":"1"})
    return json.loads(op.open(r).read())
rq("POST","/api/login",{"login":"홍길동","pw":"Admin!2345"})
seed=json.load(open(SEED,encoding="utf-8"))
c=sqlite3.connect(f"file:{DBP}?mode=ro",uri=True)
def state():
    web={}
    for no,role,name,duty in c.execute("select i.no,m.role,u.name,m.duty from issue_members m join issues i on i.id=m.issue_id join users u on u.id=m.user_id"): web.setdefault(no,{})[role]=(name,duty or "")
    info={no:(st or "",dl or "",stage,hid) for no,st,dl,stage,hid in c.execute("select no,status_text,delay_reason,stage,hidden from issues")}
    dm=[i["no"] for i in seed["issues"] if {m["role"]:m["name"] for m in i["members"]}!={k:v[0] for k,v in web.get(i["no"],{}).items()}]
    dd=[i["no"] for i in seed["issues"] if {m["role"]:m["duty"] for m in i["members"]}!={k:v[1] for k,v in web.get(i["no"],{}).items()}]
    ds=[i["no"] for i in seed["issues"] if info.get(i["no"],("",))[0]!=i["status_text"]]
    dg=[i["no"] for i in seed["issues"] if info.get(i["no"],(0,0,0))[2]!=int(i["stage"])]
    dl=[i["no"] for i in seed["issues"] if info.get(i["no"],("",""))[1]!=i.get("delay_reason","")]
    return {"담당 다름":len(dm),"맡은 일 다름":dd,"진행현황 다름":len(ds),"단계 다름":dg,"지연 사유 다름":dl,"숨김":[n for n,v in info.items() if v[3]]}
print("가져오기 전:", state())
r=rq("POST","/api/admin/import",{"seed":seed,"from":"2026-10-12","to":"2026-11-13","web_start":"2026-11-16"})
print("결과:", {k:(v if not isinstance(v,list) else len(v)) for k,v in r.items()})
print("가져온 뒤:", state())
ex=collections.defaultdict(float)
for t in seed["tasks"]:
    for d,h in t["hours"].items(): ex[(t["user"],d)]+=h
for i in seed["issues"]:
    for lg in i["logs"]:
        for d,h in lg["hours"].items(): ex[(lg["user"],d)]+=h
wb=collections.defaultdict(float)
for n,d,h in c.execute("select u.name,h.date,h.hours from task_hours h join tasks t on t.id=h.task_id join users u on u.id=t.user_id"): wb[(n,d)]+=h
for n,d,h in c.execute("select u.name,l.date,l.hours from issue_logs l join users u on u.id=l.user_id"): wb[(n,d)]+=h
print("시간 합계 다른 칸:", sum(1 for k in set(ex)|set(wb) if abs(ex.get(k,0)-wb.get(k,0))>1e-9))
