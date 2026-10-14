"""Windows Portable Devices: find a handheld on USB and copy files onto it.

This is what Explorer does when you drag a file onto "AYN Thor" under This
PC. The handheld speaks MTP, Windows wraps that in WPD, and WPD is COM, so the
calls below go through `core.device.com`.

A file is written in one stream that the device only keeps once it is
committed. A transfer that fails or is stopped part way leaves nothing behind
on the device, which is the property the delivery step relies on.

https://learn.microsoft.com/windows/win32/wpd_sdk/
Interface and property ids: win32metadata, Windows.Win32.Devices.PortableDevices
"""

from __future__ import annotations

import ctypes
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from ctypes import byref, c_uint32, c_uint64, c_void_p, c_wchar_p
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from aynthor.core.device.com import (
    GUID,
    PROPERTYKEY,
    PROPVARIANT,
    S_FALSE,
    VT_LPWSTR,
    Com,
    ComError,
    Interface,
    IStream,
    Runtime,
    create,
)
from aynthor.core.device.fs import (
    Cancelled,
    DeviceError,
    DeviceTarget,
    Entry,
    Progress,
    SendCancelled,
    key,
)

# --------------------------------------------------------------- interfaces

IPortableDeviceManager = Interface(
    "IPortableDeviceManager", "{A1567595-4C2F-4574-A6FA-ECEF917B9A40}",
    ("GetDevices", "RefreshDeviceList", "GetDeviceFriendlyName", "GetDeviceDescription",
     "GetDeviceManufacturer", "GetDeviceProperty", "GetPrivateDevices"))
IPortableDevice = Interface(
    "IPortableDevice", "{625E2DF8-6392-4CF0-9AD1-3CFA5F17775C}",
    ("Open", "SendCommand", "Content", "Capabilities", "Cancel", "Close", "Advise",
     "Unadvise", "GetPnPDeviceID"))
IPortableDeviceContent = Interface(
    "IPortableDeviceContent", "{6A96ED84-7C73-4480-9938-BF5AF477D426}",
    ("EnumObjects", "Properties", "Transfer", "CreateObjectWithPropertiesOnly",
     "CreateObjectWithPropertiesAndData", "Delete", "GetObjectIDsFromPersistentUniqueIDs",
     "Cancel", "Move", "Copy"))
IEnumPortableDeviceObjectIDs = Interface(
    "IEnumPortableDeviceObjectIDs", "{10ECE955-CF41-4728-BFA0-41EEDF1BBF19}",
    ("Next", "Skip", "Reset", "Clone", "Cancel"))
IPortableDeviceProperties = Interface(
    "IPortableDeviceProperties", "{7F6D695C-03DF-4439-A809-59266BEEE3A6}",
    ("GetSupportedProperties", "GetPropertyAttributes", "GetValues", "SetValues", "Delete",
     "Cancel"))
IPortableDeviceValues = Interface(
    "IPortableDeviceValues", "{6848F6F2-3155-4F86-B6F5-263EEEAB3143}",
    ("GetCount", "GetAt", "SetValue", "GetValue", "SetStringValue", "GetStringValue",
     "SetUnsignedIntegerValue", "GetUnsignedIntegerValue", "SetSignedIntegerValue",
     "GetSignedIntegerValue", "SetUnsignedLargeIntegerValue", "GetUnsignedLargeIntegerValue",
     "SetSignedLargeIntegerValue", "GetSignedLargeIntegerValue", "SetFloatValue",
     "GetFloatValue", "SetErrorValue", "GetErrorValue", "SetKeyValue", "GetKeyValue",
     "SetBoolValue", "GetBoolValue", "SetIUnknownValue", "GetIUnknownValue", "SetGuidValue",
     "GetGuidValue", "SetBufferValue", "GetBufferValue", "SetIPortableDeviceValuesValue",
     "GetIPortableDeviceValuesValue", "SetIPortableDevicePropVariantCollectionValue",
     "GetIPortableDevicePropVariantCollectionValue", "SetIPortableDeviceKeyCollectionValue",
     "GetIPortableDeviceKeyCollectionValue", "SetIPortableDeviceValuesCollectionValue",
     "GetIPortableDeviceValuesCollectionValue", "RemoveValue", "CopyValuesFromPropertyStore",
     "CopyValuesToPropertyStore", "Clear"))
