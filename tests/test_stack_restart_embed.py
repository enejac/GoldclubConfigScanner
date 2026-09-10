"""Standalone exe stack restart: bundled scripts, no USB, do not kill ConfigScanner."""

from __future__ import annotations

from pathlib import Path

from config_scanner.live_push import goldclub_stack_kind


def test_find_stack_scripts_uses_frozen_bundle(tmp_path: Path, monkeypatch) -> None:
    from config_scanner import stack_restart as sr

    bundle = tmp_path / "mei" / "cabinet_tools" / "roulette"
    bundle.mkdir(parents=True)
    for name in ("Kill-All.ps1", "Run-FullStack.ps1", "GoldClubServices.ps1"):
        (bundle / name).write_text("# bundle\n", encoding="utf-8")
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr(sr, "app_install_dir", lambda: install)
    monkeypatch.setattr(sr.sys, "frozen", True, raising=False)
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)

    found = sr.find_stack_scripts()
    assert found is not None
    kill, run = found
    assert kill.parent == bundle
    assert run.parent == bundle
    assert kill.name == "Kill-All.ps1"
    assert run.name == "Run-FullStack.ps1"


def test_find_stack_scripts_prefers_usb_when_complete(tmp_path: Path, monkeypatch) -> None:
    from config_scanner import stack_restart as sr

    install = tmp_path / "ConfigScanner"
    usb = install / "usb_scripts" / "roulette"
    usb.mkdir(parents=True)
    bundle = tmp_path / "mei" / "cabinet_tools" / "roulette"
    bundle.mkdir(parents=True)
    for folder in (usb, bundle):
        for name in ("Kill-All.ps1", "Run-FullStack.ps1", "GoldClubServices.ps1"):
            (folder / name).write_text(f"# {folder.name}\n", encoding="utf-8")
    monkeypatch.setattr(sr, "app_install_dir", lambda: install)
    monkeypatch.setattr(sr.sys, "frozen", True, raising=False)
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)

    found = sr.find_stack_scripts()
    assert found is not None
    assert found[0].parent == usb


def test_goldclub_stack_kind_onehand_in_slot_folder(tmp_path: Path) -> None:
    slot = tmp_path / "slot"
    slot.mkdir()
    (slot / "OneHand.exe").write_bytes(b"MZ")
    assert goldclub_stack_kind(slot) == "slot"
    gold = tmp_path / "goldclub"
    gold.mkdir()
    (gold / "Bootstrap.exe").write_bytes(b"MZ")
    assert goldclub_stack_kind(gold) == "slot"


def test_goldclub_stack_kind_ruleta_wins_over_bootstrap(tmp_path: Path) -> None:
    gold = tmp_path / "goldclub"
    (gold / "ruleta").mkdir(parents=True)
    (gold / "Bootstrap.exe").write_bytes(b"MZ")
    (gold / "ruleta" / "ruleta.exe").write_bytes(b"MZ")
    assert goldclub_stack_kind(gold) == "roulette"


def test_kill_all_protects_config_scanner() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "cabinet_tools"
        / "roulette"
        / "Kill-All.ps1"
    ).read_text(encoding="utf-8")
    assert "ConfigScanner" in src
    assert "Test-TreeHasProtectedPid" in src
    assert "taskkill /F /T /PID" in src
    assert "taskkill /F /PID $ProcessId" in src


def test_arm_watchdog_skipped_off_egm(monkeypatch) -> None:
    from config_scanner import live_push as lp

    called: list[str] = []
    monkeypatch.setattr(lp, "running_on_egm", lambda: False)
    monkeypatch.setattr(lp, "_slot_target_is_local", lambda _t: True)
    monkeypatch.setattr(
        lp.subprocess,
        "Popen",
        lambda *a, **k: called.append("popen"),
    )
    lp._arm_slot_bootstrap_watchdog(r"C:\goldclub")
    assert called == []
