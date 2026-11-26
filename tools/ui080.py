# 0.8.0 화면 확인   사용: python3 ui080.py <주소> <비밀번호> <출력> <팀원>
import sys, asyncio, json
from playwright.async_api import async_playwright
BASE, PW, OUT, MEM = sys.argv[1:5]
errs = []
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1500, "height": 950}, device_scale_factor=1.25)
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE); await pg.fill("input[autocomplete=username]", MEM); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(900)
        while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(300)
        await pg.goto(f"{BASE}/#/me"); await pg.wait_for_selector(".week tbody tr[data-id]"); await pg.wait_for_timeout(500)
        titles = await pg.evaluate("[...document.querySelectorAll('.week tbody tr[data-id] td:first-child')].map(td=>td.innerText.split('\\n')[0]).slice(0,8)")
        print("행 앞부분:", titles)
        # 외근 칸 (오늘 열) 에 8 → 나누기 칸
        row = pg.locator(".week tbody tr[data-id]", has_text="외근").first
        cells = row.locator("input.h:not([disabled])")
        print("외근 줄:", await row.count(), "· 입력 칸:", await cells.count())
        c = cells.nth(0); await c.click(); await c.fill("8"); await pg.keyboard.press("Tab"); await pg.wait_for_selector(".spl-inl"); await pg.wait_for_timeout(300)
        await pg.screenshot(path=f"{OUT}/V080_1_외근나누기_열림.png")
        m0 = pg.locator(".spl-inl .spl-row:not(.spl-lh)").nth(0)
        await m0.locator(".ssel-in").click(); await pg.wait_for_timeout(100); await pg.keyboard.type("G10", delay=60); await pg.keyboard.press("Enter"); await pg.wait_for_timeout(200)
        await m0.locator(".spl-h").fill("5"); await m0.locator(".spl-t").fill("서천공장 Event 대응")
        await pg.locator(".spl-inl button", has_text="모델 추가").click(); await pg.wait_for_timeout(200)
        m1 = pg.locator(".spl-inl .spl-row:not(.spl-lh)").nth(1)
        await m1.locator(".ssel-in").click(); await pg.wait_for_timeout(100); await pg.keyboard.type("MG10", delay=60); await pg.keyboard.press("Enter"); await pg.wait_for_timeout(200)
        print("두 번째 줄 시간(남은 시간 자동):", await m1.locator(".spl-h").input_value())
        await m1.locator(".spl-t").fill("고객사 샘플 확인")
        await pg.screenshot(path=f"{OUT}/V080_2_외근나누기_입력.png")
        await m1.locator(".spl-t").press("Enter"); await pg.wait_for_timeout(700)
        print("나누기 칸 닫힘:", await pg.locator(".spl-inl").count() == 0, "· 알림:", await pg.locator("#toast").inner_text())
        # 다중 모델 업무 추가
        await pg.locator("button", has_text="업무 추가").first.click(); await pg.wait_for_selector(".modal .mm")
        mm = pg.locator(".modal .mm")
        for nm in ("G10", "GX10"):
            await mm.locator(".ssel-in").last.click(); await pg.keyboard.type(nm); await pg.keyboard.press("Enter"); await pg.wait_for_timeout(200)
        print("고른 모델 칩:", await pg.locator(".modal .mm-chip").all_inner_texts())
        await pg.locator(".modal .form input:not(.ssel-in)").first.fill("UI 다중 모델 시험")
        await pg.screenshot(path=f"{OUT}/V080_3_다중모델_업무추가.png")
        await pg.locator(".modal .ft button.pri").click(); await pg.wait_for_timeout(900)
        row2 = pg.locator(".week tbody tr[data-id]", has_text="UI 다중 모델 시험").first
        print("행 모델 표시:", (await row2.locator("td").first.inner_text()).replace("\n", " ")[:60])
        c2 = row2.locator("input.h:not([disabled])").nth(0); await c2.click(); await c2.fill("3"); await pg.keyboard.press("Tab"); await pg.wait_for_selector(".spl-inl"); await pg.wait_for_timeout(200)
        print("기본 나눔:", await pg.locator(".spl-inl .spl-h").evaluate_all("e=>e.map(x=>x.value)"))
        await pg.keyboard.press("Enter"); await pg.wait_for_timeout(700)
        print("다중 모델 저장:", await pg.locator(".spl-inl").count() == 0)
        # 주간 한 일 보기 (새 디자인)
        await pg.locator("button.wk-log").click(); await pg.wait_for_selector(".wl-sum"); await pg.wait_for_timeout(400)
        print("구역:", await pg.locator(".wl-st b").all_inner_texts(), "· 요약:", (await pg.locator(".wl-sum").inner_text()).replace("\n", " "))
        await pg.screenshot(path=f"{OUT}/V080_4_주간한일.png")
        # 창 크기 조절 (주간 한 일 창)
        md = pg.locator(".modal.rsz").last
        print("크기 조절 가능:", await md.evaluate("e => getComputedStyle(e).resize"))
        await md.evaluate("e => { e.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true})); e.style.width='900px'; e.style.height='600px'; document.dispatchEvent(new PointerEvent('pointerup', {bubbles:true})); }")
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
        await pg.locator("button.wk-log").click(); await pg.wait_for_selector(".wl-sum"); await pg.wait_for_timeout(300)
        print("다시 열면 크기 기억:", await pg.locator(".modal.rsz").last.evaluate("e => e.style.width + ' x ' + e.style.height"))
        await pg.locator(".modal.rsz .hd").last.dblclick(); await pg.wait_for_timeout(200)
        print("제목 더블클릭 → 원래 크기:", repr(await pg.locator(".modal.rsz").last.evaluate("e => e.style.width")))
        await pg.keyboard.press("Escape")
        # 요청 복사
        await pg.goto(f"{BASE}/#/requests"); await pg.wait_for_timeout(800)
        n = await pg.locator(".req-txt .btn").count(); print("요청 복사 버튼:", n)
        if n:
            await pg.locator(".req-txt .btn").first.click(); await pg.wait_for_timeout(300)
            txt = await pg.evaluate("navigator.clipboard.readText()"); first = await pg.locator(".req-txt .pre").first.inner_text()
            print("복사 = 내용만:", txt == first)
        await b.close()
    print("화면 오류:", errs or "없음")
asyncio.run(main())
