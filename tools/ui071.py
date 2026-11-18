# 0.7.1 화면 확인: Caps Lock 안내 · PL 관리 행 · PL 이슈 등록 · 완료 최신순   사용: python3 ui071.py <주소> <비밀번호> <출력> <PL> <팀원>
import sys, asyncio
from playwright.async_api import async_playwright
BASE, PW, OUT, PL, MEM = sys.argv[1:6]
errs = []
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        async def page():
            cx = await b.new_context(viewport={"width": 1500, "height": 900}, device_scale_factor=2); pg = await cx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e))); return pg
        async def login(pg, u):
            await pg.goto(BASE); await pg.fill("input[autocomplete=username]", u); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(500)
            while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(400)
        # Caps Lock
        pg = await page(); await pg.goto(BASE); pw = pg.locator("input[type=password]"); await pw.click()
        key = "caps => document.querySelector('input[type=password]').dispatchEvent(new KeyboardEvent('keyup', { key: caps ? 'A' : 'a', modifierCapsLock: caps, bubbles: true }))"   # 헤드리스 브라우저는 실제 Caps Lock 키 상태를 못 바꿔서 같은 키 이벤트로 흉내
        await pw.type("A"); await pg.evaluate(key, True); await pg.wait_for_timeout(200)
        on = await pg.locator(".caps-tip:not([hidden])").count(); await pg.screenshot(path=f"{OUT}/V071_1_로그인_CapsLock.png")
        await pg.evaluate(key, False); await pg.wait_for_timeout(200); off = await pg.locator(".caps-tip:not([hidden])").count()
        print("Caps Lock 켬 → 안내", on, "· 끔 → 안내", off)
        await pw.fill("")
        # PL
        await login(pg, PL); await pg.goto(BASE + "/#/me"); await pg.wait_for_selector(".week table"); await pg.wait_for_timeout(500)
        plrows = await pg.locator(".week tr", has=pg.locator(".badge", has_text="PL 관리")).count()
        print("PL 내 업무: PL 관리 행", plrows, "· 담당 행", await pg.locator(".week tr", has=pg.locator(".badge.role")).count(), "· '+ 이슈 등록' 버튼", await pg.locator("button", has_text="+ 이슈 등록").count())
        await pg.screenshot(path=f"{OUT}/V071_2_PL_내업무_PL관리행.png")
        row = pg.locator(".week tr", has=pg.locator(".badge", has_text="PL 관리")).first
        name = (await row.locator(".t.lnk").text_content()).strip()
        inp = row.locator("input.h:not([disabled])").first; await inp.fill("1"); await inp.press("Tab"); await pg.wait_for_timeout(600)
        print(f"PL 관리 행({name[:20]})에 1h 입력 → 저장 표시:", await inp.evaluate("e => e.classList.contains('saved')"), "· 오류 알림:", await pg.locator(".toast.err").count())
        await row.locator(".t.lnk").click(); await pg.wait_for_selector(".iboard"); await pg.wait_for_timeout(300)
        print("행을 누르면 이슈 창 · 4칸 쓰기 가능:", await pg.eval_on_selector_all(".ibox textarea", "e => e.every(x => !x.readOnly)"), "· 저장 버튼", await pg.locator(".modal.wide .ft button.pri").count())
        await pg.screenshot(path=f"{OUT}/V071_3_PL관리행_이슈창.png"); await pg.locator(".modal.wide .ft button", has_text="닫기").click(); await pg.wait_for_timeout(300)
        await pg.click("text=+ 이슈 등록"); await pg.wait_for_selector(".modal"); await pg.wait_for_timeout(300)
        print("이슈 등록 창 모델 목록:", await pg.eval_on_selector_all(".modal select >> nth=0 >> option", "e => e.map(x => x.textContent).slice(0,8)"))
        await pg.screenshot(path=f"{OUT}/V071_4_PL_내업무_이슈등록.png"); await pg.locator(".modal .ft button", has_text="닫기").click()
        await inp.fill(""); await inp.press("Tab"); await pg.wait_for_timeout(400)
        # 팀원: 완료 최신순
        pm = await page(); await login(pm, MEM)
        ids = await pm.evaluate("""async () => { const mk = async (t, d) => { const r = await fetch('/api/tasks', { method: 'POST', headers: { 'content-type': 'application/json', 'x-req': '1' }, body: JSON.stringify({ kind: '통상', title: t, start: '2026-11-01' }) }); const x = await r.json();
            await fetch('/api/hours', { method: 'PUT', headers: { 'content-type': 'application/json', 'x-req': '1' }, body: JSON.stringify({ type: 'task', id: x.id, date: '2026-11-17', hours: 0.5 }) });
            await fetch('/api/tasks/' + x.id, { method: 'PUT', headers: { 'content-type': 'application/json', 'x-req': '1' }, body: JSON.stringify({ done: d, progress: 100 }) }); return x.id; };
            return [await mk('완료 11/03 업무', '2026-11-03'), await mk('완료 11/18 업무', '2026-11-18'), await mk('완료 11/10 업무', '2026-11-10')]; }""")
        await pm.goto(BASE + "/#/me"); await pm.wait_for_selector(".week table"); await pm.wait_for_timeout(500)
        g = pm.locator(".week tr.grp", has_text="완료")
        if await pm.locator(".week tr", has_text="완료 11/18 업무").first.is_hidden(): await g.click(); await pm.wait_for_timeout(300)
        order = [t for t in await pm.eval_on_selector_all(".week tbody tr .t.lnk", "e => e.map(x => x.textContent)") if t.startswith("완료 ")]
        print("시간 표 완료 묶음 순서:", order)
        await pm.evaluate("[...document.querySelectorAll('.week tr')].find(r => r.textContent.includes('완료 11/18 업무'))?.scrollIntoView({block:'center'})"); await pm.wait_for_timeout(300); await pm.screenshot(path=f"{OUT}/V071_5_완료_최신순_시간표.png")
        await pm.locator(".seg button", has_text="완료 (").click(); await pm.wait_for_timeout(500)
        tl = await pm.eval_on_selector_all("table.task-list tbody tr td:nth-child(3)", "e => e.map(x => x.textContent)")
        print("업무 목록 '완료' 탭 앞 5개:", [t[:16] for t in tl[:5]])
        print("업무 목록 표 수:", await pm.locator("table.task-list").count())
        await pm.evaluate("document.querySelector('table.task-list').scrollIntoView({block:'center'})"); await pm.wait_for_timeout(300); await pm.screenshot(path=f"{OUT}/V071_6_완료_최신순_업무목록.png")
        await b.close()
    print("오류:", errs or "없음")
asyncio.run(main())
