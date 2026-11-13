# 인증서 설치 안내 그림(app/guide/c1~c11.png)을 서버에 넣는 TS 모듈로 만듦
# 그림 다시 만들기: app/guide/steps.html 을 playwright 로 열어 섹션마다 캡처 (tools/guide_shot.js)
import base64, os, sys
d = sys.argv[1] if len(sys.argv) > 1 else "app/guide"
out = ["// 자동 생성 (tools/mk_guide.py) — 고치지 말 것", "export const GUIDE: Record<string, string> = {"]
for i in range(1, 12):
    b = base64.b64encode(open(os.path.join(d, f"c{i}.png"), "rb").read()).decode()
    out.append(f'  "c{i}.png": "{b}",')
out.append("};")
open("app/src/guide_img.ts", "w").write("\n".join(out) + "\n")
print("guide_img.ts", sum(os.path.getsize(os.path.join(d, f"c{i}.png")) for i in range(1, 12)) // 1024, "KB")
