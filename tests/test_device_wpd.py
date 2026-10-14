"""Talking to a handheld over Windows Portable Devices, against a fake one.

`fake_wpd` builds real function tables, so these run the client's actual
ctypes calls. After every test the fake checks that each string it handed
out was freed and each object it created was released.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from aynthor.core.device import DeviceError, DeviceTarget, open_target, scan
from aynthor.core.device.wpd import WpdDevice, WpdStorage, list_devices
from fake_wpd import Server

GB = 1024 ** 3


@pytest.fixture()
def server():
    server = Server()
    yield server
    assert server.errors == []
    assert server.strings == {}, "every string the device returns must be freed"
    assert server.live() == [], "every COM object must be released"


@pytest.fixture()
def thor(server):
    device = server.add_device(r"\\?\usb#vid_2207&pid_0006#thor", "AYN Thor")
    sd = device.storage("disk", 64 * 1024 * 1024)
    device.storage("Internal shared storage", 32 * 1024 * 1024)
    roms = device.folder(sd, "ROMs")
    psx = device.folder(roms, "psx")
    device.file(psx, "Crash Bandicoot.chd", b"x" * 1000)
    return device


def test_the_device_is_found_by_the_name_explorer_shows(server, thor):
    devices = list_devices(server)
    assert [(d.device_id, d.name) for d in devices] == [(thor.device_id, "AYN Thor")]


def test_storages_are_listed_with_their_room(server, thor):
    info = list_devices(server)[0]
    with WpdDevice(server, info) as device:
        storages = device.storages()
    assert [s.name for s in storages] == ["disk", "Internal shared storage"]
    sd = storages[0]
    assert sd.capacity == 64 * 1024 * 1024
    assert sd.free == 64 * 1024 * 1024 - 1000


def test_scan_finds_the_roms_folder(server, thor):
    found = scan(server)
    assert len(found) == 1
    assert found[0].problem == ""
    sd, internal = found[0].storages
    assert sd.roms == "ROMs"
    assert internal.roms is None
    target = found[0].target(sd)
    assert target.label.split(" \u203a ") == ["AYN Thor", "disk", "ROMs"]


def test_a_locked_device_says_how_to_fix_it(server, thor):
    thor.locked = True
    found = scan(server)
    assert "Unlock it" in found[0].problem
    assert "File transfer" in found[0].problem


def test_paths_resolve_case_insensitively(server, thor):
    target = DeviceTarget(thor.device_id, "AYN Thor", "DISK", "roms")
    with open_target(target, server) as fs:
        entry = fs.stat(PurePosixPath("PSX/crash bandicoot.chd"))
        assert entry is not None and entry.size == 1000 and not entry.is_dir
        assert fs.stat(PurePosixPath("psx/Spyro.chd")) is None
        assert [e.name for e in fs.listdir(PurePosixPath("psx"))] == ["Crash Bandicoot.chd"]


def test_upload_creates_the_folders_and_arrives_whole(server, thor, tmp_path: Path):
    """2.5 MB goes across in more than one piece, the folders it needs are
    made on the way, and the size the device reports afterwards matches."""
    local = tmp_path / "Spyro.chd"
    payload = bytes(range(256)) * (10 * 1024)
    local.write_bytes(payload)
    seen: list[int] = []
    target = DeviceTarget(thor.device_id, "AYN Thor", "disk", "ROMs")
    with open_target(target, server) as fs:
        fs.mkdirs(PurePosixPath("psx/Spyro.chd"))
        fs.upload(local, PurePosixPath("psx/Spyro.chd/Spyro.chd"), seen.append)
        assert fs.stat(PurePosixPath("psx/Spyro.chd/Spyro.chd")).size == len(payload)
    node = thor.find("disk", "ROMs", "psx", "Spyro.chd", "Spyro.chd")
    assert node is not None and bytes(node.data) == payload
    assert seen[-1] == 100 and seen == sorted(seen)


def test_sizes_past_4_gb_cross_the_call_intact(server):
    """A Switch dump is often bigger than 4 GB, and the size is declared to
    the device before the bytes are sent. It has to go across as 64 bits; a
    32-bit slip would declare 1 GB for a 5 GB file and the device would
    refuse the rest."""
    from aynthor.core.device import wpd

    five_gb = 5 * GB + 123
    with wpd._values(server) as values:
        wpd._set_u64(values, wpd.WPD_OBJECT_SIZE, five_gb)
        assert wpd._get_u64(values, wpd.WPD_OBJECT_SIZE) == five_gb


def test_the_declared_size_is_what_arrives(server, thor, tmp_path):
    """The fake refuses a commit whose bytes differ from the size declared
    up front, the way a device does."""
    local = tmp_path / "big.nsz"
    local.write_bytes(b"z" * 3000)
    target = DeviceTarget(thor.device_id, "AYN Thor", "disk", "ROMs")
    with open_target(target, server) as fs:
        fs.upload(local, PurePosixPath("switch/big.nsz"))
    assert thor.commits == 1


def test_a_stopped_send_leaves_nothing_on_the_device(server, thor, tmp_path):
    from aynthor.core.device import SendCancelled

    local = tmp_path / "Game.chd"
    local.write_bytes(b"g" * 4096)
    target = DeviceTarget(thor.device_id, "AYN Thor", "disk", "ROMs")
    with open_target(target, server) as fs, pytest.raises(SendCancelled):
        fs.upload(local, PurePosixPath("psx/Game.chd"), cancelled=lambda: True)
    assert thor.find("disk", "ROMs", "psx", "Game.chd") is None
    assert thor.commits == 0


def test_a_file_can_be_removed(server, thor):
    target = DeviceTarget(thor.device_id, "AYN Thor", "disk", "ROMs")
    with open_target(target, server) as fs:
        fs.remove(PurePosixPath("psx/Crash Bandicoot.chd"))
        assert fs.stat(PurePosixPath("psx/Crash Bandicoot.chd")) is None
    assert thor.find("disk", "ROMs", "psx", "Crash Bandicoot.chd") is None


def test_a_missing_device_says_so(server):
    target = DeviceTarget("gone", "AYN Thor", "disk", "ROMs")
    with pytest.raises(DeviceError, match="isn't connected"), open_target(target, server):
        pass


def test_a_new_usb_port_still_finds_the_device_by_name(server, thor):
    """The id Windows gives a device changes with the port it is plugged
    into. The name is the fallback, as long as only one device has it."""
    target = DeviceTarget(r"\\?\usb#old-port", "AYN Thor", "disk", "ROMs")
    with open_target(target, server) as fs:
        assert fs.stat(PurePosixPath("psx")) is not None


def test_two_devices_with_one_name_are_not_guessed_between(server, thor):
    server.add_device(r"\\?\usb#second", "AYN Thor").storage("disk", GB)
    target = DeviceTarget(r"\\?\usb#old-port", "AYN Thor", "disk", "ROMs")
    with pytest.raises(DeviceError, match="isn't connected"), open_target(target, server):
        pass


def test_a_missing_sd_card_is_named(server, thor):
    target = DeviceTarget(thor.device_id, "AYN Thor", "card", "ROMs")
    with pytest.raises(DeviceError, match="no storage called card"), \
            open_target(target, server):
        pass


def test_a_file_where_a_folder_is_needed_is_refused(server, thor, tmp_path):
    local = tmp_path / "x.chd"
    local.write_bytes(b"1")
    target = DeviceTarget(thor.device_id, "AYN Thor", "disk", "ROMs")
    with open_target(target, server) as fs, pytest.raises(DeviceError, match="is a file"):
        fs.upload(local, PurePosixPath("psx/Crash Bandicoot.chd/x.chd"))


def test_storage_root_paths_work(server, thor):
    info = list_devices(server)[0]
    with WpdDevice(server, info) as device:
        sd = device.storages()[0]
        fs = WpdStorage(device, sd)
        assert {e.name for e in fs.listdir(PurePosixPath("."))} == {"ROMs"}
