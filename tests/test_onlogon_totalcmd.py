"""Contract tests: one Total Commander instance from onlogon / USB onstart."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONLOGON = ROOT / "cabinet_tools" / "shared" / "user-init" / "onlogon.ps1"
ONSTART_SHARED = ROOT / "cabinet_tools" / "shared" / "onstart.d" / "91-EnableShareAndWinRM.ps1"
ONSTART_ROULETTE = ROOT / "cabinet_tools" / "roulette" / "onstart.d" / "91-EnableShareAndWinRM.ps1"
OO_SECURITY = ROOT / "cabinet_tools" / "shared" / "platform-security" / "OO_Security.ps1"
UNLOCK_TASK = ROOT / "cabinet_tools" / "shared" / "platform-security" / "Unlock-GoldClubVolume.ps1"
MUX_GHOSTS = ROOT / "cabinet_tools" / "shared" / "platform-security" / "Clear-MuxGhostPorts.ps1"
INSTALL_TASKS = ROOT / "cabinet_tools" / "shared" / "platform-security" / "Install-GoldClubBootTasks.ps1"
UNLOCK_RETRY = ROOT / "cabinet_tools" / "shared" / "platform-security" / "Unlock-GoldClubRetry.ps1"
ENSURE_HW = ROOT / "cabinet_tools" / "shared" / "platform-security" / "Ensure-GoldClubHwStack.ps1"
WATCH_PS1 = ROOT / "cabinet_tools" / "shared" / "Start-SlotGameWatch.ps1"
START_GAME = ROOT / "cabinet_tools" / "shared" / "platform-security" / "StartGame.cmd"
START_GAME_WAIT = ROOT / "cabinet_tools" / "shared" / "platform-security" / "StartGameWait.cmd"
COPY_ONLOGON = ROOT / "cabinet_tools" / "shared" / "CopyOnlogon.bat"


def _code_only(src: str) -> str:
    """Drop whole-line comments so ordering assertions cannot match prose."""
    return "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))


def test_onlogon_skips_second_total_commander() -> None:
    src = ONLOGON.read_text(encoding="utf-8")
    assert "Test-TotalCommanderRunning" in src
    assert "TOTALCMD64" in src
    assert "skip second instance" in src
    assert "-ArgumentList '/O'" in src
    start_idx = src.index("function Start-TotalCommanderFromUsb")
    body = src[start_idx : src.index("Write-OnlogonRunLog 'Total Commander not found'")]
    assert "Test-TotalCommanderRunning" in body
    assert "Start-Process" in body
    assert "C:\\totalcmd\\TOTALCMD.EXE" not in body
    assert "D:\\totalcmd\\TOTALCMD.EXE" not in body


def test_onlogon_stock_when_usb_missing() -> None:
    src = ONLOGON.read_text(encoding="utf-8")
    assert "stock onlogon (game start without USB extras)" in src
    assert "Start-StockGoldClubGame" in src
    assert "Test-GoldClubGameRunning" in src
    assert "G:\\Bootstrap.exe" in src
    assert "G:\\slot\\game-start.exe" in src
    assert "Test-IsGoldClubGameVolume" in src
    assert "slot\\OneHand.exe" in src
    assert "Get-PSDrive" not in src
    assert "[IO.DriveInfo]::GetDrives()" in src
    assert "IsReady" in src
    assert "G:\\Services" in src
    game_idx = src.index("Start-StockGoldClubGame")
    usb_idx = src.index("$script:UsbRoot = Get-GoldClubUsbRoot")
    assert game_idx < usb_idx


def test_onlogon_starts_slot_fullstack_before_game() -> None:
    src = ONLOGON.read_text(encoding="utf-8")
    assert "[switch]$StackOnly" in src
    assert "[string]$WorkingDirectory" in src
    assert "sc.exe create GoldClub.Aurum.Services" in src
    assert "function Start-SlotFullStack" in src
    assert "GoldClub.Aurum.Services" in src
    assert "GoldClub Hardware Subsystem" in src
    assert "GoldClub.Logging.LogDaemon" in src
    assert "XYNTService.exe" in src
    assert "--install" in src
    game_idx = src.index("Start-StockGoldClubGame\n")
    stack_before = src.index("Start-SlotFullStack\n")
    assert stack_before < game_idx
    assert "AurumSetup.xml" in src
    assert "layout.json" not in src
    assert "function Ensure-SlotDallasKey" in src
    assert "01D68A721B000019" in src
    stack_fn = src[src.index("function Start-SlotFullStack") : src.index("function Ensure-SlotDallasKey")]
    assert "GoldClub-Ensure-HwStack" in stack_fn
    assert "Ensure-SlotDallasKey" in stack_fn
    assert "WaitForExit(12000)" in src
    assert "Install-GoldClubExeService -ExePath 'C:\\goldclub\\services\\aurum\\bin\\GoldClub.Aurum.Services.exe'" not in src


def test_onlogon_consumes_pending_ramclear_before_stack() -> None:
    src = ONLOGON.read_text(encoding="utf-8")
    assert "function Invoke-PendingRamClear" in src
    assert r"G:\var\state\maintenance\invoke-task-ramclear" in src
    assert r"G:\bin\RunManteinanceTasks.1.ps1" in src
    assert r"G:\maintenance\tasks\ramclear" in src
    body = src[
        src.index("function Invoke-PendingRamClear") : src.index("function Test-IsGoldClubGameVolume")
    ]
    # goldclub.init.1 is missing on this image, so the runner must build its own
    # PSModulePath / Path - passing -nested would break Import-Ini and 7za.exe.
    args_line = next(line for line in body.splitlines() if "-ArgumentList" in line)
    assert "'-nested'" not in args_line
    assert "'-File', $runner, '-path', $tasks" in args_line
    assert "Remove-Item -LiteralPath $marker" in body
    assert "WaitForExit(300000)" in body
    # 01-StopServices stops every goldclub service, so it has to run first.
    ramclear_idx = src.index("\nInvoke-PendingRamClear\n")
    stack_idx = src.index("\nStart-SlotFullStack\n")
    game_idx = src.index("\nStart-StockGoldClubGame\n")
    assert ramclear_idx < stack_idx < game_idx


def test_oo_security_starts_game_before_any_usb_work() -> None:
    """Game start must be unconditional; USB may only add programs after it."""
    src = OO_SECURITY.read_text(encoding="utf-8")
    assert "UnlockerDisk.exe" in src
    assert "[string]$WorkingDirectory" in src
    assert "Enable-PSRemoting" not in src
    assert "Apply-CsRestore" not in src
    assert "Start-Process -WorkingDirectory 'C:\\goldclub'" not in src
    assert "boot-kick.txt" in src
    assert "holding shell" in src
    # C:\goldclub is a BitLocker junction that hangs while G: is locked. It may
    # only appear in the comment that warns about it, never in code.
    code = _code_only(src)
    assert "C:\\goldclub" not in code

    unlock_idx = code.index("UnlockerDisk.exe")
    boot_idx = code.index("Start-Process -FilePath 'G:\\Bootstrap.exe'")
    lab_idx = code.index("Start-LabDesktop.ps1")
    assert unlock_idx < boot_idx < lab_idx

    # Bootstrap is reached with no USB test in between, so a missing lab USB
    # cannot change whether the game starts.
    between = code[unlock_idx:boot_idx]
    for usb_token in ("Start-LabDesktop", "Find-LabUsbRoot", "UsbRoot", "Removable'"):
        assert usb_token not in between, usb_token


def test_oo_security_usb_extras_are_additive_and_async() -> None:
    src = OO_SECURITY.read_text(encoding="utf-8")
    assert "-PollForUsb" in src
    assert "MinDelaySeconds" in src
    assert "USB extras are additive" in src
    # Start-LabDesktop owns every USB tool. Launch it fire-and-forget (no -Wait /
    # WaitForExit) so it can never hold up or gate the game.
    lab_line = next(
        line for line in src.splitlines() if "Start-LabDesktop.ps1" in line and "Start-HiddenPowerShell" in line
    )
    assert "-PollForUsb" in lab_line
    assert "-Wait" not in lab_line
    # It is not wrapped in a USB presence test - the script decides for itself.
    assert "if (Start-HiddenPowerShell 'C:\\Platform\\Security\\Start-LabDesktop.ps1'" in src


def test_oo_security_lab_stack_is_fallback_only() -> None:
    """Wait for HWSubsys, then Bootstrap. No goldclub Start-Service slop."""
    src = OO_SECURITY.read_text(encoding="utf-8")
    assert "function Wait-GameRunning" in src
    assert "function Test-GameRunning" in src
    assert "function Wait-HwSubsysRunning" in src
    hw_idx = src.index("Wait-HwSubsysRunning -TimeoutSeconds 120")
    boot_idx = src.index("Start-Process -FilePath 'G:\\Bootstrap.exe'")
    wait_idx = src.index("Wait-GameRunning -TimeoutSeconds 180")
    assert hw_idx < boot_idx < wait_idx

    def launches(text: str) -> list[str]:
        return [line.strip() for line in _code_only(text).splitlines() if "Start-HiddenPowerShell" in line]

    fallback = src[wait_idx:]
    fallback_launches = launches(fallback)
    assert not any("Start-GoldClubHardware" in line for line in fallback_launches)
    assert not any("onlogon.ps1" in line for line in fallback_launches)
    assert not any("Start-LabDesktop" in line for line in fallback_launches)

    before_launches = launches(src[:wait_idx])
    assert not any("Start-GoldClubHardware" in line for line in before_launches)
    assert not any("onlogon.ps1" in line for line in before_launches)
    assert any("Start-LabDesktop.ps1" in line for line in before_launches)


def test_oo_security_keeps_waiting_for_the_unlock() -> None:
    src = OO_SECURITY.read_text(encoding="utf-8")
    assert "function Invoke-UnlockerDisk" in src
    assert "function Wait-GoldClubReady" in src
    assert "unlock wait" in src
    # Keep re-kicking the SYSTEM task and only declare FATAL after the deadline.
    wait_idx = src.index("while (-not (Test-GoldClubReady) -and (Get-Date) -lt $deadline)")
    fatal_idx = src.index("FATAL: G: never unlocked")
    assert wait_idx < fatal_idx
    # The legacy helper is still a fallback for cabinets without the task.
    assert "Unlock-GoldClubRetry.ps1" in src


def test_boot_scripts_are_ascii_for_powershell_51() -> None:
    """No-BOM files are read as ANSI by PS 5.1; a smart dash breaks the parse."""
    for path in (OO_SECURITY, ONLOGON, UNLOCK_TASK, UNLOCK_RETRY, MUX_GHOSTS, INSTALL_TASKS, ENSURE_HW, WATCH_PS1):
        text = path.read_text(encoding="utf-8")
        bad = sorted({ch for ch in text if ord(ch) > 126})
        assert not bad, f"{path.name} has non-ASCII: {[hex(ord(c)) for c in bad]}"


def test_all_cabinet_tools_ps1_are_ascii() -> None:
    """Lab/roulette helpers must stay ASCII if copied onto a cabinet."""
    tools = ROOT / "cabinet_tools"
    offenders: list[str] = []
    for path in sorted(tools.rglob("*.ps1")):
        text = path.read_text(encoding="utf-8")
        bad = sorted({ch for ch in text if ord(ch) > 126})
        if bad:
            offenders.append(
                f"{path.relative_to(ROOT)}: {[hex(ord(c)) for c in bad]}"
            )
    assert not offenders, "\n".join(offenders)


def test_oo_security_does_not_rely_on_a_filtered_token_to_unlock() -> None:
    """eshell runs the shell as goldclub with Administrators 'deny only'.

    BitLocker unlock needs a real admin token, so the shell must delegate to the
    SYSTEM task instead of burning minutes on calls that cannot succeed.
    """
    src = OO_SECURITY.read_text(encoding="utf-8")
    assert "function Test-Elevated" in src
    assert "GoldClub-Unlock-Volume" in src
    assert "shell token elevated=" in src
    # The direct UnlockerDisk call is gated on actually being elevated.
    code = _code_only(src)
    direct = [line for line in code.splitlines() if "Invoke-UnlockerDisk" in line and "function" not in line]
    assert direct, "expected at least one guarded direct call"
    for line in direct:
        assert "$elevated" in line or line.strip().startswith("Invoke-UnlockerDisk -Wait")
    assert "if ($elevated) {" in src


def test_oo_security_never_gives_up_before_starting_the_game() -> None:
    """The 12:11 boot unlocked G: late and nothing ever started the game."""
    src = _code_only(OO_SECURITY.read_text(encoding="utf-8"))
    fatal_idx = src.index("FATAL: G: never unlocked")
    boot_idx = src.index("Start-Process -FilePath 'G:\\Bootstrap.exe'")
    # The only script-level early exit is the genuine give-up, and it comes
    # after a long wait. Indented returns belong to functions.
    assert "AddMinutes(12)" in src
    assert fatal_idx < boot_idx
    top_level_returns = [line for line in src.splitlines() if line == "    return"]
    assert len(top_level_returns) == 1, f"unexpected early returns: {top_level_returns}"


def test_unlock_task_refuses_to_spin_without_elevation() -> None:
    src = UNLOCK_TASK.read_text(encoding="utf-8")
    assert "function Test-Elevated" in src
    assert "NOT ELEVATED" in src
    assert "UnlockerDisk.exe" in src
    # Bails immediately rather than looping on a token that cannot work.
    body = src[src.index("if (-not (Test-Elevated))") :]
    assert "exit 2" in body.split("}")[0] + "}"


def test_mux_ghost_cleanup_is_narrow_and_safe() -> None:
    src = MUX_GHOSTS.read_text(encoding="utf-8")
    assert "VID_0483&PID_5740" in src
    # Never remove the live board, and never act when it is absent.
    assert "no PRESENT MUX right now - refusing to remove anything" in src
    assert "Where-Object { -not $_.Present }" in src
    assert "COM Name Arbiter" in src
    # A COM number a live port uses must stay reserved.
    assert "is in use by a live port - leaving reserved" in src
    # Board port maps are off limits.
    assert "layout.json" not in src.replace("# ", "", 1) or "forbidden" in src
    for banned in ("Set-Content", "locations.json"):
        code_lines = [line for line in src.splitlines() if not line.lstrip().startswith("#")]
        assert not [line for line in code_lines if banned in line], banned
    # pnputil on 1809 cannot remove devices, so devcon is required.
    assert "devcon" in src
    assert "C:\\Platform\\Security\\devcon.exe" in src


def test_boot_tasks_run_as_system_at_startup() -> None:
    src = INSTALL_TASKS.read_text(encoding="utf-8")
    assert "/SC ONSTART" in src
    assert "/RU SYSTEM" in src
    assert "/RL HIGHEST" in src
    assert "GoldClub-Unlock-Volume" in src
    assert "GoldClub-Clear-MuxGhosts" in src
    assert "GoldClub-Ensure-HwStack" in src
    assert "Ensure-GoldClubHwStack.ps1" in src
    # ONSTART must Start after G: unlocks, not Restart.
    assert "-Arguments '-Restart'" not in src
    # devcon is staged on C: because G: is still locked when the task runs.
    assert "devcon.exe" in src
    assert "Test-Elevated" in src


def test_lab_onlogon_does_not_share_stock_log_file() -> None:
    """The stock chain Tee-Objects onlogon.log, and Tee truncates."""
    src = ONLOGON.read_text(encoding="utf-8")
    assert r"G:\var\log\onlogon-lab.log" in src
    assert r"'G:\var\log\onlogon.log'" not in src


def test_startgame_cmd_does_not_probe_goldclub() -> None:
    cmd = START_GAME.read_text(encoding="utf-8")
    wait = START_GAME_WAIT.read_text(encoding="utf-8")
    assert "UnlockerDisk.exe" in cmd
    assert "StartGameWait.cmd" in cmd
    assert "G:\\Bootstrap.exe" in wait
    assert "C:\\goldclub" not in cmd + wait
    assert "Test-Path" not in cmd + wait
    assert "if exist C:\\goldclub" not in (cmd + wait).lower()


def test_onstart_skips_goldclub_as_usb() -> None:
    for path in (ONSTART_SHARED, ONSTART_ROULETTE):
        src = path.read_text(encoding="utf-8")
        assert "slot\\OneHand.exe" in src
        assert "ruleta\\Ruleta.exe" in src


def test_copyonlogon_deploys_onlogon_and_oo_security() -> None:
    src = COPY_ONLOGON.read_text(encoding="utf-8")
    assert "onlogon.ps1" in src
    assert r"c:\Goldclub\platform\user\init\onlogon.ps1" in src
    assert r"c:\Platform\Security\onlogon.ps1" in src
    assert "OO_Security.ps1" in src
    assert r"c:\Platform\Security\OO_Security.ps1" in src
    assert "StartGame.cmd" in src
    assert "StartGameWait.cmd" in src
    assert "Start-LabDesktop.ps1" in src


def test_fix_usb_mount_enables_automount() -> None:
    src = (ROOT / "cabinet_tools" / "shared" / "Fix-UsbMount.ps1").read_text(encoding="utf-8")
    assert "mountvol /E" in src
    assert "automount enable" in src
    assert "Recovery" in src
    assert "Enable-PnpDevice" in src


def test_onstart_does_not_restart_existing_total_commander() -> None:
    for path in (ONSTART_SHARED, ONSTART_ROULETTE):
        src = path.read_text(encoding="utf-8")
        assert "Get-AppProcessNames" in src
        assert "skip second instance" in src
        assert "-Arguments '/O'" in src
        assert "GoldClub-TotalCommander-USB' -ExePath $tcExe -ProcessName $tcProc -Label 'TotalCommander' -RestartExisting" not in src
