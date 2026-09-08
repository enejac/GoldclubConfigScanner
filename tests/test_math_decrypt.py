"""CRYPT_TOOLS layout and read-only math decrypt."""

from __future__ import annotations

from pathlib import Path

from config_scanner.math_decrypt import (
    CRYPT_TOOL_FILES,
    JSON_DECRYPTOR_NAME,
    crypt_tools_complete,
    decrypt_math_file,
    find_crypt_tools_dir,
    find_math_decryptor,
    stage_crypt_tools,
)


def _fake_crypt_tools(tmp_path: Path) -> Path:
    folder = tmp_path / "CRYPT_TOOLS"
    folder.mkdir()
    (folder / JSON_DECRYPTOR_NAME).write_bytes(b"MZ")
    (folder / "BiOSCrypt.exe").write_bytes(b"MZ")
    (folder / "BiOS Encryptor.exe").write_bytes(b"MZ")
    (folder / "JPCrypt.exe").write_bytes(b"MZ")
    (folder / "ReadMe.txt").write_text(
        "Encryptor.exe  => For encrypting/decrypting files (.JSON, ...)\n",
        encoding="utf-8",
    )
    (folder / "TutankhamenGSBHWMath.json").write_text("{}", encoding="utf-8")
    return folder


def test_readme_names_encryptor_for_json() -> None:
    from config_scanner.math_decrypt import find_crypt_tools_dir

    folder = find_crypt_tools_dir()
    if folder is None:
        return
    text = (folder / "ReadMe.txt").read_text(encoding="utf-8", errors="replace")
    assert "Encryptor.exe" in text
    assert ".JSON" in text.upper() or "json" in text.casefold()
    assert "BiOSCrypt.exe" in text
    assert "JPCrypt.exe" in text


def test_find_decryptor_uses_crypt_tools_env(
    tmp_path: Path, monkeypatch
) -> None:
    folder = _fake_crypt_tools(tmp_path)
    monkeypatch.setenv("GCS_CRYPT_TOOLS", str(folder))
    monkeypatch.delenv("GCS_MATH_DECRYPTOR", raising=False)
    found = find_crypt_tools_dir()
    assert found == folder
    assert crypt_tools_complete(found)
    assert find_math_decryptor() == folder / JSON_DECRYPTOR_NAME


def test_stage_beside_country_selector_skips_sample_math(
    tmp_path: Path, monkeypatch
) -> None:
    folder = _fake_crypt_tools(tmp_path)
    monkeypatch.setenv("GCS_CRYPT_TOOLS", str(folder))
    tool = tmp_path / "CountrySelectorTool"
    tool.mkdir()
    (tool / "CountrySelector.exe").write_bytes(b"MZ")
    staged = stage_crypt_tools(tool)
    assert staged is not None
    assert staged == tool / "CRYPT_TOOLS"
    assert (tool / "tools").exists() is False
    for name in CRYPT_TOOL_FILES:
        assert (staged / name).is_file()
    assert not (staged / "TutankhamenGSBHWMath.json").exists()
    assert list(staged.glob("*.json")) == []


def test_decrypt_uses_temp_copy_only(tmp_path: Path) -> None:
    wrapper = tmp_path / "cli_decrypt.py"
    wrapper.write_text(
        "import pathlib, sys\n"
        "src = pathlib.Path(sys.argv[1])\n"
        "dst = pathlib.Path(sys.argv[2])\n"
        "dst.write_text('[{\"Bet\": 30, \"Denom\": 5}]', encoding='utf-8')\n",
        encoding="utf-8",
    )
    encrypted = tmp_path / "Link2WinBonusMath.json"
    encrypted.write_bytes(b"\x00\x01not-json")
    before = encrypted.read_bytes()
    plain = decrypt_math_file(encrypted, decryptor=wrapper)
    assert encrypted.read_bytes() == before
    assert plain is not None
    assert b'"Bet"' in plain
    assert b"30" in plain


