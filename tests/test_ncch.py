"""Reading 3DS encryption flags out of a header.

This one exists because of a real bug: the flags were read at 0x288 instead of
0x188, one full signature length too far into the header. The wrong bytes
happened to answer correctly for an encrypted ROM, so nothing looked broken,
but a properly decrypted ROM was also reported as encrypted and could not be
compressed at all. Both directions are asserted here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aynthor.core.ctr import ncch
from conftest import write_ncch, write_ncsd


def test_encrypted_ncch(tmp_path: Path):
    rom = write_ncch(tmp_path / "game.cxi", encrypted=True)
    assert ncch.is_encrypted(rom) is True


def test_decrypted_ncch_is_not_reported_as_encrypted(tmp_path: Path):
    rom = write_ncch(tmp_path / "game.cxi", encrypted=False)
    assert ncch.is_encrypted(rom) is False


def test_encrypted_ncsd_cart(tmp_path: Path):
    rom = write_ncsd(tmp_path / "game.cci", encrypted=True)
    assert ncch.is_encrypted(rom) is True


def test_decrypted_ncsd_cart(tmp_path: Path):
    rom = write_ncsd(tmp_path / "game.cci", encrypted=False)
    assert ncch.is_encrypted(rom) is False


def test_container_is_reported(tmp_path: Path):
    assert ncch.read_info(write_ncsd(tmp_path / "a.cci", encrypted=True)).container == "NCSD"
    assert ncch.read_info(write_ncch(tmp_path / "b.cxi", encrypted=True)).container == "NCCH"


def test_seed_crypto_flag(tmp_path: Path):
    rom = write_ncch(tmp_path / "game.cxi", encrypted=True, seed_crypto=True)
    assert ncch.read_info(rom).seed_crypto is True


def test_unknown_container_reports_none_rather_than_guessing(tmp_path: Path):
    """A CIA needs the ticket chain walked, so it must not be guessed at."""
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"\x20\x20\x00\x00" + b"\0" * 0x400)
    assert ncch.is_encrypted(rom) is None


def test_file_too_short_reports_none(tmp_path: Path):
    rom = tmp_path / "truncated.cci"
    rom.write_bytes(b"\0" * 16)
    assert ncch.is_encrypted(rom) is None


def test_missing_file_reports_none(tmp_path: Path):
    assert ncch.is_encrypted(tmp_path / "nothing.cci") is None


# ------------------------------------------------- keys are staged, not kept

def test_the_keys_copy_does_not_outlive_the_conversion(tmp_path):
    """The keys are the most sensitive file this app touches. A second copy
    used to be left in the app's data folder, where nothing removed it and the
    user had no reason to look."""
    from aynthor.core.nsz_runner import staged_keys

    keys = tmp_path / "prod.keys"
    keys.write_text("secret = 00112233\n", encoding="utf-8")
    workdir = tmp_path / "work"

    with staged_keys(keys, workdir):
        assert (workdir / "keys.txt").is_file(), "nsz needs it during the run"
    assert not (workdir / "keys.txt").exists()
    assert keys.is_file(), "the user's own file is theirs and stays"


def test_the_keys_copy_is_removed_even_when_the_run_fails(tmp_path):
    from aynthor.core.nsz_runner import staged_keys

    keys = tmp_path / "prod.keys"
    keys.write_text("secret\n", encoding="utf-8")
    workdir = tmp_path / "work"

    with pytest.raises(RuntimeError), staged_keys(keys, workdir):
        raise RuntimeError("the converter fell over")
    assert not (workdir / "keys.txt").exists()


def test_a_keys_file_the_user_pointed_at_directly_is_never_deleted(tmp_path):
    """Deleting it would destroy the user's own keys."""
    from aynthor.core.nsz_runner import staged_keys

    workdir = tmp_path / "work"
    workdir.mkdir()
    keys = workdir / "keys.txt"
    keys.write_text("secret\n", encoding="utf-8")

    with staged_keys(keys, workdir):
        pass
    assert keys.is_file()
