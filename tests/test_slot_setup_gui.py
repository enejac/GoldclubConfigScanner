"""Guards for Slot EGM setup / apply-pack / country-pack GUI wiring."""

from __future__ import annotations

from pathlib import Path

WINDOW_SRC = (
    Path(__file__).resolve().parents[1] / "gui" / "config_scanner_window.py"
).read_text(encoding="utf-8")
APP_SRC = (
    Path(__file__).resolve().parents[1] / "gui_app.py"
).read_text(encoding="utf-8")
PANEL_SRC = (
    Path(__file__).resolve().parents[1] / "gui" / "slot_setup_panel.py"
).read_text(encoding="utf-8")
COUNTRY_SRC = (
    Path(__file__).resolve().parents[1] / "gui" / "country_pack_panel.py"
).read_text(encoding="utf-8")
SHIP_SRC = (
    Path(__file__).resolve().parents[1] / "gui" / "ship_panel.py"
).read_text(encoding="utf-8")


def test_window_hosts_setup_and_apply_modes() -> None:
    home = (
        Path(__file__).resolve().parents[1] / "gui" / "simple_home.py"
    ).read_text(encoding="utf-8")
    assert "LivePushPanel" in home
    assert "Tune live cabinet" in home
    assert 'tabs.addTab(LivePushPanel' not in WINDOW_SRC
    assert "SlotApplyPanel" in WINDOW_SRC
    assert "apply_pack" in WINDOW_SRC
    assert "country_pack" in WINDOW_SRC
    assert "companion_pack" in WINDOW_SRC
    assert "SimpleShell" in WINDOW_SRC
    assert "CountryWizardPanel" in WINDOW_SRC
    assert "CompanionApplyPanel" in WINDOW_SRC
    assert "Snapshots" in WINDOW_SRC
    # Advanced view is Snapshots only; authoring tools are not tabs any more.
    assert "EGM setup" not in WINDOW_SRC
    assert "Companion packs" not in WINDOW_SRC
    assert 'addTab(ShipPanel' not in WINDOW_SRC
    assert "QTabWidget" not in WINDOW_SRC


def test_gui_app_exposes_apply_and_country_flags() -> None:
    assert "--apply-pack" in APP_SRC
    assert "--country-pack" in APP_SRC
    assert "--companion-pack" in APP_SRC
    assert "apply_pack=args.apply_pack" in APP_SRC
    assert "country_pack=args.country_pack" in APP_SRC
    assert "companion_pack=args.companion_pack" in APP_SRC


def test_setup_panel_exports_egm_update() -> None:
    assert "Export EGM update" in PANEL_SRC
    assert "pack_egm_update" in PANEL_SRC
    assert "build_config_pack" in PANEL_SRC
    assert "Apply to this machine" in PANEL_SRC
    assert "MEI" in PANEL_SRC and "JCM" in PANEL_SRC
    assert "Jurisdiction" in PANEL_SRC
    assert "Dallas" in PANEL_SRC
    assert "Offline ticket" in PANEL_SRC
    assert "MachineID" in PANEL_SRC


def test_country_panel_import_and_wizard() -> None:
    assert "Export country-wizard B2U" in COUNTRY_SRC
    assert "pack_country_update" in COUNTRY_SRC
    assert "Apply country overlay" in COUNTRY_SRC
    assert "!!MachineName!!" in COUNTRY_SRC


def test_ship_panel_exports_tool_b2u() -> None:
    assert "Export Tool B2U" in SHIP_SRC
    assert "pack_tool_update" in SHIP_SRC
    assert "ConfigScanner_Tool" in SHIP_SRC
