# DB 건수 · 합계 · 이슈 글 지문 (업그레이드 전후 비교용)  사용: python3 -I snap.py <DB> <out.json>
import sqlite3, json, sys, hashlib
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
o = {}
for t in ("users", "tasks", "task_hours", "task_notes", "issues", "issue_members", "issue_logs", "models", "categories", "grades", "holidays", "leaves", "requests", "user_prefs"):
    o["n_" + t] = c.execute(f"select count(*) from {t}").fetchone()[0]
o["sum_task_hours"] = c.execute("select round(sum(hours),2) from task_hours").fetchone()[0]
o["sum_issue_hours"] = c.execute("select round(sum(hours),2) from issue_logs").fetchone()[0]
o["by_user"] = {r[0]: [r[1], r[2]] for r in c.execute("select u.login, (select round(ifnull(sum(h.hours),0),2) from task_hours h join tasks t on t.id=h.task_id where t.user_id=u.id), (select round(ifnull(sum(hours),0),2) from issue_logs where user_id=u.id) from users u")}
def fp(sql): return hashlib.sha1(json.dumps(c.execute(sql).fetchall(), ensure_ascii=False).encode()).hexdigest()[:16]
o["fp_issues"] = fp("select no,model_id,title,source,occurred,target,stage,status_text,delay_reason,note,cause,plan,importance,done,hidden,hidden_reason from issues order by id")
o["fp_members"] = fp("select issue_id,user_id,role,duty,category from issue_members order by issue_id,role")
o["fp_tasks"] = fp("select id,user_id,kind,model_id,title,progress,start,target,done,importance,category,note,fixed,hidden,ord,assigned_by from tasks order by id")
o["fp_hours"] = fp("select task_id,date,hours from task_hours order by task_id,date")
o["fp_logs"] = fp("select issue_id,user_id,date,hours,text from issue_logs order by issue_id,user_id,date")
o["fp_notes"] = fp("select task_id,date,text from task_notes order by task_id,date")
o["fp_models"] = fp("select id,name,part,grade,phase,customer,sop,active,ord from models order by id")
o["fp_users"] = fp("select id,login,name,title,part,role,pw,active,email,joined,left_on from users order by id")
o["fp_settings"] = fp("select key,value from settings where key not in ('last_version','last_backup','daily_backup','miss_daily','miss_week') order by key")
json.dump(o, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print({k: v for k, v in o.items() if k.startswith(("n_", "sum_"))})
