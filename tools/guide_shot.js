// 인증서 설치 안내 그림 만들기: app/guide/steps.html 의 섹션마다 캡처 → app/guide/c0~c11.png
// 사용: node tools/guide_shot.js   (그 다음 python3 tools/mk_guide.py 로 서버에 넣을 모듈 생성)
// 그림 속 서버 주소는 steps.html 안의 192.168.0.10 을 바꿔서 다시 만듭니다
const path = require('path');
const { chromium } = require('playwright');
const dir = path.join(__dirname, '..', 'app', 'guide');
(async () => { const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 900, height: 700 }, deviceScaleFactor: 1 });
 await p.goto('file://' + path.join(dir, 'steps.html')); await p.waitForTimeout(500);
 for (let i = 0; i <= 11; i++) await p.locator('#s' + i).screenshot({ path: path.join(dir, `c${i}.png`) });
 await b.close(); })();
