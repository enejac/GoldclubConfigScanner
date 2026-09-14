"""Profile-aware UI strings for slot and roulette EGMs."""

from __future__ import annotations

from typing import Literal

from config_scanner.write_scope import WriteScope

GameKind = Literal["slot", "roulette"]


def game_kind_from_profile_id(profile_id: str | None) -> GameKind:
    if (profile_id or "").strip().casefold().startswith("slot"):
        return "slot"
    return "roulette"


def game_kind_from_snapshot_name(name: str | None) -> GameKind | None:
    """Infer slot vs roulette from snapshot folder naming conventions."""
    text = (name or "").casefold()
    if not text:
        return None
    if "ruleta" in text or "roulette" in text or "_grt" in text:
        return "roulette"
    if (
        "slot" in text
        or "_gst" in text
        or "onehand" in text
        or "gamestar" in text
    ):
        return "slot"
    return None


def resolve_rollback_game_kind(
    profile_id: str | None = None,
    *,
    restored_from: str | None = None,
    snapshot_name: str | None = None,
) -> GameKind:
    """Which EGM family an undo point belongs to."""
    if profile_id:
        return game_kind_from_profile_id(profile_id)
    for name in (restored_from, snapshot_name):
        inferred = game_kind_from_snapshot_name(name)
        if inferred:
            return inferred
    return "roulette"


def rollback_matches_game_kind(
    current: GameKind,
    *,
    profile_id: str | None = None,
    restored_from: str | None = None,
    snapshot_name: str | None = None,
) -> bool:
    """False when a Ruleta undo would clutter a Slot UI (and vice versa)."""
    return (
        resolve_rollback_game_kind(
            profile_id,
            restored_from=restored_from,
            snapshot_name=snapshot_name,
        )
        == current
    )


def game_kind_from_target(scan_target: str) -> GameKind | None:
    """Best-effort detect from live tree (OneHand vs Ruleta.exe)."""
    try:
        from config_scanner.build_version import (
            has_roulette_game_exe,
            has_slot_game_exe,
            scan_target_path,
        )

        root = scan_target_path(scan_target)
    except (OSError, ValueError):
        return None
    slot = has_slot_game_exe(root)
    roulette = has_roulette_game_exe(root)
    # Leftover Ruleta.exe on a Slot Goldclub tree must not hide OneHand.
    if slot:
        return "slot"
    if roulette:
        return "roulette"
    return None


def resolve_game_kind(
    *,
    profile_id: str | None = None,
    scan_target: str | None = None,
) -> GameKind:
    if profile_id and game_kind_from_profile_id(profile_id) == "slot":
        return "slot"
    if scan_target:
        from_target = game_kind_from_target(scan_target)
        if from_target:
            return from_target
    return game_kind_from_profile_id(profile_id)


def game_software_noun(kind: GameKind) -> str:
    return "slot software" if kind == "slot" else "Ruleta software"


def game_software_short(kind: GameKind) -> str:
    return "slot software" if kind == "slot" else "game software"


def game_exe_name(kind: GameKind) -> str:
    return "OneHand.exe" if kind == "slot" else "Ruleta.exe"


def game_exe_relpath(kind: GameKind) -> str:
    return "slot\\OneHand.exe" if kind == "slot" else "ruleta\\Ruleta.exe"


def uses_trial_keypad(kind: GameKind) -> bool:
    """ERROR 30 / 99 + LLAVE keypad only exist on the Ruleta exe."""
    return kind == "roulette"


def detect_target_tooltip(kind: GameKind) -> str:
    exe = game_exe_name(kind)
    return (
        "Find local image or remote .90 Goldclub when the game exe exists "
        f"({exe})."
    )


def set_baseline_tooltip(kind: GameKind) -> str:
    name = "slot_baseline" if kind == "slot" else "roulette_baseline_build…"
    return (
        f"Rename the selected snapshot to {name} and register it as the "
        "compare baseline."
    )


