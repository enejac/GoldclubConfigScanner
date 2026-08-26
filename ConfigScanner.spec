# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for Config Scanner only (no log investigator / AFT inject)."""

import os
import sys

from PyInstaller.utils.hooks import collect_all

datas = [
    ("assets/log_investigator_icon.png", "assets"),
    ("config_scanner/assets/config.json", "config_scanner/assets"),
    ("config_scanner/assets/profiles.json", "config_scanner/assets"),
    ("config_scanner/assets/templates/report.html", "config_scanner/assets/templates"),
    ("cabinet_tools/roulette/Kill-All.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/Run-FullStack.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/Clear-Error30.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/Clear-TrialPersistent.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/Fix-Error30Clock.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/GoldClubServices.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/Convert-GcxmlSetup.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/Invoke-SoftwareVersionSwap.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/GoldClubElevate.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/Bootstrap-Elevate-111.ps1", "cabinet_tools/roulette"),
    ("cabinet_tools/roulette/GCI-ELEVATE-NOW.cmd", "cabinet_tools/roulette"),
    (
        "cabinet_tools/shared/onstart.d/91-EnableShareAndWinRM.ps1",
        "cabinet_tools/shared/onstart.d",
    ),
]
binaries = []
hiddenimports = [
    "gui.app_logging",
    "gui.app_branding",
    "gui.config_scanner_tab",
    "gui.config_scanner_worker",
    "gui.config_scanner_window",
    "gui.thin_progress",
    "gui.theme",
    "gui.theme_utils",
    "gui.win_title_bar",
    "gui.notepad_pp",
    "config_scanner",
    "config_scanner.service",
    "network.lab_access",
    "network.cabinet_identity",
    "network.pe_runtime",
    "network.ruleta_stack_probe",
    "network.software_version_swap",
    "automation.remote_exec",
    "automation.cabinet_elevate",
    "automation.winrm_output",
    "gui.palette_adapt",
    "ai_helper.gcxml_decrypt",
    "win32api",
    "pywintypes",
]

if sys.platform == "win32":
    for _win_mod in ("win32api", "pywintypes", "win32ctypes"):
        try:
            _win_d, _win_b, _win_h = collect_all(_win_mod)
            datas += _win_d
            binaries += _win_b
            hiddenimports += _win_h
        except Exception as exc:  # noqa: BLE001
            print(f"[ConfigScanner.spec] WARN: could not collect {_win_mod}: {exc}")

excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "pytest",
    "_pytest",
    "matplotlib",
    "scipy",
    "pandas",
    "cv2",
    "google",
    "llama_cpp",
    "gui.main_window",
    "gui.sas_verify_app",
]

a = Analysis(
    ["gui_app.py"],
    pathex=[],
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
    name="ConfigScanner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/log_investigator.ico",
)
