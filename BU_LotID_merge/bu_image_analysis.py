"""BU Image 색 분포와 weak point 분석 (v06).

LMK6 계측기가 출력하는 BU(Black Uniformity) false-color 히트맵에서 제품별 색
분포를 집계하고, 취약 지점이 패널의 어느 위치에 몰려 있는지 9분할로 정리한다.

v033 및 `bu_weakpoint_view.py` 의 판정 기준은 사용하지 않는다. 두 모듈은
컬러맵을 "파랑=양호 → 빨강=불량" 으로 가정했는데, 실제 계측기 출력은
현장 기준으로 다음 순서다.

    초록(양호) → 청록 → 빨강 → 주황 → 노랑 → 흰색(최악)

첨부 실측 자료 53장으로 두 기준을 대조하면 차이가 분명하다. BU 수치와
색 비율의 상관계수가 v033 기준으로는 +0.04(무의미)였지만, 위 순서를 적용하면
노랑 -0.740 / 주황 -0.677 / 빨강 -0.601 로 모두 유의미한 음의 상관이 나온다.

흰색 처리에는 함정이 하나 있다. 계측기가 패널 위에 흰 글자와 테두리를 얹기
때문에 흰색 픽셀을 전부 최악값으로 보면 모든 패널의 상단이 weak point 로
잘못 잡힌다. 실측 확인 결과는 다음과 같았다.

    - 흰색 픽셀의 세로 획 길이 중앙값이 2~3px (글자 획 두께)
    - 침식을 걸수록 패널 본체가 아니라 상단으로 더 쏠림(80~99%)
    - 서로 다른 두 패널의 흰색 위치 IoU 가 0.005 (겹치지 않음)

그래서 `_is_real_white()` 로 두 단계를 거른다. 얇은 획을 침식으로 지우고,
남은 덩어리 주변이 노랑·주황인지(컬러맵 연속성) 확인한다. 실제 최악값이라면
흰색 바로 옆은 그 다음으로 나쁜 노랑이어야 하기 때문이다. 실측에서 불량품은
70.9%, 양품은 6.8% 로 갈렸다.

`matplotlib` 과 `cv2` 에 의존하지 않는다. numpy 와 Pillow 만 쓰므로 EXE 빌드가
가벼워지고, 두 패키지가 없는 환경에서도 그대로 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

# 채도가 이 값 이상이면 유채색(히트맵 본체)으로 본다.
CHROMATIC_SATURATION_MIN = 0.25

# 무채색이면서 명도가 이 값을 넘으면 흰색 후보다.
WHITE_VALUE_MIN = 0.55

# 최대 채널이 이 값 미만이면 검은 배경으로 본다.
BACKGROUND_MAX_CHANNEL = 40

# 색 구간 경계(HSV 색상환 각도). 계측기 출력 기준으로 잡았다.
HUE_RED_MAX = 15.0
HUE_ORANGE_MAX = 45.0
HUE_YELLOW_MAX = 70.0
HUE_GREEN_MAX = 180.0
HUE_CYAN_MAX = 260.0
HUE_RED_WRAP_MIN = 330.0

# 색별 심각도. 흰색이 가장 나쁘고 초록이 가장 좋다.
SEVERITY_WHITE = 1.00
SEVERITY_YELLOW = 0.80
SEVERITY_ORANGE = 0.60
SEVERITY_RED = 0.40
SEVERITY_CYAN = 0.15
SEVERITY_GREEN = 0.00

# 이 값 이상인 픽셀을 weak point 로 본다. 주황 이상이 대상이다.
WEAK_SEVERITY_MIN = 0.60

# 흰색 후보에서 글자 획을 지울 때 쓰는 침식 반경(px).
WHITE_EROSION_RADIUS = 3

# 침식 후 남은 흰색 덩어리 주변을 확인할 링의 안/바깥 반경(px).
WHITE_RING_INNER_RADIUS = 2
WHITE_RING_OUTER_RADIUS = 6

# 흰색 덩어리 주변에서 노랑·주황이 이 비율 이상이면 실제 데이터로 인정한다.
WHITE_NEIGHBOR_WARM_MIN = 0.40

# 히트맵 본체 경계를 찾을 때, 한 행/열의 유채색 비율이 이 값을 넘어야 본체로 본다.
PANEL_LINE_COVERAGE_MIN = 0.5

# 검출한 패널 경계에서 안쪽으로 깎아낼 비율. 계측기 테두리만 걷어낼 만큼 얕게 잡는다.
PANEL_INSET_RATIO = 0.015

# 9분할 영역 이름. 좌우를 먼저 부르는 현장 표기(좌상·중상·우상)를 따른다.
ZONE_COL_LABELS = ("좌", "중", "우")
ZONE_ROW_LABELS = ("상", "중", "하")
ZONE_NAMES = tuple(
    f"{ZONE_COL_LABELS[col]}{ZONE_ROW_LABELS[row]}"
    for row in range(3)
    for col in range(3)
)

COLOR_NAMES = ("흰색", "노랑", "주황", "빨강", "초록", "청록")


def _box_sum(mask: np.ndarray, radius: int) -> tuple[np.ndarray, np.ndarray]:
    """정사각 윈도우 안의 True 개수와 윈도우 크기를 적분영상으로 구한다.

    픽셀마다 슬라이딩하면 큰 이미지에서 느려서 누적합을 쓴다.
    """
    counts = mask.astype(np.int32)
    height, width = counts.shape

    integral = np.zeros((height + 1, width + 1), dtype=np.int32)
    integral[1:, 1:] = counts.cumsum(axis=0).cumsum(axis=1)

    y_low = np.clip(np.arange(height) - radius, 0, height)
    y_high = np.clip(np.arange(height) + radius + 1, 0, height)
    x_low = np.clip(np.arange(width) - radius, 0, width)
    x_high = np.clip(np.arange(width) + radius + 1, 0, width)

    total = (
        integral[y_high][:, x_high]
        - integral[y_low][:, x_high]
        - integral[y_high][:, x_low]
        + integral[y_low][:, x_low]
    )
    area = (y_high - y_low)[:, None] * (x_high - x_low)[None, :]
    return total, area


def _erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """윈도우가 전부 True 인 픽셀만 남긴다."""
    total, area = _box_sum(mask, radius)
    return total >= area


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """윈도우에 True 가 하나라도 있으면 True 로 만든다."""
    total, _ = _box_sum(mask, radius)
    return total > 0


def _decompose(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """RGB 배열을 색상환 각도, 채도, 명도, 최대채널로 벡터 변환한다."""
    array = rgb.astype(np.float32)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]

    maximum = array.max(axis=-1)
    minimum = array.min(axis=-1)
    delta = maximum - minimum
    safe_delta = np.where(delta == 0, 1e-9, delta)

    with np.errstate(divide="ignore", invalid="ignore"):
        saturation = np.where(maximum > 0, delta / np.maximum(maximum, 1e-9), 0.0)
        hue = np.where(
            maximum == red,
            ((green - blue) / safe_delta) % 6.0,
            np.where(
                maximum == green,
                ((blue - red) / safe_delta) + 2.0,
                ((red - green) / safe_delta) + 4.0,
            ),
        ) * 60.0

    return hue, saturation, maximum / 255.0, maximum


def find_panel_region(rgb: np.ndarray) -> tuple[int, int, int, int]:
    """히트맵 본체가 차지하는 영역을 찾아 안쪽으로 조금 깎아 돌려준다.

    반환값은 (top, bottom, left, right) 이고 bottom/right 는 exclusive 다.
    계측기 테두리와 헤더를 제외하되 제품 영역은 최대한 남긴다.
    """
    _, saturation, _, maximum = _decompose(rgb)
    heat = (saturation >= CHROMATIC_SATURATION_MIN) & (maximum >= BACKGROUND_MAX_CHANNEL)
    height, width = heat.shape

    rows = np.flatnonzero(heat.sum(axis=1) > width * PANEL_LINE_COVERAGE_MIN)
    cols = np.flatnonzero(heat.sum(axis=0) > height * PANEL_LINE_COVERAGE_MIN)
    if rows.size == 0 or cols.size == 0:
        return 0, height, 0, width

    top, bottom = int(rows[0]), int(rows[-1])
    left, right = int(cols[0]), int(cols[-1])

    inset_y = int((bottom - top) * PANEL_INSET_RATIO)
    inset_x = int((right - left) * PANEL_INSET_RATIO)

    top, bottom = top + inset_y, bottom - inset_y
    left, right = left + inset_x, right - inset_x
    if bottom <= top or right <= left:
        return 0, height, 0, width
    return top, bottom + 1, left, right + 1


def _is_real_white(
    white_blobs: np.ndarray,
    warm: np.ndarray,
) -> tuple[bool, float]:
    """남은 흰색 덩어리가 실제 측정값인지 계측기 글자인지 가른다.

    컬러맵이 연속이라면 최악값인 흰색 바로 옆은 그 다음으로 나쁜 노랑·주황이어야
    한다. 글자나 테두리는 초록 위에 그냥 얹혀 있으므로 주변이 따뜻한 색이 아니다.
    """
    if not white_blobs.any():
        return False, 0.0

    ring = _dilate(white_blobs, WHITE_RING_OUTER_RADIUS) & ~_dilate(
        white_blobs, WHITE_RING_INNER_RADIUS
    )
    ring_size = int(ring.sum())
    if ring_size == 0:
        return False, 0.0

    warm_ratio = float((ring & warm).sum() / ring_size)
    return warm_ratio >= WHITE_NEIGHBOR_WARM_MIN, warm_ratio


@dataclass
class BUImageAnalysis:
    """BU 이미지 한 장의 색 분포와 weak point 결과."""

    lot_id: str
    image_path: Path
    color_ratios: dict[str, float] = field(default_factory=dict)
    mean_severity: float = 0.0
    weak_ratio: float = 0.0
    zone_weak_ratios: dict[str, float] = field(default_factory=dict)
    dominant_zone: str = "없음"
    dominant_zone_ratio: float = 0.0
    white_is_real: bool = False
    white_warm_ratio: float = 0.0
    panel_region: tuple[int, int, int, int] = (0, 0, 0, 0)
    status: str = "OK"

    def summary_text(self) -> str:
        """로그 한 줄 요약."""
        if self.status != "OK":
            return f"{self.lot_id}: {self.status}"
        if self.dominant_zone == "없음":
            return f"{self.lot_id}: weak point 없음 (전 영역 양호)"
        return (
            f"{self.lot_id}: weak {self.weak_ratio * 100:.2f}% · "
            f"최다 집중 영역 {self.dominant_zone} ({self.dominant_zone_ratio * 100:.2f}%)"
        )


def analyze_bu_image(image_path: Path, lot_id: str = "") -> BUImageAnalysis:
    """BU 이미지 한 장의 색 분포와 9분할 weak point 를 계산한다."""
    label = lot_id or image_path.stem
    try:
        with Image.open(image_path) as image:
            rgb = np.asarray(image.convert("RGB"))
    except (OSError, ValueError) as error:
        return BUImageAnalysis(
            lot_id=label,
            image_path=image_path,
            status=f"ERROR: {error}",
        )

    top, bottom, left, right = find_panel_region(rgb)
    panel = rgb[top:bottom, left:right]
    if panel.size == 0:
        return BUImageAnalysis(
            lot_id=label,
            image_path=image_path,
            status="ERROR: 제품 영역을 찾지 못했습니다.",
        )

    hue, saturation, value, maximum = _decompose(panel)
    background = maximum < BACKGROUND_MAX_CHANNEL
    chromatic = (saturation >= CHROMATIC_SATURATION_MIN) & ~background

    red = chromatic & ((hue < HUE_RED_MAX) | (hue >= HUE_RED_WRAP_MIN))
    orange = chromatic & (hue >= HUE_RED_MAX) & (hue < HUE_ORANGE_MAX)
    yellow = chromatic & (hue >= HUE_ORANGE_MAX) & (hue < HUE_YELLOW_MAX)
    green = chromatic & (hue >= HUE_YELLOW_MAX) & (hue < HUE_GREEN_MAX)
    cyan = chromatic & (hue >= HUE_GREEN_MAX) & (hue < HUE_CYAN_MAX)

    white_candidates = ~chromatic & (value > WHITE_VALUE_MIN) & ~background
    white_blobs = _erode(white_candidates, WHITE_EROSION_RADIUS)
    white_is_real, warm_ratio = _is_real_white(white_blobs, yellow | orange)
    white = white_blobs if white_is_real else np.zeros_like(white_blobs)

    severity = np.full(panel.shape[:2], np.nan, dtype=np.float32)
    severity[cyan] = SEVERITY_CYAN
    severity[green] = SEVERITY_GREEN
    severity[red] = SEVERITY_RED
    severity[orange] = SEVERITY_ORANGE
    severity[yellow] = SEVERITY_YELLOW
    severity[white_candidates] = np.nan
    severity[white] = SEVERITY_WHITE
    severity[background] = np.nan

    measured = int(np.count_nonzero(~np.isnan(severity)))
    if measured == 0:
        return BUImageAnalysis(
            lot_id=label,
            image_path=image_path,
            panel_region=(top, bottom, left, right),
            status="ERROR: 측정 가능한 픽셀이 없습니다.",
        )

    ratios = {
        "흰색": float(white.sum()) / measured,
        "노랑": float(yellow.sum()) / measured,
        "주황": float(orange.sum()) / measured,
        "빨강": float(red.sum()) / measured,
        "초록": float(green.sum()) / measured,
        "청록": float(cyan.sum()) / measured,
    }

    weak = severity >= WEAK_SEVERITY_MIN
    height, width = severity.shape
    zone_ratios: dict[str, float] = {}
    for row in range(3):
        for col in range(3):
            block = severity[
                row * height // 3 : (row + 1) * height // 3,
                col * width // 3 : (col + 1) * width // 3,
            ]
            valid = ~np.isnan(block)
            name = f"{ZONE_COL_LABELS[col]}{ZONE_ROW_LABELS[row]}"
            if not valid.any():
                zone_ratios[name] = 0.0
                continue
            zone_ratios[name] = float((block[valid] >= WEAK_SEVERITY_MIN).mean())

    dominant_zone, dominant_ratio = max(zone_ratios.items(), key=lambda item: item[1])
    if dominant_ratio <= 0.0:
        dominant_zone = "없음"

    return BUImageAnalysis(
        lot_id=label,
        image_path=image_path,
        color_ratios=ratios,
        mean_severity=float(np.nanmean(severity)),
        weak_ratio=float(np.count_nonzero(weak) / measured),
        zone_weak_ratios=zone_ratios,
        dominant_zone=dominant_zone,
        dominant_zone_ratio=dominant_ratio,
        white_is_real=white_is_real,
        white_warm_ratio=warm_ratio,
        panel_region=(top, bottom, left, right),
    )


def aggregate_zone_stats(analyses: list[BUImageAnalysis]) -> dict[str, dict]:
    """여러 패널을 겹쳐 위치별 취약 통계를 낸다.

    한 장만 보면 개별 패널 불량일 수 있지만, 여러 장에서 같은 자리가 반복되면
    설비나 공정 쪽 원인을 의심할 근거가 된다.
    """
    valid = [item for item in analyses if item.status == "OK"]
    stats: dict[str, dict] = {}
    for name in ZONE_NAMES:
        ratios = [item.zone_weak_ratios.get(name, 0.0) for item in valid]
        hits = sum(1 for ratio in ratios if ratio > 0.0)
        stats[name] = {
            "평균 weak 비율": (sum(ratios) / len(ratios)) if ratios else 0.0,
            "최대 weak 비율": max(ratios, default=0.0),
            "검출 제품 수": hits,
            "검출 비율": (hits / len(valid)) if valid else 0.0,
        }
    return stats
