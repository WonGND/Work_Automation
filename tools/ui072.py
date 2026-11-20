# 0.7.2 화면 확인   사용: python3 ui072.py <주소> <비밀번호> <출력> <마스터> <PL> <휴가 있는 사람>
import sys, asyncio, json
from playwright.async_api import async_playwright
BASE, PW, OUT, MAS, PL, LV = sys.argv[1:7]
errs = []
PASTE = """async (withImg) => { const dt = new DataTransfer();
  if (withImg) { const c = document.createElement('canvas'); c.width = 320; c.height = 160; const x = c.getContext('2d'); x.fillStyle = '#2f6fd0'; x.fillRect(0, 0, 320, 160); x.fillStyle = '#fff'; x.font = '28px sans-serif'; x.fillText('붙여넣기 시험', 60, 90);
    const b = await new Promise(r => c.toBlob(r, 'image/png')); dt.items.add(new File([b], 'clip.png', { type: 'image/png' })); } else dt.setData('text/plain', '글자만');
  document.body.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }"""
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        async def page(w=1600, h=950):
            cx = await b.new_context(viewport={"width": w, "height": h}, device_scale_factor=1.5); pg = await cx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e))); return pg
        async def login(pg, u):
            await pg.goto(BASE); await pg.fill("input[autocomplete=username]", u); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(500)
            while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(400)
        pg = await page(); await login(pg, MAS)
        nav = await pg.eval_on_selector_all("nav a", "e => e.map(x => x.textContent.trim())")
        print("메뉴:", nav); print("이슈 요약 탭 없음:", not any("이슈 요약" in x for x in nav))
        print("글꼴:", await pg.evaluate("getComputedStyle(document.body).fontFamily.split(',')[0]"), "· 로드됨:", await pg.evaluate("document.fonts.check('16px \"Noto Sans KR Variable\"', '가')"))
        await pg.goto(BASE + "/#/summary"); await pg.wait_for_timeout(600); print("#/summary → ", pg.url.split("#")[1])
        await pg.goto(BASE + "/#/registry"); await pg.wait_for_selector("table.issues"); await pg.wait_for_timeout(500)
        cards = await pg.eval_on_selector_all(".icards button.card", "e => e.map(x => x.innerText.replace(/\\n/g, ' '))"); print("카드:", cards)
        n0 = await pg.locator("table.issues tbody tr").count()
        await pg.screenshot(path=f"{OUT}/V072_1_이슈정리_카드.png")
        await pg.locator(".icards button.card", has_text="지연").first.click(); await pg.wait_for_timeout(400)
        print("'지연' 카드 → 행", await pg.locator("table.issues tbody tr").count(), "/ 전체", n0, "· 필터 표시", await pg.locator(".row.filt").count())
        await pg.screenshot(path=f"{OUT}/V072_2_카드_지연만.png")
        await pg.locator(".icards button.card", has_text="완료").first.click(); await pg.wait_for_timeout(400)
        print("'완료' 카드 → 회색 행", await pg.locator("table.issues tr.is-done").count(), "· 배경", await pg.eval_on_selector("table.issues tr.is-done td", "e => getComputedStyle(e).backgroundColor") if await pg.locator("table.issues tr.is-done").count() else "-")
        await pg.locator(".icards button.card.on").click(); await pg.wait_for_timeout(300)
        await pg.locator("label.chk", has_text="완료 포함").locator("input").check(); await pg.wait_for_timeout(400)
        await pg.screenshot(path=f"{OUT}/V072_3_완료포함_회색행.png")
        sizes = await pg.eval_on_selector_all("table.issues tbody tr:first-child td", "e => [...new Set(e.map(x => getComputedStyle(x).fontSize))]"); print("표 글자 크기:", sizes)
        # 이슈 창 (예전 글이 있는 이슈)
        await pg.locator("label.chk", has_text="완료 포함").locator("input").uncheck(); await pg.wait_for_timeout(300)
        await pg.locator("table.issues tbody tr").first.click(); await pg.wait_for_selector(".iboard"); await pg.wait_for_timeout(500)
        bx = await pg.eval_on_selector(".modal.board", "e => [e.offsetWidth, e.offsetHeight, innerWidth, innerHeight, getComputedStyle(e).resize]"); print("이슈 창 크기 · 화면:", bx)
        print("칸 제목:", await pg.eval_on_selector_all(".ibox-hd b", "e => e.map(x => x.textContent)"))
        print("항목 수:", await pg.locator(".iitem:not(.old)").count(), "· 이전 기록 칸:", await pg.locator(".iitem.old").count())
        await pg.screenshot(path=f"{OUT}/V072_4_이슈창_템플릿.png")
        # 항목 쓰기 → 저장 → 현재 진행
        ta = pg.locator(".ibox.b3 .iitem:not(.old) textarea").nth(1); await ta.fill("시험: 개선안별 변경점 입력\n두 번째 줄"); await pg.wait_for_timeout(200)
        print("글이 늘면 칸이 늘어남 (높이):", await ta.evaluate("e => e.offsetHeight"))
        await pg.locator(".modal.board .ft button.pri").click(); await pg.wait_for_timeout(800)
        now = await pg.locator("table.issues tbody tr").first.locator("td.status").inner_text(); print("현재 진행:", now[:60].replace("\n", " "))
        # 크기 조절 기억
        await pg.locator("table.issues tbody tr").first.click(); await pg.wait_for_selector(".iboard"); await pg.wait_for_timeout(300)
        await pg.evaluate("() => { const m = document.querySelector('.modal.board'); m.style.width = '1100px'; m.style.height = '700px'; }"); await pg.wait_for_timeout(900)
        await pg.evaluate("() => document.documentElement.dataset.dark = '1'"); await pg.wait_for_timeout(200)
        await pg.screenshot(path=f"{OUT}/V072_5_이슈창_다크_크기조절.png")
        await pg.evaluate("() => document.documentElement.dataset.dark = ''")
        await pg.locator(".modal.board .ft button", has_text="닫기").click(); await pg.wait_for_timeout(300)
        if await pg.locator(".modal .ft button.pri", has_text="확인").count(): await pg.locator(".modal .ft button.pri").last.click()
        await pg.locator("table.issues tbody tr").first.click(); await pg.wait_for_selector(".iboard"); await pg.wait_for_timeout(400)
        print("다시 열 때 크기 기억:", await pg.eval_on_selector(".modal.board", "e => [e.offsetWidth, e.offsetHeight]"))
        await pg.locator(".modal.board .ft button", has_text="닫기").click(); await pg.wait_for_timeout(300)
        # 등록 창 이미지 붙여넣기
        await pg.click("text=+ 새 이슈"); await pg.wait_for_selector(".modal .form-img"); await pg.wait_for_timeout(300)
        await pg.evaluate(PASTE, False); await pg.wait_for_timeout(300); print("이미지 없는 붙여넣기 → 안내:", await pg.locator("#toast div", has_text="이미지가 없습니다").count())
        await pg.evaluate(PASTE, True); await pg.wait_for_timeout(500)
        print("이미지 붙여넣기 → 미리보기:", await pg.locator(".form-img img.iimg-th").count(), "· blob 주소", (await pg.eval_on_selector(".form-img img", "e => e.src"))[:5])
        await pg.screenshot(path=f"{OUT}/V072_6_등록창_이미지붙여넣기.png")
        sel = pg.locator(".modal .form select").first; opts = await sel.locator("option").evaluate_all("e => e.map(x => x.value).filter(Boolean)"); await sel.select_option(opts[0])
        await pg.locator(".modal .form input").nth(0).fill("0.7.2 화면 시험 이슈") if False else None
        tins = pg.locator(".modal .form input:not([type])"); 
        for k in range(await tins.count()):
            if await tins.nth(k).is_editable(): await tins.nth(k).fill("0.7.2 화면 시험 이슈"); break
        await pg.locator(".modal .ft button.pri", has_text="저장").click(); await pg.wait_for_timeout(1500)
        print("저장 후 알림:", await pg.locator("#toast div").all_inner_texts())
        print("목록에 🖼:", await pg.locator("table.issues tr", has_text="0.7.2 화면 시험 이슈").locator(".img-btn").count())
        # 휴가 표시
        uid = await pg.evaluate(f"M.users.find(u => u.name.startsWith('{LV}')).id")
        await pg.goto(BASE + f"/#/people/{uid}"); await pg.wait_for_selector(".week table"); await pg.wait_for_timeout(700)
        print("하루 합계 표시:", await pg.eval_on_selector_all(".week thead tr.sum td", "e => e.map(x => x.innerText.replace(/\\n/g, '/'))"))
        await pg.screenshot(path=f"{OUT}/V072_7_하루합계_연차반차.png")
        # PL
        pp = await page(); await login(pp, PL)
        await pp.goto(BASE + "/#/assign"); await pp.wait_for_selector(".pick-grp"); await pp.wait_for_timeout(400)
        print("PL 업무 지정: 파트 묶음", await pp.eval_on_selector_all(".pick-pt", "e => e.map(x => x.childNodes[0].textContent)"), "· 일을 준 사람", await pp.locator(".given .card").count())
        await pp.screenshot(path=f"{OUT}/V072_8_PL_업무지정.png", full_page=True)
        await pp.goto(BASE + "/#/registry"); await pp.wait_for_timeout(300); print("PL 이슈 정리 접근 →", pp.url.split("#")[1])
        await pp.goto(BASE + "/#/part"); await pp.wait_for_timeout(900)
        print("PL 우리 파트 이슈 카드:", await pp.eval_on_selector_all(".icards button.card", "e => e.map(x => x.innerText.replace(/\\n/g, ' '))"))
        await pp.screenshot(path=f"{OUT}/V072_9_PL_우리파트이슈.png")
        if await pp.locator(".given .card").count() or True:
            await pp.goto(BASE + "/#/assign"); await pp.wait_for_timeout(500)
            if await pp.locator(".given .card").count():
                await pp.locator(".given .card").first.click(); await pp.wait_for_selector(".week table"); await pp.wait_for_timeout(600)
                print("일을 준 사람 화면:", (await pp.locator("h1").first.inner_text()).replace("\n", " "), "· 입력 칸 잠김:", await pp.eval_on_selector_all(".week input.h", "e => e.every(x => x.disabled || x.readOnly)"))
                await pp.screenshot(path=f"{OUT}/V072_10_PL_일을준사람_읽기전용.png")
        await b.close()
asyncio.run(main())
print("화면 오류:", errs)
