"""애플리케이션 디자인 토큰과 Qt 스타일시트."""

PRIMARY = "#0064FF"
PRIMARY_DK = "#0050CC"
SUBTLE_GRAY = "#F2F4F7"
BORDER = "#E4E7EC"
TEXT_MAIN = "#191F28"
TEXT_SUB = "#6B7684"
OK_GREEN = "#12B886"
NG_RED = "#FF3B30"

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
