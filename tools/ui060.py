# 0.6.0 화면 확인 (Playwright)  사용: python3 ui060.py <주소> <아이디> <비밀번호> <출력 폴더>
import sys, asyncio, json
from playwright.async_api import async_playwright
BASE, USER, PW, OUT = sys.argv[1:5]
errs = []
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 950})
        pg.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
        await pg.goto(BASE); await pg.fill("input[autocomplete=username]", USER); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a")
        shot = lambda n, **k: pg.screenshot(path=f"{OUT}/{n}.png", **k)
        async def theme(t, dark):
            await pg.evaluate("t => { const s = document.getElementById('selTheme'); s.value = t; s.dispatchEvent(new Event('change')); }", t)
            if (await pg.evaluate("document.documentElement.dataset.dark === '1'")) != dark: await pg.evaluate("document.getElementById('btnDark').click()")
            await pg.wait_for_timeout(200)
        await theme("b", False)
        # 이슈 정리
        await pg.goto(BASE + "/#/registry"); await pg.wait_for_selector("table.issues tbody tr"); await pg.wait_for_timeout(300); await shot("01_registry")
        heads = await pg.eval_on_selector_all("table.issues thead th", "e => e.map(x => [x.textContent, getComputedStyle(x).textAlign])")
        print("이슈 정리 머리글:", heads)
        # 진행 현황이 있는 이슈 열기
        row = pg.locator("table.issues tbody tr", has=pg.locator("td.status .badge")).first
        await row.click(); await pg.wait_for_selector(".iboard"); await pg.wait_for_timeout(300); await shot("02_board_B")
        # 이미지: 화면 캡처를 붙여넣기(Ctrl+V와 같은 paste 이벤트)로 올림
        png = await pg.screenshot(clip={"x": 0, "y": 0, "width": 900, "height": 520})
        import base64; b64 = base64.b64encode(png).decode()
        await pg.evaluate("""async b64 => { const bin = atob(b64); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
            const dt = new DataTransfer(); dt.items.add(new File([u], 'shot.png', { type: 'image/png' }));
            document.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }""", b64)
        await pg.wait_for_selector(".iimg-th"); await pg.wait_for_timeout(500); print("붙여넣기 → 이미지 올라감")
        await shot("03_board_B_img")
        # 끌어다 놓기로 바꾸기 (확인 창 → 확인)
        await pg.evaluate("""async b64 => { const bin = atob(b64); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
            const dt = new DataTransfer(); dt.items.add(new File([u], 'drop.png', { type: 'image/png' }));
            document.querySelector('.modal.wide').dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); }""", b64)
        await pg.wait_for_selector(".modal-bg >> text=이미 있는 이미지를"); await pg.locator(".modal-bg").last.locator("button.pri").click(); await pg.wait_for_timeout(600); print("끌어다 놓기 → 바꾸기 확인 창 → 바뀜")
        # 4칸 쓰기 · 저장
        ta = pg.locator(".ibox.b4 textarea"); await ta.fill("DV 샘플 20EA 재검증 예정 (11/24)\n- 리셋 IC 변경품 적용")
        for t, d in (("a", False), ("c", False), ("b", True), ("a", True), ("c", True)):
            await theme(t, d); await shot(f"04_board_{t.upper()}{'_dark' if d else ''}")
        await theme("b", False)
        await pg.locator(".modal.wide .ft button.pri").click(); await pg.wait_for_selector(".iboard", state="detached"); await pg.wait_for_timeout(500)
        await shot("05_registry_after")
        # 🖼 버튼 → 크게 보기
        await pg.locator(".img-btn").first.click(); await pg.wait_for_selector(".imgview img"); await pg.wait_for_timeout(400); await shot("06_imgview"); await pg.keyboard.press("Escape"); await pg.wait_for_selector(".imgview", state="detached")
        # 저장하지 않고 닫기 확인
        await pg.locator("table.issues tbody tr", has=pg.locator(".img-btn")).first.click(); await pg.wait_for_selector(".iboard")
        at = await pg.locator(".ibox.b4 .ibox-at").text_content(); print("검증 및 적용 마지막 수정:", at)
        await pg.locator(".ibox.b1 textarea").type(" (추가)"); await pg.locator(".modal.wide .ft button", has_text="닫기").click()
        await pg.wait_for_selector("text=저장하지 않은 내용이 있습니다"); print("저장 안 하고 닫기 → 확인 창"); await pg.locator(".modal-bg").last.locator("button.pri").click(); await pg.wait_for_selector(".iboard", state="detached")
        # 정보 · 담당 고치기
        await pg.locator("table.issues tbody tr").first.click(); await pg.wait_for_selector(".iboard"); await pg.click("text=정보 · 담당 고치기"); await pg.wait_for_selector("text=정보 · 담당 고치기 >> nth=0"); await pg.wait_for_timeout(300); await shot("07_issue_form")
        await pg.locator(".modal .ft button", has_text="닫기").last.click()
        # 새 이슈 창
        await pg.click("text=+ 새 이슈"); await pg.wait_for_timeout(300); await shot("08_issue_new"); await pg.locator(".modal .ft button", has_text="닫기").last.click()
        # 이슈 요약
        await pg.goto(BASE + "/#/summary"); await pg.wait_for_selector("table tbody tr"); await pg.wait_for_timeout(300); await shot("09_summary", full_page=True)
        print("이슈 요약 머리글:", await pg.eval_on_selector_all("table >> nth=0 >> thead th", "e => e.map(x => x.textContent)"))
        print("이슈 요약 담당 칸:", await pg.eval_on_selector_all("table tbody tr td:nth-child(5)", "e => e.slice(0,6).map(x => x.textContent)"))
        # 업무로드 이전/다음
        await pg.goto(BASE + "/#/dash"); await pg.wait_for_selector(".per-prev"); r0 = await pg.locator("h1 .sub").text_content()
        await pg.click(".per-prev"); await pg.wait_for_timeout(500); r1 = await pg.locator("h1 .sub").text_content(); await shot("10_dash_prev")
        await pg.click(".per-next"); await pg.wait_for_timeout(500); r2 = await pg.locator("h1 .sub").text_content()
        await pg.click(".per .seg button:nth-child(2)"); await pg.wait_for_timeout(500); await pg.click(".per-prev"); await pg.wait_for_timeout(500); r3 = await pg.locator("h1 .sub").text_content(); await shot("11_dash_month_prev")
        await pg.click(".per .seg button:nth-child(3)"); await pg.wait_for_timeout(500); await pg.click(".per-prev"); await pg.wait_for_timeout(500); r4 = await pg.locator("h1 .sub").text_content()
        print("업무로드 기간:", r0, "| 이전 주", r1, "| 다음 주", r2, "| 이전 달", r3, "| 이전 해", r4)
        await pg.click(".per .seg button:nth-child(1)"); await pg.wait_for_timeout(300); await pg.click("text=오늘로"); await pg.wait_for_timeout(300)
        # 내 업무 월간
        await pg.goto(BASE + "/#/me"); await pg.wait_for_selector(".week table"); await shot("12_me_week")
        await pg.click(".wk-mode button:nth-child(2)"); await pg.wait_for_selector(".week.month"); await pg.wait_for_timeout(400); await shot("13_me_month")
        print("월간 날짜 칸 수:", await pg.locator(".week.month thead tr:first-child th.c").count() - 1, "· 범위", await pg.locator(".wk-range").text_content())
        await pg.click("text=◀ 이전 달"); await pg.wait_for_timeout(500); print("이전 달:", await pg.locator(".wk-range").text_content()); await shot("14_me_month_prev")
        inp = pg.locator(".week.month input.h:not([disabled])").first; await inp.fill("0.5"); await inp.press("Tab"); await pg.wait_for_timeout(500); print("월간에서 시간 입력 저장:", await inp.evaluate("e => e.classList.contains('saved')"))
        await inp.fill(""); await inp.press("Tab"); await pg.wait_for_timeout(400)
        await pg.click(".wk-mode button:nth-child(1)"); await pg.wait_for_timeout(400)
        # 업무 추가 창: 검색
        await pg.click("text=+ 업무 추가 >> nth=0"); await pg.wait_for_selector(".ssel"); cat = pg.locator(".ssel-in").nth(1); await cat.click(); await cat.type("회의"); await pg.wait_for_timeout(300); await shot("15_task_search")
        print("업무 분류 '회의' 검색 결과:", await pg.eval_on_selector_all(".ssel-list:not([hidden]) .ssel-op", "e => e.map(x => x.textContent)"))
        await cat.press("Enter"); print("고른 값:", await cat.input_value())
        mdl = pg.locator(".ssel-in").nth(0); await mdl.click(); n_all = await pg.locator(".ssel-list:not([hidden]) .ssel-op").count(); await mdl.type("2part"); await pg.wait_for_timeout(200)
        print("모델 전체", n_all, "→ '2part' 검색", await pg.locator(".ssel-list:not([hidden]) .ssel-op").count()); await mdl.press("Escape"); await pg.locator(".modal .ft button", has_text="닫기").click()
        # 기준정보 모델
        await pg.goto(BASE + "/#/master"); await pg.click(".tabs button:nth-child(2)"); await pg.wait_for_selector("table.models"); await pg.click("text=+ 줄 추가"); await pg.click("text=+ 줄 추가")
        rows = pg.locator("table.models tr.new-row"); print("새 줄 수:", await rows.count())
        for k, nm in enumerate(["화면시험 모델1", "화면시험 모델2", "화면시험 모델3"]): await rows.nth(k).locator("input.mini-in").first.fill(nm)
        await pg.locator("table.models tr.new-row").last.scroll_into_view_if_needed(); await shot("16_models_new")
        await pg.click("text=새 모델 3줄 추가"); await pg.wait_for_timeout(700)
        print("추가 뒤 모델 행에 있음:", await pg.locator("table.models input.mini-in[value^='화면시험']").count() if False else await pg.evaluate("[...document.querySelectorAll('table.models input.mini-in')].filter(x => x.value.startsWith('화면시험')).length"))
        tr = pg.locator("table.models tbody tr").filter(has=pg.locator("button", has_text="삭제")).last; await tr.locator("button", has_text="삭제").click(); await pg.wait_for_selector("text=삭제(숨김)합니다"); await pg.locator(".modal-bg").last.locator("button.pri").click(); await pg.wait_for_timeout(600)
        await pg.click("text=삭제한 모델 보기"); await pg.wait_for_timeout(500); await pg.locator("text=되살리기").first.scroll_into_view_if_needed(); await shot("17_models_hidden")
        print("삭제한 모델 수 표시:", await pg.locator("label.chk").text_content())
        # 내 이슈
        await pg.goto(BASE + "/#/myissues"); await pg.wait_for_timeout(600); c = pg.locator(".issue-card .top").first
        if await c.count(): await c.click(); await pg.wait_for_timeout(300)
        await shot("18_myissues")
        await b.close()
    print("콘솔 오류:", errs or "없음")
asyncio.run(main())
