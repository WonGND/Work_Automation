"""차트 캔버스와 사용자 상호작용 위젯."""

import platform
from pathlib import Path

import matplotlib

matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5 import QtCore, QtGui, QtWidgets

from theme import BORDER, PRIMARY, TEXT_MAIN


# 운영체제별 1순위 폰트를 먼저 보고, 없으면 뒤 후보로 넘어간다.
# 기존 구현은 설치 여부를 확인하지 않고 이름만 넣어서, 해당 폰트가 없는 PC 에서는
# 차트 한글이 통째로 두부(네모)로 깨졌다.
_KOREAN_FONT_CANDIDATES = {
    "Windows": ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Gulim"),
    "Darwin": ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "Noto Sans CJK KR"),
}
_KOREAN_FONT_FALLBACK = ("NanumGothic", "Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic")


def setup_korean_font() -> str | None:
    """실제 설치된 한국어 폰트를 골라 적용하고 그 이름을 돌려준다."""
    from matplotlib import font_manager

    matplotlib.rcParams["axes.unicode_minus"] = False
    candidates = _KOREAN_FONT_CANDIDATES.get(platform.system(), _KOREAN_FONT_FALLBACK)

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            matplotlib.rcParams["font.family"] = name
            return name

    for path in font_manager.findSystemFonts(fontext="ttf"):
        lowered = Path(path).name.lower()
        if not any(key in lowered for key in ("malgun", "nanum", "notosanscjk", "gulim")):
            continue
        try:
            font_manager.fontManager.addfont(path)
            resolved = font_manager.FontProperties(fname=path).get_name()
        except (RuntimeError, OSError, ValueError):
            continue
        matplotlib.rcParams["font.family"] = resolved
        return resolved

    return None


setup_korean_font()


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(8, 5), dpi=100, facecolor="white")
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.fig.tight_layout()


class ColorButton(QtWidgets.QPushButton):
    colorChanged = QtCore.pyqtSignal()

    def __init__(self, color="#6699CC"):
        super().__init__()
        self._color = color
        self.setFixedWidth(110)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.clicked.connect(self._pick_color)
        self._refresh()

    def _pick_color(self):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self._color), self, "색상 선택"
        )
        if color.isValid():
            self._color = color.name()
            self._refresh()
            self.colorChanged.emit()

    def _refresh(self):
        self.setStyleSheet(
            "QPushButton{background:#FFFFFF; border:1px solid %s;"
            "border-radius:12px; padding:6px 10px; text-align:left;"
            "color:%s; font-weight:600;}"
            "QPushButton:hover{border:1px solid %s;}" % (BORDER, TEXT_MAIN, PRIMARY)
        )
        pixmap = QtGui.QPixmap(16, 16)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtGui.QColor(self._color))
        painter.setPen(QtGui.QColor(BORDER))
        painter.drawRoundedRect(0, 0, 15, 15, 4, 4)
        painter.end()
        self.setIcon(QtGui.QIcon(pixmap))
        self.setIconSize(QtCore.QSize(16, 16))
        self.setText("  " + self._color)

    def color(self):
        return self._color


class BoxInteractor:
    """범례와 통계 박스의 드래그 및 휠 조작을 처리한다."""

    def __init__(self, win, canvas):
        self.win = win
        self.canvas = canvas
        self.legend = None
        self.stat_text = None
        self.drag_target = None
        self.press_xy = None
        canvas.mpl_connect("button_press_event", self.on_press)
        canvas.mpl_connect("button_release_event", self.on_release)
        canvas.mpl_connect("motion_notify_event", self.on_motion)
        canvas.mpl_connect("scroll_event", self.on_scroll)

    def set_artists(self, legend, stat_text):
        self.legend = legend
        self.stat_text = stat_text

    def _hit(self, artist, event):
        if artist is None or event.x is None:
            return False
        try:
            bbox = artist.get_window_extent()
        except (RuntimeError, ValueError, AttributeError):
            # 아직 렌더링되지 않은 아티스트는 히트 판정 대상이 아니다.
            # 이 경로는 마우스 이동마다 호출되므로 절대 다이얼로그를 띄우면 안 된다.
            return False
        return bbox.contains(event.x, event.y)

    def on_press(self, event):
        if self._hit(self.stat_text, event):
            self.drag_target = "stat"
        elif self._hit(self.legend, event):
            self.drag_target = "legend"
        else:
            self.drag_target = None
            return
        self.press_xy = (event.x, event.y)

    def on_release(self, _event):
        if self.drag_target is not None:
            self.win.schedule_drag_redraw()
        self.drag_target = None
        self.press_xy = None

    def on_motion(self, event):
        if self.drag_target is None or event.x is None or self.press_xy is None:
            return
        box = self.canvas.ax.get_window_extent()
        dx = (event.x - self.press_xy[0]) / box.width
        dy = (event.y - self.press_xy[1]) / box.height
        self.press_xy = (event.x, event.y)
        if self.drag_target == "stat":
            self.win.stat_pos[0] += dx
            self.win.stat_pos[1] += dy
        else:
            self.win.legend_anchor[0] += dx
            self.win.legend_anchor[1] += dy
        self.win.schedule_drag_redraw()

    def on_scroll(self, event):
        step = 1 if event.button == "up" else -1
        if self._hit(self.stat_text, event):
            self.win.spn_stat.setValue(self.win.spn_stat.value() + step)
        elif self._hit(self.legend, event):
            self.win.spn_legend.setValue(self.win.spn_legend.value() + step)
