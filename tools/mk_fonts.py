# Noto Sans KR (가변 굵기 · SIL OFL 1.1) 을 실행 파일 안에 넣기 위한 모듈을 만든다 → app/src/fonts_kr.ts
# 원본: npm @fontsource-variable/noto-sans-kr (bun install 로 받음). 사내망에서도 인터넷 없이 보이게 서버가 직접 준다.
# 사용: python3 -I tools/mk_fonts.py   (app/ 의 상위 폴더에서)
import base64, json, os, re
SRC = "app/node_modules/@fontsource-variable/noto-sans-kr"
css = open(f"{SRC}/wght.css", encoding="utf-8").read()
files = {}
def sub(m):
    name = os.path.basename(m.group(1))
    files[name] = base64.b64encode(open(f"{SRC}/files/{name}", "rb").read()).decode()
    return f"url(/fonts/{name})"
css = re.sub(r"url\(\./files/([^)]+)\)", sub, css)
css = "/* Noto Sans KR — SIL Open Font License 1.1 (Google) */\n" + css
with open("app/src/fonts_kr.ts", "w", encoding="utf-8") as f:
    f.write("// 자동 생성 (tools/mk_fonts.py) — 저장소에 넣지 않음\n")
    f.write("export const FONT_CSS = " + json.dumps(css, ensure_ascii=False) + ";\n")
    f.write("export const FONTS: Record<string, string> = " + json.dumps(files) + ";\n")
print(f"글꼴 조각 {len(files)}개 · {sum(len(v) * 3 // 4 for v in files.values()) // 1024} KB → app/src/fonts_kr.ts")
