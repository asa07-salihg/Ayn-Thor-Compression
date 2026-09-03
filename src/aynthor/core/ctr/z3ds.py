"""Read a Z3DS container back into the ROM it was made from.

Why
    z3ds_compressor only compresses; nothing in the reference toolchain goes
    the other way. rom-converto does, but it is an optional download, and a
    user should never be unable to open a file this app created. So the
    container is decoded here in pure Python, using only `zstandard`, which is
    already a dependency.

    The format is a plain header followed by a zstd *seekable* stream: ordinary
    zstd frames, then a skippable frame holding the seek table. Decoding the
    frames back to back reproduces the original file byte for byte, so the seek
    table can be ignored for a full extraction.

Container layout (Azahar's format, version 1):

    offset  size  field
    0x00     4    magic "Z3DS"
    0x04     4    magic of the original ROM (NCSD / NCCH / 3DSX)
    0x08     1    version (1)
    0x09     1    reserved
    0x0A     2    header size (0x20), little-endian
    0x0C     4    metadata size, padded to 16 bytes, little-endian
    0x10     8    compressed payload size, little-endian
    0x18     8    uncompressed (original) size, little-endian
    0x20     ..   metadata block
    ..       ..   zstd seekable stream

Used by
    `core.converters.z3ds.Z3dsConverter` (fallback path and header reads),
    `core.formats._decompressed_path` (naming the restored file).

Reference
    zstd seekable format specification:
    https://github.com/facebook/zstd/blob/dev/contrib/seekable_format/zstd_seekable_compression_format.md
    Azahar's compressor: https://github.com/energeticokay/z3ds_compress
"""

from __future__ import annotations

import contextlib
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"Z3DS"
HEADER_SIZE = 0x20
SUPPORTED_VERSIONS = (1,)

_ZSTD_FRAME_MAGIC = 0xFD2FB528
_SKIPPABLE_MAGIC = 0x184D2A50
_SKIPPABLE_MASK = 0xFFFFFFF0
_SEEKABLE_MAGIC = 0x8F92EAB1
_SEEK_FOOTER_SIZE = 9
_READ_CHUNK = 4 * 1024 * 1024

# Container extension -> extension of the ROM inside it.
CONTAINER_EXTENSIONS: dict[str, str] = {
    ".zcci": ".cci",
    ".zcia": ".cia",
    ".zcxi": ".cxi",
    ".z3dsx": ".3dsx",
}

# Header "underlying magic" -> extension, used for the generic .z3ds container.
_MAGIC_EXTENSIONS: dict[bytes, str] = {
    b"NCSD": ".cci",
    b"NCCH": ".cxi",
    b"3DSX": ".3dsx",
}

Emit = Callable[[str], None]


class Z3dsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Z3dsHeader:
    underlying_magic: bytes
    version: int
    header_size: int
    metadata_size: int
    compressed_size: int
    uncompressed_size: int

    @property
    def payload_offset(self) -> int:
        return self.header_size + self.metadata_size


