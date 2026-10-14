"""Running a batch: what is skipped, what is converted, what is sent, and what
is deleted afterwards. No Qt and no real converter: `get_converter` is
replaced by a fake that writes a known output."""

from __future__ import annotations

import os
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import pytest

from aynthor.core import batch as batch_module
from aynthor.core.batch import Batch, Events, Outcome
from aynthor.core.device import DeviceError, MemoryFS
from aynthor.core.models import CompressionFormat, ConversionJob, ConversionMode

P = PurePosixPath


class FakeConverter:
    """Writes `out:` plus the input's bytes, so the output is smaller than
    nothing and bigger than nothing, and its origin can be checked."""

    calls: list[Path]

    def __init__(self) -> None:
        self.calls = []
        self.on_progress = None

    def convert(self, job: ConversionJob):
        self.calls.append(job.input_path)
        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        job.output_path.write_bytes(b"out:" + job.input_path.read_bytes()[:8])
        if self.on_progress:
            self.on_progress(100)
        return True, "Converted."


@pytest.fixture()
def converter(monkeypatch) -> FakeConverter:
    fake = FakeConverter()
    monkeypatch.setattr(batch_module, "get_converter", lambda _fmt: fake)
    return fake


class Recorder:
    def __init__(self) -> None:
        self.finished: list[tuple[int, Outcome, str]] = []
        self.stages: list[tuple[int, str]] = []
        self.logs: list[str] = []

    def events(self) -> Events:
        return Events(
            log=self.logs.append,
            stage=lambda row, text: self.stages.append((row, text)),
            finished=lambda row, _job, outcome, message: self.finished.append(
                (row, outcome, message)),
        )


def job(source: Path, output: Path, *, fmt=CompressionFormat.CHD, mode=ConversionMode.COMPRESS,
        member: str = "", remote: str = "", **options) -> ConversionJob:
    return ConversionJob(input_path=source, output_path=output, format=fmt,
                         options={"mode": mode.value, **options}, member=member, remote=remote,
                         input_size=source.stat().st_size if source.is_file() else 0)


def run(jobs, policy="skip", device=None) -> Recorder:
    recorder = Recorder()
    opener = None
    if device is not None:
        @contextmanager
        def opener():
            yield device
    Batch(list(enumerate(jobs, start=1)), policy=policy, events=recorder.events(),
          open_device=opener).run()
    return recorder


def file(path: Path, data: bytes = b"cue-and-bin") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ------------------------------------------------------------ local folders


def test_skip_is_decided_when_the_job_starts(tmp_path, converter):
    """Not when the file was added and not when Start was pressed: the job
    is in the batch and reports why nothing was done."""
    source = file(tmp_path / "game.cue")
    done = file(tmp_path / "game.chd", b"old")
    result = run([job(source, done)])
    assert result.finished == [(1, Outcome.SKIPPED, "game.chd is already there.")]
    assert converter.calls == []
    assert done.read_bytes() == b"old"


def test_an_earlier_job_in_the_same_batch_counts_as_there(tmp_path, converter):
    one = file(tmp_path / "a" / "game.cue", b"first")
    two = file(tmp_path / "b" / "game.cue", b"second")
    out = tmp_path / "out" / "game.chd"
    result = run([job(one, out), job(two, out)], policy="rename")
    assert [o for _r, o, _m in result.finished] == [Outcome.DONE, Outcome.DONE]
    assert (tmp_path / "out" / "game.chd").read_bytes().endswith(b"first")
    assert (tmp_path / "out" / "game_1.chd").read_bytes().endswith(b"second")


def test_overwrite_never_overwrites_another_row_of_the_same_batch(tmp_path, converter):
    one = file(tmp_path / "a" / "game.cue", b"first")
    two = file(tmp_path / "b" / "game.cue", b"second")
    out = file(tmp_path / "out" / "game.chd", b"old")
    run([job(one, out), job(two, out)], policy="overwrite")
    assert out.read_bytes().endswith(b"first")
    assert (tmp_path / "out" / "game_1.chd").read_bytes().endswith(b"second")


def test_a_file_already_where_it_belongs_is_skipped_with_a_reason(tmp_path, converter):
    rom = file(tmp_path / "snes" / "Mario.7z")
    result = run([job(rom, rom, fmt=CompressionFormat.SEVEN_ZIP)])
    (_row, outcome, message), = result.finished
    assert outcome is Outcome.SKIPPED
    assert "already a 7z where it belongs" in message


