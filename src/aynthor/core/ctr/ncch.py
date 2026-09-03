"""Read the encryption state of a 3DS ROM straight from its header.

Why
    Compressing a still-encrypted ROM is pointless: encrypted data does not
    compress, and the result is a file the same size as the original that no
    longer opens in anything. rom-converto refuses such a ROM, but the
    z3ds_compressor fallback does not, so the app has to know for itself.
    Reading the header takes a single 512-byte read, which means the answer is
    available the moment a file enters the queue rather than several minutes
    into a run.

    Only NCSD (.cci / .3ds) and bare NCCH (.cxi) are inspected. A CIA needs the
    ticket and TMD chain walked to reach the same flags, so it reports
    "unknown" and the tools decide.

Used by
    `core.converters.z3ds` (refusing a compress, and flagging a restored ROM).

Reference
    NCCH header, flags byte 7 at offset 0x188:
    https://www.3dbrew.org/wiki/NCCH#NCCH_Header
    NCSD partition table at 0x120:
    https://www.3dbrew.org/wiki/NCSD
"""

from __future__ import annotations

import struct
from pathlib import Path

NCSD_MAGIC = b"NCSD"
NCCH_MAGIC = b"NCCH"

_MEDIA_UNIT = 0x200
_READ_LEN = 0x200
_PARTITION_TABLE = 0x120

# Offsets inside the 0x200-byte NCCH header, which begins with a 0x100-byte
# RSA signature: the magic sits at 0x100 and the flags at 0x188, both counted
# from the start of the header, not from the magic.
_MAGIC_OFFSET = 0x100
_FLAGS_OFFSET = 0x188

# NCCH flags[7]
_NO_CRYPTO = 0x04
_FIXED_KEY = 0x01
_SEED_CRYPTO = 0x20


class NcchInfo:
    """Encryption state of the first (main) NCCH partition."""

    __slots__ = ("container", "encrypted", "fixed_key", "seed_crypto")

    def __init__(
        self,
        encrypted: bool | None,
        seed_crypto: bool = False,
        fixed_key: bool = False,
        container: str = "",
    ) -> None:
        self.encrypted = encrypted
        self.seed_crypto = seed_crypto
        self.fixed_key = fixed_key
        self.container = container

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"NcchInfo(encrypted={self.encrypted}, seed_crypto={self.seed_crypto}, "
            f"fixed_key={self.fixed_key}, container={self.container!r})"
        )


UNKNOWN = NcchInfo(None)


def read_info(path: Path) -> NcchInfo:
    """Inspect a ROM. ``encrypted`` is None when the format is not understood."""
    try:
        with path.open("rb") as handle:
            head = handle.read(_READ_LEN)
            if len(head) < _READ_LEN:
                return UNKNOWN

            magic = head[_MAGIC_OFFSET:_MAGIC_OFFSET + 4]
            if magic == NCCH_MAGIC:
                return _from_ncch(head, "NCCH")
            if magic != NCSD_MAGIC:
                return UNKNOWN

            # NCSD: jump to the first partition and read its NCCH header.
            offset, length = struct.unpack_from("<II", head, _PARTITION_TABLE)
            if not offset or not length:
                return UNKNOWN
            handle.seek(offset * _MEDIA_UNIT)
            partition = handle.read(_READ_LEN)
            if len(partition) < _READ_LEN:
                return UNKNOWN
            if partition[_MAGIC_OFFSET:_MAGIC_OFFSET + 4] != NCCH_MAGIC:
                return UNKNOWN
            return _from_ncch(partition, "NCSD")
    except OSError:
        return UNKNOWN


def _from_ncch(header: bytes, container: str) -> NcchInfo:
    flags = header[_FLAGS_OFFSET:_FLAGS_OFFSET + 8]
    if len(flags) < 8:
        return UNKNOWN
    bits = flags[7]
    return NcchInfo(
        encrypted=not bool(bits & _NO_CRYPTO),
        seed_crypto=bool(bits & _SEED_CRYPTO),
        fixed_key=bool(bits & _FIXED_KEY),
        container=container,
    )


def is_encrypted(path: Path) -> bool | None:
    """True / False, or None when the container could not be read."""
    return read_info(path).encrypted
