# BU LotID 정리 도구

LotID별 최신 이미지 폴더를 선별하고 측정 데이터와 이미지를 정리해 엑셀 보고서를 만드는 Windows 업무 도구입니다.

## 실행

GUI의 표준 진입점은 다음과 같습니다.

```bash
python BU_organize_gui.py
```

GUI 없이 동일한 파이프라인을 실행하려면 다음 파일을 실행합니다.

```bash
python bu_pipeline.py
```

## 처리 순서

1. 입력 폴더 전체에서 이미지가 직접 들어 있는 LotID 폴더를 재귀 탐색하고, 같은 LotID는 생성·수정 시각이 가장 최신인 폴더를 선택합니다.
2. 선택한 폴더를 결과 merge 폴더에 병렬 복사하고, 선택 대상에 없는 이전 결과는 제거합니다.
3. `LMK6DataLog.csv`를 재귀 탐색해 LotID별 최신 판정, Black Uniformity(BU), White Uniformity(WU)를 읽습니다.
4. 이미지의 검은 배경을 병렬 크롭합니다.
5. 이미지 포함 `crop_report.xlsx`, 데이터 전용 `BU_WU_Data_정리본_NoImage.xlsx`, `merge_report.csv`를 저장합니다.

결과 폴더는 입력 폴더 옆에 `<입력명>_LotID_latest_v1`과 `<입력명>_LotID_latest_v1_cropped_v1` 이름으로 생성됩니다.

## 설정과 로그

- `tovis_bu_data_settings.json`: GUI가 실행 위치에 생성하는 사용자별 설정 파일입니다. 경로와 테마를 저장하므로 Git 추적 대상에서 제외합니다.
- `TOVIS_BU_DATA_정리_log.txt`: GUI 실행 로그입니다. `*_log.txt` 규칙으로 Git 추적 대상에서 제외합니다.

## 독립 CLI

- `BU_LotID_merge_v1.py`: 측정 데이터와 엑셀 작업 없이 최신 LotID 폴더 취합과 `merge_report.csv` 생성만 수행합니다.
- `BU_black_bg_crop_to_excel_v1.py`: LotID 취합과 측정 데이터 결합 없이 지정 폴더의 이미지 크롭과 엑셀 생성을 수행합니다.
- `BU_organize_one_click_v033.py`: 48×27 BU grid, worst-point 및 시각화 분석 기능을 담은 고급 분석 도구입니다. 표준 파이프라인과 별개로 계속 사용합니다.
- `bu_weakpoint_view.py`: v033 전용 weak point 위치 분포 시각화 모듈입니다.

## Weak Point 위치 분석 (v033)

LMK6 계측기가 출력하는 false-color 히트맵(파랑=양호 → 청록 → 초록 → 노랑 → 빨강=불량)에서 빨간 영역이 패널의 **어느 위치에** 몰려 있는지 확인하기 위한 기능입니다.

심각도는 색을 HSV 색상환 각도로 되돌려 계산합니다. 계측기 컬러맵 순서를 그대로 따르므로 파랑 0.0 → 청록 0.25 → 초록 0.5 → 노랑 0.75 → 빨강 1.0 으로 단조증가하며, 계측기가 얹은 흰색 글자나 회색 UI 같은 무채색은 후보에서 제외됩니다.

weak point 는 **노랑·주황·빨강 영역 전체**를 대상으로 합니다. 색상환에서 노랑과 연두가 갈리는 지점이 hue 70도이고 이를 심각도로 환산하면 0.708 이라, `WEAK_SEVERITY_MIN` 을 그 값으로 두었습니다. 기준을 바꾸려면 이 상수만 조정하면 됩니다.

`bu_grid_analysis.xlsx` 의 `요약` 시트 `AE` 열에 **Weak Point 위치 분포** 이미지가 삽입됩니다. 분석한 패널 전체를 누적해 위치별 weak 발생률과 평균 심각도를 나란히 보여주고, 반복해서 취약한 좌표 TOP5 를 캡션으로 적습니다. 여러 장에서 같은 자리가 반복되면 개별 패널 불량이 아니라 설비·공정 쪽 원인을 의심할 근거가 됩니다.

모듈을 직접 호출하면 패널 한 장에 대한 4분할 상세 도표도 만들 수 있습니다.

```python
from pathlib import Path
import bu_weakpoint_view as wv

analysis = wv.analyze_weak_points(Path("LOT001_BU_01.png"), grid_cols=48, grid_rows=27)
print(analysis.summary_text())
# weak 67셀 / 전체 1178셀 · 최다 집중 영역 좌상 (63셀, 해당영역의 50%)

wv.render_distribution_map(analysis, Path("dist.png"), source_image=Path("LOT001_BU_01.png"))
wv.render_aggregate_map([analysis], Path("aggregate.png"))
```

`render_distribution_map` 은 원본+weak 셀 윤곽, 심각도 그리드, 3×3 영역별 집중도, 행·열 프로파일을 한 장에 담습니다. `zone_distribution()` 은 좌상/중상/우상 … 형태의 9분할 집중도를 dict 로 돌려주므로 엑셀이나 로그에 그대로 쓸 수 있습니다.

`matplotlib` 이 필요하며, 한글 라벨은 Malgun Gothic → NanumGothic → Noto Sans CJK 순으로 탐색해 적용합니다.

`요약` 시트에는 LotID 행마다 `Weak 집중 영역` / `Weak 셀수` / `영역 점유율` 컬럼이 추가됩니다. 좌상·우상 같은 위치가 그림뿐 아니라 셀 값으로도 남아, 여러 LotID를 정렬·필터·피벗으로 한 번에 훑을 수 있습니다.

## EXE 빌드

프로젝트 폴더에서 버전 관리되는 spec 파일로 빌드합니다.

```bash
pyinstaller --clean TOVIS_BU_DATA_정리.spec
```

아이콘 파일 `tovis_bu_data.ico`가 같은 폴더에 있어야 합니다.
