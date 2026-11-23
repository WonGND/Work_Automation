# 0.7.3 화면 확인   사용: python3 ui073.py <주소> <비밀번호> <출력> <마스터>
import sys, asyncio, zipfile
from playwright.async_api import async_playwright
BASE, PW, OUT, MAS = sys.argv[1:5]
errs = []
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        cx = await b.new_context(viewport={"width": 1600, "height": 950}, device_scale_factor=1.25, accept_downloads=True); pg = await cx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE); await pg.fill("input[autocomplete=username]", MAS); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(500)
        while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(400)
        # 1) 등록 창: 뒤 화면 쓰기 · 끌어 옮기기
        await pg.goto(BASE + "/#/registry"); await pg.wait_for_selector("table.issues"); await pg.wait_for_timeout(400)
        await pg.click("text=+ 새 이슈"); await pg.wait_for_selector(".modal-bg.modeless .form-img")
        await pg.locator(".modal-bg.modeless .form input:not([type])").first.fill("작성 중인 내용 유지 확인")
        hd = pg.locator(".modal-bg.modeless .modal .hd"); bb = await hd.bounding_box()
        await pg.mouse.move(bb["x"] + 60, bb["y"] + 15); await pg.mouse.down(); await pg.mouse.move(bb["x"] + 600, bb["y"] + 260, steps=8); await pg.mouse.up()
        nb = await pg.locator(".modal-bg.modeless .modal").bounding_box(); print("등록 창 옮김:", round(nb["x"] - bb["x"]), round(nb["y"] - bb["y"] + 0), "(오른쪽 · 아래)")
        print("창 밖을 누르면 뒤 화면이 받음:", await pg.evaluate("!document.elementFromPoint(200, 600).closest('.modal-bg')"))
        await pg.locator("table.issues tbody tr").first.click(position={"x": 30, "y": 10}); await pg.wait_for_selector(".modal.board"); await pg.wait_for_timeout(400)
        zs = await pg.evaluate("[...document.querySelectorAll('.modal-bg')].map(e => [e.className, +e.style.zIndex])"); print("다른 이슈 열림 (창 순서):", zs)
        await pg.screenshot(path=f"{OUT}/V073_1_등록창_띄운채_다른이슈.png")
        # 2) PPT 내보내기
        await pg.locator(".modal.board button", has_text="PPT 내보내기").click(); await pg.wait_for_selector(".ppt-dlg"); await pg.wait_for_timeout(300)
        print("PPT 창 체크 수:", await pg.locator(".ppt-dlg input[type=checkbox]").count(), "· 기본 전부 체크:", await pg.eval_on_selector_all(".ppt-dlg input[type=checkbox]", "e => e.filter(x => !x.checked).length") == 0)
        await pg.screenshot(path=f"{OUT}/V073_2_PPT내보내기창.png")
        async with pg.expect_download() as dl: await pg.locator(".modal .ft button.pri", has_text="내려받기").click()
        d = await dl.value; path = f"{OUT}/{d.suggested_filename}"; await d.save_as(path)
        z = zipfile.ZipFile(path); print("내려받은 파일:", d.suggested_filename, "· 장 수", sum(1 for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")))
        for _ in range(4):
            if await pg.locator(".modal-bg").count() == 0: break
            c = pg.locator(".modal-bg").last.locator(".ft button", has_text="닫기")
            if await c.count(): await c.dispatch_event("click")
            await pg.wait_for_timeout(250)
            if await pg.locator(".modal .ft button.pri", has_text="확인").count(): await pg.locator(".modal .ft button.pri", has_text="확인").last.dispatch_event("click"); await pg.wait_for_timeout(250)
        # 3) 기준정보 → 이슈 템플릿
        await pg.evaluate("sessionStorage.setItem('mtab','t')"); await pg.goto(BASE + "/#/master"); await pg.wait_for_selector(".tpl-grid"); await pg.wait_for_timeout(300)
        await pg.screenshot(path=f"{OUT}/V073_3_기준정보_이슈템플릿.png", full_page=True)
        card = pg.locator(".tpl-card").nth(1)
        await card.locator("button", has_text="+ 항목 추가").click(); await pg.wait_for_timeout(200)
        await pg.locator(".tpl-card").nth(1).locator("tbody tr").last.locator("input").first.fill("화면 시험 항목")
        await pg.locator(".tpl-card").nth(1).locator("tbody tr").nth(0).locator("button", has_text="지우기").click(); await pg.wait_for_timeout(200)
        await pg.locator("button.btn.pri", has_text="저장").click(); await pg.wait_for_timeout(800)
        tpl = await pg.evaluate("M.issueTpl[1]"); print("저장 후 원인 규명 항목:", [i["code"] + " " + i["label"] for i in tpl["items"]], "· 지운 항목:", [x["label"] for x in tpl["deleted"]])
        await pg.screenshot(path=f"{OUT}/V073_4_템플릿_수정후.png", full_page=True)
        # 4) 업무 추가 창도 뒤 화면 쓰기
        await pg.goto(BASE + "/#/me"); await pg.wait_for_timeout(800)
        btn = pg.locator("button", has_text="업무 추가")
        if await btn.count():
            await btn.first.click(); await pg.wait_for_timeout(400); print("업무 추가 창 뒤 화면 쓰기:", await pg.locator(".modal-bg.modeless").count() == 1)
        await b.close()
asyncio.run(main())
print("화면 오류:", errs)
