"""Tests for decrypting official GameStar .b2u updates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config_scanner.b2u_pack import decrypt_b2u, extract_b2u_update, is_b2u_file
from config_scanner.pack_detect import PackKind, detect_update_path


def test_is_b2u_file(tmp_path: Path) -> None:
    b2u = tmp_path / "x.b2u"
    b2u.write_bytes(b"x")
    assert is_b2u_file(b2u) is True
    assert is_b2u_file(tmp_path / "folder") is False


def test_decrypt_b2u_mock(tmp_path: Path, monkeypatch) -> None:
    b2u = tmp_path / "CS-Gamestar-TT-00.b2u"
    b2u.write_bytes(b"encrypted")
    fake_gen = tmp_path / "BiOS2_PackageGenerator.exe"
    fake_gen.write_bytes(b"MZ")
    out_parent = tmp_path / "out"
    package = out_parent / "CS-Gamestar-TT-00"
    content = package / "Content" / "tmp" / "CountrySelectorTool" / "data" / "T" / "2" / "SAS"
    content.mkdir(parents=True)
    (content / "install.json").write_text(
        '{"Readme":"t","Delete":[],"Copy":[],"Data":[]}', encoding="utf-8"
    )

    def fake_run(cmd, capture_output=True, text=True, check=False, **kwargs):  # noqa: ANN001
        return MagicMock(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("config_scanner.b2u_pack.subprocess.run", fake_run)
    # Satisfy dependency guard when an explicit generator path is passed.
    (fake_gen.parent / "log4net.dll").write_bytes(b"x")
    (fake_gen.parent / "ICSharpCode.SharpZipLib.dll").write_bytes(b"x")
    result = decrypt_b2u(b2u, out_parent, generator=fake_gen)
    assert result == package
    assert (package / "Content").is_dir()


def test_detect_update_path_from_b2u(tmp_path: Path, monkeypatch) -> None:
    b2u = tmp_path / "CS-Gamestar-TT-00.b2u"
    b2u.write_bytes(b"x")
    tool = (
        tmp_path
        / "CS-Gamestar-TT-00"
        / "Content"
        / "tmp"
        / "CountrySelectorTool"
    )
    leaf = tool / "data" / "Trinidad" / "2 Screens" / "SAS"
    leaf.mkdir(parents=True)
    (leaf / "install.json").write_text(
        '{"Readme":"t","Delete":[],"Copy":[],"Data":[]}', encoding="utf-8"
    )

    monkeypatch.setattr(
        "config_scanner.b2u_pack.extract_b2u_update",
        lambda _path, **kwargs: tmp_path / "CS-Gamestar-TT-00",
    )
    detected = detect_update_path(b2u)
    assert detected.kind == PackKind.COUNTRY
    assert detected.root == tool


@pytest.mark.skipif(
    not Path(
        r"\\10.0.0.249\WinSystems_SLOT\GameStar 2.0.1\Country Selectors\Trinidad\CS-Gamestar-TT-00.b2u"
    ).is_file(),
    reason="lab share not reachable",
)
def test_decrypt_real_tt00_b2u() -> None:
    b2u = Path(
        r"\\10.0.0.249\WinSystems_SLOT\GameStar 2.0.1\Country Selectors\Trinidad\CS-Gamestar-TT-00.b2u"
    )
    from config_scanner.b2u_pack import default_package_generator

    if default_package_generator() is None:
        pytest.skip("BiOS2_PackageGenerator not installed")
    package = extract_b2u_update(b2u, reuse_cache=True)
    detected = detect_update_path(b2u)
    assert detected.kind == PackKind.COUNTRY
    assert (package / "Content" / "init.cmd").is_file()
