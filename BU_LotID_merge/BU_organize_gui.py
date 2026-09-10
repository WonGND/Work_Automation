import io
import json
import os
import queue
import re
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Literal

if getattr(sys, "frozen", False):
    bundled_base = Path(getattr(sys, "_MEIPASS", ""))
    if bundled_base and (bundled_base / "tkinter").exists():
        sys.path.insert(0, str(bundled_base))

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

def get_pipeline():
    from bu_pipeline import PipelineCancelled, run_pipeline
    return PipelineCancelled, run_pipeline

APP_TITLE = "TOVIS_BU_DATA_정리"
AUTHOR_NAME = "(made by Kwakwonyong)"
APP_NAME = f"{APP_TITLE} {AUTHOR_NAME}"
ICON_FILENAME = "tovis_bu_data.ico"
SETTINGS_FILENAME = "tovis_bu_data_settings.json"
LOG_FILENAME = "TOVIS_BU_DATA_정리_log.txt"

THEMES = {
    "light": {
        "app_bg": "#f3f4f6",
        "header_bg": "#f8fafc",
        "card_bg": "#e9eef5",
        "panel_bg": "#ffffff",
        "text": "#111827",
        "subtext": "#6b7280",
        "accent": "#2563eb",
        "accent_soft": "#dbeafe",
        "muted_btn": "#e5edf8",
        "log_bg": "#0b1220",
        "log_fg": "#dbeafe",
        "nav_bg": "#f8fafc",
        "border": "#d7deea",
        "danger": "#d97706",
    },
    "dark": {
        "app_bg": "#0f172a",
        "header_bg": "#111827",
        "card_bg": "#172133",
        "panel_bg": "#0b1220",
        "text": "#f3f4f6",
        "subtext": "#94a3b8",
        "accent": "#60a5fa",
        "accent_soft": "#1d4ed8",
        "muted_btn": "#243247",
        "log_bg": "#020617",
        "log_fg": "#cbd5e1",
        "nav_bg": "#111827",
        "border": "#334155",
        "danger": "#f59e0b",
    },
}


def get_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ICON_PATH = Path(__file__).with_name(ICON_FILENAME)
SETTINGS_PATH = Path(__file__).with_name(SETTINGS_FILENAME)
LOG_PATH = get_app_base_dir() / LOG_FILENAME


