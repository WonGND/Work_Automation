# 팀장 파일(.xlsm) + (선택) 정리된 개인 파일들 → 웹 seed.json
# 사용: python3 -I extract_seed.py <팀장.xlsm> <out.json> --parts 2part,3part [--override 이름=개인파일.xlsx ...]
import sys, json, datetime as dt, argparse, openpyxl

ap = argparse.ArgumentParser()
ap.add_argument("team"); ap.add_argument("out")
ap.add_argument("--parts", default="2part,3part")
ap.add_argument("--override", nargs="*", default=[])
a = ap.parse_args()
PARTS = a.parts.split(",")
wb = openpyxl.load_workbook(a.team, data_only=True)
m = wb["기준정보"]
T0 = dt.date(2026, 10, 12)  # 날짜 칸 시작 (AI열 = 35)
TL0, NTL = 35, 371

def d(v):
    if isinstance(v, dt.datetime): return v.date().isoformat()
    if isinstance(v, dt.date): return v.isoformat()
    return None
def s(v):
    if v is None: return ""
    if isinstance(v, str) and v.startswith("#"): return ""
    return str(v).strip()
def num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

seed = {"master": __import__("os").environ.get("WL_MASTER", ""), "source": a.team.split("/")[-1], "extracted": dt.datetime.now().isoformat(timespec="seconds"), "warnings": []}
W = seed["warnings"]
seed["grades"] = [{"name": s(m.cell(r, 2).value), "pct": num(m.cell(r, 3).value)} for r in range(6, 14) if s(m.cell(r, 2).value)]
seed["settings"] = {
    "other_pct": num(m["C14"].value) or 0, "hstart": d(m["H42"].value), "day_hours": num(m["H43"].value) or 8,
    "early_hours": num(m["H44"].value) or 2, "unit": num(m["H45"].value) or 0.5, "over": num(m["H46"].value) or 1.2,
    "fit": num(m["H47"].value) or 1, "lhi": num(m["H49"].value) or 0.7, "llo": num(m["H50"].value) or 0.35,
    "soon_days": int(num(m["C38"].value) or 7), "done_keep_days": 30,
}
seed["stages"] = [{"name": s(m.cell(r, 2).value), "pct": num(m.cell(r, 3).value)} for r in range(28, 34)]
seed["phases"] = [s(m.cell(r, 2).value) for r in range(45, 55) if s(m.cell(r, 2).value)]
seed["judge"] = [{"rate": s(m.cell(r, 5).value), "load": s(m.cell(r, 6).value), "text": s(m.cell(r, 7).value), "action": s(m.cell(r, 9).value)} for r in range(55, 62)]
seed["holidays"] = [{"date": d(m.cell(r, 2).value), "name": s(m.cell(r, 3).value)} for r in range(59, 109) if d(m.cell(r, 2).value)]
seed["parts"] = [{"name": s(m.cell(r, 2).value), "pl": s(m.cell(r, 3).value)} for r in range(19, 24) if s(m.cell(r, 2).value)]
seed["models"] = []
for r in range(6, 36):
    nm = s(m.cell(r, 16).value)
    if nm:
        seed["models"].append({"part": s(m.cell(r, 15).value), "name": nm, "grade": s(m.cell(r, 19).value),
                               "phase": s(m.cell(r, 20).value), "customer": s(m.cell(r, 18).value),
                               "sop": d(m.cell(r, 21).value), "active": s(m.cell(r, 24).value) != "N"})
cats = []
for r in range(6, 200):
    v = s(m.cell(r, 31).value)
    if v and not v.startswith("※"): cats.append({"big": s(m.cell(r, 29).value), "mid": s(m.cell(r, 30).value), "name": v})
seed["categories"] = cats
seed["leaves"] = [{"name": s(m.cell(r, 6).value), "start": d(m.cell(r, 7).value), "end": d(m.cell(r, 8).value)} for r in range(67, 97) if s(m.cell(r, 6).value)]

