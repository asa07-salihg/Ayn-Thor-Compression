"""Deciding whether to send a game, and sending it, against an in-memory device."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from aynthor.core.device import DeviceError, DeviceTarget, MemoryFS, deliver

P = PurePosixPath
TARGET = DeviceTarget("id", "AYN Thor", "disk", "ROMs")


def _local(tmp_path: Path, name: str = "Game.chd", size: int = 1000) -> Path:
    path = tmp_path / name
    path.write_bytes(b"c" * size)
    return path


def test_a_game_not_on_the_device_is_sent(tmp_path):
    fs = MemoryFS("AYN Thor")
    decided = deliver.plan(fs, P("psx/Game.chd"), "skip", set())
    assert decided.remote == P("psx/Game.chd")
    deliver.send(fs, _local(tmp_path), decided)
    assert fs.read(P("psx/Game.chd")) == b"c" * 1000


def test_skip_leaves_a_game_that_is_already_there(tmp_path):
    fs = MemoryFS("AYN Thor")
    fs.write(P("psx/Game.chd"), b"old")
    decided = deliver.plan(fs, P("psx/Game.chd"), "skip", set())
    assert decided.remote is None
    assert decided.reason == "Already on AYN Thor"


def test_overwrite_replaces_the_old_copy(tmp_path):
    fs = MemoryFS("AYN Thor")
    fs.write(P("psx/Game.chd"), b"old")
    decided = deliver.plan(fs, P("psx/Game.chd"), "overwrite", set())
    assert decided.replace
    deliver.send(fs, _local(tmp_path), decided)
    assert fs.read(P("psx/Game.chd")) == b"c" * 1000


def test_rename_finds_a_free_name_on_the_device(tmp_path):
    fs = MemoryFS("AYN Thor")
    fs.write(P("psx/Game.chd"), b"a")
    fs.write(P("psx/Game_1.chd"), b"b")
    decided = deliver.plan(fs, P("psx/Game.chd"), "rename", set())
    assert decided.remote == P("psx/Game_2.chd")


def test_overwrite_never_lands_on_what_this_run_just_sent(tmp_path):
    """Two rows heading for one path in one batch are two games, not an old
    copy and a new one."""
    fs = MemoryFS("AYN Thor")
    sent = {P("psx/Game.chd")}
    fs.write(P("psx/Game.chd"), b"first")
    decided = deliver.plan(fs, P("psx/Game.chd"), "overwrite", sent)
    assert decided.remote == P("psx/Game_1.chd")
    assert not decided.replace


def test_a_full_device_is_refused_before_anything_moves(tmp_path):
    fs = MemoryFS("AYN Thor", capacity=deliver.HEADROOM + 500)
    decided = deliver.plan(fs, P("psx/Game.chd"), "skip", set())
    with pytest.raises(DeviceError, match=r"needs .* and AYN Thor has"):
        deliver.send(fs, _local(tmp_path, size=1000), decided)
    assert fs.uploads == []


def test_replacing_counts_the_room_the_old_copy_frees(tmp_path):
    fs = MemoryFS("AYN Thor", capacity=deliver.HEADROOM + 1200)
    fs.write(P("psx/Game.chd"), b"o" * 900)
    decided = deliver.plan(fs, P("psx/Game.chd"), "overwrite", set())
    deliver.send(fs, _local(tmp_path, size=1000), decided)
    assert len(fs.read(P("psx/Game.chd"))) == 1000


def test_a_folder_in_the_way_is_reported(tmp_path):
    fs = MemoryFS("AYN Thor")
    fs.mkdirs(P("psx/Game.chd"))
    with pytest.raises(DeviceError, match=r"folder called Game\.chd"):
        deliver.plan(fs, P("psx/Game.chd"), "overwrite", set())


def test_a_dropped_connection_leaves_no_half_file(tmp_path):
    fs = MemoryFS("AYN Thor")
    fs.fail_after = 10
    decided = deliver.plan(fs, P("psx/Game.chd"), "skip", set())
    with pytest.raises(DeviceError, match="stopped responding"):
        deliver.send(fs, _local(tmp_path), decided)
    assert fs.stat(P("psx/Game.chd")) is None


def test_staging_mirrors_the_device(tmp_path):
    root = deliver.staging_root(TARGET, tmp_path)
    assert root == tmp_path / "AYN Thor" / "disk"
    staged = root / "psx" / "Game.chd" / "Game.chd"
    assert deliver.remote_for(staged, root) == P("psx/Game.chd/Game.chd")
    assert deliver.remote_for(tmp_path / "elsewhere.chd", root) is None


def test_a_device_name_cannot_escape_the_staging_folder(tmp_path):
    hostile = DeviceTarget("id", "../../Windows", "C:", "ROMs")
    root = deliver.staging_root(hostile, tmp_path)
    assert tmp_path in root.parents


def test_a_converted_copy_is_reused_only_if_nothing_changed(tmp_path):
    source = _local(tmp_path, "Game.cue", 500)
    staged = _local(tmp_path, "Game.chd", 200)
    made_from = deliver.fingerprint(source, "", "chd", {"chd_type": "createcd"})
    deliver.remember(staged, made_from)
    assert deliver.can_reuse(staged, made_from)

    other_options = deliver.fingerprint(source, "", "chd", {"chd_type": "createdvd"})
    assert not deliver.can_reuse(staged, other_options)

    source.write_bytes(b"different")
    assert not deliver.can_reuse(staged, deliver.fingerprint(source, "", "chd",
                                                             {"chd_type": "createcd"}))


def test_a_truncated_staged_copy_is_not_reused(tmp_path):
    source = _local(tmp_path, "Game.cue", 500)
    staged = _local(tmp_path, "Game.chd", 200)
    made_from = deliver.fingerprint(source, "", "chd", {})
    deliver.remember(staged, made_from)
    staged.write_bytes(b"short")
    assert not deliver.can_reuse(staged, made_from)


def test_clearing_removes_the_copy_its_record_and_empty_folders(tmp_path):
    root = tmp_path / "Staging"
    staged = root / "psx" / "Game.chd" / "Game.chd"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"x")
    deliver.remember(staged, {"a": 1})
    deliver.clear(staged)
    assert not (root / "psx").exists()


def test_a_target_round_trips_through_settings():
    data = TARGET.to_dict()
    assert DeviceTarget.from_dict(data) == TARGET
    assert DeviceTarget.from_dict({"device_id": "x"}) is None
    assert DeviceTarget.from_dict("nonsense") is None
