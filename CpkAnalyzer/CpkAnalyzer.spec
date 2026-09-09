# -*- mode: python ; coding: utf-8 -*-
"""CpkAnalyzer exe 빌드 설정.

scipy / matplotlib / PyQt5 는 동적 임포트와 확장 모듈이 많아 PyInstaller 가
자동 분석만으로는 빠뜨리기 쉽다. 실제로 --hidden-import 를 CMD 줄바꿈(^)으로
넘기던 기존 README 명령은 PowerShell 에서 첫 줄만 실행돼 scipy 가 통째로
누락됐고, 실행 시 ModuleNotFoundError: No module named 'scipy' 가 났다.
collect_all 로 서브모듈·바이너리·데이터를 한 번에 수집해 그 경로를 없앤다.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

project_dir = Path(SPECPATH)

hiddenimports = []
binaries = []
datas = []

for package in ("scipy", "numpy", "matplotlib", "pandas", "openpyxl"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# main.py 와 같은 폴더의 사이드카 모듈. 자동 수집되지만 명시해 두면
# 다른 작업 폴더에서 빌드해도 누락되지 않는다.
hiddenimports += ["stats_core", "theme", "widgets"]

datas += collect_data_files("matplotlib", subdir="mpl-data")

for resource in ("assets", "sample_data"):
    resource_dir = project_dir / resource
    if resource_dir.exists():
        datas.append((str(resource_dir), resource))

# PyQt5 는 Qt5 전체를 끌고 오므로 쓰지 않는 하위 스택을 덜어낸다.
excludes = [
    "PyQt5.QtWebEngineCore",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtQml",
    "PyQt5.QtQuick",
    "PyQt5.Qt3DCore",
    "PyQt5.QtBluetooth",
    "PyQt5.QtMultimedia",
    "tkinter",
    "scipy.io.matlab",
    "scipy.spatial",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
]

a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CpkAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 압축은 사내 백신이 자주 오탐하고 scipy/Qt DLL 파손 사례가 있어 끈다.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/app.ico"],
)
