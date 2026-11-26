# 0.8.2 창 테두리 크기 조절   사용: python3 ui082b.py <주소> <비밀번호> <출력> <팀원>
import sys, asyncio
from playwright.async_api import async_playwright
BASE, PW, OUT, MEM = sys.argv[1:5]; res = []; errs = []
def chk(n, c, i=""): res.append(bool(c)); print(("  ✓ " if c else "  ✗ ") + n, "" if c else i)
async def drag(pg, loc, dx, dy):
    b = await loc.bounding_box(); x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    await pg.mouse.move(x, y); await pg.mouse.down(); await pg.mouse.move(x + dx / 2, y + dy / 2, steps=4); await pg.mouse.move(x + dx, y + dy, steps=4); await pg.mouse.up(); await pg.wait_for_timeout(150)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={"width": 1600, "height": 950}); pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE); await pg.fill("input[autocomplete=username]", MEM); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(800)
        while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(300)
        await pg.goto(f"{BASE}/#/me"); await pg.wait_for_selector(".week tbody tr[data-id]"); await pg.wait_for_timeout(500)
        for name, cls, grow in (("회의", ".modal.hourlog", "textarea"), ("외근", ".modal.split-pop", ".spl-rows")):
            row = pg.locator(".week tbody tr[data-id]", has_text=name).first
            await row.locator("button.note-btn").nth(0).click(); await pg.wait_for_selector(cls); await pg.wait_for_timeout(400)
            M = pg.locator(cls); b0 = await M.bounding_box(); g0 = (await M.locator(grow).bounding_box())["height"]
            await drag(pg, M.locator(".rsz-s"), 0, 120); b1 = await M.bounding_box()
            chk(f"{name}: 아래 변 끌기 → 높이 +120", abs(b1["height"] - b0["height"] - 120) < 6, (b0["height"], b1["height"]))
            g1 = (await M.locator(grow).bounding_box())["height"]
            chk(f"{name}: 안쪽 칸도 같이 늘어남 ({g0:.0f}→{g1:.0f})", g1 - g0 > 100)
            await drag(pg, M.locator(".rsz-e"), 150, 0); b2 = await M.bounding_box()
            chk(f"{name}: 오른쪽 변 → 너비 +150 (왼쪽 고정)", abs(b2["width"] - b1["width"] - 150) < 6 and abs(b2["x"] - b1["x"]) < 3, (b1, b2))
            await drag(pg, M.locator(".rsz-w"), -100, 0); b3 = await M.bounding_box()
            chk(f"{name}: 왼쪽 변 → 너비 +100 (오른쪽 고정)", abs(b3["width"] - b2["width"] - 100) < 6 and abs((b3["x"] + b3["width"]) - (b2["x"] + b2["width"])) < 3)
            await drag(pg, M.locator(".rsz-nw"), 0, -60); b4 = await M.bounding_box()
            chk(f"{name}: 왼쪽 위 모서리 → 위로 60", abs(b4["height"] - b3["height"] - 60) < 6)
            await pg.screenshot(path=f"{OUT}/V082b_{name}_늘림.png")
            for _ in range(2):
                if await pg.locator(cls).count(): await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
            if await pg.locator(".modal", has_text="저장하지 않고").count(): await pg.locator(".modal", has_text="저장하지 않고").locator("button", has_text="닫기").click(); await pg.wait_for_timeout(300)
            await row.locator("button.note-btn").nth(0).click(); await pg.wait_for_selector(cls); await pg.wait_for_timeout(400)
            b5 = await M.bounding_box()
            chk(f"{name}: 다시 열면 크기 기억", abs(b5["width"] - b4["width"]) < 4 and abs(b5["height"] - b4["height"]) < 4, (b4, b5))
            chk(f"{name}: 다시 열어도 가운데", abs(b5["x"] + b5["width"] / 2 - 800) < 10 and abs(b5["y"] + b5["height"] / 2 - 475) < 15, b5)
            await M.locator(".hd").dblclick(); await pg.wait_for_timeout(300); b6 = await M.bounding_box()
            chk(f"{name}: 제목 더블클릭 → 기본 크기", abs(b6["width"] - b0["width"]) < 4 and abs(b6["height"] - b0["height"]) < 4, (b0, b6))
            for _ in range(2):
                if await pg.locator(cls).count(): await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
        # 다른 창(업무 창)도 변으로 늘어나는지
        await pg.locator("button", has_text="+ 업무 추가").first.click(); await pg.wait_for_timeout(500)
        M = pg.locator(".modal.rsz").last; b0 = await M.bounding_box()
        await drag(pg, M.locator(".rsz-e"), 120, 0); b1 = await M.bounding_box()
        chk("업무 창도 오른쪽 변으로 늘어남", b1["width"] - b0["width"] > 100)
        await M.locator(".hd").dblclick(); await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
        chk("화면 오류 없음", not errs, errs)
        await b.close()
asyncio.run(main()); print(f"0.8.2 크기 조절: 통과 {sum(res)} · 실패 {len(res) - sum(res)}")
# 주간 한 일 = 그날 한 일 양식
async def main2():
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={"width": 1600, "height": 950}); pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE); await pg.fill("input[autocomplete=username]", MEM); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(800)
        while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(300)
        await pg.goto(f"{BASE}/#/me"); await pg.wait_for_selector(".week tbody tr[data-id]"); await pg.wait_for_timeout(500)
        row = pg.locator(".week tbody tr[data-id]", has_text="회의").first; c = row.locator("input.h:not([disabled])")
        for i, (hh, tx) in enumerate((("2", "주간 회의"), ("1.5", "고객 회의"))):
            await c.nth(i).click(); await c.nth(i).fill(hh); await pg.keyboard.press("Tab"); await pg.wait_for_timeout(400)
            if await pg.locator(".note-inl input").count(): await pg.locator(".note-inl input").fill(tx); await pg.keyboard.press("Enter"); await pg.wait_for_timeout(400)
        await pg.locator(".week thead th.day-lnk").first.click()
        await pg.wait_for_timeout(400)
        chk("그날 한 일 = 주간 양식 (요약 · 구역 · 항목)", await pg.locator(".modal .wl-sum").count() == 1 and await pg.locator(".modal .wl-it").count() >= 1 and await pg.locator(".modal .lg.lg4").count() == 0)
        chk("그날 한 일 줄에 적은 글", "주간 회의" in await pg.locator(".modal .wl-it").first.inner_text())
        await pg.screenshot(path=f"{OUT}/V082c_그날.png")
        for _ in range(2):
            if await pg.locator(".modal").count(): await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
        await pg.locator("button", has_text="주간 한 일 보기").first.click(); await pg.wait_for_timeout(800)
        chk("주간 한 일 = 0.8.1 양식 그대로 (날짜별 줄)", await pg.locator(".modal .wl-it").count() >= 1 and await pg.locator(".modal .wl-ln .d").count() >= 2 and await pg.locator(".modal .pl-day").count() == 0)
        await pg.screenshot(path=f"{OUT}/V082c_주간.png")
        chk("화면 오류 없음 (2)", not errs, errs)
        await b.close()
asyncio.run(main2()); print(f"0.8.2 주간 한 일: 통과 {sum(res)} · 실패 {len(res) - sum(res)}")
