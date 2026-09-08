from __future__ import annotations

import logging
from pathlib import Path

import pytest

from datetime import date

from app_paths import app_writable_dir, dir_is_writable, is_network_path
from gui import app_logging as app_logging_mod
from logging.handlers import RotatingFileHandler


def test_dir_is_writable_true_on_temp(tmp_path: Path) -> None:
    assert dir_is_writable(tmp_path) is True
    leftovers = list(tmp_path.glob(".cs_write_probe_*.tmp"))
    assert leftovers == []


def test_dir_is_writable_false_when_write_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "locked"
    folder.mkdir()

    original = Path.write_bytes

    def boom(self: Path, data: bytes) -> None:
        if self.parent == folder and self.name.startswith(".cs_write_probe_"):
            raise PermissionError(13, "Access is denied")
        original(self, data)

    monkeypatch.setattr(Path, "write_bytes", boom)
    assert dir_is_writable(folder) is False


def test_is_network_path_unc() -> None:
    assert is_network_path(r"\\10.0.0.90\USB_Remote\ConfigScanner") is True
    assert is_network_path(r"C:\ConfigScanner") is False


def test_app_writable_dir_stays_on_writable_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "usb"
    install.mkdir()
    monkeypatch.setattr("app_paths.app_install_dir", lambda: install)
    monkeypatch.setattr("app_paths.is_network_path", lambda _path: False)
    assert app_writable_dir() == install


def test_app_writable_dir_falls_back_when_install_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "usb"
    install.mkdir()
    appdata = tmp_path / "appdata"
    monkeypatch.setattr("app_paths.app_install_dir", lambda: install)
    monkeypatch.setattr("app_paths.is_network_path", lambda _path: False)
    monkeypatch.setattr("app_paths.dir_is_writable", lambda _path: False)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    assert app_writable_dir() == appdata / "LogInvestigator"


def test_app_writable_dir_unc_uses_appdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = Path(r"\\10.0.0.90\USB_Remote\ConfigScanner")
    appdata = tmp_path / "appdata"
    monkeypatch.setattr("app_paths.app_install_dir", lambda: install)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    assert app_writable_dir() == appdata / "LogInvestigator"


def test_default_app_log_filename_is_cg_logs_plus_date() -> None:
    assert app_logging_mod.default_app_log_filename(when=date(2026, 9, 7)) == (
        "CG logs 2026-09-07.log"
    )
    name = app_logging_mod.default_app_log_filename()
    assert name.startswith("CG logs ")
    assert name.endswith(".log")


def test_log_file_path_defaults_to_dated_cg_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_logging_mod, "app_writable_dir", lambda **_kw: tmp_path)
    path = app_logging_mod.log_file_path()
    assert path.parent == tmp_path
    assert path.name == app_logging_mod.default_app_log_filename()
    assert "LogInvestigator" not in path.name
    assert "LoginInvestigator" not in path.name


def _reset_app_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except OSError:
            pass
    app_logging_mod._CONFIGURED = False
    app_logging_mod._LOG_PATH = None


def test_configure_app_logging_falls_back_on_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_app_logging()
    usb = tmp_path / "usb"
    usb.mkdir()
    appdata = tmp_path / "appdata"
    monkeypatch.setattr(app_logging_mod, "app_writable_dir", lambda **_kw: usb)
    monkeypatch.setattr(
        "gui.app_logging.app_local_data_dir",
        lambda **_kw: appdata / "LogInvestigator",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))

    real_rfh = RotatingFileHandler
    calls = {"n": 0}

    def flaky(*args: object, **kwargs: object) -> RotatingFileHandler:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "Access is denied")
        return real_rfh(*args, **kwargs)

    monkeypatch.setattr(app_logging_mod, "RotatingFileHandler", flaky)
    try:
        path = app_logging_mod.configure_app_logging(filename="ConfigScanner.log")
        assert path == appdata / "LogInvestigator" / "ConfigScanner.log"
        assert path.is_file()
    finally:
        _reset_app_logging()


def test_configure_app_logging_skips_file_when_nothing_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_app_logging()
    usb = tmp_path / "usb"
    usb.mkdir()
    appdata = tmp_path / "appdata" / "LogInvestigator"
    appdata.mkdir(parents=True)
    monkeypatch.setattr(app_logging_mod, "app_writable_dir", lambda **_kw: usb)
    monkeypatch.setattr("gui.app_logging.app_local_data_dir", lambda **_kw: appdata)

    def always_fail(*_args: object, **_kwargs: object) -> RotatingFileHandler:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(app_logging_mod, "RotatingFileHandler", always_fail)
    try:
        path = app_logging_mod.configure_app_logging(filename="ConfigScanner.log")
        assert path == usb / "ConfigScanner.log"
        assert app_logging_mod._CONFIGURED is True
    finally:
        _reset_app_logging()
