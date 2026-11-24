# 0.7.6 화면 확인 (이슈 폴더)   사용: python3 ui076.py <주소> <비밀번호> <출력> <마스터> <팀원>
import sys, asyncio
from playwright.async_api import async_playwright
BASE, PW, OUT, MAS, MEM = sys.argv[1:6]
errs = []
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        async def page():
            ctx = await b.new_context(viewport={"width": 1500, "height": 950}, device_scale_factor=1.25)
            await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
            pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e))); return pg
        async def login(pg, u):
            await pg.goto(BASE); await pg.fill("input[autocomplete=username]", u); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(800)
            while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(300)
        pg = await page(); await login(pg, MAS)
        await pg.evaluate("sessionStorage.setItem('atab','fold')"); await pg.goto(f"{BASE}/#/admin"); await pg.wait_for_selector("text=이슈 폴더 (파일 서버)"); await pg.wait_for_timeout(400)
        print("관리 상태:", (await pg.locator(".card b").filter(has_text="연결").first.inner_text()))
        print("옮길 목록 줄:", await pg.locator("table.tbl tbody tr").count())
        await pg.screenshot(path=f"{OUT}/V076_1_관리_이슈폴더.png", full_page=True)
        await pg.locator("button", has_text="연결 시험").click(); await pg.wait_for_timeout(500); print("연결 시험 알림:", await pg.locator("#toast").inner_text())
        await pg.goto(f"{BASE}/#/registry"); await pg.wait_for_selector("td.no-lnk"); await pg.wait_for_timeout(400)
        print("이슈 정리 번호 링크:", await pg.locator("td.no-lnk").count())
        await pg.locator("td.no-lnk").nth(4).click(); await pg.wait_for_selector(".fold-pop"); await pg.wait_for_timeout(500)
        print("복사된 경로:", await pg.evaluate("navigator.clipboard.readText()"))
        print("팝업 행 열림 안 함:", await pg.locator(".modal").count())
        await pg.screenshot(path=f"{OUT}/V076_2_번호클릭.png")
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200)
        pm = await page(); await login(pm, MEM)
        await pm.goto(f"{BASE}/#/myissues"); await pm.wait_for_timeout(1000)
        n = await pm.locator(".no-lnk").count(); print("팀원 내 이슈 번호 링크:", n)
        if n:
            await pm.locator(".no-lnk").first.click(); await pm.wait_for_selector(".fold-pop"); print("팀원 복사:", await pm.evaluate("navigator.clipboard.readText()"))
            print("카드 펼쳐지지 않음:", await pm.locator(".issue.open, .icard.open").count() == 0)
            await pm.screenshot(path=f"{OUT}/V076_3_내이슈.png")
        await b.close()
    print("화면 오류:", errs or "없음")
asyncio.run(main())