def encrypted_setup_noun(kind: GameKind) -> str:
    return "encrypted setup" if kind == "slot" else "ruleta setup"


def encrypted_setup_legend(kind: GameKind) -> str:
    return f"Amber = {encrypted_setup_noun(kind)}.xml"


def software_files_summary_line(
    count: int,
    *,
    kind: GameKind,
    captured: bool = True,
) -> str:
    n = max(int(count), 0)
    if not captured:
        return software_not_included_line(kind)
    if kind == "slot":
        return f"• {n} slot software files (OneHand, themes, bios…)"
    return f"• {n} Ruleta software files (exe + Godot)"


def software_not_included_line(kind: GameKind) -> str:
    if kind == "slot":
        return "• Slot software was not included"
    return "• Ruleta software was not included"


def software_restore_fallback_hint(kind: GameKind) -> str:
    if kind == "slot":
        return "  Restore will use archived software/ from the snapshot if needed."
    return "  Restore will look for a matching pack if you need the exe later."


def scan_saved_software_status(count: int, *, kind: GameKind) -> str:
    noun = game_software_noun(kind)
    return f"OK: Saved {count} {noun} files with this snapshot."


def format_live_sw_banner(version: str | None, *, kind: GameKind) -> str:
    """Toolbar line for the live exe. Empty until a real ProductVersion is known.

    Never return ``Running: Ruleta.exe unknown`` (or OneHand unknown) — that
    is a default-roulette placeholder, not a cabinet read.
    """
    ver = (version or "").strip()
    if not ver:
        return ""
    return f"Running: {game_exe_name(kind)} {ver}"


def live_exe_version_tooltip(target: str, *, kind: GameKind) -> str:
    rel = game_exe_relpath(kind)
    return (
        f"ProductVersion of live {rel} on this scan target.\n"
        f"Target: {target or '(none)'}"
    )


def live_exe_version_for_target(
    scan_target: str,
    *,
    kind: GameKind | None = None,
    profile_id: str | None = None,
) -> str | None:
    resolved = kind or resolve_game_kind(profile_id=profile_id, scan_target=scan_target)
    if resolved == "slot":
        from config_scanner.build_version import detect_slot_version, scan_target_path

        try:
            root = scan_target_path(scan_target)
            info = detect_slot_version(root)
        except OSError:
            return None
        return (
            info.product_version or info.display_version or info.file_version or ""
        ).strip() or None
    from config_scanner.software_compat import live_ruleta_exe_version_for_target

    return live_ruleta_exe_version_for_target(scan_target)


def create_full_snapshot_tooltip(kind: GameKind) -> str:
    sw = game_software_short(kind)
    return (
        f"Save live config and {sw} into one snapshot. "
        "Does not write anything back. Restore that snapshot later to "
        "return this machine to this version."
    )


def restore_snapshot_tooltip(kind: GameKind) -> str:
    sw = game_software_short(kind)
    return (
        f"Put the selected snapshot back on the machine (config + {sw}). "
        "Tick Create a backup, next to Auto-start stack, if you want an undo "
        "snapshot."
    )


def restore_config_only_tooltip(kind: GameKind) -> str:
    exe = game_exe_name(kind)
    return f"Write config files only. Live {exe} stays as-is."


def restore_binaries_only_tooltip(kind: GameKind) -> str:
    if kind == "slot":
        return (
            "Push slot binaries only. Keep this cabinet's setup, "
            "switches, SAS, serialport, and licence in place."
        )
    return (
        "Push matching Ruleta binaries only. Keep this cabinet's setup, "
        "switches, wheel, SAS, serialport, and licence. Refuses the "
        "10.2.0.684 trial and Downloads 10.2.0.0."
    )


def restore_full_software_tooltip(kind: GameKind) -> str:
    if kind == "slot":
        return (
            "Restore config, then push the matching slot software from the "
            "snapshot (or software_versions) so themes and the exe stay aligned."
        )
    return (
        "Push the matching Ruleta pack from software_versions first, then "
        "restore config (including paytables) onto that exe. Stops if "
        "the pack is missing or the copy fails."
    )