IPortableDeviceKeyCollection = Interface(
    "IPortableDeviceKeyCollection", "{DADA2357-E0AD-492E-98DB-DD61C53BA353}",
    ("GetCount", "GetAt", "Add", "Clear", "RemoveAt"))
IPortableDevicePropVariantCollection = Interface(
    "IPortableDevicePropVariantCollection", "{89B2E422-4F1B-4316-BCEF-A44AFEA83EB3}",
    ("GetCount", "GetAt", "Add", "GetType", "ChangeType", "Clear", "RemoveAt"))
IPortableDeviceDataStream = Interface(
    "IPortableDeviceDataStream", "{88E04DB3-1012-4D64-9996-F703A950D3F4}",
    ("GetObjectID", "Cancel"), base=IStream)

INTERFACES = (
    IPortableDeviceManager, IPortableDevice, IPortableDeviceContent,
    IEnumPortableDeviceObjectIDs, IPortableDeviceProperties, IPortableDeviceValues,
    IPortableDeviceKeyCollection, IPortableDevicePropVariantCollection,
    IPortableDeviceDataStream,
)

CLSID_PortableDeviceManager = "{0AF10CEC-2ECD-4B92-9581-34F6AE0637F3}"
# The free-threaded variant: the runner opens the device on its own thread.
CLSID_PortableDeviceFTM = "{F7C0039A-4762-488A-B4B3-760EF9A1BA9B}"
CLSID_PortableDeviceValues = "{0C15D503-D017-47CE-9016-7B3F978721CC}"
CLSID_PortableDeviceKeyCollection = "{DE2D022D-2480-43BE-97F0-D1FA2CF98F4F}"
CLSID_PortableDevicePropVariantCollection = "{08A99E2F-6D6D-4B80-AF5A-BAF2BCBE4CB9}"

# ------------------------------------------------------------- property keys

_OBJECT = "{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}"
_STORAGE = "{01A3057A-74D6-4E80-BEA7-DC4C212CE50A}"
_FUNCTIONAL = "{8F052D93-ABCA-4FC5-A5AC-B01DF4DBE598}"
_CLIENT = "{204D9F0C-2292-4080-9F42-40664E70F859}"

WPD_OBJECT_PARENT_ID = PROPERTYKEY.of(_OBJECT, 3)
WPD_OBJECT_NAME = PROPERTYKEY.of(_OBJECT, 4)
WPD_OBJECT_FORMAT = PROPERTYKEY.of(_OBJECT, 6)
WPD_OBJECT_CONTENT_TYPE = PROPERTYKEY.of(_OBJECT, 7)
WPD_OBJECT_SIZE = PROPERTYKEY.of(_OBJECT, 11)
WPD_OBJECT_ORIGINAL_FILE_NAME = PROPERTYKEY.of(_OBJECT, 12)
WPD_STORAGE_CAPACITY = PROPERTYKEY.of(_STORAGE, 4)
WPD_STORAGE_FREE_SPACE_IN_BYTES = PROPERTYKEY.of(_STORAGE, 5)
WPD_STORAGE_DESCRIPTION = PROPERTYKEY.of(_STORAGE, 7)
WPD_FUNCTIONAL_OBJECT_CATEGORY = PROPERTYKEY.of(_FUNCTIONAL, 2)
WPD_CLIENT_NAME = PROPERTYKEY.of(_CLIENT, 2)
WPD_CLIENT_MAJOR_VERSION = PROPERTYKEY.of(_CLIENT, 3)
WPD_CLIENT_MINOR_VERSION = PROPERTYKEY.of(_CLIENT, 4)
WPD_CLIENT_REVISION = PROPERTYKEY.of(_CLIENT, 5)
WPD_CLIENT_SECURITY_QUALITY_OF_SERVICE = PROPERTYKEY.of(_CLIENT, 8)

