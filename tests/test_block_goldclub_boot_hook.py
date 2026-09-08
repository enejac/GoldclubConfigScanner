"""Hook: refuse BCD/hive/boot-tamper commands."""

from __future__ import annotations

import importlib.util
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".cursor" / "hooks" / "block_goldclub_boot_tamper.py"


def _load():
    spec = importlib.util.spec_from_file_location("block_goldclub_boot_tamper", HOOK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_denies_bcdboot_and_offline_hive() -> None:
    m = _load()
    assert m.should_deny(r"bcdboot D:\Windows /s S: /f UEFI")
    assert m.should_deny(r'bcdedit /store S:\EFI\Microsoft\Boot\BCD /enum')
    assert m.should_deny(r'reg load HKLM\BIWINSYS D:\Windows\System32\config\SYSTEM')
    assert m.should_deny(r"powershell -File C:\logs\_fix-biwin-efi.ps1")
    assert m.should_deny(r"Set-ItemProperty CrashControl AutoReboot")


def test_allows_script_copy_and_eject() -> None:
    m = _load()
    assert m.should_deny("Copy-Item OO_Security.ps1 \\\\10.0.0.111\\c$\\Platform\\Security\\") is None
    assert m.should_deny(r"powershell -File C:\logs\_eject-biwin.ps1") is None
    assert m.should_deny("ping 10.0.0.111") is None
    assert m.should_deny("python -m pytest tests/test_onlogon_totalcmd.py") is None


def test_hook_main_utf16_stdin_denies_bcdboot(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    m = _load()

    class _Stdin:
        def __init__(self, data: bytes) -> None:
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(
        sys,
        "stdin",
        _Stdin(json.dumps({"command": r"bcdboot D:\Windows /s S: /f UEFI"}).encode("utf-16")),
    )
    m.main()
    out = json.loads(capsys.readouterr().out)
    assert out["permission"] == "deny"
