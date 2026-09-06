"""Reading the crypto key out of ctrtool's output before decrypting.

This one exists because of a real bug: the regex for the crypto key required a
colon, and the ctrtool pinned in the manifest prints the line without one. The
key therefore always came back empty. That looked fine for an encrypted cart,
which went on to decrypt.exe as it should, but an already-decrypted cart was
repacked by makerom instead of refused, and every CIA was rejected as
"Unsupported" because the word Secure was never found in an empty string. The
tests run the two entry points against captured ctrtool output; neither
decrypt.exe nor makerom is allowed to run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aynthor.core.ctr import decrypt

# Verbatim from ctrtool as shipped with Batch CIA 3DS Decryptor Redux 1.0.6.3,
# cut down to the lines the parser looks at.
_CART = """\
NcsdCommonHeader:
 Header:                 NCSD
 TitleId:                0004000000033500
 TitleVersion:           0.0.0 (v0)
NCCH:
Header:                 NCCH
Title id:               0004000000033500
Product code:           CTR-P-AQEE
 > Crypto Key           {key}
 > ContentPlatorm:      CTR
 > ContentType:         Application
"""

_CIA = """\
CIA:
Header:                 CIA
TitleVersion:           1040
NCCH:
Header:                 NCCH
Title id:               0004000000033500
 > Crypto Key           {key}
 > ContentType:         Application
"""


@pytest.fixture
def ctrtool_says(monkeypatch, tmp_path: Path):
    """Answer ctrtool with the given text; every other tool runs silently and writes nothing.

    Returns the list of tool names that ran, in order. A run that reaches
    decrypt.exe has passed the crypto check; one that stops at ctrtool has not.
    """
    ran: list[str] = []

    def install(text: str) -> list[str]:
        def fake_run_tool(executable, args, **_kwargs):
            name = Path(executable).name
            ran.append(name)
            out = text if name == "ctrtool.exe" else ""
            return subprocess.CompletedProcess([str(executable), *args], 0, stdout=out, stderr="")

        monkeypatch.setattr(decrypt, "run_tool", fake_run_tool)
        monkeypatch.setattr(decrypt, "_stage_tools", lambda _dest: None)
        monkeypatch.setattr(decrypt, "workdir", lambda: tmp_path)
        return ran

    return install


def test_an_already_decrypted_cart_is_refused(ctrtool_says, tmp_path: Path):
    ran = ctrtool_says(_CART.format(key="None"))
    with pytest.raises(decrypt.DecryptError, match="Already decrypted"):
        decrypt.decrypt_cart(tmp_path / "game.cci", tmp_path / "out.cci", lambda _l: None)
    assert ran == ["ctrtool.exe"]


def test_an_encrypted_cart_goes_on_to_decrypt(ctrtool_says, tmp_path: Path):
    ran = ctrtool_says(_CART.format(key="Secure0 (0)"))
    # The fake decrypt.exe writes no partitions, which is where a run with a
    # correctly read key stops. Refusing before that is the bug.
    with pytest.raises(decrypt.DecryptError, match="produced no output"):
        decrypt.decrypt_cart(tmp_path / "game.cci", tmp_path / "out.cci", lambda _l: None)
    assert ran == ["ctrtool.exe", "decrypt.exe"]


def test_an_encrypted_cia_is_not_rejected_as_unsupported(ctrtool_says, tmp_path: Path):
    ran = ctrtool_says(_CIA.format(key="Secure0 (0)"))
    with pytest.raises(decrypt.DecryptError, match="produced no output"):
        decrypt.decrypt_cia(tmp_path / "game.cia", tmp_path / "out.cia", lambda _l: None)
    assert "decrypt.exe" in ran


def test_an_already_decrypted_cia_is_refused(ctrtool_says, tmp_path: Path):
    ran = ctrtool_says(_CIA.format(key="None"))
    with pytest.raises(decrypt.DecryptError, match="Already decrypted"):
        decrypt.decrypt_cia(tmp_path / "game.cia", tmp_path / "out.cia", lambda _l: None)
    assert ran == ["ctrtool.exe"]


def test_the_older_ctrtool_with_a_colon_is_still_read(ctrtool_says, tmp_path: Path):
    ctrtool_says("Title id:  0004000000033500\nCrypto Key: Secure0 (0)\nTitleVersion: 1040\n")
    assert decrypt.analyze(tmp_path / "game.cci", tmp_path) == (
        "0004000000033500", 1040, "Secure0 (0)")
