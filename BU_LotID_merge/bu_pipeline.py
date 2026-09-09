import csv
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import PatternFill
from PIL import Image

from bu_common import (
    ALLOWED_EXTENSIONS,
    find_non_black_bbox,
    get_resized_xl_image,
    iter_csv_dict_rows,
    normalize_lot_id,
    parse_lot_kind,
    print_progress,
)

DATA_FILE_PATTERN = "LMK6DataLog.csv"
BU_SPEC_MIN = 50.0
WU_SPEC_MIN = 80.0
MODEL_NAME_CANDIDATES = (
    "Model_Name", "ModelName", "Model", "RecipeName", "Recipe", "Product", "Product_Name",
)
LOT_ID_CANDIDATES = ("Panel_ID", "LotID", "Lot_ID", "PanelID", "Panel Id")

class PipelineCancelled(Exception):
    pass

def ensure_not_cancelled(cancel_check=None) -> None:
    if cancel_check and cancel_check():
        raise PipelineCancelled("사용자 요청으로 작업이 중지되었습니다.")

def first_row_value(row: dict, candidates: tuple[str, ...]) -> str:
    for key in candidates:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""

def parse_lmk_time(value, fallback_path: Path) -> datetime:
    raw = "" if value is None else str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_path.stat().st_mtime)

