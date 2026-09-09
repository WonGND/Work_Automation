# =============================================================================
#  CpkAnalyzer - Process Capability Analysis Tool (Minitab-style Cp/Cpk GUI)
#  공정능력 분석 데스크탑 애플리케이션 (Toss-style UI)
# -----------------------------------------------------------------------------
#  [필요 패키지 설치]
#    pip install -r requirements.txt
#      또는
#    pip install PyQt5 matplotlib pandas numpy scipy openpyxl xlrd
#
#  [실행]
#    python main.py
#
#  [수식]
#    Cp  = (USL - LSL) / (6 * StdDev)
#    Cpk = min((USL - Mean)/(3*StdDev), (Mean - LSL)/(3*StdDev))
#    PPM = (P(x<LSL) + P(x>USL)) * 1,000,000   # scipy.stats.norm.cdf 사용
# =============================================================================

import sys
import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PyQt5 import QtCore, QtGui, QtWidgets


# -----------------------------------------------------------------------------
# 한국어 폰트 설정 (OS 별 자동 선택)
# -----------------------------------------------------------------------------
def setup_korean_font():
    import platform
    system = platform.system()
    if system == "Windows":
        font = "Malgun Gothic"
    elif system == "Darwin":          # macOS
        font = "AppleGothic"
    else:                              # Linux
        font = "NanumGothic"
    matplotlib.rcParams["font.family"] = font
    matplotlib.rcParams["axes.unicode_minus"] = False    # 마이너스 깨짐 방지


setup_korean_font()


# =============================================================================
#  Toss-style 디자인 토큰 (design.md 기반)
# =============================================================================
PRIMARY      = "#0064FF"   # Primary Blue
PRIMARY_DK   = "#0050CC"
SUBTLE_GRAY  = "#F2F4F7"   # 보조 배경
BORDER       = "#E4E7EC"   # 입력 테두리
TEXT_MAIN    = "#191F28"
TEXT_SUB     = "#6B7684"
OK_GREEN     = "#12B886"
NG_RED       = "#FF3B30"

STYLE_SHEET = f"""
QMainWindow, QWidget {{
    background-color: #FFFFFF;
    color: {TEXT_MAIN};
    font-family: "Malgun Gothic", "Pretendard", sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    background-color: #FFFFFF;
    border: 1px solid {BORDER};
    border-radius: 18px;
    margin-top: 14px;
    padding: 14px 16px 16px 16px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    padding: 0 6px;
    color: {TEXT_SUB};
}}
QLabel {{ color: {TEXT_MAIN}; }}
QLineEdit, QPlainTextEdit, QComboBox {{
    background-color: #FFFFFF;
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 7px 10px;
    selection-background-color: {PRIMARY};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 2px solid {PRIMARY};
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {PRIMARY};
    selection-color: #FFFFFF;
    background: #FFFFFF;
}}
/* 보조(Secondary) 버튼 */
QPushButton {{
    background-color: {SUBTLE_GRAY};
    color: {TEXT_MAIN};
    border: none;
    border-radius: 12px;
    padding: 8px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: #E8EBF0; }}
QPushButton:pressed {{ background-color: #DCE0E8; }}
/* Primary 버튼 */
QPushButton#primary {{
    background-color: {PRIMARY};
    color: #FFFFFF;
    padding: 11px;
    font-size: 14px;
}}
QPushButton#primary:hover {{ background-color: {PRIMARY_DK}; }}
/* 체크박스 */
QCheckBox {{ color: {TEXT_SUB}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: #FFFFFF;
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border: 1px solid {PRIMARY};
    image: none;
}}
QSpinBox, QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 6px 8px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {PRIMARY}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}
QStatusBar {{ color: {TEXT_SUB}; }}
"""


