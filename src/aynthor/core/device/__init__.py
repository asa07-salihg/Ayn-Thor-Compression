"""Handhelds and phones on USB: find them, and send games to them.

Windows only. Everything else in the app works on paths, and an MTP device has
none; see `core.device.wpd` for how it is reached instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from aynthor.core.device.com import IS_WINDOWS, ComError, Runtime
from aynthor.core.device.fs import (
    BREADCRUMB,
    DeviceError,
    DeviceFS,
    DeviceTarget,
    Entry,
    MemoryFS,
    SendCancelled,
    key,
)

__all__ = [
    "BREADCRUMB", "DeviceError", "DeviceFS", "DeviceTarget", "Entry", "FoundDevice", "FoundStorage",
    "MemoryFS", "SendCancelled", "available", "com_thread", "open_target", "scan",
]

# The folder ES-DE looks in, at the top of a storage.
ROMS_FOLDER = "ROMs"


def available() -> bool:
    return IS_WINDOWS


@contextmanager
def com_thread() -> Iterator[Runtime]:
    """COM for the calling thread, for as long as the block runs."""
    from aynthor.core.device.com import Ole32

    runtime = Ole32()
    runtime.initialize()
    try:
        yield runtime
    finally:
        runtime.uninitialize()


@dataclass(frozen=True)
class FoundStorage:
    name: str
    capacity: int
    free: int
    roms: str | None      # the ROMs folder at its top level, as it is spelled there


@dataclass(frozen=True)
class FoundDevice:
    device_id: str
    name: str
    storages: tuple[FoundStorage, ...] = field(default=())
    problem: str = ""     # why it could not be opened, when it could not

    def target(self, storage: FoundStorage, root: str | None = None) -> DeviceTarget:
        return DeviceTarget(self.device_id, self.name, storage.name,
                            root or storage.roms or ROMS_FOLDER)


def scan(runtime: Runtime) -> list[FoundDevice]:
    """Every device Windows can see, its storages, and whether each already
    has a ROMs folder. A device that cannot be opened is listed with the
    reason, because "unlock it" is the most common fix and the user needs to
    see it."""
    from aynthor.core.device.wpd import WpdDevice, WpdStorage, list_devices

    found: list[FoundDevice] = []
    for info in list_devices(runtime):
        try:
            with WpdDevice(runtime, info) as device:
                storages: list[FoundStorage] = []
                for storage in device.storages():
                    top = WpdStorage(device, storage)
                    roms = next((e.name for e in top.listdir(PurePosixPath("."))
                                 if e.is_dir and key(e.name) == key(ROMS_FOLDER)), None)
                    storages.append(FoundStorage(storage.name, storage.capacity,
                                                 storage.free, roms))
        except (DeviceError, ComError) as exc:
            found.append(FoundDevice(info.device_id, info.name, (), str(exc)))
            continue
        found.append(FoundDevice(info.device_id, info.name, tuple(storages)))
    return found


def not_connected(target: DeviceTarget) -> DeviceError:
    return DeviceError(
        f"{target.device_name} isn't connected. Plug it in with a USB cable, unlock it, "
        "and choose File transfer in the USB notification on the device.")


@contextmanager
def open_target(target: DeviceTarget, runtime: Runtime) -> Iterator[DeviceFS]:
    """The folder the user picked on the device, ready to send to."""
    from aynthor.core.device.wpd import (
        WpdDevice,
        WpdStorage,
        list_devices,
        pick_device,
        pick_storage,
    )

    try:
        info = pick_device(list_devices(runtime), target)
    except ComError as exc:
        raise DeviceError(f"Windows could not list USB devices ({exc}).") from exc
    if info is None:
        raise not_connected(target)
    with WpdDevice(runtime, info) as device:
        storage = pick_storage(device.storages(), target.storage)
        if storage is None:
            raise DeviceError(
                f"{target.device_name} has no storage called {target.storage}. "
                "If that is the SD card, check it is in.")
        yield WpdStorage(device, storage, PurePosixPath(target.root))
