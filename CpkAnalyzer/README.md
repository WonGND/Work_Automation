# CpkAnalyzer - 공정능력 분석 (Process Capability Analysis)

Minitab 스타일의 Cp/Cpk 공정능력 분석 GUI 데스크탑 프로그램입니다.

## 주요 기능
- Excel/CSV 파일 로드 및 컬럼 선택, 수동 데이터 입력
- UTF-8 및 CP949/EUC-KR CSV 인코딩 자동 감지
- LSL/USL, Cpk 기준, 제목/X축 라벨/X축 범위 설정
- 히스토그램 + 정규분포 피팅 + LSL/USL 점선 + NG 음영
- 통계 박스: N, Mean, StDev, Cp, Cpk, PPM
- 색상 실시간 변경 (히스토그램/곡선/NG음영)
- 제목/X축라벨/NG음영/범례/통계박스/OK-NG 표시 토글
- **범례/통계 박스: 마우스 드래그로 이동, 휠 스크롤로 크기 조절 (SpinBox 정밀 조절과 동기화)**
- PNG/JPG/SVG 저장, DPI(150/300/600) 선택

## 설치 및 실행
```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

`main.py`가 실행 진입점이며, 디자인 토큰은 `theme.py`, 통계 계산은
`stats_core.py`, 차트 위젯과 마우스 상호작용은 `widgets.py`에 분리되어 있습니다.

## 마우스 조작
| 조작 | 대상 | 동작 |
|---|---|---|
| 드래그 | 범례(Observed) / 통계(N=..) 박스 | 위치 이동 |
| 휠 스크롤 | 박스 위에서 | 크기(글자) 조절 |

## exe 빌드 (PyInstaller)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=assets/app.ico ^
    --hidden-import=scipy.special.cython_special ^
    --hidden-import=scipy._lib.messagestream main.py
```
결과물: `dist/main.exe`

> `theme.py` / `stats_core.py` / `widgets.py` 는 `main.py` 와 같은 폴더의 일반 모듈이라
> PyInstaller가 자동으로 수집합니다. 반드시 `CpkAnalyzer/` 폴더 안에서 빌드하세요.

## 수식
```
Cp  = (USL - LSL) / (6 * StdDev)
Cpk = min((USL - Mean)/(3*StdDev), (Mean - LSL)/(3*StdDev))
PPM = (P(x<LSL) + P(x>USL)) * 1,000,000
```