pl_of = {p["pl"]: p["name"] for p in seed["parts"] if p["pl"]}
people = []
for r in range(6, 36):
    nm = s(m.cell(r, 6).value)
    if nm and s(m.cell(r, 7).value) in PARTS and s(m.cell(r, 9).value) != "N":
        people.append({"name": nm, "part": s(m.cell(r, 7).value), "title": s(m.cell(r, 8).value).replace("_PL", ""),
                       "role": "pl" if pl_of.get(nm) else "member"})
seed["people"] = people
names = {p["name"] for p in people}

# 이슈 정리
reg = wb["이슈 정리"]
regs = {}
for r in range(7, 107):
    no = s(reg.cell(r, 36).value)
    if not no: continue
    regs[no] = {"no": no, "model": s(reg.cell(r, 3).value), "source": s(reg.cell(r, 4).value), "title": s(reg.cell(r, 6).value),
                "lead": s(reg.cell(r, 7).value), "subs": [x.strip() for x in s(reg.cell(r, 8).value).split(",") if x.strip()],
                "target": d(reg.cell(r, 9).value), "status_text": s(reg.cell(r, 10).value), "note": s(reg.cell(r, 13).value),
                "done": d(reg.cell(r, 32).value)}
mx = s(reg["AJ2"].value)
seed["issue_seq"] = mx.replace("최대", "").strip() if mx else ""

over = dict(x.split("=", 1) for x in a.override)
tasks, issue_rows = [], []
for p in people:
    nm = p["name"]
    if nm in over:
        ws = openpyxl.load_workbook(over[nm], data_only=True)[nm]
    else:
        ws = wb[nm]
    for r in range(12, 312):
        kind = s(ws.cell(r, 2).value); title = s(ws.cell(r, 4).value)
        hours = {}
        for c in range(TL0, TL0 + NTL):
            v = ws.cell(r, c).value
            if isinstance(v, (int, float)) and v:
                hours[(T0 + dt.timedelta(days=c - TL0)).isoformat()] = float(v)
            elif isinstance(v, str) and v.strip():
                W.append(f"{nm} {r}행 {openpyxl.utils.get_column_letter(c)} 날짜 칸 글자 '{v[:10]}' 건너뜀")
        if not kind and not title:
            if hours: W.append(f"{nm} {r}행: 구분 · 업무명 없이 시간 {sum(hours.values())}h → 건너뜀")
            continue
        if kind not in ("통상", "이슈", "기타", "휴가", "조퇴"):
            W.append(f"{nm} {r}행: 구분 '{kind}' 알 수 없음 → 건너뜀 ({title[:20]})"); continue
        if not title:
            if kind in ("휴가", "조퇴"):
                title = "연차·반차" if kind == "휴가" else "조퇴"
                if hours: W.append(f"{nm} {r}행: {kind} 행 업무명이 비어 '{title}'로 넣음 (엑셀에서는 집계 빠짐)")
            else:
                W.append(f"{nm} {r}행: 업무명 없음 → 건너뜀 (시간 {sum(hours.values())}h)"); continue
        model = s(ws.cell(r, 3).value)
        if model == "공통(팀 업무)": model = ""
        row = {"user": nm, "row": r, "kind": kind, "model": model, "title": title, "start": d(ws.cell(r, 7).value),
               "target": d(ws.cell(r, 8).value), "revised": d(ws.cell(r, 9).value), "done": d(ws.cell(r, 10).value),
               "importance": s(ws.cell(r, 13).value), "category": s(ws.cell(r, 14).value),
               "cause": s(ws.cell(r, 15).value), "plan": s(ws.cell(r, 16).value), "note": s(ws.cell(r, 17).value), "hours": hours}
        e = ws.cell(r, 5).value
        if kind == "이슈":
            row["no"] = s(ws.cell(r, 31).value).split("|")[0].replace("해제", "").strip()
            row["released"] = "해제" in s(ws.cell(r, 31).value)
            row["stage"] = next((i + 1 for i, st in enumerate(seed["stages"]) if st["name"] and st["name"] == s(e)), None)
            issue_rows.append(row)
        else:
            row["progress"] = round(num(e) * 100) if num(e) is not None else None
            tasks.append(row)