WPD_CONTENT_TYPE_FOLDER = GUID.of("{27E2E392-A111-48E0-AB0C-E17705A05F85}")
WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT = GUID.of("{99ED0160-17FF-4C44-9D98-1D7A6F941921}")
WPD_CONTENT_TYPE_GENERIC_FILE = GUID.of("{0085E0A6-8D34-45D7-BC5C-447E59C73D48}")
WPD_OBJECT_FORMAT_UNSPECIFIED = GUID.of("{30000000-AE6C-4804-98BA-C57B46965FE7}")
WPD_OBJECT_FORMAT_PROPERTIES_ONLY = GUID.of("{30010000-AE6C-4804-98BA-C57B46965FE7}")
WPD_FUNCTIONAL_CATEGORY_STORAGE = GUID.of("{23F05BBC-15DE-4C2A-A55B-A9AF5CE412EF}")

WPD_DEVICE_OBJECT_ID = "DEVICE"
PORTABLE_DEVICE_DELETE_NO_RECURSION = 0
SECURITY_IMPERSONATION = 2 << 16
STGC_DEFAULT = 0

E_ACCESSDENIED = 0x80070005
# A transfer is handed over in pieces at least this large. Devices report a
# preferred size, usually 256 KB, and a bigger piece costs nothing.
_MIN_CHUNK = 1024 * 1024

CLIENT_NAME = "Ayn Thor Compression"


@dataclass(frozen=True)
class StorageInfo:
    object_id: str
    name: str
    capacity: int
    free: int


@dataclass(frozen=True)
class DeviceInfo:
    device_id: str
    name: str


# ------------------------------------------------------------------ helpers


def _values(runtime: Runtime) -> Com:
    return create(runtime, CLSID_PortableDeviceValues, IPortableDeviceValues)


def _set_string(values: Com, prop: PROPERTYKEY, text: str) -> None:
    values.call("SetStringValue", (c_void_p, c_wchar_p), byref(prop), text)


def _set_guid(values: Com, prop: PROPERTYKEY, value: GUID) -> None:
    values.call("SetGuidValue", (c_void_p, c_void_p), byref(prop), byref(value))


def _set_u32(values: Com, prop: PROPERTYKEY, value: int) -> None:
    values.call("SetUnsignedIntegerValue", (c_void_p, c_uint32), byref(prop), value)


def _set_u64(values: Com, prop: PROPERTYKEY, value: int) -> None:
    values.call("SetUnsignedLargeIntegerValue", (c_void_p, c_uint64), byref(prop), value)


def _get_string(values: Com, prop: PROPERTYKEY) -> str | None:
    out = c_void_p()
    if values.raw("GetStringValue", (c_void_p, c_void_p), byref(prop), byref(out)) < 0:
        return None
    return values.take_string(out.value)


def _get_u64(values: Com, prop: PROPERTYKEY) -> int | None:
    out = c_uint64()
    if values.raw("GetUnsignedLargeIntegerValue", (c_void_p, c_void_p),
                  byref(prop), byref(out)) < 0:
        return None
    return int(out.value)


def _get_guid(values: Com, prop: PROPERTYKEY) -> GUID | None:
    out = GUID()
    if values.raw("GetGuidValue", (c_void_p, c_void_p), byref(prop), byref(out)) < 0:
        return None
    return out


def _explain(error: ComError, device: str) -> DeviceError:
    if error.hresult == E_ACCESSDENIED:
        return DeviceError(
            f"Windows can't open {device}. Unlock it and choose File transfer "
            "in the USB notification on the device.")
    return DeviceError(f"{device} stopped responding ({error}).")


# ----------------------------------------------------------------- discovery