def test_moving_a_file_onto_itself_is_skipped_not_deleted(tmp_path, converter):
    """The card was chosen as the destination and the game already sits on
    it. A move onto itself followed by "delete the source" would lose it."""
    rom = file(tmp_path / "ROMs" / "psx" / "Game.chd", b"disc")
    moving = job(rom, rom, fmt=CompressionFormat.CHD)
    moving.options["mode"] = ConversionMode.MOVE.value
    moving.options["delete_source"] = True
    result = run([moving], policy="overwrite")
    (_row, outcome, _message), = result.finished
    assert outcome is Outcome.SKIPPED
    assert rom.read_bytes() == b"disc"
    assert converter.calls == []


def test_a_failing_job_does_not_stop_the_next(tmp_path, monkeypatch):
    class Broken:
        on_progress = None

        def convert(self, _job):
            raise RuntimeError("boom")

    monkeypatch.setattr(batch_module, "get_converter", lambda _fmt: Broken())
    a = file(tmp_path / "a.cue")
    b = file(tmp_path / "b.cue")
    result = run([job(a, tmp_path / "a.chd"), job(b, tmp_path / "b.chd")])
    assert [o for _r, o, _m in result.finished] == [Outcome.FAILED, Outcome.FAILED]
    assert "RuntimeError: boom" in result.finished[0][2]


def test_a_member_job_restores_the_archive_path_after_unpacking(tmp_path, converter):
    archive = tmp_path / "game.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("game.iso", b"disc")
    output = tmp_path / "out" / "game.chd"
    single = job(archive, output, member="game.iso")
    ok, _message = Batch([]).execute(0, single)
    assert ok is True
    assert single.input_path == archive
    assert converter.calls[0].name == "game.iso"
    assert output.read_bytes() == b"out:disc"


def test_a_stale_output_does_not_authorise_deleting_the_source(tmp_path):
    """On overwrite a leftover from an earlier run met every other guard by
    itself, and a converter exiting zero without writing anything would have
    deleted the source against somebody else's file."""
    source = file(tmp_path / "game.iso", b"\0" * 2048)
    stale = file(tmp_path / "game.chd", b"\0" * 2048)
    single = job(source, stale)
    runner = Batch([])
    assert runner.delete_source(single, started_at=stale.stat().st_mtime + 60) is False
    assert source.is_file()
    assert runner.delete_source(single, started_at=stale.stat().st_mtime - 60) is True
    assert not source.exists()


def test_the_runner_can_fold_a_loose_rom_into_its_own_folder(tmp_path):
    """Folding `Game.7z` into `Game.7z/Game.7z` asks for a folder whose path
    is the source file; creating the parent first used to raise."""
    rom = file(tmp_path / "snes" / "Front Mission.7z", b"archive-bytes")
    out = tmp_path / "snes" / "Front Mission.7z" / "Front Mission.7z"
    ok, message = Batch([]).execute(0, job(rom, out, fmt=CompressionFormat.SEVEN_ZIP,
                                           mode=ConversionMode.MOVE))
    assert ok, message
    assert out.read_bytes() == b"archive-bytes"


def test_delete_source_after_a_real_conversion(tmp_path, converter):
    source = file(tmp_path / "game.cue")
    result = run([job(source, tmp_path / "out" / "game.chd", delete_source=True)])
    assert result.finished[0][1] is Outcome.DONE
    assert "Source deleted." in result.finished[0][2]
    assert not source.exists()


def test_an_archive_is_deleted_only_after_its_last_disc(tmp_path, converter):
    archive = tmp_path / "ff7.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("FF7 (Disc 1).cue", b"one")
        opened.writestr("FF7 (Disc 2).cue", b"two")
    jobs = [job(archive, tmp_path / "out" / f"FF7 (Disc {n}).chd",
                member=f"FF7 (Disc {n}).cue", delete_source=True) for n in (1, 2)]
    result = run(jobs)
    assert [o for _r, o, _m in result.finished] == [Outcome.DONE, Outcome.DONE]
    assert "Source deleted." not in result.finished[0][2]
    assert "Source deleted." in result.finished[1][2]
    assert not archive.exists()


def test_a_skipped_disc_still_lets_the_archive_finish(tmp_path, converter):
    """Disc 1 is already converted and skipped; disc 2 converts. The skipped
    disc must still count, or the shared unpacked copy is never cleaned up
    and the archive never deleted."""
    archive = tmp_path / "ff7.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("FF7 (Disc 1).cue", b"one")
        opened.writestr("FF7 (Disc 2).cue", b"two")
    file(tmp_path / "out" / "FF7 (Disc 1).chd", b"done before")
    jobs = [job(archive, tmp_path / "out" / f"FF7 (Disc {n}).chd",
                member=f"FF7 (Disc {n}).cue", delete_source=True) for n in (1, 2)]
    result = run(jobs)
    assert [o for _r, o, _m in result.finished] == [Outcome.SKIPPED, Outcome.DONE]
    assert not archive.exists()
    assert not list(tmp_path.glob(".aynthor-unpack-*"))


