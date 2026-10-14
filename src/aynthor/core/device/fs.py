"""What the app needs from a device it sends games to, and where on it they go.

The converters only work on real files, so a game bound for a device is
converted on this PC first and then sent. Sending needs very little: is this
path there, how big is it, make these folders, copy this file in, remove that
one, how much room is left. `DeviceFS` is exactly that, with paths relative to
the storage the user chose ("disk" on an Ayn Thor is the SD card).

`MemoryFS` is the same contract held in a dict. The delivery rules are tested
against it, so they do not need a device or Windows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

# The arrow between the parts of a location, as Explorer's address bar shows it.
BREADCRUMB = "\u203a"

Progress = Callable[[int], None]
Cancelled = Callable[[], bool]


class DeviceError(OSError):
    """The device refused, vanished, or ran out of room. The message is meant
    for the user as it stands."""


class SendCancelled(DeviceError):
    """Stop was pressed while a file was on its way."""


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool
    size: int = 0


@dataclass(frozen=True)
class DeviceTarget:
    """Where on which device games go, as the user picked it.

    The id is what Windows calls the device this time it was plugged in, and
    it can change with the USB port, so the name is kept as well and used when
    the id is not found.
    """

    device_id: str
    device_name: str
    storage: str           # the storage's description, "disk" or "Internal shared storage"
    root: str = "ROMs"     # folder inside that storage, "/"-separated

    @property
    def label(self) -> str:
        """How the target reads in the window: AYN Thor > disk > ROMs, with the
        breadcrumb arrow Explorer uses."""
        parts = [self.device_name, self.storage, *PurePosixPath(self.root).parts]
        return f" {BREADCRUMB} ".join(part for part in parts if part and part != "/")

    def to_dict(self) -> dict[str, str]:
        return {"device_id": self.device_id, "device_name": self.device_name,
                "storage": self.storage, "root": self.root}

    @classmethod
    def from_dict(cls, data: object) -> DeviceTarget | None:
        if not isinstance(data, dict):
            return None
        try:
            target = cls(str(data["device_id"]), str(data["device_name"]),
                         str(data["storage"]), str(data.get("root", "ROMs")))
        except KeyError:
            return None
        if not target.device_name or not target.storage:
            return None
        return target


class DeviceFS(Protocol):
    """Paths are relative to the storage the user chose, `/`-separated."""

    @property
    def label(self) -> str: ...

    def free_space(self) -> int: ...
    def stat(self, path: PurePosixPath) -> Entry | None: ...
    def listdir(self, path: PurePosixPath) -> list[Entry]: ...
    def mkdirs(self, path: PurePosixPath) -> None: ...
    def upload(self, local: Path, path: PurePosixPath,
               on_progress: Progress | None = None,
               cancelled: Cancelled | None = None) -> None: ...
    def remove(self, path: PurePosixPath) -> None: ...


def key(name: str) -> str:
    """Android shares are case-insensitive, like Windows: `ROMs` and `roms`
    are the same folder."""
    return name.casefold()


@dataclass
class _Node:
    name: str
    is_dir: bool
    data: bytes = b""
    children: dict[str, _Node] = field(default_factory=dict)


class MemoryFS:
    """A device held in memory. `capacity` caps what fits."""

    def __init__(self, label: str = "Test device", capacity: int = 1 << 40) -> None:
        self._label = label
        self.capacity = capacity
        self.root = _Node("", True)
        self.uploads: list[PurePosixPath] = []
        self.fail_after: int | None = None   # bytes, to simulate a cable pulled mid-copy

    @property
    def label(self) -> str:
        return self._label

    def _walk(self, path: PurePosixPath) -> _Node | None:
        node = self.root
        for part in path.parts:
            if part in ("/", "."):
                continue
            if not node.is_dir:
                return None
            child = node.children.get(key(part))
            if child is None:
                return None
            node = child
        return node

    def _used(self, node: _Node | None = None) -> int:
        node = node or self.root
        if not node.is_dir:
            return len(node.data)
        return sum(self._used(child) for child in node.children.values())

    def free_space(self) -> int:
        return max(0, self.capacity - self._used())

    def stat(self, path: PurePosixPath) -> Entry | None:
        node = self._walk(path)
        if node is None:
            return None
        return Entry(node.name, node.is_dir, 0 if node.is_dir else len(node.data))

    def listdir(self, path: PurePosixPath) -> list[Entry]:
        node = self._walk(path)
        if node is None or not node.is_dir:
            raise DeviceError(f"{path} is not a folder on {self.label}.")
        return [Entry(c.name, c.is_dir, 0 if c.is_dir else len(c.data))
                for c in node.children.values()]

    def mkdirs(self, path: PurePosixPath) -> None:
        node = self.root
        for part in path.parts:
            if part in ("/", "."):
                continue
            child = node.children.get(key(part))
            if child is None:
                child = _Node(part, True)
                node.children[key(part)] = child
            elif not child.is_dir:
                raise DeviceError(f"{part} is a file on {self.label}, not a folder.")
            node = child

    def write(self, path: PurePosixPath, data: bytes) -> None:
        """Put a file in place directly, for setting up a test."""
        self.mkdirs(path.parent)
        parent = self._walk(path.parent)
        assert parent is not None
        parent.children[key(path.name)] = _Node(path.name, False, data)

    def read(self, path: PurePosixPath) -> bytes:
        node = self._walk(path)
        if node is None or node.is_dir:
            raise DeviceError(f"{path} is not a file on {self.label}.")
        return node.data

    def upload(self, local: Path, path: PurePosixPath,
               on_progress: Progress | None = None,
               cancelled: Cancelled | None = None) -> None:
        parent = self._walk(path.parent)
        if parent is None or not parent.is_dir:
            raise DeviceError(f"{path.parent} is not a folder on {self.label}.")
        if key(path.name) in parent.children:
            raise DeviceError(f"{path.name} is already on {self.label}.")
        data = local.read_bytes()
        if len(data) > self.free_space():
            raise DeviceError(f"{self.label} is full.")
        if cancelled is not None and cancelled():
            raise SendCancelled("Stopped before the file was sent.")
        if self.fail_after is not None and len(data) > self.fail_after:
            # Nothing is committed, the same as a real device that loses the
            # connection before the end of the stream.
            raise DeviceError(f"{self.label} stopped responding.")
        if on_progress is not None:
            on_progress(50)
            on_progress(100)
        parent.children[key(path.name)] = _Node(path.name, False, data)
        self.uploads.append(path)

    def remove(self, path: PurePosixPath) -> None:
        parent = self._walk(path.parent)
        if parent is None or key(path.name) not in parent.children:
            raise DeviceError(f"{path} is not on {self.label}.")
        del parent.children[key(path.name)]
