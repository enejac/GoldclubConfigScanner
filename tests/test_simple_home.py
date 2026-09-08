"""Tests for simple Create/Restore pack detection."""

from __future__ import annotations

from pathlib import Path

from config_scanner.pack_detect import PackKind, detect_pack


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_detect_country_tool(tmp_path: Path) -> None:
    tool = tmp_path / "CountrySelectorTool"
    leaf = tool / "data" / "PR" / "2 Screens" / "SAS"
    leaf.mkdir(parents=True)
    _write(leaf / "install.json", '{"Readme":"x","Delete":[],"Copy":[],"Data":[]}')
    d = detect_pack(tool)
    assert d.kind == PackKind.COUNTRY


def test_detect_egm_and_companion(tmp_path: Path) -> None:
    egm = tmp_path / "config-pack"
    _write(egm / "recipe.json", '{"version":1,"label":"t"}')
    assert detect_pack(egm).kind == PackKind.EGM_RECIPE

    comp = tmp_path / "companion-pack"
    _write(comp / "companion.json", '{"kind":"bills","label":"x"}')
    assert detect_pack(comp).kind == PackKind.COMPANION


def test_detect_nested_b2u_content(tmp_path: Path) -> None:
    root = tmp_path / "ConfigScanner_Country_X"
    tool = root / "Content" / "tmp" / "CountrySelectorTool"
    leaf = tool / "data" / "T" / "2" / "SAS"
    leaf.mkdir(parents=True)
    _write(leaf / "install.json", '{"Readme":"t","Delete":[],"Copy":[],"Data":[]}')
    d = detect_pack(root)
    assert d.kind == PackKind.COUNTRY
    assert d.root == tool


def test_simple_home_wiring() -> None:
    window = (
        Path(__file__).resolve().parents[1] / "gui" / "config_scanner_window.py"
    ).read_text(encoding="utf-8")
    home = (
        Path(__file__).resolve().parents[1] / "gui" / "simple_home.py"
    ).read_text(encoding="utf-8")
    app = (Path(__file__).resolve().parents[1] / "gui_app.py").read_text(encoding="utf-8")
    b2u = (
        Path(__file__).resolve().parents[1] / "config_scanner" / "b2u_pack.py"
    ).read_text(encoding="utf-8")
    assert "program_title" in window
    assert "program_title" in home
    assert "SimpleShell" in window
    assert "Create client update" in home
    assert "full CS" in home.casefold() or "Country Selector" in home
    assert "CreateCountryPanel" not in home
    assert "manual_create" not in home
    assert "JurisdictionWizard" in home
    assert "Apply update on cabinet" in home
    assert "Tune live cabinet" in home
    assert "Advanced tools" in home
    assert "LivePushPanel" in home
    assert "_show_push" in home
    assert "autoload=False" in home
    assert "ensure_started" in home
    # Must not construct Live Push at SimpleShell __init__ (freezes home).
    shell_init = home.split("class SimpleShell")[1].split("def _show_push")[0]
    assert "LivePushPanel(" not in shell_init
    assert "OfficialUpdateCombo" in home
    assert "try_acquire_config_scanner_lock" in window
    assert "show_already_running_warning" in window
    assert "Screenshot" in window
    assert "save_widget_screenshot" in window
    assert "Apply & restart game" in (
        Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    live_push = (
        Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    assert "Export full CS" in live_push
    assert "Check SlotLog" in live_push
    assert "review_slot_logs" in live_push
    wiz = (
        Path(__file__).resolve().parents[1] / "gui" / "jurisdiction_wizard.py"
    ).read_text(encoding="utf-8")
    assert "Export full Country Selector from live" in wiz
    assert "export_full_country_selector" in wiz
    assert "decrypt" in home.casefold() or ".b2u" in home
    assert "CRYPT_TOOLS" in home or "Encryptor.exe" in home
    assert "mathPreflight" in home
    assert "_start_math_preflight" in home
    assert "JinLong" in home
    assert "_B2U" in home
    assert "Live push" not in window or 'tabs.addTab(LivePushPanel' not in window
    assert "Country packs" not in window or 'tabs.addTab(CountryPackAuthorPanel' not in window
    assert "Snapshots, EGM pack authoring" in window
    assert "--snapshots" in app
    assert "--restore-b2u" in app
    assert "snapshots_mode" in window or "_snapshots_mode" in window
    assert "ConfigScannerTabWidget" in window
    assert "--snapshots" in b2u
    assert "launched_from_tool_b2u" in b2u


def test_jurisdiction_wizard_module_imports() -> None:
    from gui.jurisdiction_wizard import JurisdictionWizard

    assert JurisdictionWizard is not None
    wiz = (
        Path(__file__).resolve().parents[1] / "gui" / "jurisdiction_wizard.py"
    ).read_text(encoding="utf-8")
    assert "Step 1 of 4 — Market" in wiz
    assert "Create client update" in wiz
    assert "Copy official .b2u" in wiz
    assert "_copy_official_b2u" in wiz
    assert "Problems only" in wiz
    assert "probe_against_profile" in wiz
    assert "Recommended denoms" in wiz
    assert "_selected_denoms" in wiz
    assert "ensure_expected_locale_keys" in wiz
    assert "_set_status" in wiz
    assert "include_share_scan" in wiz
    assert "Show Debug / Test packs" in wiz
    assert "recommend_cs_source" in wiz


def test_jurisdiction_wizard_constructs() -> None:
    from PySide6.QtWidgets import QApplication, QGroupBox

    from gui.jurisdiction_wizard import JurisdictionWizard
    from gui.live_push_panel import LivePushPanel

    QApplication.instance() or QApplication([])
    wizard = JurisdictionWizard()
    assert wizard._status is not None
    assert wizard._stack.count() == 4
    panel = LivePushPanel(autoload=False)
    from config_scanner.live_push import default_live_cabinet_target
    from gui.live_push_panel import _combo_code

    assert panel._path.text() == default_live_cabinet_target()
    assert panel._commit.text() == "Apply & restart game"
    assert panel._commit.isEnabled()
    assert panel._currency.isEditable()
    assert panel._currency.count() >= 8
    titles = {box.title() for box in panel.findChildren(QGroupBox)}
    assert "Magic wheel" in titles
    assert "Jackpots" in titles
    assert "Denoms / bets" in titles
    assert "Ticketing" in titles
    assert panel._mw_limit.count() >= 6
    assert panel._jp_counters.count() >= 4
    ttd = panel._currency.findData("TTD")
    assert ttd >= 0
    panel._currency.setCurrentIndex(ttd)
    assert _combo_code(panel._currency) == "TTD"
    panel._dallas.setCurrentIndex(0)
    assert _combo_code(panel._dallas) == ""