def list_devices(runtime: Runtime) -> list[DeviceInfo]:
    """Every portable device Windows can see right now, by name."""
    found: list[DeviceInfo] = []
    with create(runtime, CLSID_PortableDeviceManager, IPortableDeviceManager) as manager:
        manager.call("RefreshDeviceList", ())
        count = c_uint32(0)
        manager.call("GetDevices", (c_void_p, c_void_p), None, byref(count))
        if count.value == 0:
            return found
        ids = (c_void_p * count.value)()
        manager.call("GetDevices", (c_void_p, c_void_p), ids, byref(count))
        device_ids = [manager.take_string(ids[i]) for i in range(count.value)]
        for device_id in device_ids:
            found.append(DeviceInfo(device_id, _friendly_name(manager, device_id)))
    return found


def _friendly_name(manager: Com, device_id: str) -> str:
    for method in ("GetDeviceFriendlyName", "GetDeviceDescription"):
        length = c_uint32(0)
        argtypes = (c_wchar_p, c_void_p, c_void_p)
        if manager.raw(method, argtypes, device_id, None, byref(length)) < 0 or not length.value:
            continue
        buffer = ctypes.create_unicode_buffer(length.value + 1)
        if manager.raw(method, argtypes, device_id, buffer, byref(length)) >= 0 and buffer.value:
            return buffer.value
    return device_id