# =============================================================================
#  통계 계산 모듈
# =============================================================================
class CapabilityResult:
    """공정능력 분석 결과를 담는 데이터 클래스"""
    def __init__(self, data, lsl, usl):
        self.data = np.asarray(data, dtype=float)
        self.data = self.data[~np.isnan(self.data)]   # NaN 제거
        self.lsl = lsl
        self.usl = usl
        self._compute()

    def _compute(self):
        d = self.data
        self.n = len(d)
        if self.n < 2:
            raise ValueError("분석을 위해 최소 2개 이상의 데이터가 필요합니다.")
        self.mean = float(np.mean(d))
        self.std = float(np.std(d, ddof=1))           # 표본 표준편차
        if self.std <= 0:
            raise ValueError("표준편차가 0입니다. 데이터 값이 모두 동일합니다.")

        # Cp / Cpk
        self.cp = (self.usl - self.lsl) / (6.0 * self.std)
        cpu = (self.usl - self.mean) / (3.0 * self.std)
        cpl = (self.mean - self.lsl) / (3.0 * self.std)
        self.cpk = min(cpu, cpl)

        # PPM (규격 이탈 확률)
        p_below = stats.norm.cdf(self.lsl, self.mean, self.std)
        p_above = 1.0 - stats.norm.cdf(self.usl, self.mean, self.std)
        self.ppm = (p_below + p_above) * 1_000_000


# =============================================================================
#  Matplotlib 캔버스 (PyQt5 임베딩)
# =============================================================================
class MplCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(8, 5), dpi=100, facecolor="white")
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.fig.tight_layout()


# =============================================================================
#  컬러 선택 버튼 (배경은 항상 흰색, 선택색은 작은 스와치 칩으로 표시)
# =============================================================================
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
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self._color), self,
                                              "색상 선택")
        if col.isValid():
            self._color = col.name()
            self._refresh()
            self.colorChanged.emit()

    def _refresh(self):
        # 항상 흰 배경 + 좌측 색상 스와치 칩 + HEX 텍스트
        self.setStyleSheet(
            "QPushButton{background:#FFFFFF; border:1px solid %s;"
            "border-radius:12px; padding:6px 10px; text-align:left;"
            "color:%s; font-weight:600;}"
            "QPushButton:hover{border:1px solid %s;}" % (BORDER, TEXT_MAIN, PRIMARY)
        )
        # 스와치 아이콘 생성
        pix = QtGui.QPixmap(16, 16)
        pix.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QColor(self._color))
        p.setPen(QtGui.QColor(BORDER))
        p.drawRoundedRect(0, 0, 15, 15, 4, 4)
        p.end()
        self.setIcon(QtGui.QIcon(pix))
        self.setIconSize(QtCore.QSize(16, 16))
        self.setText("  " + self._color)

    def color(self):
        return self._color


# =============================================================================
#  마우스 인터랙션 (범례 / 통계박스: 드래그=이동, 스크롤=크기 조절)
# =============================================================================
class BoxInteractor:
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
        except Exception:
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

    def on_release(self, event):
        self.drag_target = None
        self.press_xy = None

    def on_motion(self, event):
        if self.drag_target is None or event.x is None or self.press_xy is None:
            return
        box = self.win.canvas.ax.get_window_extent()
        dx = (event.x - self.press_xy[0]) / box.width
        dy = (event.y - self.press_xy[1]) / box.height
        self.press_xy = (event.x, event.y)
        if self.drag_target == "stat":
            self.win.stat_pos[0] += dx
            self.win.stat_pos[1] += dy
        else:
            self.win.legend_anchor[0] += dx
            self.win.legend_anchor[1] += dy
        self.win.draw_chart()

    def on_scroll(self, event):
        step = 1 if event.button == "up" else -1
        if self._hit(self.stat_text, event):
            self.win.spn_stat.setValue(self.win.spn_stat.value() + step)
        elif self._hit(self.legend, event):
            self.win.spn_legend.setValue(self.win.spn_legend.value() + step)


