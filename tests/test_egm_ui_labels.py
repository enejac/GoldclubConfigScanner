"""Profile-aware UI labels for slot and roulette snapshots."""

from __future__ import annotations

from config_scanner.egm_ui_labels import (
    detect_target_tooltip,
    encrypted_setup_legend,
    full_snapshot_saved_message,
    game_kind_from_profile_id,
    rollback_summary,
    set_baseline_tooltip,
    software_files_summary_line,
    uses_trial_keypad,
    write_scope_label,
)
from config_scanner.write_scope import WriteScope


def test_slot_snapshot_saved_message() -> None:
    text = full_snapshot_saved_message(
        "2026-08-30_GST20664_Slot_b98170458_075646",
        185,
        software_file_count=959,
        software_captured=True,
        profile_id="slot_lab_90",
    )
    assert "959 slot software files" in text
    assert "Ruleta" not in text


def test_roulette_snapshot_saved_message() -> None:
    text = full_snapshot_saved_message(
        "2026-08-21_GRT330106_v10.2_b40119",
        457,
        software_file_count=7,
        software_captured=True,
        profile_id="roulette_usb",
    )
    assert "7 Ruleta software files (exe + Godot)" in text


def test_write_scope_labels_differ_by_profile() -> None:
    assert "slot software" in write_scope_label(
        WriteScope.FULL_SOFTWARE, "slot"
    ).casefold()
    assert "ruleta software" in write_scope_label(
        WriteScope.FULL_SOFTWARE, "roulette"
    ).casefold()


def test_game_kind_from_profile_id() -> None:
    assert game_kind_from_profile_id("slot_lab_90") == "slot"
    assert game_kind_from_profile_id("roulette_usb") == "roulette"


def test_format_live_sw_banner_empty_until_version() -> None:
    from config_scanner.egm_ui_labels import format_live_sw_banner

    assert format_live_sw_banner(None, kind="roulette") == ""
    assert format_live_sw_banner("  ", kind="slot") == ""
    assert format_live_sw_banner("3.0.0+RC2", kind="slot") == (
        "Running: OneHand.exe 3.0.0+RC2"
    )
    assert format_live_sw_banner("10.2.0.876", kind="roulette") == (
        "Running: Ruleta.exe 10.2.0.876"
    )


def test_resolve_game_kind_uses_cabinet_path_over_roulette_profile(
    tmp_path,
) -> None:
    from config_scanner.egm_ui_labels import resolve_game_kind

    gold = tmp_path / "Goldclub"
    (gold / "slot").mkdir(parents=True)
    (gold / "slot" / "OneHand.exe").write_bytes(b"MZ")
    leftover = gold / "ruleta"
    leftover.mkdir()
    (leftover / "Ruleta.exe").write_bytes(b"MZ")
    assert (
        resolve_game_kind(profile_id="roulette_usb", scan_target=str(gold))
        == "slot"
    )


def test_rollback_summary_slot() -> None:
    line = rollback_summary("2.1.0-rc2", has_software=True, kind="slot")
    assert "Slot" in line
    assert "slot binaries" in line


def test_rollback_matches_hides_ruleta_on_slot() -> None:
    from config_scanner.egm_ui_labels import (
        game_kind_from_snapshot_name,
        rollback_matches_game_kind,
        resolve_rollback_game_kind,
    )

    name = "2026-08-25_GRT330106_Ruleta_Allegro_Wing_v10.2.0.876_b38884_123743"
    assert game_kind_from_snapshot_name(name) == "roulette"
    assert resolve_rollback_game_kind(None, restored_from=name) == "roulette"
    assert not rollback_matches_game_kind(
        "slot",
        restored_from=name,
        snapshot_name="2026-08-25_GRT330106_Ruleta_Allegro_Wing_v10.1.8.0_b38884_124021",
    )
    assert rollback_matches_game_kind(
        "roulette",
        restored_from=name,
        snapshot_name="2026-08-25_GRT330106_Ruleta_Allegro_Wing_v10.1.8.0_b38884_124021",
    )
    assert rollback_matches_game_kind(
        "slot",
        profile_id="slot_lab_90",
        restored_from="2026-08-30_GST20664_Slot_b98170458_075646",
    )


def test_trial_keypad_is_roulette_only() -> None:
    assert uses_trial_keypad("roulette") is True
    assert uses_trial_keypad("slot") is False


def test_slot_tooltips_never_mention_ruleta() -> None:
    slot_strings = (
        detect_target_tooltip("slot"),
        set_baseline_tooltip("slot"),
        encrypted_setup_legend("slot"),
    )
    for text in slot_strings:
        assert "ruleta" not in text.casefold()
    assert "OneHand.exe" in detect_target_tooltip("slot")
    assert "Ruleta.exe" in detect_target_tooltip("roulette")
    assert "ruleta" in encrypted_setup_legend("roulette").casefold()
