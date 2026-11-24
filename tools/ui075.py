# 0.7.5 화면 확인   사용: python3 ui075.py <주소> <비밀번호> <출력> <마스터> <팀원> <팀원 id>
import sys, asyncio
from playwright.async_api import async_playwright
BASE, PW, OUT, MAS, MEM, MID = sys.argv[1:7]
errs = []
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        async def page():
            pg = await (await b.new_context(viewport={"width": 1500, "height": 950}, device_scale_factor=1.25)).new_page(); pg.on("pageerror", lambda e: errs.append(str(e))); return pg
        async def login(pg, u, keep_pop=False):
            await pg.goto(BASE); await pg.fill("input[autocomplete=username]", u); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(900)
            if keep_pop: return
            while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(300)
        async def prev(pg): await pg.locator(".week").locator("xpath=..").locator("button", has_text="◀ 이전 주").last.click(); await pg.wait_for_timeout(700)
        # ── 마스터: 사람별 → 날짜 · 하루 합계 · 주간 한 일 ──
        pg = await page(); await login(pg, MAS)
        await pg.goto(f"{BASE}/#/people/{MID}"); await pg.wait_for_selector(".week table"); await prev(pg)
        print("주황 ✎ (사람별):", await pg.locator(".week .note-btn.miss").count())
        await pg.locator(".week thead th.day-lnk").nth(1).click(); await pg.wait_for_selector(".log-pop"); await pg.wait_for_timeout(300)
        print("날짜 팝업 제목:", await pg.locator(".modal > .hd").last.inner_text(), "· 줄", await pg.locator(".log-pop .lg4 > div").count() // 4 - 1)
        hdh = await pg.eval_on_selector_all(".log-pop .lg > .lh", "e => e.map(x => x.getBoundingClientRect().height)"); print("머리글 한 줄 (높이):", [round(x) for x in hdh])
        await pg.screenshot(path=f"{OUT}/V075_1_날짜팝업.png")
        await pg.keyboard.press("ArrowRight"); await pg.wait_for_timeout(200); print("→ 다음 날:", await pg.locator(".modal > .hd").last.inner_text())
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200); print("Esc 로 닫힘:", await pg.locator(".log-pop").count() == 0)
        await pg.locator(".week thead tr.sum td.day-lnk").nth(2).click(); await pg.wait_for_timeout(300); print("하루 합계 클릭 → 팝업:", await pg.locator(".log-pop").count() == 1); await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200)
        await pg.locator("button.wk-log").click(); await pg.wait_for_selector(".log-pop .lg3"); await pg.wait_for_timeout(300)
        print("주간 팝업:", await pg.locator(".modal > .hd").last.inner_text(), "· 업무/이슈", await pg.locator(".log-pop .lg3 > .lgp").count() // 3)
        await pg.screenshot(path=f"{OUT}/V075_2_주간한일.png")
        await pg.locator(".modal .seg button", has_text="이슈").click(); await pg.wait_for_timeout(200); print("이슈만:", await pg.locator(".log-pop .lg3 > .lgp").count() // 3)
        await pg.screenshot(path=f"{OUT}/V075_3_주간한일_이슈만.png")
        await pg.keyboard.press("ArrowLeft"); await pg.wait_for_timeout(600); print("← 이전 주:", await pg.locator(".modal > .hd").last.inner_text())
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200)
        # 월간
        await pg.locator(".wk-mode button", has_text="월간").click(); await pg.wait_for_timeout(800)
        print("월간 버튼:", await pg.locator("button.wk-log").inner_text()); await pg.locator(".wk-mode button", has_text="주간").click(); await pg.wait_for_timeout(600)
        # Esc: 이슈 창 (안 고치면 바로), 업무 추가 창 (쓴 내용 → 확인)
        await pg.goto(f"{BASE}/#/registry"); await pg.wait_for_selector("table.issues"); await pg.locator("table.issues tbody tr").first.click(); await pg.wait_for_selector(".iboard"); await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
        print("이슈 창 Esc (변경 없음) → 닫힘:", await pg.locator(".iboard").count() == 0)
        await pg.locator("table.issues tbody tr").first.click(); await pg.wait_for_selector(".iboard"); await pg.locator(".iitem textarea").first.fill("Esc 시험"); await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
        print("이슈 창 Esc (고침) → 확인 창:", await pg.locator(".modal .hd", has_text="확인").count() >= 1 or await pg.locator(".modal").count() >= 2)
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200); print("확인 창 Esc → 이슈 창 남음:", await pg.locator(".iboard").count() == 1)
        # ── 팀원: 한 줄 입력 · 주황 · Esc ──
        async def empty_cell(pm, tag):
            ok = await pm.evaluate("""t => { const a=[...document.querySelectorAll('.week tbody.gbody tr[data-id] input.h:not([disabled])')].filter(i=>!i.value && i.closest('td').querySelector('.note-btn:not(.has)')); if(!a.length) return false; a[Math.floor(a.length/2)].setAttribute('data-t', t); return true; }""", tag)
            return pm.locator(f'input[data-t="{tag}"]')
        pm = await page(); await login(pm, MEM)
        await pm.goto(f"{BASE}/#/pw"); await pm.wait_for_timeout(500); await pm.locator("label.chk", has_text="한 일 한 줄").locator("input").check(); await pm.wait_for_timeout(400)
        await pm.goto(f"{BASE}/#/me"); await pm.wait_for_selector(".week table"); await prev(pm)
        miss0 = await pm.locator(".week .note-btn.miss").count()
        # 빈 칸 하나에 시간 넣고 Enter
        cell = await empty_cell(pm, "c1")
        await cell.click(); await cell.fill("1.5"); await pm.keyboard.press("Enter"); await pm.wait_for_selector(".note-inl", timeout=4000)
        print("시간 넣고 Enter → 한 줄 칸:", await pm.locator(".note-inl").count() == 1, "· 포커스:", await pm.evaluate("document.activeElement.closest('.note-inl') != null"))
        print("주황 ✎ 늘어남:", await pm.locator(".week .note-btn.miss").count(), "(전", miss0, ")")
        await pm.screenshot(path=f"{OUT}/V075_4_한줄입력.png")
        await pm.keyboard.type("한 줄 입력 시험 — 측정 2EA"); await pm.keyboard.press("Enter"); await pm.wait_for_timeout(600)
        print("Enter 저장 → 칸 닫힘:", await pm.locator(".note-inl").count() == 0, "· 주황 줄어듦:", await pm.locator(".week .note-btn.miss").count(), "· 다음 칸 포커스:", await pm.evaluate("document.activeElement.matches('.week input.h')"))
        cell2 = await empty_cell(pm, "c2")
        await cell2.click(); await cell2.fill("2"); await pm.keyboard.press("Enter"); await pm.wait_for_selector(".note-inl"); await pm.keyboard.press("Escape"); await pm.wait_for_timeout(300)
        print("Esc 건너뛰기 → 칸 닫힘:", await pm.locator(".note-inl").count() == 0, "· 주황 그대로:", await pm.locator(".week .note-btn.miss").count())
        await pm.screenshot(path=f"{OUT}/V075_5_주황표시.png")
        # 업무 추가 창 Esc
        await pm.locator("button", has_text="+ 업무 추가").first.click(); await pm.wait_for_timeout(400); await pm.keyboard.press("Escape"); await pm.wait_for_timeout(300); print("업무 추가 (빈) Esc → 닫힘:", await pm.locator(".modal").count() == 0)
        await pm.locator("button", has_text="+ 업무 추가").first.click(); await pm.wait_for_timeout(400)
        await pm.locator(".modal input:not([type]):not(.ssel-in)").first.fill("Esc 시험 업무"); await pm.keyboard.press("Escape"); await pm.wait_for_timeout(300)
        print("업무 추가 (쓴 내용) Esc → 확인:", await pm.locator(".modal .bd", has_text="저장하지 않고 닫을까요").count() == 1)
        await pm.screenshot(path=f"{OUT}/V075_6_Esc확인.png")
        await pm.locator(".modal .ft button.pri", has_text="확인").last.click(); await pm.wait_for_timeout(300); print("확인 → 둘 다 닫힘:", await pm.locator(".modal").count() == 0)
        # ✎ 창 안내 · 내 정보 끄기
        await pm.locator(".week .note-btn.has").first.click(); await pm.wait_for_timeout(300); print("✎ 창 안내:", await pm.locator(".modal", has_text="팀장 · PL이 사람별 화면에서").count() == 1); await pm.keyboard.press("Escape"); await pm.wait_for_timeout(200)
        await pm.goto(f"{BASE}/#/pw"); await pm.wait_for_timeout(500)
        ck = pm.locator("label.chk", has_text="한 일 한 줄").locator("input"); print("내 정보 설정 칸:", await ck.count()); await ck.uncheck(); await pm.wait_for_timeout(400)
        await pm.goto(f"{BASE}/#/me"); await pm.wait_for_selector(".week table"); await prev(pm)
        c3 = await empty_cell(pm, "c3"); await c3.click(); await c3.fill("0.5"); await pm.keyboard.press("Enter"); await pm.wait_for_timeout(800)
        print("끄면 한 줄 칸 안 뜸:", await pm.locator(".note-inl").count() == 0)
        # ── 공지 팝업: 접속하자마자 · Esc 로 안 닫힘 ──
        await pg.close(); pg = await page(); await login(pg, MAS)
        await pg.goto(f"{BASE}/#/notices"); await pg.wait_for_timeout(500)
        await pg.locator("button", has_text="+ 공지 쓰기").click(); await pg.wait_for_timeout(300)
        await pg.locator(".modal input").first.fill("0.7.5 시험 공지"); await pg.locator(".modal textarea").first.fill("접속하면 바로 뜨는지 확인")
        await pg.locator(".modal .ft button.pri").click(); await pg.wait_for_timeout(600)
        pn = await page(); await login(pn, MEM, keep_pop=True)
        print("다시 접속 → 공지 팝업 바로:", await pn.locator(".modal.pop", has_text="0.7.5 시험 공지").count() == 1)
        await pn.keyboard.press("Escape"); await pn.wait_for_timeout(300); print("공지 팝업은 Esc 로 안 닫힘:", await pn.locator(".modal.pop").count() >= 1)
        await b.close()
asyncio.run(main())
print("화면 오류:", errs)
