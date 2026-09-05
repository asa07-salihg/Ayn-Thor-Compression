"""Reading a Z3DS container back into the ROM it was made from.

The containers here are built by hand from the format description in
`core.ctr.z3ds`, both with and without a seek table, because the decoder takes
a different path for each and only one of them is exercised by files that
rom-converto produces.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

zstandard = pytest.importorskip("zstandard")

from aynthor.core.ctr import z3ds  # noqa: E402

PAYLOAD = bytes(range(256)) * 400  # 102,400 bytes, compresses well


def build_container(
    path: Path,
    payload: bytes = PAYLOAD,
    *,
    underlying: bytes = b"NCSD",
    version: int = 1,
    metadata: bytes = b"",
    frames: int = 1,
) -> Path:
    compressor = zstandard.ZstdCompressor(level=3)
    chunk = len(payload) // frames
    blobs = [
        compressor.compress(payload[i * chunk: (i + 1) * chunk if i < frames - 1 else len(payload)])
        for i in range(frames)
    ]
    body = b"".join(blobs)
    header = b"Z3DS"
    header += struct.pack(
        "<4sBBHIQQ", underlying, version, 0, z3ds.HEADER_SIZE, len(metadata),
        len(body), len(payload),
    )
    assert len(header) == z3ds.HEADER_SIZE
    path.write_bytes(header + metadata + body)
    return path


def build_container_with_seek_table(path: Path, payload: bytes = PAYLOAD,
                                    frames: int = 4) -> Path:
    compressor = zstandard.ZstdCompressor(level=3)
    chunk = len(payload) // frames
    parts = [payload[i * chunk: (i + 1) * chunk if i < frames - 1 else len(payload)]
             for i in range(frames)]
    blobs = [compressor.compress(part) for part in parts]
    body = b"".join(blobs)

    table = b"".join(struct.pack("<II", len(c), len(p)) for c, p in zip(blobs, parts, strict=True))
    footer = struct.pack("<IBI", frames, 0, 0x8F92EAB1)
    skippable = struct.pack("<II", 0x184D2A50, len(table) + len(footer)) + table + footer

    header = b"Z3DS" + struct.pack(
        "<4sBBHIQQ", b"NCSD", 1, 0, z3ds.HEADER_SIZE, 0,
        len(body) + len(skippable), len(payload),
    )
    path.write_bytes(header + body + skippable)
    return path


def test_round_trip_without_a_seek_table(tmp_path: Path):
    source = build_container(tmp_path / "game.zcci")
    written = z3ds.decompress(source, tmp_path / "game.cci")
    assert written.read_bytes() == PAYLOAD


def test_round_trip_with_a_seek_table(tmp_path: Path):
    source = build_container_with_seek_table(tmp_path / "game.zcci")
    written = z3ds.decompress(source, tmp_path / "game.cci")
    assert written.read_bytes() == PAYLOAD


def test_round_trip_across_several_frames(tmp_path: Path):
    source = build_container(tmp_path / "game.zcci", frames=5)
    written = z3ds.decompress(source, tmp_path / "game.cci")
    assert written.read_bytes() == PAYLOAD


def test_metadata_block_is_skipped(tmp_path: Path):
    source = build_container(tmp_path / "game.zcci", metadata=b"x" * 48)
    written = z3ds.decompress(source, tmp_path / "game.cci")
    assert written.read_bytes() == PAYLOAD


def test_header_fields(tmp_path: Path):
    header = z3ds.read_header(build_container(tmp_path / "game.zcci"))
    assert header.version == 1
    assert header.uncompressed_size == len(PAYLOAD)
    assert header.underlying_magic == b"NCSD"


def test_a_file_without_the_magic_is_rejected(tmp_path: Path):
    path = tmp_path / "not-z3ds.zcci"
    path.write_bytes(b"\0" * 512)
    with pytest.raises(z3ds.Z3dsError, match="not a Z3DS file"):
        z3ds.read_header(path)


def test_an_unsupported_version_is_rejected(tmp_path: Path):
    source = build_container(tmp_path / "future.zcci", version=99)
    with pytest.raises(z3ds.Z3dsError, match="Unsupported Z3DS version"):
        z3ds.read_header(source)


def test_a_truncated_payload_is_reported_and_the_output_removed(tmp_path: Path):
    source = build_container(tmp_path / "game.zcci")
    data = source.read_bytes()
    source.write_bytes(data[: len(data) - 40])
    destination = tmp_path / "game.cci"
    with pytest.raises(z3ds.Z3dsError):
        z3ds.decompress(source, destination)
    # A half-written ROM that looks finished is worse than no ROM at all.
    assert not destination.exists()


def test_a_size_mismatch_is_caught(tmp_path: Path):
    source = build_container(tmp_path / "game.zcci")
    raw = bytearray(source.read_bytes())
    struct.pack_into("<Q", raw, 0x18, len(PAYLOAD) + 1024)  # lie about the size
    source.write_bytes(bytes(raw))
    with pytest.raises(z3ds.Z3dsError, match="Size mismatch"):
        z3ds.decompress(source, tmp_path / "game.cci")


def test_refuses_to_overwrite_its_own_input(tmp_path: Path):
    source = build_container(tmp_path / "game.zcci")
    with pytest.raises(z3ds.Z3dsError, match="overwrite"):
        z3ds.decompress(source, source)


def test_is_z3ds_file(tmp_path: Path):
    assert z3ds.is_z3ds_file(build_container(tmp_path / "a.zcci")) is True
    plain = tmp_path / "b.cci"
    plain.write_bytes(b"\0" * 64)
    assert z3ds.is_z3ds_file(plain) is False


@pytest.mark.parametrize(
    ("name", "expected"),
    [("game.zcci", ".cci"), ("game.zcia", ".cia"),
     ("game.zcxi", ".cxi"), ("game.z3dsx", ".3dsx")],
)
def test_extension_comes_from_the_container_name(name, expected):
    assert z3ds.original_extension(Path(name)) == expected


def test_generic_container_falls_back_to_the_header_magic(tmp_path: Path):
    source = build_container(tmp_path / "game.z3ds", underlying=b"3DSX")
    header = z3ds.read_header(source)
    assert z3ds.original_extension(source, header) == ".3dsx"


def test_generic_container_recognises_a_cia_by_its_first_byte(tmp_path: Path):
    source = build_container(tmp_path / "game.z3ds", underlying=b"\x20\x20\x00\x00")
    header = z3ds.read_header(source)
    assert z3ds.original_extension(source, header) == ".cia"


# --------------------------------------------- the decoder must be bounded

def test_a_container_cannot_expand_past_the_size_it_declares(tmp_path):
    """A few hundred KB of crafted zstd expanded to hundreds of gigabytes: the
    stream was written until the input ran out and the size was only compared
    afterwards, by which time the disk was full."""
    import zstandard

    from aynthor.core.ctr import z3ds

    payload = b"\0" * (4 * 1024 * 1024)
    compressed = zstandard.ZstdCompressor().compress(payload)

    source = tmp_path / "bomb.z3ds"
    # A header that understates the size, and no seek table, so the streaming
    # branch runs.
    header = b"Z3DS" + struct.pack(
        "<4sBBHIQQ", b"NCSD", 1, 0, z3ds.HEADER_SIZE, 0,
        len(compressed), 1024,
    )
    source.write_bytes(header + compressed)

    destination = tmp_path / "out.cci"
    with pytest.raises(z3ds.Z3dsError, match="expands to more"):
        z3ds.decompress(source, destination)
    assert not destination.exists(), "the partial output must be removed"