seed["tasks"] = tasks

# 이슈 = 8명 중 누가 담당하거나 (정/부/개인 시트 행) 우리 파트 모델인 이슈
mpart = {x["name"]: x["part"] for x in seed["models"]}
issues = {}
for no, g in regs.items():
    if g["lead"] in names or any(x in names for x in g["subs"]) or mpart.get(g["model"]) in PARTS or any(ir["no"] == no for ir in issue_rows):
        issues[no] = dict(g)
for ir in issue_rows:
    no = ir["no"]
    if not no:
        W.append(f"{ir['user']} {ir['row']}행 이슈 '{ir['title'][:20]}' 번호 없음 → 새 번호로 등록")
        no = "NEW-" + str(len(issues) + 1)
        issues[no] = {"no": no, "model": ir["model"], "source": "", "title": ir["title"], "lead": ir["user"], "subs": [], "target": ir["target"], "status_text": "", "note": "", "done": ir["done"]}
    g = issues.setdefault(no, {"no": no, "model": ir["model"], "source": "", "title": ir["title"], "lead": ir["user"], "subs": [], "target": ir["target"], "status_text": "", "note": "", "done": ir["done"]})
    g.setdefault("rows", []).append(ir)
out = []
for no, g in sorted(issues.items()):
    rows = g.get("rows", [])
    lead_row = next((x for x in rows if x["user"] == g["lead"]), rows[0] if rows else None)
    subs = g["subs"]
    if len(subs) > 2: W.append(f"{no}: 부 담당 {len(subs)}명 → 부1 · 부2만 넣고 나머지 {', '.join(subs[2:])} 는 비고에 적음")
    members = [{"name": g["lead"], "role": "정"}] if g["lead"] else []
    members += [{"name": n, "role": f"부{i + 1}"} for i, n in enumerate(subs[:2])]
    for x in members:
        if x["name"] in pl_of: W.append(f"{no}: PL {x['name']} 이 {x['role']} 담당으로 되어 있음 (새 규칙: PL은 담당 불가) → 그대로 가져옴 · 재지정 필요")
    mrow = {x["user"]: x for x in rows}
    for x in members:
        rr = mrow.get(x["name"])
        x["category"] = rr["category"] if rr else ""
        # 맡은 일: 부 담당 비고 중 v1.7.7 정→부 맞추기 흔적('[이전 …]')은 빼고 가져옴
        x["duty"] = rr["note"] if rr and x["role"] != "정" and "[이전" not in rr["note"] else ""
    for rr in rows:
        if rr["user"] not in [x["name"] for x in members]:
            W.append(f"{no}: {rr['user']} 개인 시트에 이슈 행이 있지만 담당자 목록에 없음 → 시간만 가져옴")
    gm = g["model"] if g["model"] in mpart else ""   # 이슈 정리 모델 칸이 '(개인 시트에 없음)' 등이면 담당자 행 모델
    out.append({"no": no, "model": gm or (lead_row["model"] if lead_row else ""), "title": g["title"] or (lead_row["title"] if lead_row else ""),
                "source": g["source"], "occurred": lead_row["start"] if lead_row else None, "target": g["target"] or (lead_row and (lead_row["revised"] or lead_row["target"])),
                "stage": (lead_row or {}).get("stage") or 1, "status_text": g["status_text"], "note": g["note"] + (" / 부: " + ", ".join(subs[2:]) if len(subs) > 2 else ""),
                "cause": (lead_row or {}).get("cause", ""), "plan": (lead_row or {}).get("plan", ""),
                "done": g["done"] or (lead_row or {}).get("done"), "importance": (lead_row or {}).get("importance", ""),
                "members": members, "logs": [{"user": rr["user"], "hours": rr["hours"]} for rr in rows]})
seed["issues"] = out
json.dump(seed, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("people", len(people), "tasks", len(tasks), "issues", len(out), "warnings", len(W))
for w in W: print(" -", w)