def test_cancel_stops_before_the_next_job(tmp_path, converter):
    a = file(tmp_path / "a.cue")
    b = file(tmp_path / "b.cue")
    recorder = Recorder()
    runner = Batch([(1, job(a, tmp_path / "a.chd")), (2, job(b, tmp_path / "b.chd"))],
                   events=recorder.events())
    original = converter.convert

    def convert_then_cancel(single):
        result = original(single)
        runner.cancel()
        return result

    converter.convert = convert_then_cancel
    runner.run()
    assert [r for r, _o, _m in recorder.finished] == [1]
    assert any("Stopped with 1 left" in line for line in recorder.logs)


# ------------------------------------------------------------------ devices


def staged_job(tmp_path: Path, name: str = "Spyro", data: bytes = b"track data",
               **options) -> ConversionJob:
    source = file(tmp_path / "Downloads" / f"{name}.cue", data)
    staged = tmp_path / "Staging" / "psx" / f"{name}.chd"
    return job(source, staged, remote=f"psx/{name}.chd", **options)


def test_a_converted_game_is_sent_and_the_staged_copy_removed(tmp_path, converter):
    device = MemoryFS("AYN Thor")
    single = staged_job(tmp_path)
    result = run([single], device=device)
    assert result.finished == [(1, Outcome.DONE, "Sent to AYN Thor.")]
    assert device.read(P("psx/Spyro.chd")) == b"out:track da"
    assert result.stages == [(1, "Sending to AYN Thor")]
    assert not single.output_path.exists()
    assert single.output_size == len(b"out:track da")


def test_a_game_already_on_the_device_is_not_converted(tmp_path, converter):
    device = MemoryFS("AYN Thor")
    device.write(P("psx/Spyro.chd"), b"already")
    result = run([staged_job(tmp_path)], device=device)
    assert result.finished == [(1, Outcome.SKIPPED, "Already on AYN Thor")]
    assert converter.calls == []


def test_a_finished_file_is_sent_as_it_is(tmp_path, converter):
    """A `.chd` bound for the device's psx folder is only copied across; it
    is not staged first."""
    device = MemoryFS("AYN Thor")
    source = file(tmp_path / "Downloads" / "Spyro.chd", b"finished chd")
    staged = tmp_path / "Staging" / "psx" / "Spyro.chd"
    result = run([job(source, staged, mode=ConversionMode.MOVE, remote="psx/Spyro.chd")],
                 device=device)
    assert result.finished[0][1] is Outcome.DONE
    assert device.read(P("psx/Spyro.chd")) == b"finished chd"
    assert converter.calls == []
    assert not staged.exists()
    assert source.is_file()


def test_a_failed_send_keeps_the_converted_copy_for_next_time(tmp_path, converter):
    device = MemoryFS("AYN Thor")
    device.fail_after = 0
    single = staged_job(tmp_path)
    result = run([single], device=device)
    (_row, outcome, message), = result.finished
    assert outcome is Outcome.FAILED
    assert "goes across on the next Start" in message
    assert single.output_path.is_file()

    # The cable is back: the second Start sends without converting again.
    device.fail_after = None
    again = job(single.input_path, tmp_path / "Staging" / "psx" / "Spyro.chd",
                remote="psx/Spyro.chd")
    converter.calls.clear()
    result = run([again], device=device)
    assert result.finished[0][1] is Outcome.DONE
    assert converter.calls == []
    assert device.read(P("psx/Spyro.chd")) == b"out:track da"


def test_a_changed_source_is_converted_again_instead_of_reused(tmp_path, converter):
    device = MemoryFS("AYN Thor")
    device.fail_after = 0
    run([staged_job(tmp_path, data=b"version one")], device=device)
    device.fail_after = None
    time.sleep(0.01)
    single = staged_job(tmp_path, data=b"version two")
    os.utime(single.input_path, None)
    converter.calls.clear()
    run([single], device=device)
    assert len(converter.calls) == 1
    assert device.read(P("psx/Spyro.chd")) == b"out:version "


def test_a_full_device_fails_with_the_sizes(tmp_path, converter):
    device = MemoryFS("AYN Thor", capacity=10)
    result = run([staged_job(tmp_path)], device=device)
    (_row, outcome, message), = result.finished
    assert outcome is Outcome.FAILED
    assert "AYN Thor has" in message


def test_a_device_that_will_not_open_fails_each_job_and_is_retried(tmp_path, converter):
    attempts: list[int] = []

    @contextmanager
    def unplugged():
        attempts.append(1)
        raise DeviceError("AYN Thor isn't connected.")
        yield  # pragma: no cover

    recorder = Recorder()
    jobs = [(1, staged_job(tmp_path, "A")), (2, staged_job(tmp_path, "B"))]
    Batch(jobs, events=recorder.events(), open_device=unplugged).run()
    assert [(r, o) for r, o, _m in recorder.finished] == [(1, Outcome.FAILED),
                                                         (2, Outcome.FAILED)]
    assert recorder.finished[0][2] == "AYN Thor isn't connected."
    assert len(attempts) == 2
    assert converter.calls == []


