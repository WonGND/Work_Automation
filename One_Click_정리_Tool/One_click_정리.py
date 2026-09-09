
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import os
import sys
import pandas as pd
from openpyxl import load_workbook
from datetime import datetime
import threading

# [설정] 시간 포맷 및 기본 양식 경로
TIME_FMT = "%Y.%m.%d %H:%M:%S"
DEFAULT_TEMPLATE_PATH = r"../../업무/00. 곽원용/01. PJT/2025/3. 12.9 inch_VDA129BLAC01/0. 양산 대응 폴더/Daily data 정리/양식_Daily data_BU설비_광학데이터_날짜.xlsx"
SUPPORTED_TIME_FORMATS = (
    "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
)

# 시트별 선별 컬럼 정의
CA_SELECTED_COLS = [
    "Time", "Panel", "Panel_ID",
    "Red_X", "Red_Y",
    "Green_X", "Green_Y",
    "Blue_X", "Blue_Y",
    "White_SX", "White_SY", "White_LV",
    "Black_LV", "EEPROM_59"
]

LMK_SELECTED_COLS = [
    "Time", "Panel", "Panel_ID", "Judge",
    "Black_Uniformity", "White_Uniformity"
]

class OneClickApp:
    def __init__(self, root):
        self.root = root
        self.root.title("One Click 데이터 정리 도구 v1.4.1")
        self.root.geometry("800x700")
        
        self.last_saved_file = None
        self.last_saved_folder = None
        self.template_path = self.get_default_template_path()
        self._main_thread = threading.current_thread()

        self.setup_ui()
        self.log("프로그램이 시작되었습니다.")
        self.check_template()

    def setup_ui(self):
        # 파일 선택 프레임
        file_frame = tk.LabelFrame(self.root, text="입력 파일 설정 (CSV/Excel)", padx=10, pady=10)
        file_frame.pack(fill="x", padx=10, pady=5)

        # CA410
        tk.Label(file_frame, text="1. CA410 (색좌표):").grid(row=0, column=0, sticky="w")
        self.ent_ca = tk.Entry(file_frame)
        self.ent_ca.grid(row=0, column=1, sticky="ew", padx=5)
        tk.Button(file_frame, text="찾기", command=lambda: self.browse_file(self.ent_ca, "CA410")).grid(row=0, column=2)

        # LMK6
        tk.Label(file_frame, text="2. LMK6 (BU/WU):").grid(row=1, column=0, sticky="w", pady=5)
        self.ent_lmk = tk.Entry(file_frame)
        self.ent_lmk.grid(row=1, column=1, sticky="ew", padx=5)
        tk.Button(file_frame, text="찾기", command=lambda: self.browse_file(self.ent_lmk, "LMK6")).grid(row=1, column=2)

        # 양식 파일
        tk.Label(file_frame, text="3. 양식 파일:").grid(row=2, column=0, sticky="w")
        self.ent_temp = tk.Entry(file_frame)
        self.ent_temp.insert(0, self.template_path if self.template_path else "")
        self.ent_temp.grid(row=2, column=1, sticky="ew", padx=5)
        tk.Button(file_frame, text="변경", command=self.browse_template).grid(row=2, column=2)

        # 저장 경로
        tk.Label(file_frame, text="4. 저장 폴더:").grid(row=3, column=0, sticky="w", pady=5)
        self.ent_save = tk.Entry(file_frame)
        self.ent_save.grid(row=3, column=1, sticky="ew", padx=5)
        tk.Button(file_frame, text="찾기", command=self.browse_folder).grid(row=3, column=2)

        # 옵션 설정
        self.var_make_individual = tk.BooleanVar(value=True)
        self.chk_individual = tk.Checkbutton(file_frame, text="개별 정리 파일(Cleaned) 생성 (2개 시트 구성)", variable=self.var_make_individual)
        self.chk_individual.grid(row=4, column=0, columnspan=3, sticky="w", pady=5)

        file_frame.columnconfigure(1, weight=1)

        # 실행 버튼
        self.btn_run = tk.Button(self.root, text="▶ One-Click 정리 시작", 
                                 bg="#28a745", fg="white", font=("맑은 고딕", 12, "bold"), 
                                 height=2, command=self.start_process)
        self.btn_run.pack(fill="x", padx=10, pady=10)

        # 로그창
        log_frame = tk.LabelFrame(self.root, text="처리 로그", padx=10, pady=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.txt_log = scrolledtext.ScrolledText(log_frame, height=15, state="disabled", font=("Consolas", 10))
        self.txt_log.pack(fill="both", expand=True)

        # 결과 버튼
        res_frame = tk.Frame(self.root)
        res_frame.pack(fill="x", padx=10, pady=10)
        self.btn_open_f = tk.Button(res_frame, text="결과 파일 열기", state="disabled", command=self.open_last_file)
        self.btn_open_f.pack(side="left", expand=True, fill="x", padx=5)
        self.btn_open_d = tk.Button(res_frame, text="폴더 열기", state="disabled", command=self.open_last_folder)
        self.btn_open_d.pack(side="left", expand=True, fill="x", padx=5)

    def log(self, msg):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n"
        if threading.current_thread() is self._main_thread:
            self._append_log(line)
        else:
            self.root.after(0, self._append_log, line)

    def _append_log(self, line):
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, line)
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def _set_run_button(self, state, text=None):
        self.btn_run.config(state=state, text=text if text is not None else self.btn_run.cget("text"))

    def _set_result_buttons(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_open_f.config(state=state)
        self.btn_open_d.config(state=state)

    def _show_info(self, title, text):
        messagebox.showinfo(title, text)

    def _show_error(self, title, text):
        messagebox.showerror(title, text)

    def get_default_template_path(self):
        base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.normpath(os.path.join(base, DEFAULT_TEMPLATE_PATH))
        if os.path.exists(candidate):
            return candidate
        alt = os.path.normpath(os.path.join(os.path.dirname(base), DEFAULT_TEMPLATE_PATH))
        if os.path.exists(alt):
            return alt
        return candidate

    def check_template(self):
        path = self.ent_temp.get()
        if os.path.exists(path):
            self.log(f"양식 파일 감지됨: {os.path.basename(path)}")
            if not self.ent_save.get(): self.ent_save.insert(0, os.path.dirname(path))
        else:
            self.log("⚠ 기본 경로에 양식 파일이 없습니다. 직접 선택해 주세요.")

    def browse_file(self, entry, name):
        p = filedialog.askopenfilename(title=f"{name} 파일 선택", filetypes=[("Data files", "*.csv *.xlsx *.xls")])
        if p:
            entry.delete(0, tk.END); entry.insert(0, p)
            if not self.ent_save.get(): self.ent_save.insert(0, os.path.dirname(p))

    def browse_template(self):
        p = filedialog.askopenfilename(title="양식 파일 선택", filetypes=[("Excel files", "*.xlsx")])
        if p: self.ent_temp.delete(0, tk.END); self.ent_temp.insert(0, p)

    def browse_folder(self):
        p = filedialog.askdirectory(title="저장 폴더 선택")
        if p: self.ent_save.delete(0, tk.END); self.ent_save.insert(0, p)

    def read_df(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == '.csv':
            last_error = None
            for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
                try:
                    return pd.read_csv(path, encoding=encoding)
                except UnicodeDecodeError as exc:
                    last_error = exc
            raise last_error
        return pd.read_excel(path)

    def clean_df(self, df, mode):
        df = df.copy()
        # 시간 처리
        if "Time" in df.columns:
            df["Time_dt"] = pd.to_datetime(df["Time"], format=TIME_FMT, errors="coerce")
            for fmt in SUPPORTED_TIME_FORMATS[1:]:
                missing = df["Time_dt"].isna()
                if not missing.any():
                    break
                parsed = pd.to_datetime(df.loc[missing, "Time"], format=fmt, errors="coerce")
                df.loc[missing, "Time_dt"] = parsed
            df = df[df["Time_dt"].notna()]
            df = df.sort_values("Time_dt")
        
        # Panel_ID 기준 최신화
        if "Panel_ID" in df.columns:
            df["Panel_ID"] = df["Panel_ID"].astype(str).str.strip().str.replace(" ", "", regex=False).str.replace("-", "", regex=False).str.replace("_", "", regex=False)
            df["Panel_ID"] = df["Panel_ID"].str.replace(".0", "", regex=False).str.upper()
            df = df.drop_duplicates(subset=["Panel_ID"], keep="last")
            df = df.sort_values("Panel_ID")
        
        return df

    def save_individual_file(self, df, mode, save_dir):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_path = os.path.join(save_dir, f"{mode}_cleaned_{timestamp}.xlsx")
        
        # 선별 컬럼 필터링
        selected_cols = CA_SELECTED_COLS if mode == "CA410" else LMK_SELECTED_COLS
        # 실제 데이터에 있는 컬럼만 필터링 (에러 방지)
        actual_cols = [c for c in selected_cols if c in df.columns]
        df_selected = df[actual_cols].copy()
        
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1_All", index=False)
            df_selected.to_excel(writer, sheet_name="Sheet2_Selected", index=False)
        
        return out_path

    def start_process(self):
        self.btn_run.config(state="disabled", text="처리 중...")
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        ca_path = self.ent_ca.get()
        lmk_path = self.ent_lmk.get()
        save_dir = self.ent_save.get()
        temp_path = self.ent_temp.get()

        if not any([ca_path, lmk_path]):
            messagebox.showwarning("알림", "정리할 파일을 하나 이상 선택해 주세요.")
            return
        if not save_dir:
            messagebox.showwarning("알림", "저장 폴더를 지정해 주세요.")
            return

        try:
            df_ca, df_lmk = None, None
            make_indiv = self.var_make_individual.get()

            # 1. 데이터 로드 및 정리
            if ca_path:
                self.log("CA410 데이터 정리 중...")
                df_ca = self.clean_df(self.read_df(ca_path), "CA410")
            
            if lmk_path:
                self.log("LMK6 데이터 정리 중...")
                df_lmk = self.clean_df(self.read_df(lmk_path), "LMK6")

            # 2. 결과 생성
            out_path = None
            
            # 개별 파일 생성 처리
            if make_indiv:
                if df_ca is not None:
                    self.log("CA410 개별 정리 파일(2개 시트) 생성 중...")
                    res = self.save_individual_file(df_ca, "CA410", save_dir)
                    if not (ca_path and lmk_path): out_path = res # 단일 모드일 때만 last_saved로 지정
                
                if df_lmk is not None:
                    self.log("LMK6 개별 정리 파일(2개 시트) 생성 중...")
                    res = self.save_individual_file(df_lmk, "LMK6", save_dir)
                    if not (ca_path and lmk_path): out_path = res # 단일 모드일 때만 last_saved로 지정

            # 통합 양식 기입 처리
            if ca_path and lmk_path:
                if not os.path.exists(temp_path):
                    raise FileNotFoundError(f"양식 파일을 찾을 수 없습니다: {temp_path}")
                if "Panel_ID" not in df_ca.columns or "Panel_ID" not in df_lmk.columns:
                    raise ValueError("CA410/LMK6 양쪽 모두 Panel_ID 컬럼이 필요합니다.")
                
                self.log("데이터 병합 중...")
                # LMK에서 필요한 것만 가져와서 병합
                lmk_merge_cols = ["Panel_ID", "Black_Uniformity", "White_Uniformity"]
                lmk_subset = df_lmk[[c for c in lmk_merge_cols if c in df_lmk.columns]]
                merged = pd.merge(df_ca, lmk_subset, on="Panel_ID", how="outer").sort_values("Panel_ID")
                
                self.log("양식 기입 중...")
                wb = load_workbook(temp_path)
                ws = wb.active
                start_row = 20
                mapping = {
                    'Red_X': 6, 'Red_Y': 7, 'Green_X': 8, 'Green_Y': 9, 'Blue_X': 10, 'Blue_Y': 11,
                    'White_SX': 13, 'White_SY': 14, 'White_LV': 15, 'Black_LV': 16,
                    'White_Uniformity': 19, 'Black_Uniformity': 20, 'EEPROM_59': 27
                }
                
                for i, row in enumerate(merged.itertuples(), start=start_row):
                    ws.cell(row=i, column=2, value=i - start_row + 1)
                    ws.cell(row=i, column=3, value=row.Panel_ID)
                    for attr, col in mapping.items():
                        if hasattr(row, attr): ws.cell(row=i, column=col, value=getattr(row, attr))
                
                out_path = os.path.join(save_dir, f"Daily data 통합정리_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                wb.save(out_path)
                self.log(f"✅ 통합 완료: {os.path.basename(out_path)}")

            if out_path:
                self.last_saved_file = out_path
                self.last_saved_folder = save_dir
                self.root.after(0, self._set_result_buttons, True)
                self.root.after(0, self._show_info, "성공", "데이터 정리가 완료되었습니다.")
            else:
                self.log("⚠ 작업은 완료되었으나 생성된 파일이 없습니다 (옵션 확인).")

        except Exception as e:
            self.log(f"❌ 에러: {str(e)}")
            self.root.after(0, self._show_error, "오류", f"처리 중 에러 발생:\n{str(e)}")
        finally:
            self.root.after(0, self._set_run_button, "normal", "▶ One-Click 정리 시작")

    def open_last_file(self):
        if self.last_saved_file: os.startfile(self.last_saved_file)
    def open_last_folder(self):
        if self.last_saved_folder: os.startfile(self.last_saved_folder)

if __name__ == "__main__":
    root = tk.Tk()
    app = OneClickApp(root)
    root.mainloop()