def collect_latest_lotid_folders(
    integrated_root: Path,
    cancel_check=None,
    recursive: bool = True,
) -> tuple[dict[str, Path], list[dict]]:
    """이미지가 직접 든 LotID 폴더를 찾아 이름별 최신 폴더를 고른다.

    recursive=False는 예전 v0.5의 직계 하위 폴더 범위가 필요한 경우를 위한 선택지다.
    """
    candidates = integrated_root.rglob("*") if recursive else integrated_root.iterdir()
    lotid_folders = [
        folder
        for folder in candidates
        if folder.is_dir()
        and any(
            child.is_file() and child.suffix.lower() in ALLOWED_EXTENSIONS
            for child in folder.iterdir()
        )
    ]
    total = len(lotid_folders)
    scope = "전체 하위" if recursive else "직계 하위"
    print(f"\n[1/5] LotID 폴더 스캔 시작 ({scope}, 대상 폴더: {total}개)")

    latest_by_lotid: dict[str, Path] = {}
    latest_times: dict[str, tuple[float, float]] = {}
    all_rows: list[dict] = []

    for idx, folder in enumerate(lotid_folders, start=1):
        ensure_not_cancelled(cancel_check)
        lot_id = folder.name
        stat = folder.stat()
        folder_time = (stat.st_ctime, stat.st_mtime)
        
        row = {
            "lot_id": lot_id,
            "folder_path": str(folder),
            "created_time": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "modified_time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }

        if lot_id not in latest_by_lotid or folder_time > latest_times[lot_id]:
            latest_by_lotid[lot_id] = folder
            latest_times[lot_id] = folder_time

        all_rows.append(row)
        if idx == 1 or idx % 50 == 0 or idx == total:
            print_progress("  스캔 진행", idx, total, done=(idx == total))

    selected = {str(path) for path in latest_by_lotid.values()}
    for row in all_rows:
        row["selected_latest_final"] = "TRUE" if row["folder_path"] in selected else "FALSE"
    return latest_by_lotid, all_rows

def copy_latest_folders(latest_by_lotid: dict[str, Path], dst_root: Path, cancel_check=None) -> None:
    dst_root.mkdir(parents=True, exist_ok=True)
    selected_names = set(latest_by_lotid)
    for stale in dst_root.iterdir():
        if stale.name not in selected_names:
            if stale.is_dir():
                shutil.rmtree(stale)
            else:
                stale.unlink()

    items = sorted(latest_by_lotid.items())
    total = len(items)
    print(f"\n[2/5] 최신 LotID 폴더 병렬 복사 시작 (대상: {total}개)")
    lock = threading.Lock()
    copied = 0

    def copy_one(item: tuple[str, Path]) -> None:
        nonlocal copied
        ensure_not_cancelled(cancel_check)
        lot_id, src_path = item
        destination = dst_root / lot_id
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(src_path, destination)
        with lock:
            copied += 1
            if copied == 1 or copied % 20 == 0 or copied == total:
                print_progress("  복사 진행", copied, total, done=copied == total)

    max_workers = min(16, max(1, len(items)), (os.cpu_count() or 4) + 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(copy_one, items))

def collect_latest_measurements(data_root: Path, cancel_check=None) -> tuple[dict[str, dict], list[dict]]:
    csv_files = sorted(data_root.rglob(DATA_FILE_PATTERN))
    total = len(csv_files)
    print(f"\n[3/5] 측정 CSV 스캔 시작 (대상 파일: {total}개)")

    latest_measurements: dict[str, dict] = {}
    all_measurement_rows = []
    if total == 0:
        print("  측정 CSV를 찾지 못해서 판정/BU/WU data는 공란으로 둡니다.")
        return latest_measurements, all_measurement_rows

    for idx, csv_path in enumerate(csv_files, start=1):
        ensure_not_cancelled(cancel_check)
        try:
            for row_data in iter_csv_dict_rows(csv_path):
                lot_id = first_row_value(row_data, LOT_ID_CANDIDATES)
                if not lot_id:
                    continue

                time_str = str(row_data.get("Time", "")).strip()
                time_val = parse_lmk_time(time_str, csv_path)

                m_row = {
                    "lot_id": lot_id,
                    "judge": str(row_data.get("Judge", "")).strip(),
                    "black_uniformity": str(row_data.get("Black_Uniformity", "")).strip(),
                    "white_uniformity": str(row_data.get("White_Uniformity", "")).strip(),
                    "time_raw": time_val,
                    "time_str": time_str,
                    "model_name": first_row_value(row_data, MODEL_NAME_CANDIDATES),
                    "source_file": str(csv_path),
                }

                normalized_lot_id = normalize_lot_id(lot_id)
                if (
                    normalized_lot_id not in latest_measurements
                    or time_val > latest_measurements[normalized_lot_id]["time_raw"]
                ):
                    latest_measurements[normalized_lot_id] = m_row
                all_measurement_rows.append({**m_row, "status": "OK"})
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            print(f"  CSV 읽기 실패: {csv_path} ({exc})")
            all_measurement_rows.append(
                {
                    "lot_id": "",
                    "judge": "",
                    "black_uniformity": "",
                    "white_uniformity": "",
                    "time_raw": "",
                    "time_str": "",
                    "model_name": "",
                    "source_file": str(csv_path),
                    "status": f"ERROR: {exc}",
                }
            )

        if idx == 1 or idx % 50 == 0 or idx == total:
            print_progress("  CSV 스캔 진행", idx, total, done=(idx == total))

    return latest_measurements, all_measurement_rows

def find_measurement(lot_id: str, latest_measurements: dict[str, dict]) -> dict:
    normalized = normalize_lot_id(lot_id)
    if normalized in latest_measurements:
        return latest_measurements[normalized]
    candidates = [
        (key, measurement)
        for key, measurement in latest_measurements.items()
        if normalized and (normalized in key or key in normalized)
    ]
    if candidates:
        longest = max(len(key) for key, _ in candidates)
        best = [(key, measurement) for key, measurement in candidates if len(key) == longest]
        if len(best) == 1:
            key, measurement = best[0]
            print(f"  측정값 유사 LotID 연결: {lot_id} -> {key}")
            return measurement
        print(f"  측정값 유사 LotID가 모호하여 연결하지 않음: {lot_id}")
    return {}

def excel_measurement_value(value):
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    try:
        return float(text)
    except ValueError:
        return text

def crop_images(merged_root: Path, cropped_root: Path, threshold: int, padding: int, cancel_check=None) -> list[dict]:
    if cropped_root.exists():
        shutil.rmtree(cropped_root)
    cropped_root.mkdir(parents=True, exist_ok=True)

    image_files = sorted(
        path
        for path in merged_root.rglob("*")
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
    )
    
    total = len(image_files)
    print(f"\n[4/5] 이미지 크롭 시작 (대상: {total}개, 멀티스레드 활성화)")

    records = []
    lock = threading.Lock()
    processed_count = 0

    def process_one(src: Path) -> None:
        nonlocal processed_count
        ensure_not_cancelled(cancel_check)
        
        rel_path = src.relative_to(merged_root)
        dst = cropped_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        lot_id, kind = parse_lot_kind(src.stem)

        try:
            with Image.open(src) as img:
                bbox = find_non_black_bbox(img, threshold=threshold)
                if bbox is None:
                    status = "NO_OBJECT_DETECTED"
                    used_bbox = (0, 0, img.width, img.height)
                    cropped = img.copy()
                else:
                    status = "OK"
                    x_min, y_min, x_max, y_max = bbox
                    used_bbox = (max(0, x_min-padding), max(0, y_min-padding), min(img.width, x_max+padding), min(img.height, y_max+padding))
                    cropped = img.crop(used_bbox)

                if dst.suffix.lower() in (".jpg", ".jpeg") and cropped.mode not in ("RGB", "L"):
                    cropped = cropped.convert("RGB")
                cropped.save(dst)
            
            record = {"lot_id": lot_id, "kind": kind, "src": src, "dst": dst, "bbox": used_bbox, "status": status}
        except Exception as exc:
            record = {"lot_id": lot_id, "kind": kind, "src": src, "dst": None, "bbox": None, "status": f"ERROR: {exc}"}
            print(f"  이미지 크롭 실패: {src} ({exc})")

        with lock:
            records.append(record)
            processed_count += 1
            if processed_count == 1 or processed_count % 20 == 0 or processed_count == total:
                print_progress("  크롭 진행", processed_count, total, done=(processed_count == total))

    max_workers = min(32, (os.cpu_count() or 4) + 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(process_one, image_files))

    records.sort(key=lambda record: str(record["src"]))
    return records

def write_excel(
    records,
    excel_path: Path,
    latest_measurements=None,
    merge_rows=None,
    measurement_rows=None,
    image_width_px: int = 240,
    cancel_check=None,
):
    wb = Workbook()
    ws = wb.active
    if ws is None:
        raise RuntimeError("엑셀 결과 시트를 만들지 못했습니다.")
    ws.title = "결과"
    ws.append(["LotID", "판정", "BU data 수치화", "BU Image", "WU data", "WU Image"])
    print(f"\n[5/5] 엑셀 작성 시작 (이미지 기록: {len(records)}개)")

    grouped = {}
    for rec in records:
        lot_id, kind = rec["lot_id"], rec["kind"]
        grouped.setdefault(lot_id, {"BU": None, "WU": None})
        if kind in ("BU", "WU") and rec["dst"] and not grouped[lot_id][kind]:
            grouped[lot_id][kind] = rec["dst"]

    row_idx = 2
    for lot_id in sorted(grouped.keys()):
        ensure_not_cancelled(cancel_check)
        ws.cell(row=row_idx, column=1, value=lot_id)
        m = find_measurement(lot_id, latest_measurements or {})
        ws.cell(row=row_idx, column=2, value=m.get("judge", ""))
        ws.cell(row=row_idx, column=3, value=excel_measurement_value(m.get("black_uniformity", "")))
        ws.cell(row=row_idx, column=5, value=excel_measurement_value(m.get("white_uniformity", "")))

        max_h = 0
        for col, kind in [("D", "BU"), ("F", "WU")]:
            img_path = grouped[lot_id][kind]
            if img_path and Path(img_path).exists():
                xl_img = get_resized_xl_image(Path(img_path), image_width_px)
                if xl_img:
                    ws.add_image(xl_img, f"{col}{row_idx}")
                    max_h = max(max_h, xl_img.height)

        ws.row_dimensions[row_idx].height = max(25, int(max_h * 0.75))
        row_idx += 1

    # 조건부 서식
    last_row = max(2, row_idx - 1)
    green_fill = PatternFill("solid", fgColor="D1FAE5")
    red_fill = PatternFill("solid", fgColor="FEE2E2")
    yellow_fill = PatternFill("solid", fgColor="FEF3C7")
    
    ws.conditional_formatting.add(f"B2:B{last_row}", FormulaRule(formula=['B2="OK"'], fill=green_fill))
    ws.conditional_formatting.add(f"B2:B{last_row}", FormulaRule(formula=['B2="NG"'], fill=red_fill))
    ws.conditional_formatting.add(f"C2:C{last_row}", CellIsRule(operator="lessThan", formula=[str(BU_SPEC_MIN)], fill=yellow_fill))
    ws.conditional_formatting.add(f"E2:E{last_row}", CellIsRule(operator="lessThan", formula=[str(WU_SPEC_MIN)], fill=yellow_fill))

    # 컬럼 너비
    for col, width in zip("ABCDEF", [26, 12, 14, 36, 14, 36]):
        ws.column_dimensions[col].width = width

    detail_ws = wb.create_sheet("처리_상세")
    detail_ws.append(["구분", "LotID", "종류", "상태", "원본 경로", "결과 경로", "기타"])
    for record in records:
        detail_ws.append(
            [
                "CROP",
                record["lot_id"],
                record["kind"],
                record["status"],
                str(record["src"]),
                "" if record["dst"] is None else str(record["dst"]),
                "" if record["bbox"] is None else str(record["bbox"]),
            ]
        )
    for row in merge_rows or []:
        detail_ws.append(
            [
                "MERGE",
                row["lot_id"],
                "",
                "SELECTED" if row.get("selected_latest_final") == "TRUE" else "EXCLUDED",
                row["folder_path"],
                "",
                f"created={row['created_time']}, modified={row['modified_time']}",
            ]
        )
    for row in measurement_rows or []:
        detail_ws.append(
            [
                "MEASURE",
                row.get("lot_id", ""),
                "",
                row.get("status", "OK"),
                row.get("source_file", ""),
                "",
                f"time={row.get('time_str', '')}, BU={row.get('black_uniformity', '')}, WU={row.get('white_uniformity', '')}",
            ]
        )
    for column, width in zip("ABCDEFG", [12, 26, 10, 28, 60, 60, 48]):
        detail_ws.column_dimensions[column].width = width

    print("\n메인 엑셀 저장")
    wb.save(excel_path)

def write_merge_report(rows: list[dict], output_root: Path) -> Path:
    report_path = output_root / "merge_report.csv"
    fieldnames = ["lot_id", "folder_path", "created_time", "modified_time", "selected_latest_final"]
    with report_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return report_path

def run_pipeline(integrated_root: Path, data_root: Path, threshold: int, padding: int, cancel_check=None) -> dict:
    cropped_root = integrated_root.parent / f"{integrated_root.name}_LotID_latest_v1_cropped_v1"
    excel_path = cropped_root / "crop_report.xlsx"

    ensure_not_cancelled(cancel_check)
    latest_folders, merge_rows = collect_latest_lotid_folders(integrated_root, cancel_check)
    if not latest_folders:
        raise RuntimeError("LotID 폴더를 찾지 못했습니다. 이미지 통합 폴더 구조를 확인하세요.")

    merged_root = integrated_root.parent / f"{integrated_root.name}_LotID_latest_v1"
    copy_latest_folders(latest_folders, merged_root, cancel_check)
    merge_report_path = write_merge_report(merge_rows, merged_root)
    
    latest_m, measurement_rows = collect_latest_measurements(data_root, cancel_check)
    crop_records = crop_images(merged_root, cropped_root, threshold, padding, cancel_check)
    
    write_excel(
        crop_records,
        excel_path,
        latest_m,
        merge_rows,
        measurement_rows,
        cancel_check=cancel_check,
    )

    success_count = sum(1 for record in crop_records if record["status"] == "OK")
    error_count = sum(1 for record in crop_records if record["status"].startswith("ERROR"))
    print("\n--- 최종 결과 ---")
    print(f"완료! (크롭 성공: {success_count}, 오류: {error_count})")

    return {
        "merged_root": merged_root,
        "cropped_root": cropped_root,
        "excel_path": excel_path,
        "merge_report_path": merge_report_path,
        "latest_lotids": len(latest_folders),
        "crop_records": len(crop_records),
        "crop_ok": success_count,
        "crop_error": error_count,
    }

if __name__ == "__main__":
    print("\n--- BU Organize One Click ---")
    ir = Path(input("1) 이미지 통합 폴더: ").strip())
    dr = Path(input("2) 측정 데이터 폴더: ").strip())
    th = int(input("3) 임계값 [12]: ") or 12)
    padding = int(input("4) 패딩 [20]: ") or 20)
    run_pipeline(ir, dr, th, padding)
