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
- `BU_organize_one_click_v033.py`: 표준 경로에서는 사용하지 않는 기존 48×27 BU grid, worst-point 및 시각화 분석 기능을 보존한 레거시 고급 분석 도구입니다.

## EXE 빌드

프로젝트 폴더에서 버전 관리되는 spec 파일로 빌드합니다.

```bash
pyinstaller --clean TOVIS_BU_DATA_정리.spec
```

아이콘 파일 `tovis_bu_data.ico`가 같은 폴더에 있어야 합니다.
