# 0.7.0 화면 확인 (Playwright): 팝업 · 공지 · 빨간 점   사용: python3 ui070.py <주소> <비밀번호> <출력 폴더> <마스터> <팀장> <PL> <팀원>
import sys, asyncio
from playwright.async_api import async_playwright
BASE, PW, OUT, MAS, LEAD, PL, MEM = sys.argv[1:8]
errs = []
async def login(b, u):
    cx = await b.new_context(viewport={"width": 1500, "height": 900}, device_scale_factor=2); pg = await cx.new_page()
    pg.on("pageerror", lambda e: errs.append(f"{u}: {e}"))
    await pg.goto(BASE); await pg.fill("input[autocomplete=username]", u); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a")
    return pg
poll = "poll()"
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        shot = lambda pg, n: pg.screenshot(path=f"{OUT}/{n}.png")
        # 1) 마스터: 들어오자마자 버전 공지 초안 팝업
        ms = await login(b, MAS); await ms.wait_for_selector(".modal.pop"); await ms.wait_for_timeout(400); await shot(ms, "R2_01_마스터_버전초안_팝업")
        print("마스터 팝업:", await ms.locator(".pop-it .pop-hd b").all_text_contents(), "· 닫기 버튼 수(확인만 있어야 1):", await ms.locator(".modal.pop .ft button").count())
        await ms.mouse.click(5, 5); await ms.wait_for_timeout(300); print("바깥을 눌러도 안 닫힘:", await ms.locator(".modal.pop").count() == 1)
        await ms.locator(".modal.pop .ft button.pri").click(); await ms.wait_for_selector(".modal.pop", state="detached")
        await ms.goto(BASE + "/#/notices"); await ms.wait_for_selector(".card.notice.draft"); await shot(ms, "R2_02_마스터_공지_초안")
        await ms.click("text=고쳐서 배포"); await ms.wait_for_selector(".modal textarea"); await ms.wait_for_timeout(300); await shot(ms, "R2_03_마스터_버전공지_배포창")
        await ms.locator(".modal .ft button.pri").click(); await ms.wait_for_selector(".card.notice.ver"); await ms.wait_for_timeout(400)
        print("배포 뒤 초안 수:", await ms.locator(".card.notice.draft").count(), "· 지난 공지:", await ms.locator(".card.notice .nt-ttl").all_text_contents())
        # 2) 팀장: 업데이트 안내 팝업 → 공지 쓰기 (파트별)
        ld = await login(b, LEAD); await ld.wait_for_selector(".modal.pop"); print("팀장 팝업:", await ld.locator(".pop-it .pop-hd b").all_text_contents()); await ld.locator(".modal.pop .ft button.pri").click()
        await ld.goto(BASE + "/#/notices"); await ld.click("text=+ 공지 쓰기"); await ld.fill(".modal input[maxlength='100']", "11/20(금) 주간 입력 마감 안내"); await ld.fill(".modal textarea", "· 금요일 17시까지 이번 주 시간을 입력해 주세요\n· 지연 이슈는 지연 사유를 적어 주세요")
        await ld.click(".modal .seg button:nth-child(3)"); await ld.wait_for_timeout(200); await shot(ld, "R2_04_팀장_공지쓰기_개인별")
        await ld.click(".modal .seg button:nth-child(2)"); await ld.locator(".modal .picks label", has_text="3part").locator("input").check(); await ld.wait_for_timeout(200); await shot(ld, "R2_05_팀장_공지쓰기_파트별")
        print("파트별 받는 사람:", await ld.locator(".modal .row .muted.small").first.text_content())
        await ld.locator(".modal .ft button.pri").click(); await ld.wait_for_timeout(600)
        # 3) PL: 업무 지정(요약) + 이슈 담당 지정
        pl = await login(b, PL); await pl.wait_for_selector(".modal.pop"); await pl.wait_for_timeout(300); await shot(pl, "R2_06_PL_팝업_업데이트안내와_공지")
        print("PL 팝업:", await pl.locator(".pop-it .pop-hd b").all_text_contents()); await pl.locator(".modal.pop .ft button.pri").click()
        await pl.goto(BASE + "/#/assign"); await pl.wait_for_selector("text=지정하기"); await pl.fill("input[placeholder^='업무명']", "DV 시료 20EA 전원 시퀀스 재측정"); await pl.fill("input[placeholder^='간략한 요약']", "POC 조건에서 잔류 전압 0.1V 이하 확인")
        await pl.locator(".dt-in, input[type=date]").nth(1).click() if False else None
        await pl.locator(".picks label", has_text=MEM).locator("input").check(); await pl.wait_for_timeout(200); await shot(pl, "R2_07_PL_업무지정_요약칸")
        await pl.click("text=지정하기"); await pl.wait_for_timeout(700)
        r = await pl.evaluate("""async mem => { const M2 = await (await fetch('/api/meta')).json(); const u = M2.users.find(x => x.login === mem); const md = M2.models.find(m => m.part === M2.user.part && m.active);
            const res = await fetch('/api/issues', { method: 'POST', headers: { 'content-type': 'application/json', 'x-req': '1' }, body: JSON.stringify({ model_id: md.id, title: '부팅 시 화면 깜박임', target: '2026-12-01', members: [{ role: '정', user_id: u.id, duty: '재현 조건 정리 · 파형 측정' }] }) }); return res.status; }""", MEM)
        print("PL 이슈 등록 + 담당 지정:", r)
        # 4) 팀원: 팝업(업데이트 안내 + 공지 + 업무 지정 + 이슈 담당) → 빨간 점
        me = await login(b, MEM); await me.wait_for_selector(".modal.pop"); await me.wait_for_timeout(400); await shot(me, "R2_08_팀원_팝업_여러건")
        print("팀원 팝업:", await me.locator(".pop-it .pop-hd b").all_text_contents(), "· 🔔", await me.locator("#bellN").text_content())
        print("업무 지정 카드:", (await me.locator(".pop-it.task").first.inner_text()).replace("\n", " | "))
        print("팝업이 떠 있는 동안 탭의 점:", await me.locator("nav a .ndot").count())
        await me.locator(".modal.pop .ft button.pri").click(); await me.wait_for_selector(".modal.pop", state="detached"); await me.wait_for_timeout(600)
        print("확인 뒤 🔔 숨김:", await me.locator("#bellN").is_hidden(), "· 탭의 점(내 업무는 지금 열려 있어 꺼짐, 내 이슈는 남음):", await me.eval_on_selector_all("nav a", "e => e.filter(a => a.querySelector('.ndot')).map(a => a.firstChild.textContent)"))
        await me.goto(BASE + "/#/me"); await me.wait_for_selector(".week table"); await me.wait_for_timeout(500); await shot(me, "R2_09_팀원_내업무_빨간점")
        print("내 업무 행의 점:", await me.locator(".week .rdot").count(), "(시간 표) ·", await me.locator(".rdot").count(), "(전체)")
        await me.locator(".week tr", has=me.locator(".rdot")).filter(has_text="DV 시료").locator(".t.lnk").click(); await me.wait_for_selector(".modal"); await me.wait_for_timeout(400); await shot(me, "R2_10_팀원_업무창_요약"); await me.locator(".modal .ft button", has_text="닫기").click(); await me.wait_for_timeout(400)
        print("업무 행을 누른 뒤 시간 표의 점:", await me.locator(".week .rdot").count())
        await me.goto(BASE + "/#/myissues"); await me.wait_for_selector(".issue-card"); await me.wait_for_timeout(500); await shot(me, "R2_11_팀원_내이슈_빨간점")
        print("내 이슈 카드의 점:", await me.locator(".issue-card .rdot").count(), "· 탭의 점:", await me.locator("nav a .ndot").count())
        await me.locator(".issue-card", has=me.locator(".rdot")).locator(".top").click(); await me.wait_for_timeout(500); print("카드를 누른 뒤 점:", await me.locator(".issue-card .rdot").count())
        # 5) 입력 중에는 팝업을 미룸
        await me.goto(BASE + "/#/me"); await me.wait_for_selector(".week input.h"); inp = me.locator(".week input.h:not([disabled])").first; await inp.click(); await inp.type("1")
        await pl.evaluate("""async mem => { const M2 = await (await fetch('/api/meta')).json(); const u = M2.users.find(x => x.login === mem);
            await fetch('/api/assign', { method: 'POST', headers: { 'content-type': 'application/json', 'x-req': '1' }, body: JSON.stringify({ user_ids: [u.id], title: '입력 중 팝업 시험', summary: '입력이 끝난 뒤에 떠야 함' }) }); }""", MEM)
        await inp.type(".5"); await me.evaluate(poll); await me.wait_for_timeout(1200); a = await me.locator(".modal.pop").count()
        await me.wait_for_timeout(5500); c = await me.locator(".modal.pop").count()
        print("입력 중(글자 치는 중)에는 팝업 수:", a, "→ 입력을 멈춘 뒤:", c)
        await me.locator(".modal.pop .ft button.pri").click(); await inp.fill(""); await inp.press("Tab")
        # 6) 지난 공지 (팀원)
        await me.goto(BASE + "/#/notices"); await me.wait_for_selector(".card.notice"); await me.wait_for_timeout(300); await shot(me, "R2_12_팀원_지난공지")
        print("팀원 지난 공지:", await me.locator(".card.notice .nt-ttl").all_text_contents(), "· 공지 쓰기 버튼:", await me.locator("text=+ 공지 쓰기").count())
        # 다크 모드 팝업
        await pl.evaluate(poll); await pl.wait_for_timeout(500)
        await ld.evaluate("""async () => { await fetch('/api/notices', { method: 'POST', headers: { 'content-type': 'application/json', 'x-req': '1' }, body: JSON.stringify({ title: '다크 모드 확인용 공지', body: '· 화면 C 다크 모드에서 팝업 모양 확인', target: { all: true } }) }); }""")
        await me.evaluate("() => { const s = document.getElementById('selTheme'); s.value = 'c'; s.dispatchEvent(new Event('change')); if (document.documentElement.dataset.dark !== '1') document.getElementById('btnDark').click(); }")
        await me.evaluate(poll); await me.wait_for_selector(".modal.pop"); await me.wait_for_timeout(400); await shot(me, "R2_13_팀원_팝업_화면C_다크")
        await b.close()
    print("오류:", errs or "없음")
asyncio.run(main())
