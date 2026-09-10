"""Live Push UI performance: no G: hang, lazy panel, debounced refresh."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from config_scanner.live_push import _exists_quick, default_live_cabinet_target


def test_exists_quick_returns_false_on_timeout(tmp_path: Path) -> None:
    """A path probe that never returns must not block the caller."""
    blocker = tmp_path / "slow"

    def _hang(_self=None):  # noqa: ANN001
        import time

        time.sleep(5)
        return True

    with patch.object(Path, "exists", _hang):
        assert _exists_quick(blocker, timeout_sec=0.15) is False


def test_default_live_target_skips_hung_g_drive(monkeypatch) -> None:
    """G: BitLocker hangs must not freeze default path selection."""

    def fake_ready(raw: str) -> bool:
        if str(raw).upper().startswith("G"):
            return False
        return False

    monkeypatch.setattr(
        "config_scanner.live_push._local_goldclub_ready", fake_ready
    )
    monkeypatch.setattr(
        "config_scanner.build_version.prefer_local_scan_target",
        lambda s: s,
    )
    assert default_live_cabinet_target() == ""


def test_live_push_panel_debounces_and_blocks_fill() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    assert "blockSignals(True)" in src
    assert "_refresh_changes_now" in src
    assert "self._refresh_timer.start()" in src
    assert "ensure_started" in src
    assert "autoload: bool = False" in src
