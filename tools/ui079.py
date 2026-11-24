# 0.7.9 화면 확인 (폴더 바로 열기)   사용: python3 ui079.py <주소> <비밀번호> <출력> <팀원>
import sys, asyncio, zipfile, io
from playwright.async_api import async_playwright
BASE, PW, OUT, MEM = sys.argv[1:5]
errs = []
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1400, "height": 950}, device_scale_factor=1.25, accept_downloads=True)
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE); await pg.fill("input[autocomplete=username]", MEM); await pg.fill("input[type=password]", PW); await pg.click("button.pri"); await pg.wait_for_selector("nav a"); await pg.wait_for_timeout(800)
        while await pg.locator(".modal.pop").count(): await pg.locator(".modal.pop .ft button.pri").click(); await pg.wait_for_timeout(300)
        await pg.goto(f"{BASE}/#/pw"); await pg.wait_for_selector("text=폴더 바로 열기"); await pg.wait_for_timeout(300)
        async with pg.expect_download() as dl:
            await pg.locator("button", has_text="설치 파일 받기").click()
        d = await dl.value; data = open(await d.path(), "rb").read(); z = zipfile.ZipFile(io.BytesIO(data))
        print("설치 묶음:", d.suggested_filename, sorted(z.namelist()))
        ps = z.read("open-folder.ps1"); print("ps1 BOM:", ps[:3] == b"\xef\xbb\xbf", "· 경로 들어감:", "이슈업무원본자료".encode() in ps)
        await pg.screenshot(path=f"{OUT}/V079_1_내정보.png", full_page=True)
        # 설치 전: 경로 복사
        await pg.goto(f"{BASE}/#/myissues"); await pg.wait_for_selector(".no-lnk"); await pg.locator(".no-lnk").first.click(); await pg.wait_for_selector(".fold-pop")
        print("설치 전 → 경로 복사 창:", await pg.locator(".fold-pop").count() == 1, "· 설치 안내 줄:", await pg.locator(".fold-pop", has_text="폴더 바로 열기").count() == 1)
        await pg.keyboard.press("Escape")
        # 설치했다고 체크 → workfolder: 링크로 감
        await pg.goto(f"{BASE}/#/pw"); await pg.wait_for_selector("text=이 PC에 설치했습니다"); await pg.locator("label.chk", has_text="이 PC에 설치했습니다").locator("input").check(); await pg.wait_for_timeout(300)
        await pg.evaluate("""() => { window.__hrefs = []; const o = HTMLAnchorElement.prototype.click; HTMLAnchorElement.prototype.click = function () { if (this.href.startsWith('workfolder:')) { window.__hrefs.push(this.href); return; } return o.call(this); }; }""")
        await pg.goto(f"{BASE}/#/myissues"); await pg.wait_for_selector(".no-lnk")
        await pg.evaluate("""() => { window.__hrefs = []; const o = HTMLAnchorElement.prototype.click; HTMLAnchorElement.prototype.click = function () { if (this.href.startsWith('workfolder:')) { window.__hrefs.push(this.href); return; } return o.call(this); }; }""")
        print("제목:", await pg.locator(".no-lnk").first.get_attribute("title"))
        await pg.locator(".no-lnk").first.click(); await pg.wait_for_timeout(400)
        print("설치 후 → 링크:", await pg.evaluate("window.__hrefs"), "· 복사 창 없음:", await pg.locator(".fold-pop").count() == 0, "· 알림:", await pg.locator("#toast").inner_text())
        await b.close()
    print("화면 오류:", errs or "없음")
asyncio.run(main())
