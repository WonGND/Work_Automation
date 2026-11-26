# 0.8.2 화면: 업무 시간 입력 창 · 나누기 창 크기 · 가운데   사용: python3 ui082.py <주소> <비밀번호> <출력> <팀원>
import sys, asyncio
from playwright.async_api import async_playwright
BASE, PW, OUT, MEM = sys.argv[1:5]; res = []; errs = []
def chk(n, c, i=""): res.append(bool(c)); print(("  ✓ " if c else "  ✗ ") + n, "" if c else i)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for vw, vh in ((1920, 1080), (1366, 768)):
            ctx = await b.new_context(viewport={"width": vw, "height": vh}); pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(BASE); await pg.fill("input[autocomplete=username]", MEM); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(800)
            while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(300)
            await pg.goto(f"{BASE}/#/me"); await pg.wait_for_selector(".week tbody tr[data-id]"); await pg.wait_for_timeout(500)
            for name, sel, cls in (("회의", "회의", ".modal.hourlog"), ("외근", "외근", ".modal.split-pop")):
                row = pg.locator(".week tbody tr[data-id]", has_text=sel).first
                await row.locator("button.note-btn").nth(0).click(); await pg.wait_for_selector(cls); await pg.wait_for_timeout(400)
                bb = await pg.locator(cls).bounding_box()
                cy = bb["y"] + bb["height"] / 2; cx = bb["x"] + bb["width"] / 2
                chk(f"{vw}: {name} 창 가운데 (x {cx:.0f}/{vw/2:.0f} · y {cy:.0f}/{vh/2:.0f})", abs(cx - vw / 2) < 20 and abs(cy - vh / 2) < 30)
                chk(f"{vw}: {name} 창 너비 {bb['width']:.0f}", bb["width"] >= min(900, vw - 60))
                await pg.screenshot(path=f"{OUT}/V082_{vw}_{name}.png")
                await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
            await ctx.close()
        chk("화면 오류 없음", not errs, errs)
        await b.close()
asyncio.run(main()); print(f"0.8.2 화면: 통과 {sum(res)} · 실패 {len(res) - sum(res)}")
