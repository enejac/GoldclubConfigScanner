"""Create client update wizard: no auto-modals and no share hangs when offline."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from config_scanner.cs_sources import CsSource, CsSourceKind, NOT_SHIPPED_NOTE  # noqa: E402
from gui import jurisdiction_wizard as wiz  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _embedded(eid: str, *, shipped: bool) -> CsSource:
    return CsSource(
        id=f"embedded-{eid}",
        label=eid.replace("CS-Gamestar-", "Puerto Rico "),
        country="PuertoRico",
        gamestar_line="2.0.1",
        kind=CsSourceKind.EMBEDDED,
        embedded_id=eid,
        authoring=shipped,
        note="" if shipped else NOT_SHIPPED_NOTE.format(id=eid),
    )


@pytest.fixture
def offline_wizard(monkeypatch: pytest.MonkeyPatch):
    _app()
    warnings: list[tuple[str, str]] = []
    loads: list[str] = []

    monkeypatch.setattr(
        wiz.QMessageBox,
        "warning",
        staticmethod(lambda _parent, title, text, *a, **k: warnings.append((title, text))),
    )
    monkeypatch.setattr(
        wiz.QMessageBox,
        "information",
        staticmethod(lambda _parent, title, text, *a, **k: warnings.append((title, text))),
    )
    monkeypatch.setattr(
        wiz,
        "share_offline_note",
        lambda: "Lab share \\\\10.0.0.249 not reachable (SMB 445) — built-in packs only.",
    )
    monkeypatch.setattr(wiz, "load_catalog", lambda: [])

    def fake_load(src: CsSource):
        loads.append(src.id)
        raise FileNotFoundError(
            f"embedded update {src.embedded_id} has no staged tree or .b2u "
            "(looked under C:/Temp/_MEI/embedded_updates; staged beside exe required)"
        )

    monkeypatch.setattr(wiz, "load_leaves_for_source", fake_load)
    return warnings, loads


def _make(monkeypatch: pytest.MonkeyPatch, sources: list[CsSource]) -> wiz.JurisdictionWizard:
    monkeypatch.setattr(wiz, "list_cs_sources", lambda **_kw: list(sources))
    return wiz.JurisdictionWizard()


def test_next_from_market_never_pops_modal_and_loads_once(
    offline_wizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings, loads = offline_wizard
    shipped = _embedded("CS-Gamestar-PR-03", shipped=True)
    not_shipped = _embedded("CS-Gamestar-PR-06", shipped=False)
    w = _make(monkeypatch, [shipped, not_shipped])

    w._go_next()

    assert w._stack.currentIndex() == 1
    assert warnings == [], "automatic pack selection must report inline, not modal"
    # recommended pack is the shipped one, PR-06 (newer) is skipped
    assert loads == ["embedded-CS-Gamestar-PR-03"], "leaf load ran more than once or picked PR-06"
    assert w._source is not None and w._source.id == "embedded-CS-Gamestar-PR-03"
    note = w._pack_note.text()
    assert "Could not open" in note and "no staged tree or .b2u" in note
    assert "Could not open" in w._status.text()
    assert w._share_lbl.isVisibleTo(w) and "10.0.0.249" in w._share_lbl.text()

    # PR-06 is listed but greyed out
    combo = w._pack_combo
    idx = next(i for i in range(combo.count()) if combo.itemData(i) == not_shipped.id)
    assert not combo.model().item(idx).isEnabled()
    assert "Recommended" not in combo.itemText(idx)


def test_only_not_shipped_packs_gives_inline_guidance(
    offline_wizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings, loads = offline_wizard
    w = _make(monkeypatch, [_embedded("CS-Gamestar-PR-06", shipped=False)])

    w._go_next()

    assert warnings == []
    assert loads == []
    note = w._pack_note.text()
    assert "CS-Gamestar-PR-06" in note
    assert "catalog entry only" in note
    assert "10.0.0.249" in note
    assert w._source is None


def test_user_opened_file_still_gets_a_dialog(
    offline_wizard, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    warnings, _loads = offline_wizard
    w = _make(monkeypatch, [_embedded("CS-Gamestar-PR-03", shipped=True)])
    warnings.clear()

    picked = tmp_path / "broken.b2u"
    picked.write_bytes(b"x")
    monkeypatch.setattr(
        wiz.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(picked), ""))
    )
    monkeypatch.setattr(
        wiz,
        "materialize_cs_path",
        lambda _p: (_ for _ in ()).throw(FileNotFoundError("Could not decrypt broken.b2u")),
    )

    w._browse_cs_file()

    assert len(warnings) == 1
    assert warnings[0][0] == "Pack"
    assert "Could not decrypt" in warnings[0][1]
    assert "Could not open" in w._pack_note.text()


def test_browse_share_offline_does_not_open_unc_dialog(
    offline_wizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings, _loads = offline_wizard
    w = _make(monkeypatch, [_embedded("CS-Gamestar-PR-03", shipped=True)])
    warnings.clear()
    monkeypatch.setattr(wiz, "remote_path_available", lambda _p, **_k: False)

    def no_dialog(*_a, **_k):
        raise AssertionError("file dialog must not open on a dead UNC share")

    monkeypatch.setattr(wiz.QFileDialog, "getExistingDirectory", staticmethod(no_dialog))

    w._browse_share()

    assert len(warnings) == 1 and warnings[0][0] == "Lab share"
    assert "not reachable" in warnings[0][1]


def test_matrix_skips_unreachable_live_unc(offline_wizard, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from config_scanner.cs_catalog import CountryLeaf

    _warnings, _loads = offline_wizard
    w = _make(monkeypatch, [_embedded("CS-Gamestar-PR-03", shipped=True)])
    leaf_dir = tmp_path / "data" / "PuertoRico" / "2 Screens" / "SAS 10c"
    leaf_dir.mkdir(parents=True)
    (leaf_dir / "install.json").write_text('{"Readme":"","Delete":[],"Copy":[],"Data":[]}')
    w._leaf = CountryLeaf(
        path=leaf_dir,
        rel_parts=("PuertoRico", "2 Screens", "SAS 10c"),
        country="PuertoRico",
        screens="2 Screens",
        mode="SAS 10c",
        readme="",
    )
    w._live_edit.setText(r"\\10.0.0.111\slot")
    monkeypatch.setattr(wiz, "remote_path_available", lambda _p, **_k: False)

    def no_io(_raw):
        raise AssertionError("goldclub_root_from_target must not run for a dead host")

    monkeypatch.setattr(wiz, "goldclub_root_from_target", no_io)

    w._fill_matrix()

    assert w._live_root is None
    assert "10.0.0.111" in w._issues_lbl.text() and "not reachable" in w._issues_lbl.text()
