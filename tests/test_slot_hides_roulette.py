"""A detected slot cabinet must not surface Ruleta trial tooling or wording."""

from __future__ import annotations

import json
from pathlib import Path

from config_scanner.service import ConfigScannerService
from roulette_trial import ROLLBACK_TRIAL_SUBDIR


def _tool_root(tmp_path: Path) -> Path:
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    (tool_root / "config.json").write_text(
        json.dumps(
            {
                "gameDrive": None,
                "scanRoots": ["config"],
                "includePatterns": ["*.xml"],
                "parallelWorkers": 1,
                "snapshotsDir": "snapshots",
                "reportsDir": "reports",
            }
        ),
        encoding="utf-8",
    )
    (tool_root / "snapshots").mkdir()
    (tool_root / "reports").mkdir()
    (tool_root / "templates").mkdir()
    return tool_root


def _slot_root(tmp_path: Path) -> Path:
    slot_root = tmp_path / "Goldclub" / "slot"
    slot_root.mkdir(parents=True)
    (slot_root / "OneHand.exe").write_bytes(b"onehand")
    (slot_root / "game-start.exe").write_bytes(b"start")
    (slot_root / "GoldClub.Settings.dll").write_bytes(b"dll")
    (slot_root / "mgconfig.xml").write_text("<Multigamer/>", encoding="utf-8")
    return slot_root


def _roulette_root(tmp_path: Path) -> Path:
    root = tmp_path / "usb_d"
    ruleta = root / "ruleta"
    ruleta.mkdir(parents=True)
    (ruleta / "Ruleta.exe").write_bytes(b"MZ")
    (ruleta / "BuildVersion.txt").write_text(
        "Source Version: 1\nBranch: $/x/10.2.0.876\nBuild Number: 40119\n",
        encoding="utf-8",
    )
    (ruleta / "persistent").mkdir()
    (ruleta / "persistent" / "RouletteActivate.dat").write_bytes(b"\x01" * 32)
    (root / "config").mkdir()
    (root / "config" / "setup.xml").write_text("<root/>", encoding="utf-8")
    return root


def test_game_kind_for_target_detects_slot(tmp_path: Path) -> None:
    service = ConfigScannerService(_tool_root(tmp_path), profile_id="slot_lab_90")
    assert service.game_kind_for_target(str(_slot_root(tmp_path))) == "slot"


def test_slot_scan_writes_no_rollback_trial(tmp_path: Path) -> None:
    slot_root = _slot_root(tmp_path)
    service = ConfigScannerService(_tool_root(tmp_path), profile_id="slot_lab_90")
    result = service.run_scan(str(slot_root))
    assert not (result.snapshot_path / ROLLBACK_TRIAL_SUBDIR).exists()
    joined = " ".join(result.warnings).casefold()
    assert "ruleta" not in joined
    assert "roulette" not in joined


def test_roulette_scan_still_captures_rollback_trial(tmp_path: Path) -> None:
    roulette_root = _roulette_root(tmp_path)
    service = ConfigScannerService(_tool_root(tmp_path), profile_id="roulette_usb")
    result = service.run_scan(str(roulette_root))
    assert (result.snapshot_path / ROLLBACK_TRIAL_SUBDIR).is_dir()


def test_capture_rollback_trial_bind_is_noop_on_slot(tmp_path: Path) -> None:
    slot_root = _slot_root(tmp_path)
    service = ConfigScannerService(_tool_root(tmp_path), profile_id="slot_lab_90")
    result = service.run_scan(str(slot_root))
    notes = service.capture_rollback_trial_bind(result.snapshot_name, str(slot_root))
    assert notes == []
    assert not (result.snapshot_path / ROLLBACK_TRIAL_SUBDIR).exists()


def test_tab_hides_trial_keypad_actions_on_slot() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "config_scanner_tab.py"
    ).read_text(encoding="utf-8")
    assert "def _refresh_game_kind_actions" in src
    for action in ("_clear_error30_action", "_llave_password_action"):
        assert f'"{action}"' in src
    # Detection result must be applied before actions are re-enabled.
    validated = src.split("def _on_target_validated", 1)[1].split("def ", 1)[0]
    assert "_refresh_egm_ui_strings()" in validated
    # Kind is read from the Cabinet path immediately (no valid-flag gate).
    kind_fn = src.split("def _game_kind", 1)[1].split("\n    def ", 1)[0]
    assert "if target and self._target_valid" not in kind_fn
    assert "scan_target=target" in kind_fn
    assert "self._live_sw_label.setVisible(False)" in src
    assert "self._live_sw_label.setVisible(True)" in src
    # Version / kind SMB stays off the UI thread so Create is not frozen.
    assert "schedule_live_exe_version" in src
    assert "live_exe_version_for_target(" not in src.split(
        "def _refresh_live_game_version", 1
    )[1].split("def ", 1)[0]
    # ERROR 30 / LLAVE stay disabled while hidden.
    assert "self._clear_error30_action.isVisible()" in src
    assert "self._llave_password_action.isVisible()" in src
    # Compare legend no longer hardcodes the roulette wording.
    assert "Amber = encrypted ruleta setup.xml" not in src
    assert "encrypted_setup_legend(self._game_kind())" in src
    assert "rollback_matches_game_kind(" in src
    # Construction tooltips must not hardcode Ruleta software wording.
    assert "config + Ruleta software" not in src
    assert "Save live config and Ruleta software" not in src


def test_llave_prompt_and_error30_guarded_by_game_kind() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "config_scanner_tab.py"
    ).read_text(encoding="utf-8")
    for name in (
        "_on_clear_error30_clicked",
        "_prompt_llave_trial_password",
        "_remote_software_transfer",
    ):
        body = src.split(f"def {name}", 1)[1].split("\n    def ", 1)[0]
        assert "uses_trial_keypad(self._game_kind())" in body, name
