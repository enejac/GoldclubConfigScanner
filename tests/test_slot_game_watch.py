"""Escape / Bootstrap GameBinRun watcher."""

from __future__ import annotations

from pathlib import Path

from config_scanner.slot_game_watch import (
    GAMEBINRUN_WATCH,
    HW_SERVICE_NAMES,
    STOCK_GAMEBINRUN,
    rewrite_bootstrap_gamebinrun,
)

ROOT = Path(__file__).resolve().parents[1]
WATCH_PS1 = ROOT / "cabinet_tools" / "shared" / "Start-SlotGameWatch.ps1"
ENSURE_PS1 = (
    ROOT
    / "cabinet_tools"
    / "shared"
    / "platform-security"
    / "Ensure-GoldClubHwStack.ps1"
)
WATCH_CS = ROOT / "cabinet_tools" / "shared" / "Start-SlotGameWatch.cs"

STOCK_INI = """# log directory
LogDir %:/var/log

# define actual game executable
GameDir %:/slot
GameBinRun %:/slot/game-start.exe
GameBin %:/slot/OneHand.exe

# game configuration utility
ConfigDir %:/BiOS
ConfigBin %:/BiOS/BiOS2.exe

#eof
"""


def test_rewrite_bootstrap_gamebinrun_points_at_watcher() -> None:
    out = rewrite_bootstrap_gamebinrun(STOCK_INI)
    assert "GameBinRun %:/slot/Start-SlotGameWatch.exe" in out
    assert "GameBin %:/slot/OneHand.exe" in out
    assert "ConfigBin %:/BiOS/BiOS2.exe" in out
    assert "GameBinRun %:/slot/game-start.exe" not in out


def test_rewrite_bootstrap_gamebinrun_can_restore_stock() -> None:
    watched = rewrite_bootstrap_gamebinrun(STOCK_INI)
    restored = rewrite_bootstrap_gamebinrun(watched, STOCK_GAMEBINRUN)
    assert "GameBinRun %:/slot/game-start.exe" in restored
    assert GAMEBINRUN_WATCH not in restored


def test_rewrite_bootstrap_preserves_crlf() -> None:
    crlf = STOCK_INI.replace("\n", "\r\n")
    out = rewrite_bootstrap_gamebinrun(crlf)
    assert "\r\n" in out
    assert out.split("GameBinRun")[1].startswith(" %:/slot/Start-SlotGameWatch.exe\r\n")


def test_hw_service_names_include_subsystem() -> None:
    assert "GoldClub Hardware Subsystem" in HW_SERVICE_NAMES
    assert "GoldClub.Aurum.Services" in HW_SERVICE_NAMES


def test_watch_script_absorbs_escape_and_bounces_hw() -> None:
    src = WATCH_PS1.read_text(encoding="utf-8")
    assert "Unexpected game stop" in src
    assert "Start-SlotGameWatch" in src
    assert "GoldClub-Ensure-HwStack" in src
    assert "SharedPreferences.bin" in src
    assert "game-start.exe" in src
    assert "BiOS2.exe" in src
    assert "OneHand already running" in src
    assert "not Escape" in src
    assert "HWSubsys already Running - skip bounce" in src
    assert "function Get-AurumRunning" in src
    assert "function Get-HwStackReady" in src
    assert "Get-HwStackReady" in src
    assert "Global\\GoldClub-Start-SlotGameWatch" in src
    assert "game-start returned but OneHand still running" in src
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "exit 11" not in code
    assert "$code -ne 11" in code
    assert "while ($true)" in src
    # Live Push kill must restart OneHand, not open the BiOS2 menu.
    bounce_idx = src.index("Wait-SlotGameReady -BounceHw")
    escape_idx = src.index("$code -ne 11")
    assert bounce_idx > escape_idx


def test_slot_start_script_waits_for_onehand_not_bios2() -> None:
    from config_scanner.live_push import _slot_start_script

    script = _slot_start_script((r"G:\Bootstrap.exe",))
    assert "OneHand did not start after Bootstrap" in script
    assert "Live Push started BiOS2 menu instead of OneHand" in script
    assert "Get-Process -Name Bootstrap,OneHand" not in script
    assert "Ensure-GoldClubAurumRunning" in script
    assert script.index("Ensure-GoldClubAurumRunning") < script.index(
        "GoldClub-LivePush-Start"
    )


def test_ensure_hw_stack_refuses_filtered_token() -> None:
    src = ENSURE_PS1.read_text(encoding="utf-8")
    assert "function Test-Elevated" in src
    assert "exit 2" in src
    assert "GoldClub Hardware Subsystem" in src
    assert "Restart-Service" in src
    assert "SettleSec" in src
    assert "waiting for G: GOLDCLUB before starting services" in src
    assert "function Test-GoldClubReady" in src
    assert "Aurum Running" in src
    assert "Aurum not Running" in src


def test_unlock_task_starts_services_after_g_ready() -> None:
    src = (
        ROOT
        / "cabinet_tools"
        / "shared"
        / "platform-security"
        / "Unlock-GoldClubVolume.ps1"
    ).read_text(encoding="utf-8")
    assert "function Invoke-HwStackAfterUnlock" in src
    assert "Ensure-GoldClubHwStack.ps1" in src
    assert "G: ready - starting GoldClub services" in src
    assert src.count("Invoke-HwStackAfterUnlock") >= 3


def test_watch_cs_hosts_powershell() -> None:
    src = WATCH_CS.read_text(encoding="utf-8")
    assert "Start-SlotGameWatch.ps1" in src
    assert "powershell.exe" in src
    assert "game-start.exe" in src