def test_delete_source_after_the_device_confirms(tmp_path, converter):
    device = MemoryFS("AYN Thor")
    single = staged_job(tmp_path, delete_source=True)
    result = run([single], device=device)
    assert "Source deleted." in result.finished[0][2]
    assert not single.input_path.exists()


def test_rename_on_the_device_says_what_it_was_called(tmp_path, converter):
    device = MemoryFS("AYN Thor")
    device.write(P("psx/Spyro.chd"), b"other game")
    result = run([staged_job(tmp_path)], policy="rename", device=device)
    assert result.finished == [(1, Outcome.DONE, "Sent to AYN Thor as Spyro_1.chd.")]
    assert device.read(P("psx/Spyro.chd")) == b"other game"


# ------------------------------------------------------- cue sheets and tracks


def _cue(folder: Path, name: str = "Game") -> Path:
    file(folder / f"{name} (Track 1).bin", b"1" * 40)
    file(folder / f"{name} (Track 2).bin", b"2" * 20)
    return file(folder / f"{name}.cue", (
        f'FILE "{name} (Track 1).bin" BINARY\nFILE "{name} (Track 2).bin" BINARY\n'
    ).encode())


def test_a_cue_sent_as_it_is_takes_its_tracks_and_arrives_last(tmp_path, converter):
    device = MemoryFS("AYN Thor")
    sheet = _cue(tmp_path / "Downloads")
    staged = tmp_path / "Staging" / "psx" / "Game.cue"
    order: list[str] = []
    upload = device.upload

    def watched(local, remote, *args, **kwargs):
        order.append(remote.name)
        return upload(local, remote, *args, **kwargs)

    device.upload = watched
    result = run([job(sheet, staged, mode=ConversionMode.MOVE, remote="psx/Game.cue")],
                 device=device)
    assert result.finished[0][1] is Outcome.DONE
    assert device.read(P("psx/Game (Track 1).bin")) == b"1" * 40
    assert device.read(P("psx/Game (Track 2).bin")) == b"2" * 20
    assert order[-1] == "Game.cue"
    assert converter.calls == []


def test_a_cue_with_a_missing_track_is_not_sent(tmp_path, converter):
    device = MemoryFS("AYN Thor")
    sheet = _cue(tmp_path / "Downloads")
    (sheet.parent / "Game (Track 2).bin").unlink()
    staged = tmp_path / "Staging" / "psx" / "Game.cue"
    result = run([job(sheet, staged, mode=ConversionMode.MOVE, remote="psx/Game.cue")],
                 device=device)
    (_row, outcome, message), = result.finished
    assert outcome is Outcome.FAILED
    assert "Game (Track 2).bin" in message
    assert device.uploads == []


def test_deleting_a_converted_cue_deletes_its_tracks(tmp_path, converter):
    sheet = _cue(tmp_path / "psx")
    out = tmp_path / "psx" / "Game.chd"
    result = run([job(sheet, out, delete_source=True)])
    assert result.finished[0][1] is Outcome.DONE
    assert sorted(p.name for p in sheet.parent.iterdir()) == ["Game.chd"]


def test_a_renamed_copy_keeps_the_tracks_it_shares_with_the_source(tmp_path, converter):
    """Rename put `Game_1.cue` next to `Game.cue`; both list the same tracks,
    and deleting the source must not take them from the copy."""
    sheet = _cue(tmp_path / "psx")
    file(tmp_path / "out" / "Game.cue", b"someone else's")
    moved = job(sheet, tmp_path / "out" / "Game.cue", mode=ConversionMode.MOVE,
                delete_source=True)
    moved.output_path = tmp_path / "psx" / "Game_1.cue"
    run([moved], policy="overwrite")
    assert not sheet.exists()
    assert (tmp_path / "psx" / "Game (Track 1).bin").is_file()
    assert (tmp_path / "psx" / "Game_1.cue").is_file()


def test_moving_a_cue_out_of_a_zip_brings_its_tracks(tmp_path, converter):
    archive = tmp_path / "Downloads" / "Game.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("Game.cue", 'FILE "Game.bin" BINARY\n')
        opened.writestr("Game.bin", b"b" * 30)
    out = tmp_path / "ROMs" / "psx" / "Game.cue"
    result = run([job(archive, out, mode=ConversionMode.MOVE, member="Game.cue")])
    assert result.finished[0][1] is Outcome.DONE
    assert (out.parent / "Game.bin").read_bytes() == b"b" * 30
