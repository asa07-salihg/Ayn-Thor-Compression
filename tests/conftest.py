"""Shared fixtures.

The suite deliberately never imports anything from `aynthor.ui`: the point of
keeping `core` free of Qt is that its behaviour can be tested without a display
server, and a stray import here would quietly undo that.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

NCCH_HEADER_SIZE = 0x200
NCCH_MAGIC_OFFSET = 0x100
NCCH_FLAGS_OFFSET = 0x188
NCSD_PARTITION_TABLE = 0x120
MEDIA_UNIT = 0x200

NO_CRYPTO_BIT = 0x04


def ncch_header(*, encrypted: bool, seed_crypto: bool = False) -> bytes:
    """A 0x200-byte NCCH header with the crypto flags set as asked.

    Everything before 0x100 is the RSA signature, which nothing here reads.
    """
    header = bytearray(NCCH_HEADER_SIZE)
    header[NCCH_MAGIC_OFFSET:NCCH_MAGIC_OFFSET + 4] = b"NCCH"
    flags = 0
    if not encrypted:
        flags |= NO_CRYPTO_BIT
    if seed_crypto:
        flags |= 0x20
    header[NCCH_FLAGS_OFFSET + 7] = flags
    return bytes(header)


def write_ncch(path: Path, *, encrypted: bool, seed_crypto: bool = False) -> Path:
    path.write_bytes(ncch_header(encrypted=encrypted, seed_crypto=seed_crypto))
    return path


def write_ncsd(path: Path, *, encrypted: bool) -> Path:
    """An NCSD cart whose first partition is an NCCH with those crypto flags."""
    partition_offset_units = 4  # first partition starts at 0x800
    outer = bytearray(partition_offset_units * MEDIA_UNIT)
    outer[NCCH_MAGIC_OFFSET:NCCH_MAGIC_OFFSET + 4] = b"NCSD"
    struct.pack_into("<II", outer, NCSD_PARTITION_TABLE, partition_offset_units, 8)
    path.write_bytes(bytes(outer) + ncch_header(encrypted=encrypted))
    return path


@pytest.fixture()
def roms_root(tmp_path: Path) -> Path:
    """A small ES-DE style card: ROMs/<platform>/<game files>."""
    root = tmp_path / "SDCARD" / "ROMs"
    layout = {
        "psx": ["Chrono Cross (USA) (Disc 1).cue", "Chrono Cross (USA) (Disc 1).bin"],
        "ps2": ["Persona 4 (USA).iso"],
        "gc": ["Metroid Prime (USA).iso"],
        "snes": ["Super Mario World (USA).sfc"],
        "switch": [],
    }
    for platform, files in layout.items():
        folder = root / platform
        folder.mkdir(parents=True)
        for name in files:
            (folder / name).write_bytes(b"\0" * 1024)

    game_dir = root / "switch" / "Mario Kart 8 Deluxe"
    game_dir.mkdir(parents=True)
    for name in (
        "Mario Kart 8 Deluxe [0100152000022000][v0].nsp",
        "Mario Kart 8 Deluxe [0100152000022800][v65536].nsp",
        "Mario Kart 8 Deluxe DLC [0100152000022001][v0].nsp",
    ):
        (game_dir / name).write_bytes(b"\0" * 1024)
    return root
