import csv
import io
import re
import sys
from pathlib import Path

import numpy as np
from openpyxl.drawing.image import Image as XLImage
from PIL import Image


ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
LOT_PATTERN = re.compile(r"^(?P<lotid>.+)_(?P<kind>BU|WU)_\d+$", re.IGNORECASE)
CSV_ENCODINGS = ("utf-8-sig", "cp949", "euc-kr", "utf-8")


def print_progress(
    label: str,
    current: int,
    total: int,
    done: bool = False,
    carriage_return: bool | None = None,
) -> None:
    """터미널에서는 한 줄을 갱신하고 GUI/파일 출력에서는 줄 단위로 기록한다."""
    if total <= 0:
        return
    if carriage_return is None:
        isatty = getattr(sys.stdout, "isatty", None)
        carriage_return = bool(isatty and isatty())
    percent = current / total * 100
    end = "\r" if carriage_return and not done else "\n"
    print(f"{label}: {current}/{total} ({percent:5.1f}%)", end=end, flush=True)


def print_stage(step: int, total_steps: int, title: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"\n[{step}/{total_steps}] {title}{suffix}")


def print_file_created(path, label: str = "") -> None:
    from pathlib import Path as _Path

    target = _Path(path)
    size_text = ""
    try:
        size_kb = target.stat().st_size / 1024
        size_text = f", {size_kb:,.0f} KB" if size_kb >= 1 else ", 1 KB 미만"
    except OSError:
        pass
    prefix = f"{label} " if label else ""
    print(f"  -> {prefix}{target.name} 파일 생성 완료{size_text}")



def parse_lot_kind(stem: str) -> tuple[str, str]:
    """확장자를 제외한 파일명 전체가 규칙과 일치할 때 LotID와 종류를 반환한다."""
    match = LOT_PATTERN.fullmatch(stem)
    if match is None:
        return stem, "UNKNOWN"
    return match.group("lotid"), match.group("kind").upper()


def normalize_lot_id(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return re.sub(r"[\s_-]+", "", text).upper()


def find_non_black_bbox(
    img: Image.Image,
    threshold: int = 12,
) -> tuple[int, int, int, int] | None:
    """PIL crop 규약에 맞는 우측/하단 exclusive 비검정 영역을 찾는다."""
    gray = np.asarray(img.convert("L"))
    rows = np.any(gray > threshold, axis=1)
    cols = np.any(gray > threshold, axis=0)
    if not rows.any() or not cols.any():
        return None
    min_y, max_y = np.flatnonzero(rows)[[0, -1]]
    min_x, max_x = np.flatnonzero(cols)[[0, -1]]
    return int(min_x), int(min_y), int(max_x + 1), int(max_y + 1)


def iter_csv_dict_rows(csv_path: Path) -> list[dict[str, str]]:
    last_error: UnicodeDecodeError | None = None
    for encoding in CSV_ENCODINGS:
        try:
            with csv_path.open("r", encoding=encoding, newline="") as file:
                return list(csv.DictReader(file))
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise UnicodeDecodeError(
            last_error.encoding,
            last_error.object,
            last_error.start,
            last_error.end,
            f"{csv_path} 파일 인코딩을 읽지 못함",
        )
    raise OSError(f"{csv_path} 파일을 읽지 못했습니다.")


def get_resized_xl_image(image_path: Path, max_width_px: int) -> XLImage | None:
    """작은 PNG는 원본을 사용하고 리사이즈가 필요할 때만 PNG로 재인코딩한다."""
    if not image_path.exists():
        return None
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            if width <= max_width_px and image.format == "PNG":
                return XLImage(str(image_path))
            if width > max_width_px:
                ratio = max_width_px / width
                image = image.resize(
                    (max_width_px, max(1, int(height * ratio))),
                    Image.Resampling.LANCZOS,
                )
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            buffer.seek(0)
            return XLImage(buffer)
    except (OSError, ValueError) as exc:
        print(f"이미지 엑셀 변환 실패: {image_path} ({exc})")
        return None
