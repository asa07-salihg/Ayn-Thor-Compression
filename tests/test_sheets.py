"""Cue sheets and GDI files, and the tracks that have to travel with them."""

from __future__ import annotations

from pathlib import Path

from aynthor.core.converters.base import place_file
from aynthor.core.models import CompressionFormat, ConversionJob, ConversionMode
from aynthor.core.sheets import disc_size, missing_track, relative_tracks, tracks


def _disc(folder: Path, sheet: str = "Game.cue", text: str | None = None,
          files: dict[str, bytes] | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    files = files if files is not None else {
        "Game (Track 1).bin": b"1" * 100, "Game (Track 2).bin": b"2" * 50}
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    if text is None:
        text = "".join(f'FILE "{name}" BINARY\n  TRACK 01 MODE2/2352\n' for name in files)
    (folder / sheet).write_text(text, encoding="utf-8")
    return folder / sheet


def test_a_cue_lists_its_tracks_in_order(tmp_path: Path):
    sheet = _disc(tmp_path)
    assert [t.name for t in tracks(sheet)] == ["Game (Track 1).bin", "Game (Track 2).bin"]


def test_unquoted_names_bom_and_backslashes_are_read(tmp_path: Path):
    text = "\ufeffFILE track1.bin BINARY\r\nfile \"sub\\track2.bin\" BINARY\r\n"
    sheet = _disc(tmp_path, text=text, files={"track1.bin": b"a", "sub/track2.bin": b"b"})
    assert [str(t) for t in relative_tracks(sheet)] == ["track1.bin", "sub/track2.bin"]


def test_a_track_outside_the_folder_is_never_listed(tmp_path: Path):
    text = ('FILE "../elsewhere.bin" BINARY\nFILE "C:\\rips\\x.bin" BINARY\n'
            'FILE "/etc/passwd" BINARY\nFILE "ok.bin" BINARY\n')
    sheet = _disc(tmp_path / "game", text=text, files={"ok.bin": b"x"})
    assert [t.name for t in tracks(sheet)] == ["ok.bin"]


def test_a_gdi_lists_its_tracks(tmp_path: Path):
    text = ('3\n1 0 4 2352 track01.bin 0\n2 756 0 2352 "track 02.raw" 0\n'
            "3 45000 4 2352 track03.bin 0\n")
    sheet = _disc(tmp_path, "Game.gdi", text,
                  {"track01.bin": b"1", "track 02.raw": b"22", "track03.bin": b"333"})
    assert [t.name for t in tracks(sheet)] == ["track01.bin", "track 02.raw", "track03.bin"]
    assert disc_size(sheet) == sheet.stat().st_size + 6


def test_the_size_of_a_cue_row_is_the_whole_disc(tmp_path: Path):
    sheet = _disc(tmp_path)
    assert disc_size(sheet) == sheet.stat().st_size + 150


def test_a_missing_track_is_named(tmp_path: Path):
    sheet = _disc(tmp_path)
    (tmp_path / "Game (Track 2).bin").unlink()
    assert "Game (Track 2).bin" in missing_track(sheet)


def test_anything_else_has_no_tracks(tmp_path: Path):
    iso = tmp_path / "Game.iso"
    iso.write_bytes(b"FILE \"x.bin\" BINARY\n")
    assert tracks(iso) == []
    assert disc_size(iso) == iso.stat().st_size


def _move(source: Path, output: Path) -> ConversionJob:
    return ConversionJob(input_path=source, output_path=output, format=CompressionFormat.CHD,
                         options={"mode": ConversionMode.MOVE.value})


def test_moving_a_cue_takes_its_tracks(tmp_path: Path):
    sheet = _disc(tmp_path / "Downloads")
    out = tmp_path / "Card" / "psx" / "Game.cue"
    seen: list[int] = []
    ok, _message = place_file(_move(sheet, out), on_progress=seen.append)
    assert ok
    assert (out.parent / "Game (Track 1).bin").read_bytes() == b"1" * 100
    assert (out.parent / "Game (Track 2).bin").read_bytes() == b"2" * 50
    assert sheet.is_file()
    assert seen[-1] == 100
    assert seen == sorted(seen)


def test_folding_a_cue_into_its_own_folder_moves_the_tracks_too(tmp_path: Path):
    sheet = _disc(tmp_path / "psx")
    out = tmp_path / "psx" / "Game.cue" / "Game.cue"
    ok, _message = place_file(_move(sheet, out))
    assert ok
    assert out.is_file()
    assert sorted(p.name for p in out.parent.iterdir()) == [
        "Game (Track 1).bin", "Game (Track 2).bin", "Game.cue"]
    assert not (tmp_path / "psx" / "Game (Track 1).bin").exists()


def test_a_cue_with_a_missing_track_is_not_moved(tmp_path: Path):
    sheet = _disc(tmp_path / "Downloads")
    (sheet.parent / "Game (Track 1).bin").unlink()
    out = tmp_path / "Card" / "Game.cue"
    ok, message = place_file(_move(sheet, out))
    assert not ok
    assert "Game (Track 1).bin" in message
    assert not out.exists()
