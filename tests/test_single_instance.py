"""Single-instance lock for Config Scanner."""

from __future__ import annotations

import os

from gui.single_instance import (
    ALREADY_RUNNING_TEXT,
    ALREADY_RUNNING_TITLE,
    ALLOW_MULTI_ENV,
    show_already_running_warning,
    try_acquire_config_scanner_lock,
)


def _test_key() -> str:
    return f"GoldClub.ConfigScanner.test.{os.getpid()}"


def test_allow_multi_env_bypasses_lock(monkeypatch) -> None:
    monkeypatch.setenv(ALLOW_MULTI_ENV, "1")
    assert try_acquire_config_scanner_lock(key=_test_key()) is not None


def test_second_acquire_fails_until_release() -> None:
    os.environ.pop(ALLOW_MULTI_ENV, None)
    key = _test_key()
    first = try_acquire_config_scanner_lock(key=key)
    assert first is not None
    second = try_acquire_config_scanner_lock(key=key)
    assert second is None
    if hasattr(first, "detach"):
        first.detach()
    third = try_acquire_config_scanner_lock(key=key)
    assert third is not None
    if hasattr(third, "detach"):
        third.detach()


def test_warning_uses_ok_dialog(monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    QApplication.instance() or QApplication([])
    calls: list[tuple[str, str]] = []

    def _warning(parent, title, text):  # noqa: ANN001
        calls.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warning)
    show_already_running_warning()
    assert calls == [(ALREADY_RUNNING_TITLE, ALREADY_RUNNING_TEXT)]
    assert "already open" in ALREADY_RUNNING_TEXT.casefold()
    assert ALREADY_RUNNING_TITLE


def test_run_config_scanner_app_refuses_second_instance(monkeypatch) -> None:
    from gui import config_scanner_window as mod

    monkeypatch.setattr(mod, "try_acquire_config_scanner_lock", lambda: None)
    shown: list[bool] = []
    monkeypatch.setattr(mod, "show_already_running_warning", lambda: shown.append(True))
    monkeypatch.setattr(
        mod,
        "ConfigScannerWindow",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("window opened")),
    )
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    rc = mod.run_config_scanner_app()
    assert rc == 1
    assert shown == [True]
