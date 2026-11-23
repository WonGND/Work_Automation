# PPT 내보내기 양식(.pptx)을 실행 파일 안에 넣기 위한 모듈을 만든다 → app/src/ppt_tpl.ts
# 사용: python3 -I tools/mk_ppt_tpl.py [양식.pptx]   (app/ 의 상위 폴더에서)
# 양식을 주지 않으면 sample/ppt_template_sample.pptx (회사 정보 없는 샘플) 을 쓴다.
# 양식 조건: 16:9 · 1장 · 제목 상자 이름 'TextBox 1' (안내 문구 'TextBox 2' 는 지워짐)
import base64, sys, zipfile
src = sys.argv[1] if len(sys.argv) > 1 else "sample/ppt_template_sample.pptx"
z = zipfile.ZipFile(src)
s1 = z.read("ppt/slides/slide1.xml").decode("utf-8")
assert 'name="TextBox 1"' in s1, "1장에 제목 상자(TextBox 1)가 없습니다"
b = open(src, "rb").read()
open("app/src/ppt_tpl.ts", "w", encoding="utf-8").write(
    "// tools/mk_ppt_tpl.py 가 만든 파일 (고치지 말 것)\n" f"export const PPT_TPL = \"{base64.b64encode(b).decode()}\";\n")
print(f"PPT 양식 {src} · {len(b)//1024} KB → app/src/ppt_tpl.ts")