def restore_no_paytable_tooltip(kind: GameKind) -> str:
    exe = game_exe_name(kind)
    return (
        "Save live config first, then restore all restorable files except "
        f"paytable JSON. Use when live {exe} cannot load the snapshot paytables."
    )


def undo_missing_binaries_warning(kind: GameKind) -> str:
    noun = "slot binaries" if kind == "slot" else "Ruleta binaries"
    return (
        f"\n  Warning: this undo point has no {noun}, so the "
        "exe stays on the version running now. Restore a full snapshot "
        "of the version you want if the game must go back too."
    )


def undo_backup_step_line(kind: GameKind) -> str:
    noun = "slot binaries" if kind == "slot" else "Ruleta binaries"
    return f"1. Save a backup of what is running now (config + {noun})."


def rollback_summary(version: str, *, has_software: bool, kind: GameKind) -> str:
    if kind == "slot":
        software = "config + slot binaries" if has_software else "config only"
        label = "Slot"
    else:
        software = "config + Ruleta binaries" if has_software else "config only"
        label = "Ruleta"
    ver = (version or "").strip() or "?"
    return f"{label} {ver}, {software}"


def write_scope_label(scope: WriteScope, kind: GameKind) -> str:
    if kind == "slot":
        labels = {
            WriteScope.FULL: "Full config",
            WriteScope.HARDWARE: "Hardware only",
            WriteScope.SOFTWARE: "Software only",
            WriteScope.NO_PAYTABLE: "Config except paytables",
            WriteScope.FULL_SOFTWARE: "Config + slot software",
            WriteScope.BINARIES_ONLY: "Slot software only (keep cabinet profile)",
        }
    else:
        labels = {
            WriteScope.FULL: "Full config",
            WriteScope.HARDWARE: "Hardware only",
            WriteScope.SOFTWARE: "Software only",
            WriteScope.NO_PAYTABLE: "Config except paytables",
            WriteScope.FULL_SOFTWARE: "Config + Ruleta software",
            WriteScope.BINARIES_ONLY: "Ruleta software only (keep cabinet profile)",
        }
    return labels[scope]


def write_scope_description(scope: WriteScope, kind: GameKind) -> str:
    if scope is WriteScope.FULL:
        return "All config except serialport/ and EGM identity"
    if scope is WriteScope.HARDWARE:
        return "Bill / ticket / switches / LEDs / counters / SAS / CommCtrl"
    if scope is WriteScope.SOFTWARE:
        if kind == "slot":
            return "Slot / themes / mgconfig / app behaviour"
        return "Ruleta / mgconfig / themes / app behaviour"
    if scope is WriteScope.NO_PAYTABLE:
        exe = game_exe_name(kind)
        return (
            "All restorable config except paytable JSON — use when live "
            f"{exe} cannot load the snapshot paytables"
        )
    if scope is WriteScope.FULL_SOFTWARE:
        return restore_full_software_tooltip(kind)
    if scope is WriteScope.BINARIES_ONLY:
        return restore_binaries_only_tooltip(kind)
    return ""


def write_scope_short(scope: WriteScope, kind: GameKind) -> str:
    if kind == "slot":
        shorts = {
            WriteScope.FULL: "full config",
            WriteScope.HARDWARE: "hardware",
            WriteScope.SOFTWARE: "software",
            WriteScope.NO_PAYTABLE: "config except paytables",
            WriteScope.FULL_SOFTWARE: "config + slot software",
            WriteScope.BINARIES_ONLY: "slot binaries (keep profile)",
        }
    else:
        shorts = {
            WriteScope.FULL: "full config",
            WriteScope.HARDWARE: "hardware",
            WriteScope.SOFTWARE: "software",
            WriteScope.NO_PAYTABLE: "config except paytables",
            WriteScope.FULL_SOFTWARE: "config + Ruleta software",
            WriteScope.BINARIES_ONLY: "Ruleta binaries (keep profile)",
        }
    return shorts[scope]


