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
from PyQt5 import QtCore, QtGui, QtWidgets

from stats_core import CapabilityResult
from theme import NG_RED, OK_GREEN, STYLE_SHEET, TEXT_MAIN, TEXT_SUB
from widgets import BoxInteractor, ColorButton, MplCanvas


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
        self._curve_cache = None
        self.legend_anchor = [0.01, 0.99]   # 범례 위치 (드래그로 이동)
        self.stat_pos = [0.98, 0.98]        # 통계박스 위치 (드래그로 이동)

        self._redraw_timer = QtCore.QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(140)
        self._redraw_timer.timeout.connect(self._draw_if_ready_now)

        self._drag_redraw_timer = QtCore.QTimer(self)
        self._drag_redraw_timer.setSingleShot(True)
        self._drag_redraw_timer.setInterval(16)
        self._drag_redraw_timer.timeout.connect(self._draw_if_ready_now)

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
    @staticmethod
    def _read_csv(path):
        """국내 설비 CSV는 cp949/euc-kr 인 경우가 많아 인코딩을 순서대로 시도한다."""
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                return pd.read_csv(path, encoding=encoding)
            except UnicodeDecodeError as error:
                last_error = error
        raise UnicodeError(
            "지원하는 인코딩(utf-8-sig, utf-8, cp949, euc-kr)으로 읽지 못했습니다."
        ) from last_error

    def _clear_loaded_state(self):
        self._redraw_timer.stop()
        self._drag_redraw_timer.stop()
        self.df = None
        self.result = None
        self._curve_cache = None
        self.cmb_column.clear()
        self.interactor.set_artists(None, None)
        self.canvas.ax.clear()
        self.canvas.draw()
        self.statusBar().showMessage("새 파일을 불러오는 중...")

    def load_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "",
            "데이터 파일 (*.xlsx *.xls *.csv);;모든 파일 (*.*)"
        )
        if not path:
            return
        self._clear_loaded_state()
        try:
            if path.lower().endswith(".csv"):
                loaded_df = self._read_csv(path)
            else:
                loaded_df = pd.read_excel(path)
        except Exception as error:
            self.statusBar().showMessage(f"파일 로드 실패: {path}")
            QtWidgets.QMessageBox.critical(self, "파일 로드 실패",
                                           f"파일을 읽을 수 없습니다.\n\n{error}")
            return

        numeric_columns = []
        for index, column in enumerate(loaded_df.columns):
            if pd.api.types.is_numeric_dtype(loaded_df.iloc[:, index]):
                numeric_columns.append((index, column))
        if not numeric_columns:
            self.statusBar().showMessage("파일 로드 실패 — 숫자형 컬럼이 없습니다.")
            QtWidgets.QMessageBox.warning(self, "경고", "숫자형 컬럼이 없습니다.")
            return

        self.df = loaded_df
        for index, column in numeric_columns:
            self.cmb_column.addItem(str(column), userData=(index, column))
        self.statusBar().showMessage(
            f"로드 완료: {path}  (행 {len(self.df)}개, 숫자컬럼 {len(numeric_columns)}개)")

    # ----------------------------------------------------------- 데이터 취득
    @staticmethod
    def _parse_manual_data(manual_text):
        raw = manual_text.replace("\n", ",").replace("\t", ",")
        tokens = [token.strip() for token in raw.split(",") if token.strip()]
        values = []
        for token in tokens:
            try:
                value = float(token)
            except ValueError:
                continue
            if np.isfinite(value):
                values.append(value)
        return np.asarray(values)

    def _get_data(self):
        manual_text = self.txt_manual.toPlainText().strip()
        file_value_count = None
        if self.df is not None and self.cmb_column.currentData() is not None:
            column_index, _column = self.cmb_column.currentData()
            series = pd.to_numeric(self.df.iloc[:, column_index], errors="coerce")
            file_values = np.asarray(series, dtype=float)
            file_values = file_values[np.isfinite(file_values)]
            file_value_count = len(file_values)
            if file_value_count >= 2:
                return file_values

        if manual_text:
            manual_values = self._parse_manual_data(manual_text)
            if len(manual_values) >= 2:
                return manual_values
            if file_value_count is not None:
                raise ValueError(
                    "선택한 파일 컬럼과 수동 입력 모두 유효한 숫자 데이터가 "
                    "2개 미만입니다."
                )
            raise ValueError("수동 입력에 유효한 숫자 데이터가 2개 이상 필요합니다.")

        if file_value_count is not None:
            raise ValueError(
                "선택한 파일 컬럼에 유효한 숫자 데이터가 2개 미만입니다. "
                "다른 컬럼을 선택하거나 수동 입력을 작성하세요."
            )
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
            self._redraw_timer.stop()
            self._drag_redraw_timer.stop()
            data = self._get_data()
            lsl, usl, cpk_crit, xmin, xmax = self._get_params()
            self.result = CapabilityResult(data, lsl, usl)
            self._cpk_crit = cpk_crit
            self._xrange = (xmin, xmax)
            self._curve_cache = None
            self.draw_chart()
            verdict = "OK" if self.result.cpk >= cpk_crit else "NG"
            self.statusBar().showMessage(
                f"분석 완료 — N={self.result.n}, Cpk={self.result.cpk:.3f} -> {verdict}")
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, "분석 오류", str(error))

    def redraw_if_ready(self, *_args):
        if self.result is not None:
            self._redraw_timer.start()

    def schedule_drag_redraw(self):
        if self.result is not None and not self._drag_redraw_timer.isActive():
            self._drag_redraw_timer.start()

    def _draw_if_ready_now(self):
        if self.result is not None:
            self.draw_chart()

    def _get_curve_data(self, result, xmin, xmax):
        cache_key = (id(result), xmin, xmax)
        if self._curve_cache is None or self._curve_cache[0] != cache_key:
            xs = np.linspace(xmin, xmax, 400)
            ys = stats.norm.pdf(xs, result.mean, result.std)
            self._curve_cache = (cache_key, xs, ys)
        return self._curve_cache[1], self._curve_cache[2]

    # --------------------------------------------------------------- 차트 그리기
    def draw_chart(self):
        r = self.result
        if r is None:
            return
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
        xs, ys = self._get_curve_data(r, xmin, xmax)
        ax.plot(xs, ys, color=c_curve, lw=2.4, label="Normal Fit")

        # NG 음영 (체크박스 ON 시에만)
        if self.chk_ng_fill.isChecked():
            left_mask = xs <= r.lsl
            right_mask = xs >= r.usl
            if np.any(left_mask):
                ax.fill_between(xs[left_mask], ys[left_mask],
                                color=c_ng, alpha=0.7)
            if np.any(right_mask):
                ax.fill_between(xs[right_mask], ys[right_mask],
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
        path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
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
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, "저장 실패", str(error))


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
