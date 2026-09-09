"""BU weak point 공간 분포 시각화.

`BU_organize_one_click_v033.py` 전용 모듈이다. LMK6 계측기가 뽑아내는
false-color 히트맵(파랑=양호 → 청록 → 초록 → 노랑 → 빨강=불량)을 입력으로
받아, 빨간 영역(weak point)이 패널의 "어디에" 몰려 있는지 한눈에 보이도록
그린다.

기존 v033 의 `compute_red_white_score()` 는 휘도(luminance)와 붉은 정도를
가중합해 점수를 매겼다. 이 방식은 계측기 컬러맵의 실제 순서를 따르지 않아
아래와 같이 어긋난다.

    파랑(가장 양호)  v033 점수  0.014   <- 초록보다 높다
    초록(중간)       v033 점수 -0.857
    흰색(글자/반사)  v033 점수  1.600   <- 빨강 다음으로 높다

즉 가장 양호한 파랑 영역과 계측기가 얹은 흰색 오버레이가 weak point 로
잘못 뽑힐 수 있다. 이 모듈은 색을 HSV 색상환으로 되돌려 컬러맵 상의 위치
자체를 심각도로 환산하므로 그런 역전이 생기지 않는다.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# 계측기 컬러맵의 양 끝 색상(HSV 색상환 각도)
# 파랑 240도 = 가장 양호, 빨강 0도 = 가장 불량
HUE_BEST_DEG = 240.0
HUE_WORST_DEG = 0.0

# 채도가 이보다 낮으면 무채색(흰색 글자, 회색 테두리, 계측기 UI)으로 보고 제외한다.
# 히트맵 본체는 채도가 높아서 이 값으로 안전하게 갈린다.
ACHROMATIC_SATURATION_MAX = 0.25

# 명도가 이보다 낮으면 배경(검정)으로 본다.
BACKGROUND_VALUE_MAX = 0.16

# 자홍(300도 초과)은 빨강을 넘어선 오버레인지이므로 최대 심각도로 취급한다.
HUE_OVERRANGE_MIN_DEG = 300.0

# 심각도가 이 값 이상인 셀을 weak point 로 본다.
# 노랑·주황·빨강 영역 전체가 대상이다. 색상환에서 노랑과 연두가 갈리는 지점이
# hue 70도이고 이를 심각도로 환산하면 0.708 이라, 그 값을 경계로 쓴다.
WEAK_SEVERITY_MIN = 0.708

# 셀이 유효하려면 이 비율 이상이 히트맵 픽셀이어야 한다.
CELL_CONTENT_RATIO_MIN = 0.70

# 9분할 영역 이름. 좌우를 먼저 부르는 현장 표기(좌상·중상·우상)를 따른다.
ZONE_COL_LABELS = ("좌", "중", "우")
ZONE_ROW_LABELS = ("상", "중", "하")

# 한글 라벨이 두부(□)로 깨지지 않도록 우선순위대로 탐색한다.
# Windows 실사용 환경은 Malgun Gothic, 리눅스 빌드 환경은 Noto/Nanum 이 잡힌다.
KOREAN_FONT_CANDIDATES = (
    "Malgun Gothic",
    "NanumGothic",
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "AppleGothic",
)


def apply_korean_font() -> str | None:
    """matplotlib 한글 폰트를 설정하고 적용된 폰트 이름을 돌려준다."""
    from matplotlib import font_manager, rcParams

    rcParams["axes.unicode_minus"] = False

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in KOREAN_FONT_CANDIDATES:
        if name in available:
            rcParams["font.family"] = name
            return name

    scanned = list(font_manager.findSystemFonts(fontext="ttf"))
    scanned += [
        str(path)
        for root in font_manager.OSXFontDirectories + font_manager.X11FontDirectories
        for path in Path(root).rglob("*.ttc")
        if Path(root).is_dir()
    ]
    for path in scanned:
        lowered = Path(path).name.lower()
        if not any(key in lowered for key in ("notosanscjk", "nanum", "malgun")):
            continue
        try:
            font_manager.fontManager.addfont(path)
            resolved = font_manager.FontProperties(fname=path).get_name()
        except (RuntimeError, OSError, ValueError):
            continue
        rcParams["font.family"] = resolved
        return resolved

    return None


def severity_from_rgb(rgb) -> float | None:
    """계측기 컬러맵 색상 하나를 0.0(양호) ~ 1.0(불량) 심각도로 되돌린다.

    배경이나 무채색(흰 글자, 회색 UI)이면 None 을 준다.
    """
    r, g, b = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    hue_frac, saturation, value = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

    if value <= BACKGROUND_VALUE_MAX:
        return None
    if saturation <= ACHROMATIC_SATURATION_MAX:
        return None

    hue = hue_frac * 360.0
    if hue >= HUE_OVERRANGE_MIN_DEG:
        return 1.0

    span = HUE_BEST_DEG - HUE_WORST_DEG
    return max(0.0, min(1.0, (HUE_BEST_DEG - hue) / span))


def severity_map_from_array(rgb_array: np.ndarray) -> np.ndarray:
    """이미지 배열 전체를 심각도 배열로 벡터 변환한다.

    픽셀마다 `colorsys` 를 부르면 수백만 번 호출이라 느리므로 numpy 로 처리한다.
    유효하지 않은 픽셀(배경/무채색)은 NaN 으로 남긴다.
    """
    arr = rgb_array.astype(np.float32) / 255.0
    red, green, blue = arr[..., 0], arr[..., 1], arr[..., 2]

    value = arr.max(axis=-1)
    minimum = arr.min(axis=-1)
    delta = value - minimum

    with np.errstate(divide="ignore", invalid="ignore"):
        saturation = np.where(value > 0, delta / np.maximum(value, 1e-12), 0.0)

        hue = np.zeros_like(value)
        mask = delta > 1e-12
        r_max = mask & (value == red)
        g_max = mask & (value == green) & ~r_max
        b_max = mask & (value == blue) & ~r_max & ~g_max
        hue[r_max] = ((green - blue)[r_max] / delta[r_max]) % 6.0
        hue[g_max] = ((blue - red)[g_max] / delta[g_max]) + 2.0
        hue[b_max] = ((red - green)[b_max] / delta[b_max]) + 4.0
        hue *= 60.0

    severity = (HUE_BEST_DEG - hue) / (HUE_BEST_DEG - HUE_WORST_DEG)
    severity = np.clip(severity, 0.0, 1.0)
    severity[hue >= HUE_OVERRANGE_MIN_DEG] = 1.0

    invalid = (value <= BACKGROUND_VALUE_MAX) | (saturation <= ACHROMATIC_SATURATION_MAX)
    severity[invalid] = np.nan
    return severity


@dataclass
class WeakPointCell:
    """그리드 셀 하나의 판정 결과."""

    row: int
    col: int
    severity: float
    content_ratio: float

    @property
    def coord(self) -> str:
        return f"({self.col},{self.row})"


@dataclass
class WeakPointAnalysis:
    """패널 한 장의 weak point 분포."""

    grid_rows: int
    grid_cols: int
    severity_grid: np.ndarray
    cells: list[WeakPointCell] = field(default_factory=list)
    image_size: tuple[int, int] = (0, 0)
    label: str = ""

    @property
    def weak_cells(self) -> list[WeakPointCell]:
        """심각도 높은 순으로 정렬된 weak point 목록."""
        weak = [c for c in self.cells if c.severity >= WEAK_SEVERITY_MIN]
        return sorted(weak, key=lambda c: (-c.severity, c.row, c.col))

    @property
    def valid_cell_count(self) -> int:
        return len(self.cells)

    def zone_distribution(self) -> dict[str, dict]:
        """패널을 3x3 으로 나눠 영역별 weak point 집중도를 낸다.

        "주로 어디에 몰려 있는가" 에 답하기 위한 핵심 지표다.
        """
        zones: dict[str, dict] = {}
        weak = self.weak_cells
        for zr in range(3):
            for zc in range(3):
                r0 = zr * self.grid_rows // 3
                r1 = (zr + 1) * self.grid_rows // 3
                c0 = zc * self.grid_cols // 3
                c1 = (zc + 1) * self.grid_cols // 3

                total = sum(
                    1 for c in self.cells
                    if r0 < c.row <= r1 and c0 < c.col <= c1
                )
                hit = [
                    c for c in weak
                    if r0 < c.row <= r1 and c0 < c.col <= c1
                ]
                name = f"{ZONE_COL_LABELS[zc]}{ZONE_ROW_LABELS[zr]}"
                zones[name] = {
                    "weak_count": len(hit),
                    "cell_count": total,
                    "ratio": (len(hit) / total) if total else 0.0,
                    "max_severity": max((c.severity for c in hit), default=0.0),
                }
        return zones

    def dominant_zone(self) -> tuple[str, dict] | None:
        """weak point 가 가장 많이 몰린 영역."""
        zones = self.zone_distribution()
        ranked = sorted(
            zones.items(),
            key=lambda kv: (-kv[1]["weak_count"], -kv[1]["ratio"]),
        )
        if not ranked or ranked[0][1]["weak_count"] == 0:
            return None
        return ranked[0]

    def summary_text(self) -> str:
        """사람이 읽는 한 줄 요약."""
        weak = self.weak_cells
        if not weak:
            return "weak point 없음 (전 영역 양호)"
        dominant = self.dominant_zone()
        head = f"weak {len(weak)}셀 / 전체 {self.valid_cell_count}셀"
        if dominant is None:
            return head
        name, info = dominant
        return (
            f"{head} · 최다 집중 영역 {name} "
            f"({info['weak_count']}셀, 해당영역의 {info['ratio']*100:.0f}%)"
        )


def analyze_weak_points(
    image_path: Path,
    grid_cols: int,
    grid_rows: int,
    label: str = "",
) -> WeakPointAnalysis:
    """히트맵 이미지를 그리드로 나눠 셀별 심각도를 계산한다."""
    with Image.open(image_path) as img:
        rgb = np.asarray(img.convert("RGB"))

    height, width, _ = rgb.shape
    severity = severity_map_from_array(rgb)

    x_edges = [round(i * width / grid_cols) for i in range(grid_cols + 1)]
    y_edges = [round(i * height / grid_rows) for i in range(grid_rows + 1)]

    grid = np.full((grid_rows, grid_cols), np.nan, dtype=np.float32)
    cells: list[WeakPointCell] = []

    for r in range(grid_rows):
        for c in range(grid_cols):
            block = severity[y_edges[r]:y_edges[r + 1], x_edges[c]:x_edges[c + 1]]
            if block.size == 0:
                continue
            valid = ~np.isnan(block)
            ratio = float(valid.mean())
            if ratio < CELL_CONTENT_RATIO_MIN:
                continue
            cell_severity = float(np.nanmean(block))
            grid[r, c] = cell_severity
            cells.append(
                WeakPointCell(
                    row=r + 1,
                    col=c + 1,
                    severity=cell_severity,
                    content_ratio=ratio,
                )
            )

    return WeakPointAnalysis(
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        severity_grid=grid,
        cells=cells,
        image_size=(width, height),
        label=label,
    )


def render_distribution_map(
    analysis: WeakPointAnalysis,
    output_path: Path,
    source_image: Path | None = None,
) -> Path:
    """weak point 분포를 4분할 도표 한 장으로 그린다.

    좌상: 원본 히트맵 + weak 셀 윤곽
    우상: 심각도 그리드(정량화된 48x27)
    좌하: 3x3 영역별 집중도
    우하: 행/열 프로파일 — 어느 행·열에 몰렸는지
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    apply_korean_font()

    cmap = LinearSegmentedColormap.from_list(
        "lmk_severity",
        ["#1e3a8a", "#0891b2", "#16a34a", "#facc15", "#ea580c", "#dc2626"],
    )

    fig, axes = plt.subplots(2, 2, figsize=(16, 9), dpi=140)
    fig.patch.set_facecolor("#0b1220")
    title = analysis.label or output_path.stem
    fig.suptitle(
        f"{title}   weak point 분포",
        color="#f8fafc", fontsize=15, fontweight="bold", y=0.98,
    )

    for ax in axes.ravel():
        ax.set_facecolor("#0f172a")
        for spine in ax.spines.values():
            spine.set_color("#334155")
        ax.tick_params(colors="#cbd5e1", labelsize=8)

    weak = analysis.weak_cells
    grid_rows, grid_cols = analysis.grid_rows, analysis.grid_cols

    ax = axes[0][0]
    ax.set_title("원본 히트맵 + weak 셀", color="#f8fafc", fontsize=11, pad=8)
    if source_image is not None and Path(source_image).exists():
        with Image.open(source_image) as img:
            ax.imshow(img.convert("RGB"))
        width, height = analysis.image_size
        for cell in weak:
            x0 = (cell.col - 1) * width / grid_cols
            y0 = (cell.row - 1) * height / grid_rows
            ax.add_patch(
                Rectangle(
                    (x0, y0), width / grid_cols, height / grid_rows,
                    fill=False, edgecolor="#ffffff", linewidth=0.9, alpha=0.95,
                )
            )
        ax.set_xlim(0, width)
        ax.set_ylim(height, 0)
    ax.set_xticks([])
    ax.set_yticks([])

    ax = axes[0][1]
    ax.set_title(
        f"심각도 그리드 ({grid_cols}x{grid_rows})", color="#f8fafc", fontsize=11, pad=8
    )
    masked = np.ma.masked_invalid(analysis.severity_grid)
    mesh = ax.imshow(
        masked, cmap=cmap, vmin=0.0, vmax=1.0,
        interpolation="nearest", aspect="auto",
    )
    for cell in weak:
        ax.add_patch(
            Rectangle(
                (cell.col - 1.5, cell.row - 1.5), 1, 1,
                fill=False, edgecolor="#ffffff", linewidth=0.7,
            )
        )
    ax.set_xlabel("열 (col)", color="#cbd5e1", fontsize=9)
    ax.set_ylabel("행 (row)", color="#cbd5e1", fontsize=9)
    bar = fig.colorbar(mesh, ax=ax, fraction=0.035, pad=0.02)
    bar.set_label("심각도 (0 양호 → 1 불량)", color="#cbd5e1", fontsize=8)
    bar.ax.tick_params(colors="#cbd5e1", labelsize=7)

    ax = axes[1][0]
    ax.set_title("영역별 weak 집중도", color="#f8fafc", fontsize=11, pad=8)
    zones = analysis.zone_distribution()
    zone_grid = np.zeros((3, 3))
    for zr in range(3):
        for zc in range(3):
            name = f"{ZONE_COL_LABELS[zc]}{ZONE_ROW_LABELS[zr]}"
            zone_grid[zr][zc] = zones[name]["ratio"]
    ax.imshow(zone_grid, cmap=cmap, vmin=0.0, vmax=max(0.001, zone_grid.max()))
    for zr in range(3):
        for zc in range(3):
            name = f"{ZONE_COL_LABELS[zc]}{ZONE_ROW_LABELS[zr]}"
            info = zones[name]
            ax.text(
                zc, zr,
                f"{name}\n{info['weak_count']}셀\n{info['ratio']*100:.0f}%",
                ha="center", va="center", fontsize=10,
                color="#ffffff", fontweight="bold",
            )
    ax.set_xticks([])
    ax.set_yticks([])

    ax = axes[1][1]
    ax.set_title("행·열별 weak 셀 수", color="#f8fafc", fontsize=11, pad=8)
    col_counts = np.zeros(grid_cols)
    row_counts = np.zeros(grid_rows)
    for cell in weak:
        col_counts[cell.col - 1] += 1
        row_counts[cell.row - 1] += 1
    ax.bar(
        np.arange(1, grid_cols + 1), col_counts,
        color="#f97316", width=0.85, label="열(col)별",
    )
    ax.set_xlabel("열 (col)", color="#cbd5e1", fontsize=9)
    ax.set_ylabel("weak 셀 수", color="#f97316", fontsize=9)

    twin = ax.twiny()
    twin.plot(
        np.arange(1, grid_rows + 1), row_counts,
        color="#38bdf8", marker="o", markersize=3, linewidth=1.6, label="행(row)별",
    )
    twin.set_xlabel("행 (row)", color="#38bdf8", fontsize=9)
    twin.tick_params(colors="#38bdf8", labelsize=8)
    for spine in twin.spines.values():
        spine.set_color("#334155")

    handles = [
        Line2D([], [], color="#f97316", linewidth=6, label="열(col)별"),
        Line2D([], [], color="#38bdf8", marker="o", label="행(row)별"),
    ]
    legend = ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.25)
    for text in legend.get_texts():
        text.set_color("#e2e8f0")

    fig.text(
        0.5, 0.015, analysis.summary_text(),
        ha="center", color="#fbbf24", fontsize=11, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.955))
    fig.savefig(output_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


def render_aggregate_map(
    analyses: list[WeakPointAnalysis],
    output_path: Path,
) -> Path:
    """여러 패널의 weak point 를 겹쳐 "설비 공통 취약 위치" 를 찾는다.

    한 장짜리 분포는 그 패널의 개별 불량일 수 있지만, 여러 장에서 같은 자리가
    반복해서 빨갛다면 설비/공정 쪽 문제로 볼 근거가 된다.
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    valid = [a for a in analyses if a.valid_cell_count > 0]
    if not valid:
        raise ValueError("집계할 분석 결과가 없습니다.")

    grid_rows = valid[0].grid_rows
    grid_cols = valid[0].grid_cols
    hit_count = np.zeros((grid_rows, grid_cols), dtype=float)
    severity_sum = np.zeros((grid_rows, grid_cols), dtype=float)
    observed = np.zeros((grid_rows, grid_cols), dtype=float)

    for analysis in valid:
        if analysis.grid_rows != grid_rows or analysis.grid_cols != grid_cols:
            continue
        finite = np.isfinite(analysis.severity_grid)
        observed += finite
        filled = np.where(finite, analysis.severity_grid, 0.0)
        severity_sum += filled
        hit_count += (filled >= WEAK_SEVERITY_MIN) & finite

    with np.errstate(invalid="ignore", divide="ignore"):
        hit_rate = np.where(observed > 0, hit_count / np.maximum(observed, 1), np.nan)
        mean_severity = np.where(
            observed > 0, severity_sum / np.maximum(observed, 1), np.nan
        )

    cmap = LinearSegmentedColormap.from_list(
        "lmk_severity",
        ["#1e3a8a", "#0891b2", "#16a34a", "#facc15", "#ea580c", "#dc2626"],
    )
    apply_korean_font()
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), dpi=140)
    fig.patch.set_facecolor("#0b1220")
    fig.suptitle(
        f"패널 {len(valid)}장 누적 weak point 분포",
        color="#f8fafc", fontsize=15, fontweight="bold",
    )

    for ax, data, title, label in (
        (axes[0], hit_rate, "위치별 weak 발생률", "발생률 (0~1)"),
        (axes[1], mean_severity, "위치별 평균 심각도", "심각도 (0~1)"),
    ):
        ax.set_facecolor("#0f172a")
        ax.set_title(title, color="#f8fafc", fontsize=11, pad=8)
        mesh = ax.imshow(
            np.ma.masked_invalid(data), cmap=cmap, vmin=0.0, vmax=1.0,
            interpolation="nearest", aspect="auto",
        )
        ax.set_xlabel("열 (col)", color="#cbd5e1", fontsize=9)
        ax.set_ylabel("행 (row)", color="#cbd5e1", fontsize=9)
        ax.tick_params(colors="#cbd5e1", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#334155")
        bar = fig.colorbar(mesh, ax=ax, fraction=0.035, pad=0.02)
        bar.set_label(label, color="#cbd5e1", fontsize=8)
        bar.ax.tick_params(colors="#cbd5e1", labelsize=7)

    flat = [
        (hit_rate[r][c], r + 1, c + 1)
        for r in range(grid_rows) for c in range(grid_cols)
        if np.isfinite(hit_rate[r][c]) and hit_rate[r][c] > 0
    ]
    flat.sort(reverse=True)
    if flat:
        top = "  ".join(f"({c},{r}) {v*100:.0f}%" for v, r, c in flat[:5])
        caption = f"반복 취약 위치 TOP5 → {top}"
    else:
        caption = "누적 weak point 없음"
    fig.text(
        0.5, 0.02, caption,
        ha="center", color="#fbbf24", fontsize=11, fontweight="bold",
    )

    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    fig.savefig(output_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path
