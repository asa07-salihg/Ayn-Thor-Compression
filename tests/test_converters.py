"""Converters whose output path is not simply the one the queue predicted.

The queue decides where a row's result goes, the conflict policy is applied to
that path, and only then does a tool run. A converter that names its own output
therefore has to be brought back to the agreed path, or the policy was decided
about a file nobody writes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aynthor.core.models import CompressionFormat, ConversionJob


def _nsz_job(src: Path, dst: Path) -> ConversionJob:
    return ConversionJob(
        input_path=src,
        output_path=dst,
        format=CompressionFormat.NSZ,
        options={"level": 18},
    )


def test_nsz_output_lands_on_the_path_the_queue_promised(tmp_path: Path, monkeypatch):
    """nsz only takes a directory and names the file itself, from the *input*
    stem. So `Ys X Nordics [0100BAC01E57E800][v0].nsp` came out as
    `…[0100BAC01E57E800][v0].nsz` while the queue, the game folder and the
    conflict policy had all agreed on `Ys X Nordics.nsz`. The folder ES-DE
    launches is the one holding a file with the folder's own name, and that
    file was never written."""
    from aynthor.core.converters import nsz as nsz_module

    keys = tmp_path / "prod.keys"
    keys.write_text("key = value\n")
    source = tmp_path / "Ys X Nordics [0100BAC01E57E800][v0].nsp"
    source.write_bytes(b"\0" * 64)
    folder = tmp_path / "switch" / "Ys X Nordics.nsz"
    folder.mkdir(parents=True)
    wanted = folder / "Ys X Nordics.nsz"

    def fake_run(_command, args, **_kwargs):
        out_dir = Path(args[args.index("-o") + 1])
        (out_dir / f"{source.stem}.nsz").write_bytes(b"compressed")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(nsz_module, "run_tool", fake_run)
    monkeypatch.setattr(
        nsz_module, "nsz_command", lambda: (["nsz"], tmp_path, None))

    job = _nsz_job(source, wanted)
    job.options["keys_path"] = str(keys)
    ok, message = nsz_module.NszConverter().convert(job)

    assert ok, message
    assert wanted.read_bytes() == b"compressed"
    assert not list(folder.glob("*.aynthor-nsz-*"))


def test_nsz_does_not_write_over_the_file_the_policy_stepped_around(
    tmp_path: Path, monkeypatch,
):
    """With the policy on rename the queue hands back `Game_1.nsz`, and nsz
    still wrote `Game.nsz` -- straight over the file the policy existed to
    protect."""
    from aynthor.core.converters import nsz as nsz_module

    keys = tmp_path / "prod.keys"
    keys.write_text("key = value\n")
    source = tmp_path / "Game.nsp"
    source.write_bytes(b"\0" * 64)
    existing = tmp_path / "out" / "Game.nsz"
    existing.parent.mkdir()
    existing.write_bytes(b"do not touch")

    def fake_run(_command, args, **_kwargs):
        out_dir = Path(args[args.index("-o") + 1])
        (out_dir / "Game.nsz").write_bytes(b"new")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(nsz_module, "run_tool", fake_run)
    monkeypatch.setattr(
        nsz_module, "nsz_command", lambda: (["nsz"], tmp_path, None))

    job = _nsz_job(source, existing.with_name("Game_1.nsz"))
    job.options["keys_path"] = str(keys)
    ok, message = nsz_module.NszConverter().convert(job)

    assert ok, message
    assert existing.read_bytes() == b"do not touch"
    assert (tmp_path / "out" / "Game_1.nsz").read_bytes() == b"new"


@pytest.mark.skipif(shutil.which("7za") is None, reason="needs a real 7-Zip")
def test_archiving_over_an_existing_archive_replaces_it(tmp_path: Path, monkeypatch):
    """7-Zip's `a` is add-or-update, not create. Pointed at an archive that is
    already there it merged the new ROM in beside the old one, so "overwrite"
    produced a 7z holding two games and a saving figure measured against the
    pair."""
    from aynthor.core.converters import archive as archive_module

    monkeypatch.setattr(
        archive_module, "tool_path", lambda _name: Path(shutil.which("7za")))

    first = tmp_path / "Game.sfc"
    first.write_bytes(b"a" * 512)
    second = tmp_path / "Other.sfc"
    second.write_bytes(b"b" * 512)
    output = tmp_path / "Game.7z"

    converter = archive_module.SevenZipConverter()
    for source in (first, second):
        ok, message = converter.convert(ConversionJob(
            input_path=source, output_path=output,
            format=CompressionFormat.SEVEN_ZIP,
            options={"archive_type": "7z", "level": 1},
        ))
        assert ok, message

    listing = subprocess.run(
        [shutil.which("7za"), "l", "-slt", str(output)],
        capture_output=True, text=True, check=True).stdout
    assert "Game.sfc" not in listing
    assert "Other.sfc" in listing
