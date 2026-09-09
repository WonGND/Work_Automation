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

반드시 `CpkAnalyzer/` 폴더 안에서, 의존 패키지를 설치한 **같은 파이썬 환경**으로 빌드합니다. PyInstaller는 빌드 환경에 설치된 패키지만 수집하므로 `requirements.txt`를 건너뛰면 scipy가 조용히 빠진 채 exe가 만들어지고, 실행할 때 `ModuleNotFoundError: No module named 'scipy'`가 납니다.

```bash
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --clean --noconfirm CpkAnalyzer.spec
```

결과물: `dist/CpkAnalyzer.exe`

빌드 설정은 `CpkAnalyzer.spec`에 있습니다. scipy·numpy·matplotlib·pandas·openpyxl을 `collect_all`로 수집하므로 `--hidden-import`를 따로 넘길 필요가 없습니다.

> 이전 README는 `--hidden-import`를 CMD 줄바꿈 문자(`^`)로 이어 붙였는데, PowerShell에서는 `^`가 줄바꿈으로 동작하지 않아 첫 줄만 실행되고 옵션이 통째로 누락됐습니다. spec 파일을 쓰면 셸 종류와 무관하게 같은 결과가 나옵니다.

### 배포 시 참고
- onefile이라 `dist/CpkAnalyzer.exe` 한 파일만 압축해 전달하면 됩니다.
- UPX 압축은 사내 백신 오탐과 Qt/scipy DLL 파손 사례가 있어 spec에서 꺼두었습니다.
- onefile은 실행할 때마다 임시 폴더에 압축을 풀어 첫 구동이 수 초에서 수십 초 걸립니다. 체감이 나쁘면 onedir 방식이 훨씬 빠릅니다.

## 수식
```
Cp  = (USL - LSL) / (6 * StdDev)
Cpk = min((USL - Mean)/(3*StdDev), (Mean - LSL)/(3*StdDev))
PPM = (P(x<LSL) + P(x>USL)) * 1,000,000
```