def write_scope_combo_tooltip(kind: GameKind) -> str:
    sw = game_software_short(kind)
    return (
        "Bulk restore scope: Full, Config except paytables, Config + "
        f"{sw}, game software only (keep cabinet profile), Hardware, "
        "Software."
    )


def welcome_panel_create_step(kind: GameKind) -> str:
    sw = game_software_short(kind)
    return f"<i>and</i> {sw}"


def restore_full_context_menu_tip(kind: GameKind) -> str:
    if kind == "slot":
        return (
            "Restore config + matching slot software from this snapshot. "
            "Tick Create a backup, next to Auto-start stack, if you want an "
            "undo snapshot."
        )
    return (
        "Restore config + matching Ruleta software. WIBU licence is kept; "
        "LLAVE trial bind is restored from this snapshot when it was captured. "
        "Tick Create a backup, next to Auto-start stack, if you want an undo "
        "snapshot."
    )


def restore_binaries_step_line(kind: GameKind) -> str:
    if kind == "slot":
        return (
            "Push slot binaries from this snapshot and keep this "
            "cabinet's setup / SAS / licence."
        )
    return (
        "Push Ruleta binaries from this snapshot and keep this "
        "cabinet's setup / SAS / licence."
    )


def incomplete_undo_point_title(kind: GameKind) -> str:
    return "Config Scanner — undo point is incomplete"


def incomplete_undo_point_body(snapshot_name: str, *, kind: GameKind) -> str:
    noun = game_software_noun(kind)
    return (
        f"Live config was saved, but the {noun} running now could "
        "not be copied into the undo point:\n\n"
        f"  {snapshot_name}\n\n"
        "If you continue, Revert last restore puts the config back but "
        "leaves the exe on the version you are about to install.\n\n"
        "The GoldClub stack is already stopped. Choose No to stop here and "
        "start it again with Start GoldClub stack.\n\n"
        f"Install the new {game_software_short(kind)} anyway?"
    )


def incomplete_undo_cancel_status(kind: GameKind) -> str:
    noun = "slot binaries" if kind == "slot" else "Ruleta binaries"
    return f"Restore cancelled — undo point has no {noun}."


def files_locked_during_restore_message(kind: GameKind) -> str:
    noun = "slot" if kind == "slot" else "Ruleta"
    return (
        f"Kill-All ran but {noun} files are still locked, so "
        "software was not fully replaced."
    )


def game_may_already_be_up_hint(kind: GameKind) -> str:
    label = "Slot" if kind == "slot" else "Ruleta"
    return f"\n\n{label} may already be up — check the cabinet screen. "


def full_snapshot_saved_message(
    snapshot_name: str,
    file_count: int,
    *,
    software_file_count: int = 0,
    software_captured: bool = False,
    extra_notes: tuple[str, ...] | list[str] = (),
    profile_id: str | None = None,
) -> str:
    """One success dialog after Create full snapshot (no compare, no write-back)."""
    from config_scanner.software_compat import scan_user_warnings

    kind = game_kind_from_profile_id(profile_id)
    name = (snapshot_name or "").strip() or "(unnamed)"
    count = max(int(file_count), 0)
    files = "file" if count == 1 else "files"
    lines = [
        "This machine is saved.",
        "",
        name,
        "",
        f"• {count} config {files}",
    ]
    if software_captured:
        lines.append(
            software_files_summary_line(
                software_file_count, kind=kind, captured=True
            )
        )
    else:
        lines.append(software_not_included_line(kind))
        lines.append(software_restore_fallback_hint(kind))
    lines.extend(
        [
            "",
            "The machine was not changed.",
            "",
            "This snapshot is selected. Click Restore snapshot when you "
            "want this version back.",
        ]
    )
    notes = scan_user_warnings(tuple(extra_notes))
    if notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"• {note}" for note in notes)
    return "\n".join(lines)