# =============================================================================
#  메인 윈도우
# =============================================================================
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("공정능력 분석 (Process Capability Analysis)")
        self.resize(1180, 840)

        self.df = None                 # 로드된 DataFrame
        self.result = None             # 최근 분석 결과
        self.legend_anchor = [0.01, 0.99]   # 범례 위치 (드래그로 이동)
        self.stat_pos = [0.98, 0.98]        # 통계박스 위치 (드래그로 이동)

        self._build_ui()

    # ----------------------------------------------------------------- UI 구성
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # ===== 상단 입력부 (카드) =====
        top = QtWidgets.QGroupBox("입력 / 파라미터 설정")
        grid = QtWidgets.QGridLayout(top)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        # --- 1행: 파일 불러오기 / 컬럼 선택 / 수동 입력 ---
        self.btn_load = QtWidgets.QPushButton("파일 불러오기 (Excel/CSV)")
        self.btn_load.clicked.connect(self.load_file)
        self.cmb_column = QtWidgets.QComboBox()
        self.cmb_column.setMinimumWidth(170)
        grid.addWidget(self.btn_load, 0, 0, 1, 2)
        grid.addWidget(QtWidgets.QLabel("분석 컬럼"), 0, 2)
        grid.addWidget(self.cmb_column, 0, 3, 1, 2)

        grid.addWidget(QtWidgets.QLabel("수동 입력\n(콤마/줄바꿈)"), 0, 5)
        self.txt_manual = QtWidgets.QPlainTextEdit()
        self.txt_manual.setPlaceholderText("예: 51, 49, 53, 47 ...  (파일 미사용 시)")
        self.txt_manual.setFixedHeight(56)
        grid.addWidget(self.txt_manual, 0, 6, 1, 4)

        # --- 2행: 규격 / Cpk 기준 ---
        self.ed_lsl = self._num_edit("50")
        self.ed_usl = self._num_edit("100")
        self.ed_cpk_crit = self._num_edit("1.33")
        grid.addWidget(QtWidgets.QLabel("LSL"), 1, 0)
        grid.addWidget(self.ed_lsl, 1, 1)
        grid.addWidget(QtWidgets.QLabel("USL"), 1, 2)
        grid.addWidget(self.ed_usl, 1, 3)
        grid.addWidget(QtWidgets.QLabel("Cpk 기준"), 1, 4)
        grid.addWidget(self.ed_cpk_crit, 1, 5)

        # --- 3행: 제목 (+표시 체크박스) / X축 라벨 (+표시 체크박스) ---
        self.chk_title = self._check("제목 표시", True)
        self.ed_title = QtWidgets.QLineEdit("공정능력 분석")
        self.chk_xlabel = self._check("X축 라벨 표시", True)
        self.ed_xlabel = QtWidgets.QLineEdit("측정값")
        grid.addWidget(self.chk_title, 2, 0)
        grid.addWidget(self.ed_title, 2, 1, 1, 3)
        grid.addWidget(self.chk_xlabel, 2, 4)
        grid.addWidget(self.ed_xlabel, 2, 5, 1, 5)

        # --- 4행: X축 범위 / NG 표시 체크박스 ---
        self.ed_xmin = self._num_edit("0")
        self.ed_xmax = self._num_edit("100")
        grid.addWidget(QtWidgets.QLabel("X축 Min"), 3, 0)
        grid.addWidget(self.ed_xmin, 3, 1)
        grid.addWidget(QtWidgets.QLabel("X축 Max"), 3, 2)
        grid.addWidget(self.ed_xmax, 3, 3)
        self.chk_verdict = self._check("OK/NG 판정 표시", True)
        grid.addWidget(self.chk_verdict, 3, 4, 1, 2)

        # --- 5행: 색상 + 각 색상 표시 체크박스 ---
        self.col_hist = ColorButton("#0bccaf")    # 히스토그램
        self.col_curve = ColorButton("#1F4E79")   # 정규분포 곡선
        self.col_ng = ColorButton("#FFC9C9")      # NG 음영
        self.chk_ng_fill = self._check("NG 음영 표시", True)
        grid.addWidget(QtWidgets.QLabel("히스토그램색"), 4, 0)
        grid.addWidget(self.col_hist, 4, 1)
        grid.addWidget(QtWidgets.QLabel("곡선색"), 4, 2)
        grid.addWidget(self.col_curve, 4, 3)
        grid.addWidget(QtWidgets.QLabel("NG음영색"), 4, 4)
        grid.addWidget(self.col_ng, 4, 5)
        grid.addWidget(self.chk_ng_fill, 4, 6, 1, 2)

        # --- 6행: 박스(범례/통계) 크기 조절 컨트롤 ---
        box_bar = QtWidgets.QWidget()
        hb = QtWidgets.QHBoxLayout(box_bar)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(8)

        self.chk_legend = self._check("범례(Observed) 표시", True)
        self.spn_legend = QtWidgets.QSpinBox()
        self.spn_legend.setRange(6, 30)
        self.spn_legend.setValue(9)
        self.spn_legend.setFixedWidth(70)

        self.chk_stat = self._check("통계박스 표시", True)
        self.spn_stat = QtWidgets.QSpinBox()
        self.spn_stat.setRange(6, 30)
        self.spn_stat.setValue(10)
        self.spn_stat.setFixedWidth(70)

        self.spn_stat_pad = QtWidgets.QDoubleSpinBox()
        self.spn_stat_pad.setRange(0.1, 3.0)
        self.spn_stat_pad.setSingleStep(0.1)
        self.spn_stat_pad.setValue(0.4)
        self.spn_stat_pad.setFixedWidth(80)

        hb.addWidget(self.chk_legend)
        hb.addWidget(QtWidgets.QLabel("범례 크기"))
        hb.addWidget(self.spn_legend)
        hb.addSpacing(14)
        hb.addWidget(self.chk_stat)
        hb.addWidget(QtWidgets.QLabel("통계 글자"))
        hb.addWidget(self.spn_stat)
        hb.addWidget(QtWidgets.QLabel("통계 여백"))
        hb.addWidget(self.spn_stat_pad)
        hb.addStretch(1)
        hint = QtWidgets.QLabel("드래그=이동 · 마우스 휠=크기 조절")
        hint.setStyleSheet("color:%s; font-size:12px;" % TEXT_SUB)
        hb.addWidget(hint)
        grid.addWidget(box_bar, 5, 0, 1, 10)

        # --- 7행: 분석 실행 버튼 ---
        self.btn_run = QtWidgets.QPushButton("분석 실행")
        self.btn_run.setObjectName("primary")
        self.btn_run.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self.run_analysis)
        grid.addWidget(self.btn_run, 6, 0, 1, 10)

        root.addWidget(top)

        # ----- 실시간 반영 시그널 연결 -----
        for cb in (self.col_hist, self.col_curve, self.col_ng):
            cb.colorChanged.connect(self.redraw_if_ready)
        self.ed_title.textChanged.connect(self.redraw_if_ready)
        self.ed_xlabel.textChanged.connect(self.redraw_if_ready)
        for chk in (self.chk_title, self.chk_xlabel,
                    self.chk_verdict, self.chk_ng_fill,
                    self.chk_legend, self.chk_stat):
            chk.toggled.connect(self.redraw_if_ready)
        for spn in (self.spn_legend, self.spn_stat, self.spn_stat_pad):
            spn.valueChanged.connect(self.redraw_if_ready)

        # ===== 중앙 차트부 (카드) =====
        chart_card = QtWidgets.QGroupBox("분석 결과")
        cv = QtWidgets.QVBoxLayout(chart_card)
        self.canvas = MplCanvas(self)
        self.interactor = BoxInteractor(self, self.canvas)   # 마우스 조작 연결
        cv.addWidget(self.canvas)
        root.addWidget(chart_card, stretch=1)

        # ===== 하단 저장부 =====
        bottom = QtWidgets.QHBoxLayout()
        self.btn_save = QtWidgets.QPushButton("이미지 저장 (PNG/JPG/SVG)")
        self.btn_save.clicked.connect(self.save_image)
        bottom.addWidget(self.btn_save)
        bottom.addStretch(1)
        bottom.addWidget(QtWidgets.QLabel("DPI"))
        self.cmb_dpi = QtWidgets.QComboBox()
        self.cmb_dpi.addItems(["150", "300", "600"])
        self.cmb_dpi.setCurrentText("300")
        self.cmb_dpi.setFixedWidth(90)
        bottom.addWidget(self.cmb_dpi)
        root.addLayout(bottom)

        # 상태바
        self.statusBar().showMessage("준비됨 — 파일을 불러오거나 수동 데이터를 입력하세요.")

    # --------- 위젯 헬퍼 ---------
    def _num_edit(self, default=""):
        e = QtWidgets.QLineEdit(default)
        e.setValidator(QtGui.QDoubleValidator())
        e.setFixedWidth(90)
        return e

    def _check(self, text, checked=True):
        c = QtWidgets.QCheckBox(text)
        c.setChecked(checked)
        c.setCursor(QtCore.Qt.PointingHandCursor)
        return c

    # --------------------------------------------------------------- 파일 로드
    def load_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "",
            "데이터 파일 (*.xlsx *.xls *.csv);;모든 파일 (*.*)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                self.df = pd.read_csv(path)
            else:
                self.df = pd.read_excel(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "파일 로드 실패",
                                           f"파일을 읽을 수 없습니다.\n\n{e}")
            return

        numeric_cols = [c for c in self.df.columns
                        if pd.api.types.is_numeric_dtype(self.df[c])]
        if not numeric_cols:
            QtWidgets.QMessageBox.warning(self, "경고", "숫자형 컬럼이 없습니다.")
            return
        self.cmb_column.clear()
        self.cmb_column.addItems([str(c) for c in numeric_cols])
        self.statusBar().showMessage(
            f"로드 완료: {path}  (행 {len(self.df)}개, 숫자컬럼 {len(numeric_cols)}개)")

    # ----------------------------------------------------------- 데이터 취득
    def _get_data(self):
        manual_text = self.txt_manual.toPlainText().strip()
        if self.df is not None and self.cmb_column.currentText():
            col = self.cmb_column.currentText()
            col_key = None
            for c in self.df.columns:
                if str(c) == col:
                    col_key = c
                    break
            if col_key is not None:
                return pd.to_numeric(self.df[col_key],
                                     errors="coerce").dropna().values
        if manual_text:
            raw = manual_text.replace("\n", ",").replace("\t", ",")
            tokens = [t.strip() for t in raw.split(",") if t.strip()]
            vals = []
            for t in tokens:
                try:
                    vals.append(float(t))
                except ValueError:
                    continue
            if not vals:
                raise ValueError("수동 입력에서 유효한 숫자를 찾지 못했습니다.")
            return np.array(vals)
        raise ValueError("데이터가 없습니다. 파일을 불러오거나 수동 입력을 작성하세요.")

    def _get_params(self):
        def to_float(edit, name):
            txt = edit.text().strip().replace(",", "")
            if txt == "":
                raise ValueError(f"'{name}' 값을 입력하세요.")
            return float(txt)

        lsl = to_float(self.ed_lsl, "LSL")
        usl = to_float(self.ed_usl, "USL")
        if usl <= lsl:
            raise ValueError("USL은 LSL보다 커야 합니다.")
        cpk_crit = to_float(self.ed_cpk_crit, "Cpk 기준")
        xmin = to_float(self.ed_xmin, "X축 Min")
        xmax = to_float(self.ed_xmax, "X축 Max")
        if xmax <= xmin:
            raise ValueError("X축 Max는 Min보다 커야 합니다.")
        return lsl, usl, cpk_crit, xmin, xmax

    # --------------------------------------------------------------- 분석 실행
    def run_analysis(self):
        try:
            data = self._get_data()
            lsl, usl, cpk_crit, xmin, xmax = self._get_params()
            self.result = CapabilityResult(data, lsl, usl)
            self._cpk_crit = cpk_crit
            self._xrange = (xmin, xmax)
            self.draw_chart()
            verdict = "OK" if self.result.cpk >= cpk_crit else "NG"
            self.statusBar().showMessage(
                f"분석 완료 — N={self.result.n}, Cpk={self.result.cpk:.3f} -> {verdict}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "분석 오류", str(e))

    def redraw_if_ready(self):
        if self.result is not None:
            self.draw_chart()

    # --------------------------------------------------------------- 차트 그리기
    def draw_chart(self):
        r = self.result
        ax = self.canvas.ax
        ax.clear()

        xmin, xmax = self._xrange
        c_hist = self.col_hist.color()
        c_curve = self.col_curve.color()
        c_ng = self.col_ng.color()

        # 히스토그램
        bins = max(10, int(np.sqrt(r.n)) + 5)
        ax.hist(r.data, bins=bins, range=(xmin, xmax), density=True,
                color=c_hist, alpha=0.85, edgecolor="white",
                label="Observed")

        # 정규분포 피팅 곡선
        xs = np.linspace(xmin, xmax, 400)
        ys = stats.norm.pdf(xs, r.mean, r.std)
        ax.plot(xs, ys, color=c_curve, lw=2.4, label="Normal Fit")

        # NG 음영 (체크박스 ON 시에만)
        if self.chk_ng_fill.isChecked():
            left = xs[xs <= r.lsl]
            right = xs[xs >= r.usl]
            if len(left):
                ax.fill_between(left, stats.norm.pdf(left, r.mean, r.std),
                                color=c_ng, alpha=0.7)
            if len(right):
                ax.fill_between(right, stats.norm.pdf(right, r.mean, r.std),
                                color=c_ng, alpha=0.7)

        # LSL / USL 점선
        ax.axvline(r.lsl, color=NG_RED, ls="--", lw=1.6, label=f"LSL={r.lsl:g}")
        ax.axvline(r.usl, color=NG_RED, ls=":", lw=1.6, alpha=0.7,
                   label=f"USL={r.usl:g}")

        # 제목 (체크박스 ON 시에만)
        if self.chk_title.isChecked():
            ax.set_title(self.ed_title.text(), fontsize=15, pad=12,
                         color=TEXT_MAIN, fontweight="bold")
        else:
            ax.set_title("")

        # X축 라벨 (체크박스 ON 시에만)
        if self.chk_xlabel.isChecked():
            ax.set_xlabel(self.ed_xlabel.text())
        else:
            ax.set_xlabel("")

        ax.set_ylabel("Density")
        ax.set_xlim(xmin, xmax)

        # 범례 (Observed) - 표시 여부 / 크기 / 드래그 위치 반영
        legend = None
        if self.chk_legend.isChecked():
            legend = ax.legend(loc="upper left",
                               bbox_to_anchor=tuple(self.legend_anchor),
                               fontsize=self.spn_legend.value(),
                               framealpha=0.9)

        # 통계 박스 - 표시 여부 / 글자 크기 / 여백 / 드래그 위치 반영
        stat_text = None
        if self.chk_stat.isChecked():
            stat_txt = (
                f"N = {r.n}\n"
                f"Mean = {r.mean:.2f}\n"
                f"StDev = {r.std:.2f}\n"
                f"Cp = {r.cp:.3f}\n"
                f"Cpk = {r.cpk:.3f}\n"
                f"PPM = {r.ppm:,.0f}"
            )
            stat_text = ax.text(
                self.stat_pos[0], self.stat_pos[1], stat_txt,
                transform=ax.transAxes, va="top", ha="right",
                fontsize=self.spn_stat.value(), family="monospace",
                bbox=dict(boxstyle=f"round,pad={self.spn_stat_pad.value():.2f}",
                          facecolor="#FFFDE7", edgecolor="#C9CDD2"))

        # 마우스 인터랙터에 현재 아티스트 전달
        self.interactor.set_artists(legend, stat_text)

        # OK/NG 판정 라벨 (체크박스 ON 시에만)
        if self.chk_verdict.isChecked():
            verdict = "OK" if r.cpk >= self._cpk_crit else "NG"
            v_color = OK_GREEN if verdict == "OK" else NG_RED
            ax.text(0.97, 0.55, verdict, transform=ax.transAxes,
                    va="top", ha="right", fontsize=22, fontweight="bold",
                    color=v_color,
                    bbox=dict(boxstyle="round", facecolor="white",
                              edgecolor=v_color, lw=2.2))

        self.canvas.fig.tight_layout()
        self.canvas.draw()

    # --------------------------------------------------------------- 이미지 저장
    def save_image(self):
        if self.result is None:
            QtWidgets.QMessageBox.information(self, "알림",
                                              "먼저 '분석 실행'을 수행하세요.")
            return
        path, sel = QtWidgets.QFileDialog.getSaveFileName(
            self, "이미지 저장", "capability_chart.png",
            "PNG 이미지 (*.png);;JPG 이미지 (*.jpg);;SVG 벡터 (*.svg)"
        )
        if not path:
            return
        dpi = int(self.cmb_dpi.currentText())
        try:
            self.canvas.fig.savefig(path, dpi=dpi, bbox_inches="tight",
                                    facecolor="white")
            self.statusBar().showMessage(f"저장 완료: {path}  ({dpi} dpi)")
            QtWidgets.QMessageBox.information(self, "저장 완료",
                                              f"이미지를 저장했습니다.\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "저장 실패", str(e))


# =============================================================================
#  진입점
# =============================================================================
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()


# =============================================================================
#  README - PyInstaller .exe 빌드 방법
# -----------------------------------------------------------------------------
#  1) 가상환경 생성 및 패키지 설치
#       python -m venv venv
#       venv\Scripts\activate            (Windows)
#       pip install -r requirements.txt
#       pip install pyinstaller
#
#  2) 단일 실행파일(.exe) 빌드  (콘솔창 숨김)
#       pyinstaller --onefile --windowed --icon=assets/app.ico main.py
#
#  3) scipy/matplotlib 누락 오류 시 hidden-import 추가:
#       pyinstaller --onefile --windowed ^
#           --hidden-import=scipy.special.cython_special ^
#           --hidden-import=scipy._lib.messagestream ^
#           --icon=assets/app.ico main.py
#
#  4) 결과물: dist/main.exe
# =============================================================================