def read_header(path: Path) -> Z3dsHeader:
    """Parse the Z3DS header, or raise Z3dsError if this is not a Z3DS file."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(HEADER_SIZE)
    except OSError as exc:
        raise Z3dsError(f"Cannot read {path.name}: {exc}") from exc

    if len(raw) < HEADER_SIZE or raw[:4] != MAGIC:
        raise Z3dsError(f"{path.name} is not a Z3DS file (no 'Z3DS' magic).")

    underlying, version, _reserved, header_size, metadata_size, comp, uncomp = struct.unpack(
        "<4sBBHIQQ", raw[4:HEADER_SIZE],
    )
    if version not in SUPPORTED_VERSIONS:
        raise Z3dsError(f"Unsupported Z3DS version {version} (this build reads v1).")
    if header_size < HEADER_SIZE:
        raise Z3dsError(f"Corrupt Z3DS header (header size {header_size}).")
    return Z3dsHeader(underlying, version, header_size, metadata_size, comp, uncomp)


def is_z3ds_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == MAGIC
    except OSError:
        return False


def original_extension(path: Path, header: Z3dsHeader | None = None) -> str:
    """Extension the decompressed ROM should get."""
    ext = CONTAINER_EXTENSIONS.get(path.suffix.lower())
    if ext:
        return ext
    if header is not None:
        magic = header.underlying_magic
        if magic in _MAGIC_EXTENSIONS:
            return _MAGIC_EXTENSIONS[magic]
        # CIAs have no ASCII magic; the compressor stores their raw first bytes.
        if magic[:1] == b"\x20":
            return ".cia"
    return ".cci"


def _read_seek_table(handle, payload_offset: int, file_size: int) -> list[tuple[int, int]] | None:
    """Frame sizes from the seekable seek table, or None when it is absent."""
    if file_size - payload_offset < _SEEK_FOOTER_SIZE + 8:
        return None
    handle.seek(file_size - _SEEK_FOOTER_SIZE)
    frames, descriptor, magic = struct.unpack("<IBI", handle.read(_SEEK_FOOTER_SIZE))
    if magic != _SEEKABLE_MAGIC or descriptor & 0x7C:
        return None

    entry_size = 8 + (4 if descriptor & 0x80 else 0)
    table_size = frames * entry_size
    table_start = file_size - _SEEK_FOOTER_SIZE - table_size
    frame_start = table_start - 8
    if frame_start < payload_offset:
        return None

    handle.seek(frame_start)
    skip_magic, skip_size = struct.unpack("<II", handle.read(8))
    if skip_magic & _SKIPPABLE_MASK != _SKIPPABLE_MAGIC:
        return None
    if skip_size != table_size + _SEEK_FOOTER_SIZE:
        return None

    raw = handle.read(table_size)
    entries: list[tuple[int, int]] = []
    for index in range(frames):
        chunk = raw[index * entry_size:index * entry_size + 8]
        compressed, decompressed = struct.unpack("<II", chunk)
        entries.append((compressed, decompressed))
    return entries


def decompress(
    source: Path,
    destination: Path,
    emit: Emit | None = None,
    *,
    verify_size: bool = True,
) -> Path:
    """Restore the ROM inside a Z3DS container. Returns the written path."""
    try:
        import zstandard
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise Z3dsError("The 'zstandard' package is required to open Z3DS files.") from exc

    header = read_header(source)
    file_size = source.stat().st_size
    if header.payload_offset >= file_size:
        raise Z3dsError(f"{source.name} is truncated (no compressed data).")

    if destination.resolve() == source.resolve():
        raise Z3dsError("Output would overwrite the input file.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    if emit:
        size_mb = header.uncompressed_size / (1024 * 1024)
        emit(f"Z3DS v{header.version} -> {destination.name} ({size_mb:.1f} MB)")

    dctx = zstandard.ZstdDecompressor()
    total = header.uncompressed_size
    written = 0
    last_pct = -1

    def report() -> None:
        nonlocal last_pct
        if not emit or not total:
            return
        pct = min(100, int(written * 100 / total))
        if pct != last_pct:
            last_pct = pct
            emit(f"Decompressing: {pct}%")

    try:
        with source.open("rb") as src, destination.open("wb") as dst:
            entries = _read_seek_table(src, header.payload_offset, file_size)
            src.seek(header.payload_offset)

            if entries:
                for compressed_size, decompressed_size in entries:
                    frame = src.read(compressed_size)
                    if len(frame) != compressed_size:
                        raise Z3dsError("Compressed data ends early (file truncated).")
                    block = dctx.decompress(frame, max_output_size=decompressed_size)
                    dst.write(block)
                    written += len(block)
                    report()
            else:
                # No usable seek table: stream every frame instead.
                reader = dctx.stream_reader(src, read_across_frames=True)
                while True:
                    block = reader.read(_READ_CHUNK)
                    if not block:
                        break
                    dst.write(block)
                    written += len(block)
                    report()
    except Z3dsError:
        _cleanup(destination)
        raise
    except zstandard.ZstdError as exc:
        _cleanup(destination)
        raise Z3dsError(f"Corrupt Z3DS data: {exc}") from exc
    except OSError as exc:
        _cleanup(destination)
        raise Z3dsError(f"Write failed: {exc}") from exc

    if verify_size and total and written != total:
        _cleanup(destination)
        raise Z3dsError(
            f"Size mismatch: got {written} bytes, header expects {total}.",
        )

    if emit:
        emit("Decompressing: 100%")
    return destination


def _cleanup(path: Path) -> None:
    """Remove a partial output. A half-written ROM that looks finished is
    worse than no ROM at all, and a failure to remove it must not mask the
    original error."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