class QueueWriter(io.TextIOBase):
    def __init__(self, log_queue: queue.Queue, log_path: Path):
        self.log_queue = log_queue
        self.log_path = log_path
        self._buffer = ""

    def _write_line(self, text: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {text}\n"
        self.log_queue.put(line)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._write_line(line)
        return len(s)

    def flush(self) -> None:
        if self._buffer.strip():
            self._write_line(self._buffer.rstrip())
        self._buffer = ""


class BUOrganizeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1120x860")
        self.root.minsize(980, 760)
        self._apply_icon()
        self.font_family = self._resolve_font_family()

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_requested = threading.Event()
        self.latest_result: dict | None = None
        self.preview_limit = 120

        self.settings = self._load_settings()
        self.theme_name_var = tk.StringVar(value=self.settings.get("theme", "light"))
        self.auto_open_var = tk.StringVar(value=self.settings.get("auto_open", "none"))
        self.remember_paths_var = tk.BooleanVar(value=bool(self.settings.get("remember_paths", True)))
        self.default_threshold_var = tk.StringVar(value=str(self.settings.get("default_threshold", 12)))
        self.default_padding_var = tk.StringVar(value=str(self.settings.get("default_padding", 20)))

        self.image_root_var = tk.StringVar(value=self.settings.get("image_root", ""))
        self.data_root_var = tk.StringVar(value=self.settings.get("data_root", ""))
        self.threshold_var = tk.StringVar(value=str(self.settings.get("default_threshold", 12)))
        self.padding_var = tk.StringVar(value=str(self.settings.get("default_padding", 20)))
        self.analyze_bu_var = tk.BooleanVar(value=bool(self.settings.get("analyze_bu_images", False)))
        self.status_var = tk.StringVar(value="대기 중")
        self.main_result_var = tk.StringVar(value="아직 생성되지 않음")
        self.analysis_result_var = tk.StringVar(value="분석 안 함")
        self.progress_text_var = tk.StringVar(value="대기 중")
        self._stage_index = 0
        self._stage_total = 5
        self.log_path_var = tk.StringVar(value=str(LOG_PATH))
        self.session_note_var = tk.StringVar(value="실행 대기")
        self.current_view = "main"
        self.preview_text = None
        self.log_text = None
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.view_frames: dict[str, ttk.Frame] = {}
        self.scroll_canvases: dict[str, tk.Canvas] = {}
        self.status_badge = None
        self.status_note_label = None
        self.status_value_label = None
        self._drag_target = None
        self._drag_start_y = 0
        self._drag_start_height = 0

        self._build_ui()
        self._apply_global_fonts()
        self._apply_theme()
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self._poll_log_queue()

    def _resolve_font_family(self) -> str:
        available = set(tkfont.families(self.root))
        if "Malgun Gothic" in available:
            return "Malgun Gothic"
        return "TkDefaultFont"

    def _font(
        self,
        size: int,
        weight: Literal["normal", "bold"] = "normal",
    ) -> tuple[str, int, Literal["normal", "bold"]]:
        return (self.font_family, size, weight)

    def _apply_global_fonts(self) -> None:
        defaults = {
            "TkDefaultFont": self._font(10),
            "TkTextFont": self._font(10),
            "TkMenuFont": self._font(10),
            "TkHeadingFont": self._font(10, "bold"),
            "TkCaptionFont": self._font(10),
            "TkIconFont": self._font(10),
            "TkTooltipFont": self._font(10),
        }
        for name, spec in defaults.items():
            try:
                tkfont.nametofont(name).configure(family=spec[0], size=spec[1], weight=spec[2])
            except tk.TclError:
                pass

    def _default_settings(self) -> dict:
        return {
            "theme": "light",
            "auto_open": "none",
            "remember_paths": True,
            "default_threshold": 12,
            "default_padding": 20,
            "image_root": "",
            "data_root": "",
            "analyze_bu_images": False,
        }

    def _load_settings(self) -> dict:
        settings = self._default_settings()
        if SETTINGS_PATH.exists():
            try:
                loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                settings.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        return settings

    def _save_settings(self) -> None:
        self.settings.update(
            {
                "theme": self.theme_name_var.get(),
                "auto_open": self.auto_open_var.get(),
                "remember_paths": self.remember_paths_var.get(),
                "default_threshold": self._safe_int(self.default_threshold_var.get(), 12),
                "default_padding": self._safe_int(self.default_padding_var.get(), 20),
                "analyze_bu_images": self.analyze_bu_var.get(),
            }
        )
        if self.remember_paths_var.get():
            self.settings["image_root"] = self.image_root_var.get().strip()
            self.settings["data_root"] = self.data_root_var.get().strip()
        else:
            self.settings["image_root"] = ""
            self.settings["data_root"] = ""
        try:
            SETTINGS_PATH.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _safe_int(self, raw: str, default: int) -> int:
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return default

    def _apply_icon(self) -> None:
        if ICON_PATH.exists():
            try:
                self.root.iconbitmap(str(ICON_PATH))
            except tk.TclError:
                pass

    def _build_ui(self) -> None:
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self.header = ttk.Frame(self.root, padding=(18, 12))
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.columnconfigure(1, weight=1)

        self.header_icon = tk.Label(self.header, text="▣", font=self._font(16, "bold"))
        self.header_icon.grid(row=0, column=0, sticky="w")
        
        # 제목과 작성자 정보를 담을 컨테이너
        self.title_container = ttk.Frame(self.header, style="Header.TFrame")
        self.title_container.grid(row=0, column=1, sticky="w", padx=(10, 0))
        
        self.header_title = ttk.Label(self.title_container, text=APP_TITLE, font=self._font(20, "bold"), style="Header.TLabel")
        self.header_title.pack(side="left", anchor="w")
        
        self.header_author = ttk.Label(self.title_container, text=AUTHOR_NAME, font=self._font(10, "bold"), style="HeaderAuthor.TLabel")
        self.header_author.pack(side="left", anchor="sw", padx=(5, 0), pady=(0, 3))

        self.header_status = ttk.Label(self.header, textvariable=self.status_var, font=self._font(11, "bold"))
        self.header_status.grid(row=0, column=2, sticky="e", padx=(0, 8))
        self.settings_button = ttk.Button(self.header, text="설정", command=lambda: self._show_view("settings"))
        self.settings_button.grid(row=0, column=3, sticky="e")

        self.content = ttk.Frame(self.root, padding=(14, 0, 14, 0))
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        main_outer, self.main_view = self._create_scrollable_view(self.content)
        settings_outer, self.settings_view = self._create_scrollable_view(self.content)
        self.log_view = ttk.Frame(self.content, padding=(0, 0, 0, 0))
        self.view_frames = {
            "main": main_outer,
            "log": self.log_view,
            "settings": settings_outer,
        }
        for frame in self.view_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self._build_main_view()
        self._build_log_view()
        self._build_settings_view()
        self._sync_log_heights()

        self.nav_bar = ttk.Frame(self.root, padding=(14, 10))
        self.nav_bar.grid(row=2, column=0, sticky="ew")
        for idx in range(3):
            self.nav_bar.columnconfigure(idx, weight=1)
        self.nav_buttons["main"] = ttk.Button(self.nav_bar, text="데이터 정리", command=lambda: self._show_view("main"))
        self.nav_buttons["main"].grid(row=0, column=0, sticky="ew", padx=6)
        self.nav_buttons["log"] = ttk.Button(self.nav_bar, text="로그 기록", command=lambda: self._show_view("log"))
        self.nav_buttons["log"].grid(row=0, column=1, sticky="ew", padx=6)
        self.nav_buttons["settings"] = ttk.Button(self.nav_bar, text="설정", command=lambda: self._show_view("settings"))
        self.nav_buttons["settings"].grid(row=0, column=2, sticky="ew", padx=6)

        self._show_view("main")

    def _create_scrollable_view(self, parent):
        outer = ttk.Frame(parent, padding=(0, 0, 0, 0))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(0, 0, 0, 0))

        inner.bind(
            "<Configure>",
            lambda _e, c=canvas, w=inner: c.configure(scrollregion=c.bbox("all"), width=c.winfo_width()),
        )
        canvas.bind(
            "<Configure>",
            lambda e, c=canvas, win=inner: c.itemconfigure(getattr(win, "_canvas_window"), width=e.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        setattr(inner, "_canvas_window", canvas.create_window((0, 0), window=inner, anchor="nw"))

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.scroll_canvases[str(id(outer))] = canvas
        return outer, inner

    def _build_main_view(self) -> None:
        self.main_view.columnconfigure(0, weight=1)

        source_card = self._make_card(self.main_view, "데이터 소스 설정", 0)
        self._add_source_block(source_card, 0, "이미지 통합 폴더", self.image_root_var, self._choose_image_root)
        self._add_source_block(source_card, 1, "측정 데이터 상위 폴더", self.data_root_var, self._choose_data_root)
        self._add_spin_block(source_card, 2, "비검정 판정 임계값", "데이터 필터링 강도 설정", self.threshold_var, 1)
        self._add_spin_block(source_card, 3, "크롭 패딩(px)", "이미지 추출 여유 공간", self.padding_var, 1)
        self._add_option_block(
            source_card,
            4,
            "BU Image 분석",
            "제품별 색 분포와 9분할 weak point를 분석합니다",
            self.analyze_bu_var,
        )

        status_card = self._make_card(self.main_view, "현재 상태", 1)
        status_row = ttk.Frame(status_card, style="Card.TFrame")
        status_row.grid(row=0, column=0, sticky="ew", pady=(8, 0))
        for idx in range(3):
            status_row.columnconfigure(idx, weight=1)

        status_box = ttk.Frame(status_row, padding=10, style="Panel.TFrame")
        status_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        status_box.columnconfigure(0, weight=1)
        self.status_badge = tk.Label(status_box, text="⌛", font=self._font(24, "bold"), width=3, height=1)
        self.status_badge.grid(row=0, column=0, pady=(4, 2))
        self.status_note_label = ttk.Label(status_box, textvariable=self.session_note_var, style="StatusNote.TLabel", anchor="center")
        self.status_note_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.status_value_label = ttk.Label(status_box, textvariable=self.status_var, style="StatusValue.TLabel", anchor="center")
        self.status_value_label.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        self.run_button = ttk.Button(status_row, text="▶\n실행", style="BigAction.TButton", command=self.start_run)
        self.run_button.grid(row=0, column=1, sticky="nsew", padx=4)
        self.run_button.configure(takefocus=False)
        self.stop_button = ttk.Button(status_row, text="■\n중지", style="BigStop.TButton", command=self.stop_run, state="disabled")
        self.stop_button.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        self.stop_button.configure(takefocus=False)
        self.progress = ttk.Progressbar(status_card, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(status_card, textvariable=self.progress_text_var, style="Subtle.TLabel").grid(
            row=2, column=0, sticky="w", pady=(4, 0)
        )

        result_card = self._make_card(self.main_view, "결과 파일", 2)
        file_grid = ttk.Frame(result_card, style="Card.TFrame")
        file_grid.grid(row=0, column=0, sticky="ew")
        file_grid.columnconfigure(0, weight=1)
        file_grid.columnconfigure(1, weight=1)
        ttk.Label(file_grid, text="메인 엑셀 파일", style="CardCaption.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(file_grid, textvariable=self.main_result_var, style="FileValue.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 8), padx=(0, 10))
        ttk.Label(file_grid, text="BU Image 분석", style="CardCaption.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(file_grid, textvariable=self.analysis_result_var, style="FileValue.TLabel").grid(row=1, column=1, sticky="w", pady=(5, 8), padx=(10, 0))
        result_actions = ttk.Frame(result_card)
        result_actions.grid(row=1, column=0, sticky="ew")
        for idx in range(2):
            result_actions.columnconfigure(idx, weight=1)
        ttk.Button(result_actions, text="엑셀 열기", command=self._open_main_excel).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(result_actions, text="결과 폴더", command=self._open_result_folder).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        log_card = self._make_card(self.main_view, "실행 로그", 3)
        top_row = ttk.Frame(log_card)
        top_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top_row.columnconfigure(0, weight=1)
        ttk.Label(top_row, text="로그 파일", style="CardCaption.TLabel").grid(row=0, column=0, sticky="w")
        actions = ttk.Frame(top_row)
        actions.grid(row=0, column=1, sticky="e")
        ttk.Button(actions, text="로그 열기", command=lambda: self._open_path(LOG_PATH)).pack(side="left")

        preview_text_wrap = ttk.Frame(log_card, style="Panel.TFrame")
        preview_text_wrap.columnconfigure(0, weight=1)
        preview_text_wrap.rowconfigure(0, weight=1)
        preview_handle = ttk.Frame(preview_text_wrap, height=10, style="Panel.TFrame", cursor="sb_v_double_arrow")
        preview_handle.grid(row=0, column=0, sticky="ew")
        ttk.Separator(preview_handle, orient="horizontal").pack(fill="x", padx=6, pady=4)
        self.preview_text = tk.Text(preview_text_wrap, height=10, wrap="word", relief="flat", padx=12, pady=12, font=self._font(10))
        self.preview_text.grid(row=1, column=0, sticky="nsew")
        self.preview_text.configure(state="disabled")
        preview_text_wrap.grid(row=1, column=0, sticky="nsew")
        self._bind_log_resizer(preview_handle, self.preview_text, minimum_height=6, maximum_height=36)

    def _build_log_view(self) -> None:
        self.log_view.columnconfigure(0, weight=1)
        self.log_view.rowconfigure(1, weight=1)
        
        top_bar = ttk.Frame(self.log_view, padding=(18, 10))
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.columnconfigure(0, weight=1)
        
        ttk.Label(top_bar, textvariable=self.log_path_var, font=self._font(9)).grid(row=0, column=0, sticky="w")
        
        actions = ttk.Frame(top_bar)
        actions.grid(row=0, column=1, sticky="e")
        ttk.Button(actions, text="로그 파일 열기", command=lambda: self._open_path(LOG_PATH)).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="로그 화면 지우기", command=self._clear_log).pack(side="left")

        self.log_text = tk.Text(
            self.log_view,
            wrap="word",
            relief="flat",
            padx=20,
            pady=20,
            borderwidth=0,
            highlightthickness=0,
            font=self._font(10)
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    def _build_settings_view(self) -> None:
        self.settings_view.columnconfigure(0, weight=1)
        LBL_W = 22

        general = self._make_card(self.settings_view, "일반", 0)
        general.columnconfigure(1, weight=1)
        ttk.Label(general, text="테마", style="CardCaption.TLabel", width=LBL_W).grid(row=0, column=0, sticky="w")
        theme_combo = ttk.Combobox(general, state="readonly", values=["light", "dark"], textvariable=self.theme_name_var, width=18)
        theme_combo.grid(row=0, column=1, sticky="w", padx=(12, 0))
        theme_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_settings_changed(apply_theme=True))

        ttk.Label(general, text="완료 후 자동 열기", style="CardCaption.TLabel", width=LBL_W).grid(row=1, column=0, sticky="w", pady=(10, 0))
        auto_combo = ttk.Combobox(general, state="readonly", values=["none", "excel", "folder", "both"], textvariable=self.auto_open_var, width=18)
        auto_combo.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(10, 0))
        auto_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_settings_changed())

        remember = ttk.Checkbutton(general, text="최근 사용 경로 기억", variable=self.remember_paths_var, command=self._on_settings_changed)
        remember.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        analysis = self._make_card(self.settings_view, "분석 기본값", 1)
        analysis.columnconfigure(1, weight=1)
        ttk.Label(analysis, text="임계값 기본값", style="CardCaption.TLabel", width=LBL_W).grid(row=0, column=0, sticky="w")
        ttk.Entry(analysis, textvariable=self.default_threshold_var, width=21).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(analysis, text="크롭 패딩 기본값", style="CardCaption.TLabel", width=LBL_W).grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(analysis, textvariable=self.default_padding_var, width=21).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(10, 0))
        ttk.Button(analysis, text="현재 입력값 반영", command=self._apply_defaults_to_inputs).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        paths = self._make_card(self.settings_view, "바로가기", 2)
        btn_row = ttk.Frame(paths)
        btn_row.grid(row=0, column=0, sticky="ew")
        for idx in range(3):
            btn_row.columnconfigure(idx, weight=1)
        ttk.Button(btn_row, text="이미지 폴더", command=self._open_image_root).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(btn_row, text="측정 폴더", command=self._open_data_root).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(btn_row, text="로그 폴더", command=lambda: self._open_path(LOG_PATH.parent)).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        bottom = ttk.Frame(self.settings_view)
        bottom.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Button(bottom, text="설정 저장", command=self._on_settings_changed).grid(row=0, column=0, sticky="e")

    def _make_card(self, parent, title: str, row: int):
        card = ttk.Frame(parent, padding=14, style="Card.TFrame")
        sticky = "nsew" if parent is self.log_view else "ew"
        card.grid(row=row, column=0, sticky=sticky, pady=(0, 10))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=title, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        return card

    def _add_source_block(self, parent, row: int, title: str, variable: tk.StringVar, command) -> None:
        block = ttk.Frame(parent, padding=(0, 10, 0, 0), style="Card.TFrame")
        block.grid(row=row + 1, column=0, sticky="ew")
        block.columnconfigure(0, weight=1)
        ttk.Label(block, text=title, style="CardCaption.TLabel").grid(row=0, column=0, sticky="w")
        entry_row = ttk.Frame(block, style="Panel.TFrame", padding=8)
        entry_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        entry_row.columnconfigure(0, weight=1)
        ttk.Entry(entry_row, textvariable=variable).grid(row=0, column=0, sticky="ew")
        ttk.Button(entry_row, text="찾아보기", command=command).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(entry_row, text="열기", command=lambda v=variable: self._open_path(Path(v.get().strip()))).grid(row=0, column=2, padx=(6, 0))

    def _add_spin_block(self, parent, row: int, title: str, desc: str, variable: tk.StringVar, step: int) -> None:
        block = ttk.Frame(parent, padding=(0, 10, 0, 0), style="Card.TFrame")
        block.grid(row=row + 1, column=0, sticky="ew")
        block.columnconfigure(1, weight=1)
        ttk.Label(block, text=title, style="CardCaption.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(block, text=desc, style="Subtle.TLabel").grid(row=1, column=0, sticky="w")
        spin_wrap = ttk.Frame(block, style="Panel.TFrame", padding=6)
        spin_wrap.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(spin_wrap, text="－", width=2, style="MiniSpin.TButton", command=lambda: self._adjust_number(variable, -step)).grid(row=0, column=0)
        ttk.Entry(spin_wrap, textvariable=variable, width=6, justify="center").grid(row=0, column=1, padx=6)
        ttk.Button(spin_wrap, text="＋", width=2, style="MiniSpin.TButton", command=lambda: self._adjust_number(variable, step)).grid(row=0, column=2)

    def _add_option_block(self, parent, row: int, title: str, desc: str, variable: tk.BooleanVar) -> None:
        block = ttk.Frame(parent, padding=(0, 10, 0, 0), style="Card.TFrame")
        block.grid(row=row + 1, column=0, sticky="ew")
        block.columnconfigure(1, weight=1)
        ttk.Label(block, text=title, style="CardCaption.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(block, text=desc, style="Subtle.TLabel").grid(row=1, column=0, sticky="w")
        toggle_wrap = ttk.Frame(block, style="Panel.TFrame", padding=6)
        toggle_wrap.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Checkbutton(
            toggle_wrap,
            text="실행",
            variable=variable,
            command=self._on_settings_changed,
            style="Panel.TCheckbutton",
        ).grid(row=0, column=0)

    def _bind_log_resizer(self, handle, text_widget, minimum_height: int, maximum_height: int) -> None:
        handle.bind("<ButtonPress-1>", lambda e, t=text_widget: self._start_resize(e, t))
        handle.bind("<B1-Motion>", lambda e, t=text_widget, mn=minimum_height, mx=maximum_height: self._perform_resize(e, t, mn, mx))
        handle.bind("<ButtonRelease-1>", self._stop_resize)

    def _start_resize(self, event, text_widget) -> None:
        self._drag_target = text_widget
        self._drag_start_y = event.y_root
        self._drag_start_height = int(text_widget.cget("height"))

    def _perform_resize(self, event, text_widget, minimum_height: int, maximum_height: int) -> None:
        if self._drag_target is not text_widget:
            return
        delta = event.y_root - self._drag_start_y
        new_height = max(minimum_height, min(maximum_height, self._drag_start_height + int(delta / 10)))
        text_widget.configure(height=new_height)
        if text_widget is self.log_text and self.preview_text is not None:
            self.preview_text.configure(height=new_height)
        elif text_widget is self.preview_text and self.log_text is not None:
            self.log_text.configure(height=new_height)
        text_widget.update_idletasks()

    def _stop_resize(self, _event) -> None:
        self._drag_target = None

    def _sync_log_heights(self) -> None:
        if self.preview_text is None or self.log_text is None:
            return
        try:
            full_height = int(self.log_text.cget("height"))
            self.preview_text.configure(height=full_height)
        except (tk.TclError, ValueError):
            pass

    def _adjust_number(self, variable: tk.StringVar, delta: int) -> None:
        value = self._safe_int(variable.get(), 0) + delta
        variable.set(str(max(0, value)))

    def _choose_image_root(self) -> None:
        path = filedialog.askdirectory(title="이미지 통합 폴더 선택")
        if path:
            self.image_root_var.set(path)
            self._on_settings_changed(save_only=self.remember_paths_var.get())

    def _choose_data_root(self) -> None:
        path = filedialog.askdirectory(title="측정 데이터 상위 폴더 선택")
        if path:
            self.data_root_var.set(path)
            self._on_settings_changed(save_only=self.remember_paths_var.get())

    def _show_view(self, name: str) -> None:
        self.current_view = name
        self.view_frames[name].tkraise()
        canvas = self.scroll_canvases.get(str(id(self.view_frames[name])))
        if canvas is not None:
            canvas.yview_moveto(0)
        self._apply_theme()

    def _on_mousewheel(self, event) -> None:
        canvas = self.scroll_canvases.get(str(id(self.view_frames.get(self.current_view))))
        if canvas is not None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_settings_changed(self, apply_theme: bool = False, save_only: bool = True) -> None:
        self.settings["default_threshold"] = self._safe_int(self.default_threshold_var.get(), 12)
        self.settings["default_padding"] = self._safe_int(self.default_padding_var.get(), 20)
        self._save_settings()
        if apply_theme:
            self._apply_theme()
        if not save_only:
            self.threshold_var.set(str(self.settings["default_threshold"]))
            self.padding_var.set(str(self.settings["default_padding"]))

    def _apply_defaults_to_inputs(self) -> None:
        self._on_settings_changed(save_only=False)
        messagebox.showinfo("설정 적용", "기본 설정값을 현재 입력칸에 반영했습니다.")

    def _apply_theme(self) -> None:
        theme = THEMES.get(self.theme_name_var.get(), THEMES["light"])
        self.root.configure(bg=theme["app_bg"])
        self.style.configure("Card.TFrame", background=theme["card_bg"], relief="flat")
        self.style.configure("Panel.TFrame", background=theme["panel_bg"], relief="flat")
        self.style.configure("SectionTitle.TLabel", background=theme["card_bg"], foreground=theme["text"], font=self._font(14, "bold"))
        self.style.configure("CardCaption.TLabel", background=theme["card_bg"], foreground=theme["subtext"], font=self._font(10, "bold"))
        self.style.configure("CardValue.TLabel", background=theme["card_bg"], foreground=theme["text"], font=self._font(11, "bold"))
        self.style.configure("FileValue.TLabel", background=theme["card_bg"], foreground=theme["text"], font=self._font(11, "bold"))
        self.style.configure("StatusNote.TLabel", background=theme["panel_bg"], foreground=theme["subtext"], font=self._font(11, "bold"))
        self.style.configure("StatusValue.TLabel", background=theme["panel_bg"], foreground=theme["accent"], font=self._font(14, "bold"))
        self.style.configure("Subtle.TLabel", background=theme["card_bg"], foreground=theme["subtext"], font=self._font(9))
        self.style.configure("TLabel", background=theme["card_bg"], foreground=theme["text"], font=self._font(10))
        self.style.configure("TFrame", background=theme["app_bg"])
        self.style.configure("TButton", font=self._font(9, "bold"), padding=6, anchor="center")
        self.style.configure("BigAction.TButton", font=self._font(13, "bold"), padding=10, anchor="center", justify="center")
        self.style.configure("BigStop.TButton", font=self._font(13, "bold"), padding=10, anchor="center", justify="center")
        self.style.configure("MiniSpin.TButton", font=self._font(8, "bold"), padding=2)
        self.style.configure("TEntry", fieldbackground=theme["panel_bg"], foreground=theme["text"], font=self._font(10))
        self.style.configure("TCombobox", fieldbackground=theme["panel_bg"], foreground=theme["text"], font=self._font(10))
        self.style.configure("TCheckbutton", background=theme["card_bg"], foreground=theme["text"], font=self._font(10))
        self.style.configure("Panel.TCheckbutton", background=theme["panel_bg"], foreground=theme["text"], font=self._font(10, "bold"))
        self.style.map("Panel.TCheckbutton", background=[("active", theme["panel_bg"])])
        self.style.configure("Horizontal.TProgressbar", troughcolor=theme["muted_btn"], background=theme["accent"], bordercolor=theme["border"], lightcolor=theme["accent"], darkcolor=theme["accent"])

        self.header.configure(style="Header.TFrame")
        self.style.configure("Header.TFrame", background=theme["header_bg"])
        self.style.configure("Header.TLabel", background=theme["header_bg"], foreground=theme["text"], font=self._font(20, "bold"))
        self.style.configure("HeaderAuthor.TLabel", background=theme["header_bg"], foreground=theme["subtext"], font=self._font(10, "bold"))
        
        self.header_icon.configure(bg=theme["header_bg"], fg=theme["accent"])
        self.header_status.configure(background=theme["header_bg"], foreground=theme["accent"])
        self.nav_bar.configure(style="Nav.TFrame")
        self.style.configure("Nav.TFrame", background=theme["nav_bg"])
        for canvas in self.scroll_canvases.values():
            canvas.configure(bg=theme["app_bg"])

        if self.preview_text is not None:
            self.preview_text.configure(bg=theme["log_bg"], fg=theme["log_fg"], insertbackground=theme["log_fg"])
        if self.log_text is not None:
            self.log_text.configure(bg=theme["log_bg"], fg=theme["log_fg"], insertbackground=theme["log_fg"])
        if self.status_badge is not None:
            self.status_badge.configure(bg=theme["accent_soft"], fg=theme["accent"])
        self._refresh_status_display()

        for name, button in self.nav_buttons.items():
            if name == self.current_view:
                button.configure(style="ActiveNav.TButton")
            else:
                button.configure(style="NavBtn.TButton")
        self.style.configure("NavBtn.TButton", background=theme["muted_btn"], foreground=theme["text"], padding=10)
        self.style.map("NavBtn.TButton", background=[("active", theme["accent_soft"])])
        self.style.configure("ActiveNav.TButton", background=theme["accent"], foreground="#ffffff", padding=10)
        self.style.map("ActiveNav.TButton", background=[("active", theme["accent"])])

    def _append_log(self, text: str) -> None:
        for widget in (self.preview_text, self.log_text):
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.insert("end", text)
            if widget is self.preview_text:
                lines = widget.get("1.0", "end-1c").splitlines()
                if len(lines) > self.preview_limit:
                    widget.delete("1.0", f"{len(lines) - self.preview_limit + 1}.0")
            widget.see("end")
            widget.configure(state="disabled")

    def _refresh_status_display(self) -> None:
        status = self.status_var.get().strip()
        theme = THEMES.get(self.theme_name_var.get(), THEMES["light"])
        icon = "⌛"
        fg = theme["accent"]
        bg = theme["accent_soft"]
        if "실행" in status:
            icon = "▶"
            fg = theme["accent"]
            bg = theme["accent_soft"]
        elif "완료" in status:
            icon = "✓"
            fg = "#15803d"
            bg = "#dcfce7" if self.theme_name_var.get() == "light" else "#14532d"
        elif "중지" in status:
            icon = "■"
            fg = theme["danger"]
            bg = "#ffedd5" if self.theme_name_var.get() == "light" else "#451a03"
        elif "오류" in status:
            icon = "!"
            fg = "#dc2626"
            bg = "#fee2e2" if self.theme_name_var.get() == "light" else "#450a0a"
        if self.status_badge is not None:
            self.status_badge.configure(text=icon, fg=fg, bg=bg)
        self.style.configure("StatusValue.TLabel", background=theme["panel_bg"], foreground=fg, font=self._font(14, "bold"))

    def _poll_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._update_progress_from_log(message)
            self._append_log(message)
        self.root.after(120, self._poll_log_queue)

    def _update_progress_from_log(self, message: str) -> None:
        """파이프라인이 찍는 단계 머리말과 진행률 줄을 읽어 막대에 반영한다.

        파이프라인은 표준 출력만 쓰고 GUI를 모른다. 그 경계를 유지하려고
        콜백을 새로 넘기는 대신 이미 흐르고 있는 로그를 해석한다.
        """
        stage = re.search(r"\[(\d+)/(\d+)\]\s*(.+)", message)
        if stage is not None:
            self._stage_index = int(stage.group(1))
            self._stage_total = max(int(stage.group(2)), 1)
            self._set_progress(0.0, stage.group(3).split("(")[0].strip())
            return

        detail = re.search(r"(\S[^:]*):\s*(\d+)/(\d+)\s*\(\s*([\d.]+)%\)", message)
        if detail is not None and self._stage_index:
            done, total = int(detail.group(2)), max(int(detail.group(3)), 1)
            self._set_progress(done / total, f"{detail.group(1).strip()} {done}/{total}")

    def _set_progress(self, stage_ratio: float, label: str) -> None:
        completed = max(self._stage_index - 1, 0)
        overall = (completed + min(max(stage_ratio, 0.0), 1.0)) / self._stage_total * 100
        self.progress.configure(value=overall)
        self.progress_text_var.set(
            f"[{self._stage_index}/{self._stage_total}] {label} · 전체 {overall:.0f}%"
        )

    def start_run(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("실행 중", "현재 작업이 진행 중입니다.")
            return

        image_root = Path(self.image_root_var.get().strip())
        data_root = Path(self.data_root_var.get().strip())

        if not image_root.exists() or not image_root.is_dir():
            messagebox.showerror("입력 오류", "이미지 통합 폴더 경로를 확인하세요.")
            return
        if not data_root.exists() or not data_root.is_dir():
            messagebox.showerror("입력 오류", "측정 데이터 상위 폴더 경로를 확인하세요.")
            return

        try:
            threshold = int(self.threshold_var.get().strip())
            padding = int(self.padding_var.get().strip())
        except ValueError:
            messagebox.showerror("입력 오류", "임계값과 패딩은 숫자로 입력해야 합니다.")
            return

        self._save_settings()
        self.cancel_requested.clear()
        self.latest_result = None
        self.status_var.set("실행 중")
        self.session_note_var.set("작업이 진행 중입니다")
        self.main_result_var.set("작업이 진행 중입니다.")
        self._refresh_status_display()
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._stage_index = 0
        self._stage_total = 6 if self.analyze_bu_var.get() else 5
        self.progress.configure(value=0)
        self.progress_text_var.set("시작 준비 중... 0%")
        for widget in (self.preview_text, self.log_text):
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")

        self.worker = threading.Thread(
            target=self._run_worker,
            args=(image_root, data_root, threshold, padding, self.analyze_bu_var.get()),
            daemon=True,
        )
        self.worker.start()

    def _run_worker(
        self,
        image_root: Path,
        data_root: Path,
        threshold: int,
        padding: int,
        analyze_bu_images: bool,
    ) -> None:
        writer = QueueWriter(self.log_queue, LOG_PATH)
        PipelineCancelled, run_pipeline = get_pipeline()
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                print("=" * 70)
                print(f"{APP_NAME} 실행 시작")
                print(f"이미지 통합 폴더: {image_root}")
                print(f"측정 데이터 폴더: {data_root}")
                print(f"비검정 임계값: {threshold}")
                print(f"크롭 패딩: {padding}")
                print(f"BU Image 분석: {'실행' if analyze_bu_images else '건너뜀'}")
                print(f"로그 파일: {LOG_PATH}")
                result = run_pipeline(
                    image_root,
                    data_root,
                    threshold,
                    padding,
                    cancel_check=self.cancel_requested.is_set,
                    analyze_bu_images=analyze_bu_images,
                )
                print(f"실행 완료: {result.get('excel_path', 'N/A')}")
                print("=" * 70)
                writer.flush()
            self.root.after(0, self._on_success, result)
        except PipelineCancelled as exc:
            writer.write(f"실행 중지: {exc}\n")
            writer.write("=" * 70 + "\n")
            writer.flush()
            self.root.after(0, self._on_cancelled, str(exc))
        except Exception as exc:
            writer.write(f"실행 오류: {exc}\n")
            writer.write("=" * 70 + "\n")
            writer.flush()
            self.root.after(0, self._on_failure, str(exc))

    def _on_success(self, result: dict) -> None:
        self.latest_result = result
        self.progress.configure(value=100)
        self.progress_text_var.set("완료 100%")
        self.run_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("완료")
        self.session_note_var.set("DATA 정리 완료")
        self.main_result_var.set(Path(result["excel_path"]).name if result.get("excel_path") else "생성됨")
        if result.get("analysis_excel_path"):
            self.analysis_result_var.set(
                f"같은 파일에 포함 (분석 {result.get('analyzed_images', 0)}개, "
                f"weak {result.get('weak_products', 0)}개)"
            )
        else:
            self.analysis_result_var.set("분석 안 함")
        self._refresh_status_display()
        self._append_log(
            f"\n완료: {result.get('excel_path', '')}\n"
        )
        messagebox.showinfo("완료", "DATA 정리 완료!")
        self._handle_auto_open()

    def _handle_auto_open(self) -> None:
        if not self.latest_result or not self.latest_result.get("excel_path"):
            return
        auto_open = self.auto_open_var.get()
        if auto_open == "excel":
            self._open_result(self.latest_result["excel_path"])
        elif auto_open == "folder":
            self._open_path(Path(self.latest_result["excel_path"]).parent)
        elif auto_open == "both":
            self._open_result(self.latest_result["excel_path"])
            self._open_path(Path(self.latest_result["excel_path"]).parent)

    def _on_cancelled(self, message: str) -> None:
        self.progress_text_var.set("중지됨")
        self.run_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("중지됨")
        self.session_note_var.set("사용자 요청으로 중지")
        self.main_result_var.set("사용자 요청으로 작업이 중지되었습니다.")
        self._refresh_status_display()
        self._append_log(f"\n중지: {message}\n")
        messagebox.showinfo("중지됨", message)

    def _on_failure(self, error_message: str) -> None:
        self.progress_text_var.set("오류 발생")
        self.run_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("오류 발생")
        self.session_note_var.set("실행 중 오류 발생")
        self.main_result_var.set("오류로 인해 결과 파일이 생성되지 않았습니다.")
        self._refresh_status_display()
        self._append_log(f"\n오류: {error_message}\n")
        messagebox.showerror("실행 오류", error_message)

    def stop_run(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_requested.set()
            self.status_var.set("중지 요청됨")
            self.session_note_var.set("현재 단계 완료 후 안전 중지")
            self._refresh_status_display()
            self.stop_button.configure(state="disabled")
            self._append_log("\n중지 요청: 현재 단계 완료 후 안전하게 작업을 멈춥니다.\n")

    def _open_result(self, result_path: str | Path) -> None:
        try:
            startfile = getattr(os, "startfile")
            startfile(str(result_path))
        except OSError as exc:
            messagebox.showerror("열기 실패", f"결과 파일을 열지 못했습니다.\n{exc}")

    def _open_path(self, path: Path) -> None:
        try:
            if not str(path).strip():
                return
            startfile = getattr(os, "startfile")
            startfile(str(path))
        except OSError as exc:
            messagebox.showerror("열기 실패", f"경로를 열지 못했습니다.\n{exc}")

    def _open_main_excel(self) -> None:
        if self.latest_result and self.latest_result.get("excel_path"):
            self._open_result(self.latest_result["excel_path"])

    def _open_result_folder(self) -> None:
        if self.latest_result and self.latest_result.get("excel_path"):
            self._open_path(Path(self.latest_result["excel_path"]).parent)

    def _open_image_root(self) -> None:
        raw = self.image_root_var.get().strip()
        if raw:
            self._open_path(Path(raw))

    def _open_data_root(self) -> None:
        raw = self.data_root_var.get().strip()
        if raw:
            self._open_path(Path(raw))

    def _clear_log(self) -> None:
        for widget in (self.preview_text, self.log_text):
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")
        try:
            LOG_PATH.write_text("", encoding="utf-8")
        except OSError:
            pass


def main() -> None:
    root = tk.Tk()
    app = BUOrganizeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