class WpdDevice:
    """One device, opened. Use as a context manager so it is always closed."""

    def __init__(self, runtime: Runtime, info: DeviceInfo) -> None:
        self.runtime = runtime
        self.info = info
        self._device: Com | None = None
        self._content: Com | None = None
        self._properties: Com | None = None

    def __enter__(self) -> WpdDevice:
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def open(self) -> None:
        client = _values(self.runtime)
        try:
            _set_string(client, WPD_CLIENT_NAME, CLIENT_NAME)
            _set_u32(client, WPD_CLIENT_MAJOR_VERSION, 1)
            _set_u32(client, WPD_CLIENT_MINOR_VERSION, 0)
            _set_u32(client, WPD_CLIENT_REVISION, 0)
            _set_u32(client, WPD_CLIENT_SECURITY_QUALITY_OF_SERVICE, SECURITY_IMPERSONATION)
            device = create(self.runtime, CLSID_PortableDeviceFTM, IPortableDevice)
            try:
                device.call("Open", (c_wchar_p, c_void_p), self.info.device_id, client.address)
            except ComError as exc:
                device.release()
                raise _explain(exc, self.info.name) from exc
        finally:
            client.release()
        self._device = device
        self._content = device.get("Content", IPortableDeviceContent)
        self._properties = self._content.get("Properties", IPortableDeviceProperties)

    def close(self) -> None:
        for com in (self._properties, self._content):
            if com is not None:
                com.release()
        self._properties = self._content = None
        if self._device is not None:
            with suppress(ComError):
                self._device.call("Close", ())
            self._device.release()
            self._device = None

    @property
    def content(self) -> Com:
        if self._content is None:
            raise DeviceError(f"{self.info.name} is not open.")
        return self._content

    # ------------------------------------------------------------ reading

    def children(self, parent_id: str) -> list[str]:
        ids: list[str] = []
        try:
            enum = self.content.get(
                "EnumObjects", IEnumPortableDeviceObjectIDs, (c_uint32, c_wchar_p, c_void_p),
                0, parent_id, None)
        except ComError as exc:
            raise _explain(exc, self.info.name) from exc
        with enum:
            while True:
                batch = (c_void_p * 64)()
                fetched = c_uint32(0)
                hr = enum.call("Next", (c_uint32, c_void_p, c_void_p), 64, batch, byref(fetched))
                ids.extend(enum.take_string(batch[i]) for i in range(fetched.value))
                if hr == S_FALSE or fetched.value == 0:
                    break
        return ids

    @contextmanager
    def _read(self, object_id: str, *props: PROPERTYKEY) -> Iterator[Com]:
        assert self._properties is not None
        with create(self.runtime, CLSID_PortableDeviceKeyCollection,
                    IPortableDeviceKeyCollection) as keys:
            for prop in props:
                keys.call("Add", (c_void_p,), byref(prop))
            try:
                values = self._properties.get(
                    "GetValues", IPortableDeviceValues, (c_wchar_p, c_void_p),
                    object_id, keys.address)
            except ComError as exc:
                raise _explain(exc, self.info.name) from exc
        with values:
            yield values

    def entry(self, object_id: str) -> tuple[Entry, GUID | None]:
        """Name, kind and size of one object, and its content type."""
        with self._read(object_id, WPD_OBJECT_ORIGINAL_FILE_NAME, WPD_OBJECT_NAME,
                        WPD_OBJECT_CONTENT_TYPE, WPD_OBJECT_SIZE) as values:
            name = (_get_string(values, WPD_OBJECT_ORIGINAL_FILE_NAME)
                    or _get_string(values, WPD_OBJECT_NAME) or object_id)
            kind = _get_guid(values, WPD_OBJECT_CONTENT_TYPE)
            size = _get_u64(values, WPD_OBJECT_SIZE) or 0
        is_dir = kind is not None and kind in (WPD_CONTENT_TYPE_FOLDER,
                                               WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT)
        return Entry(name, is_dir, 0 if is_dir else size), kind

    def storages(self) -> list[StorageInfo]:
        """The places files can go: on a handheld, the SD card and the internal
        storage, each with the name Explorer shows."""
        found: list[StorageInfo] = []
        for object_id in self.children(WPD_DEVICE_OBJECT_ID):
            with self._read(object_id, WPD_OBJECT_CONTENT_TYPE, WPD_FUNCTIONAL_OBJECT_CATEGORY,
                            WPD_STORAGE_DESCRIPTION, WPD_OBJECT_NAME, WPD_STORAGE_CAPACITY,
                            WPD_STORAGE_FREE_SPACE_IN_BYTES) as values:
                if _get_guid(values, WPD_OBJECT_CONTENT_TYPE) != WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT:
                    continue
                if _get_guid(values, WPD_FUNCTIONAL_OBJECT_CATEGORY) != \
                        WPD_FUNCTIONAL_CATEGORY_STORAGE:
                    continue
                name = (_get_string(values, WPD_STORAGE_DESCRIPTION)
                        or _get_string(values, WPD_OBJECT_NAME) or object_id)
                found.append(StorageInfo(
                    object_id, name,
                    _get_u64(values, WPD_STORAGE_CAPACITY) or 0,
                    _get_u64(values, WPD_STORAGE_FREE_SPACE_IN_BYTES) or 0))
        return found

    def free_space(self, storage_id: str) -> int:
        with self._read(storage_id, WPD_STORAGE_FREE_SPACE_IN_BYTES) as values:
            free = _get_u64(values, WPD_STORAGE_FREE_SPACE_IN_BYTES)
        if free is None:
            raise DeviceError(f"{self.info.name} did not say how much room is left.")
        return free

    # ------------------------------------------------------------ writing

    def make_folder(self, parent_id: str, name: str) -> str:
        with _values(self.runtime) as values:
            _set_string(values, WPD_OBJECT_PARENT_ID, parent_id)
            _set_string(values, WPD_OBJECT_NAME, name)
            _set_string(values, WPD_OBJECT_ORIGINAL_FILE_NAME, name)
            _set_guid(values, WPD_OBJECT_CONTENT_TYPE, WPD_CONTENT_TYPE_FOLDER)
            _set_guid(values, WPD_OBJECT_FORMAT, WPD_OBJECT_FORMAT_PROPERTIES_ONLY)
            out = c_void_p()
            try:
                self.content.call("CreateObjectWithPropertiesOnly", (c_void_p, c_void_p),
                                  values.address, byref(out))
            except ComError as exc:
                raise DeviceError(
                    f"{self.info.name} would not create the folder {name} ({exc}).") from exc
            return self.content.take_string(out.value)

    def upload(self, parent_id: str, name: str, local: Path,
               on_progress: Progress | None = None,
               cancelled: Cancelled | None = None) -> str:
        """Copy `local` into the folder `parent_id` as `name`. Nothing is kept
        on the device unless the whole file arrives."""
        size = local.stat().st_size
        with _values(self.runtime) as values:
            _set_string(values, WPD_OBJECT_PARENT_ID, parent_id)
            _set_string(values, WPD_OBJECT_NAME, name)
            _set_string(values, WPD_OBJECT_ORIGINAL_FILE_NAME, name)
            _set_u64(values, WPD_OBJECT_SIZE, size)
            _set_guid(values, WPD_OBJECT_CONTENT_TYPE, WPD_CONTENT_TYPE_GENERIC_FILE)
            _set_guid(values, WPD_OBJECT_FORMAT, WPD_OBJECT_FORMAT_UNSPECIFIED)
            stream_out = c_void_p()
            optimal = c_uint32(0)
            cookie = c_void_p()
            try:
                self.content.call(
                    "CreateObjectWithPropertiesAndData", (c_void_p, c_void_p, c_void_p, c_void_p),
                    values.address, byref(stream_out), byref(optimal), byref(cookie))
            except ComError as exc:
                raise DeviceError(f"{self.info.name} would not accept {name} ({exc}).") from exc
            self.content.take_string(cookie.value)
        stream = Com(stream_out.value or 0, IPortableDeviceDataStream, self.runtime)
        committed = False
        try:
            chunk = max(int(optimal.value), _MIN_CHUNK)
            buffer = ctypes.create_string_buffer(chunk)
            sent = 0
            last = -1
            with local.open("rb") as handle:
                while True:
                    if cancelled is not None and cancelled():
                        raise SendCancelled(f"Stopped while sending {name}.")
                    read = handle.readinto(buffer)
                    if not read:
                        break
                    written = c_uint32(0)
                    try:
                        stream.call("Write", (c_void_p, c_uint32, c_void_p),
                                    buffer, read, byref(written))
                    except ComError as exc:
                        raise _explain(exc, self.info.name) from exc
                    if written.value != read:
                        raise DeviceError(f"{self.info.name} took only part of {name}.")
                    sent += read
                    if on_progress is not None and size:
                        percent = min(99, sent * 100 // size)
                        if percent != last:
                            last = percent
                            on_progress(percent)
            if sent != size:
                raise DeviceError(f"{name} changed size while it was being sent.")
            try:
                stream.call("Commit", (c_uint32,), STGC_DEFAULT)
            except ComError as exc:
                raise _explain(exc, self.info.name) from exc
            committed = True
            out = c_void_p()
            object_id = ""
            if stream.raw("GetObjectID", (c_void_p,), byref(out)) >= 0:
                object_id = stream.take_string(out.value)
            if on_progress is not None:
                on_progress(100)
            return object_id
        finally:
            if not committed:
                with suppress(ComError):
                    stream.raw("Revert", ())
            stream.release()

    def delete(self, object_id: str) -> None:
        with create(self.runtime, CLSID_PortableDevicePropVariantCollection,
                    IPortableDevicePropVariantCollection) as ids:
            text = ctypes.create_unicode_buffer(object_id)
            variant = PROPVARIANT()
            variant.vt = VT_LPWSTR
            variant.pointer = ctypes.addressof(text)
            ids.call("Add", (c_void_p,), byref(variant))   # the collection copies it
            try:
                self.content.call("Delete", (c_uint32, c_void_p, c_void_p),
                                  PORTABLE_DEVICE_DELETE_NO_RECURSION, ids.address, None)
            except ComError as exc:
                raise DeviceError(f"{self.info.name} would not remove the file ({exc}).") from exc


# ----------------------------------------------------- one storage, by path


class WpdStorage:
    """A `DeviceFS` over one storage of an open device, rooted at a folder in it.

    WPD addresses everything by object id, so each path is walked one folder at
    a time and what was seen is remembered for the session. Listing a folder
    with a few hundred games costs a round trip per game, and a batch touches
    the same few platform folders over and over.
    """

    def __init__(self, device: WpdDevice, storage: StorageInfo,
                 root: PurePosixPath | None = None) -> None:
        self.device = device
        self.storage = storage
        self.root = root if root is not None else PurePosixPath(".")
        self._listings: dict[str, dict[str, tuple[str, Entry]]] = {}

    @property
    def label(self) -> str:
        return self.device.info.name

    def _listing(self, folder_id: str) -> dict[str, tuple[str, Entry]]:
        found = self._listings.get(folder_id)
        if found is None:
            found = {}
            for object_id in self.device.children(folder_id):
                entry, _kind = self.device.entry(object_id)
                found[key(entry.name)] = (object_id, entry)
            self._listings[folder_id] = found
        return found

    def _parts(self, path: PurePosixPath) -> list[str]:
        full = self.root / path
        return [part for part in full.parts if part not in ("/", ".", "")]

    def _locate(self, parts: list[str]) -> tuple[str, Entry] | None:
        folder_id = self.storage.object_id
        entry = Entry(self.storage.name, True)
        for part in parts:
            if not entry.is_dir:
                return None
            hit = self._listing(folder_id).get(key(part))
            if hit is None:
                return None
            folder_id, entry = hit
        return folder_id, entry

    def free_space(self) -> int:
        return self.device.free_space(self.storage.object_id)

    def stat(self, path: PurePosixPath) -> Entry | None:
        hit = self._locate(self._parts(path))
        return hit[1] if hit else None

    def listdir(self, path: PurePosixPath) -> list[Entry]:
        hit = self._locate(self._parts(path))
        if hit is None or not hit[1].is_dir:
            raise DeviceError(f"{path} is not a folder on {self.label}.")
        return [entry for _id, entry in self._listing(hit[0]).values()]

    def mkdirs(self, path: PurePosixPath) -> None:
        self._folder_id(self._parts(path), create_missing=True)

    def _folder_id(self, parts: list[str], *, create_missing: bool) -> str:
        folder_id = self.storage.object_id
        for part in parts:
            listing = self._listing(folder_id)
            hit = listing.get(key(part))
            if hit is None:
                if not create_missing:
                    raise DeviceError(f"{part} is not on {self.label}.")
                new_id = self.device.make_folder(folder_id, part)
                listing[key(part)] = (new_id, Entry(part, True))
                self._listings[new_id] = {}
                folder_id = new_id
                continue
            object_id, entry = hit
            if not entry.is_dir:
                raise DeviceError(f"{part} is a file on {self.label}, not a folder.")
            folder_id = object_id
        return folder_id

    def upload(self, local: Path, path: PurePosixPath,
               on_progress: Progress | None = None,
               cancelled: Cancelled | None = None) -> None:
        parts = self._parts(path)
        folder_id = self._folder_id(parts[:-1], create_missing=True)
        name = parts[-1]
        object_id = self.device.upload(folder_id, name, local, on_progress, cancelled)
        size = local.stat().st_size
        self._listing(folder_id)[key(name)] = (object_id, Entry(name, False, size))

    def remove(self, path: PurePosixPath) -> None:
        parts = self._parts(path)
        folder_id = self._folder_id(parts[:-1], create_missing=False)
        listing = self._listing(folder_id)
        hit = listing.get(key(parts[-1]))
        if hit is None:
            raise DeviceError(f"{path} is not on {self.label}.")
        self.device.delete(hit[0])
        del listing[key(parts[-1])]

    def refresh(self) -> None:
        """Forget what was listed; the device may have changed since."""
        self._listings.clear()


def pick_device(devices: list[DeviceInfo], target: DeviceTarget) -> DeviceInfo | None:
    """The device this target means: the same id, or failing that the only
    device with the same name. Two devices with one name is ambiguous, and
    sending to the wrong one is worse than asking."""
    for info in devices:
        if info.device_id == target.device_id:
            return info
    named = [info for info in devices if info.name == target.device_name]
    return named[0] if len(named) == 1 else None


def pick_storage(storages: list[StorageInfo], name: str) -> StorageInfo | None:
    for storage in storages:
        if key(storage.name) == key(name):
            return storage
    return None
