"""Design tokens and the Qt style sheet of the desktop tool.

Same palette as the HTML report (``pcbsim.report``): zinc neutrals, one teal
accent, red / amber / green status colours, hairline borders.
"""

from __future__ import annotations

ACCENT = "#0f766e"
ACCENT_DK = "#115e59"
FG = "#18181b"
MUTED = "#52525b"
FAINT = "#a1a1aa"
WELL = "#fafafa"
LINE = "rgba(0,0,0,0.10)"
LINE_SOLID = "#e4e4e7"
OK = "#15803d"
WARN = "#b45309"
NG = "#b91c1c"

FONT_FAMILY = '"Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "Segoe UI", sans-serif'

STYLE_SHEET = f"""
QMainWindow, QDialog {{ background: #ffffff; }}
QWidget {{ color: {FG}; font-family: {FONT_FAMILY}; font-size: 13px; }}
QLabel#title {{ font-size: 17px; font-weight: 600; }}
QLabel#muted, QLabel#hint {{ color: {MUTED}; }}
QLabel#section {{ color: {MUTED}; font-weight: 600; padding-top: 4px; }}
QLabel#verdict_ok {{ color: {OK}; font-weight: 600; background: #f0fdf4;
    border-radius: 6px; padding: 3px 10px; }}
QLabel#verdict_ng {{ color: {NG}; font-weight: 600; background: #fef2f2;
    border-radius: 6px; padding: 3px 10px; }}
QLabel#verdict_idle {{ color: {MUTED}; font-weight: 600; background: {WELL};
    border-radius: 6px; padding: 3px 10px; }}
QFrame#side {{ background: {WELL}; border-right: 1px solid {LINE_SOLID}; }}
QFrame#rule {{ background: {LINE_SOLID}; max-height: 1px; min-height: 1px; border: none; }}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background: #ffffff; border: 1px solid {LINE_SOLID}; border-radius: 8px;
    padding: 5px 8px; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit[readOnly="true"] {{ background: {WELL}; color: {MUTED}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ border: 1px solid {LINE_SOLID}; background: #ffffff;
    selection-background-color: {ACCENT}; selection-color: #ffffff; }}
QPushButton {{ background: #ffffff; color: {FG}; border: 1px solid {LINE_SOLID};
    border-radius: 8px; padding: 6px 12px; font-weight: 500; }}
QPushButton:hover {{ background: #f4f4f5; }}
QPushButton:pressed {{ background: #e4e4e7; }}
QPushButton:disabled {{ color: {FAINT}; background: {WELL}; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; color: #ffffff; border: 1px solid {ACCENT};
    padding: 8px 14px; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_DK}; }}
QPushButton#primary:disabled {{ background: #99c7c1; border-color: #99c7c1; color: #ffffff; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #a1a1aa;
    border-radius: 4px; background: #ffffff; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ background: {WELL}; border-color: {LINE_SOLID}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {LINE_SOLID}; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px;
    border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {FG}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {FG}; }}
QTableWidget {{ border: none; gridline-color: transparent; background: #ffffff;
    alternate-background-color: {WELL}; selection-background-color: #ccfbf1;
    selection-color: {FG}; }}
QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid #f4f4f5; }}
QHeaderView::section {{ background: #ffffff; color: {MUTED}; font-weight: 500;
    border: none; border-bottom: 1px solid {LINE_SOLID}; padding: 6px 8px; }}
QPlainTextEdit {{ background: {WELL}; border: 1px solid {LINE_SOLID}; border-radius: 8px;
    font-family: "Consolas", "D2Coding", "Menlo", monospace; font-size: 12px; padding: 6px; }}
QProgressBar {{ border: none; background: #f4f4f5; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QStatusBar {{ color: {MUTED}; }}
QScrollArea {{ border: none; }}
QSplitter::handle {{ background: {LINE_SOLID}; }}
"""