def test_decrypt_uses_found_encryptor_without_env_flag(
    tmp_path: Path, monkeypatch
) -> None:
    """Live Push must run the shipped Encryptor on a temp copy by default."""
    wrapper = tmp_path / "cli_decrypt.py"
    wrapper.write_text(
        "import pathlib, sys\n"
        "src = pathlib.Path(sys.argv[1])\n"
        "dst = pathlib.Path(sys.argv[2])\n"
        "dst.write_text('[{\"Bet\": 30, \"Denom\": 5}]', encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GCS_MATH_DECRYPT_CLI", raising=False)
    monkeypatch.delenv("GCS_MATH_DECRYPTOR", raising=False)
    monkeypatch.setattr(
        "config_scanner.math_decrypt.find_math_decryptor",
        lambda: wrapper,
    )
    encrypted = tmp_path / "Link2WinBonusMath.json"
    encrypted.write_bytes(b"\x00\x01not-json")
    from config_scanner.math_decrypt import clear_math_decrypt_cache

    clear_math_decrypt_cache()
    plain = decrypt_math_file(encrypted)
    assert plain is not None
    assert b'"Denom"' in plain
    assert encrypted.read_bytes() == b"\x00\x01not-json"


def test_decrypt_command_is_single_src_dest(tmp_path: Path) -> None:
    from config_scanner.math_decrypt import _decrypt_command

    exe = tmp_path / "Encryptor.exe"
    src = tmp_path / "in.json"
    dest = tmp_path / "out.json"
    assert _decrypt_command(exe, src, dest) == [str(exe), str(src), str(dest)]


def test_hidden_popen_hides_window(monkeypatch) -> None:
    import os
    import subprocess

    from config_scanner.math_decrypt import _hidden_popen_kwargs

    monkeypatch.setattr(
        "config_scanner.math_decrypt._windows_hidden_desktop",
        lambda: "gcs_math_decrypt",
    )
    kw = _hidden_popen_kwargs()
    if os.name != "nt":
        assert "startupinfo" not in kw
        return
    startup = kw["startupinfo"]
    assert startup.wShowWindow == 0
    assert startup.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startup.lpDesktop == "gcs_math_decrypt"
    assert kw["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_decrypt_spawn_false_does_not_launch_encryptor(
    tmp_path: Path, monkeypatch
) -> None:
    from config_scanner.math_decrypt import clear_math_decrypt_cache, decrypt_math_file

    launched: list[int] = []
    wrapper = tmp_path / "cli_decrypt.py"
    wrapper.write_text(
        "import pathlib, sys\n"
        "src = pathlib.Path(sys.argv[1])\n"
        "dst = pathlib.Path(sys.argv[2])\n"
        "dst.write_text('[{\"Bet\": 30, \"Denom\": 5}]', encoding='utf-8')\n",
        encoding="utf-8",
    )
    encrypted = tmp_path / "Link2WinBonusMath.json"
    encrypted.write_bytes(b"\x00\x01not-json")
    real_run = None
    import config_scanner.math_decrypt as md

    real_run = md._run_decryptor

    def wrapped(exe, src_copy, dest_plain):
        launched.append(1)
        return real_run(exe, src_copy, dest_plain)

    monkeypatch.setattr(md, "_run_decryptor", wrapped)
    clear_math_decrypt_cache()
    assert decrypt_math_file(encrypted, decryptor=wrapper, spawn=False) is None
    assert launched == []
    plain = decrypt_math_file(encrypted, decryptor=wrapper, spawn=True)
    assert launched == [1]
    assert plain is not None
    assert decrypt_math_file(encrypted, decryptor=wrapper, spawn=False) == plain
    assert launched == [1]


def test_run_decryptor_kills_stalled_child(tmp_path: Path, monkeypatch) -> None:
    import time

    from config_scanner.math_decrypt import _run_decryptor

    wrapper = tmp_path / "hang.py"
    wrapper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    src = tmp_path / "in.json"
    dest = tmp_path / "out.json"
    src.write_bytes(b"\x00x")
    monkeypatch.setenv("GCS_MATH_DECRYPT_TIMEOUT", "0.8")
    started = time.monotonic()
    assert _run_decryptor(wrapper, src, dest) is None
    assert time.monotonic() - started < 8
