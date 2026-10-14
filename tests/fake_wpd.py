"""A pretend Windows Portable Devices stack, for testing `core.device.wpd`.

The objects here are real C function tables built with ctypes, so the client
calls them exactly as it calls Windows: through the table, by position, with
the same pointer and string conventions. What is checked that a mock could not
check: every argument crosses a real C call, every string the "device" hands
out has to be freed by the client, and every object has to be released.
"""

from __future__ import annotations

import ctypes
import itertools
from ctypes import POINTER, c_uint32, c_uint64, c_void_p, c_wchar_p
from dataclasses import dataclass, field

from aynthor.core.device import com, wpd
from aynthor.core.device.com import FUNCTYPE, GUID, HRESULT, PROPERTYKEY, PROPVARIANT

E_NOTIMPL = com.E_NOTIMPL
E_FAIL = com.E_FAIL
E_NOT_FOUND = -2147023728          # HRESULT_FROM_WIN32(ERROR_NOT_FOUND)
E_ACCESSDENIED = -2147024891       # 0x80070005


# Function tables, copied from Microsoft's metadata (win32metadata, as generated
# into the `windows` crate) and NOT from the module under test: the fake has to
# disagree with the client whenever the client has a method in the wrong slot.
IUNKNOWN = ("QueryInterface", "AddRef", "Release")
ISTREAM = ("Read", "Write", "Seek", "SetSize", "CopyTo", "Commit", "Revert",
           "LockRegion", "UnlockRegion", "Stat", "Clone")
TRUTH = {
    "IPortableDeviceManager": (
        "GetDevices", "RefreshDeviceList", "GetDeviceFriendlyName", "GetDeviceDescription",
        "GetDeviceManufacturer", "GetDeviceProperty", "GetPrivateDevices"),
    "IPortableDevice": (
        "Open", "SendCommand", "Content", "Capabilities", "Cancel", "Close", "Advise",
        "Unadvise", "GetPnPDeviceID"),
    "IPortableDeviceContent": (
        "EnumObjects", "Properties", "Transfer", "CreateObjectWithPropertiesOnly",
        "CreateObjectWithPropertiesAndData", "Delete", "GetObjectIDsFromPersistentUniqueIDs",
        "Cancel", "Move", "Copy"),
    "IEnumPortableDeviceObjectIDs": ("Next", "Skip", "Reset", "Clone", "Cancel"),
    "IPortableDeviceProperties": (
        "GetSupportedProperties", "GetPropertyAttributes", "GetValues", "SetValues", "Delete",
        "Cancel"),
    "IPortableDeviceValues": (
        "GetCount", "GetAt", "SetValue", "GetValue", "SetStringValue", "GetStringValue",
        "SetUnsignedIntegerValue", "GetUnsignedIntegerValue", "SetSignedIntegerValue",
        "GetSignedIntegerValue", "SetUnsignedLargeIntegerValue",
        "GetUnsignedLargeIntegerValue", "SetSignedLargeIntegerValue",
        "GetSignedLargeIntegerValue", "SetFloatValue", "GetFloatValue", "SetErrorValue",
        "GetErrorValue", "SetKeyValue", "GetKeyValue", "SetBoolValue", "GetBoolValue",
        "SetIUnknownValue", "GetIUnknownValue", "SetGuidValue", "GetGuidValue",
        "SetBufferValue", "GetBufferValue", "SetIPortableDeviceValuesValue",
        "GetIPortableDeviceValuesValue", "SetIPortableDevicePropVariantCollectionValue",
        "GetIPortableDevicePropVariantCollectionValue",
        "SetIPortableDeviceKeyCollectionValue", "GetIPortableDeviceKeyCollectionValue",
        "SetIPortableDeviceValuesCollectionValue", "GetIPortableDeviceValuesCollectionValue",
        "RemoveValue", "CopyValuesFromPropertyStore", "CopyValuesToPropertyStore", "Clear"),
    "IPortableDeviceKeyCollection": ("GetCount", "GetAt", "Add", "Clear", "RemoveAt"),
    "IPortableDevicePropVariantCollection": (
        "GetCount", "GetAt", "Add", "GetType", "ChangeType", "Clear", "RemoveAt"),
    "IPortableDeviceDataStream": (*ISTREAM, "GetObjectID", "Cancel"),
}


def table(name: str) -> tuple[str, ...]:
    return IUNKNOWN + TRUTH[name]


def _key(address: int) -> tuple[str, int]:
    prop = PROPERTYKEY.from_address(address)
    return str(prop.fmtid).upper(), int(prop.pid)


def _k(prop: PROPERTYKEY) -> tuple[str, int]:
    return str(prop.fmtid).upper(), int(prop.pid)


# Callee-side signatures. `this` comes first everywhere.
P = c_void_p
SIGNATURES: dict[str, tuple] = {
    "QueryInterface": (HRESULT, P, P, P),
    "AddRef": (c_uint32, P),
    "Release": (c_uint32, P),
    # manager
    "GetDevices": (HRESULT, P, P, P),
    "RefreshDeviceList": (HRESULT, P),
    "GetDeviceFriendlyName": (HRESULT, P, c_wchar_p, P, P),
    "GetDeviceDescription": (HRESULT, P, c_wchar_p, P, P),
    # values
    "SetStringValue": (HRESULT, P, P, c_wchar_p),
    "GetStringValue": (HRESULT, P, P, P),
    "SetUnsignedIntegerValue": (HRESULT, P, P, c_uint32),
    "SetUnsignedLargeIntegerValue": (HRESULT, P, P, c_uint64),
    "GetUnsignedLargeIntegerValue": (HRESULT, P, P, P),
    "SetGuidValue": (HRESULT, P, P, P),
    "GetGuidValue": (HRESULT, P, P, P),
    # collections
    "Add": (HRESULT, P, P),
    # device
    "Open": (HRESULT, P, c_wchar_p, P),
    "Content": (HRESULT, P, P),
    "Close": (HRESULT, P),
    # content
    "EnumObjects": (HRESULT, P, c_uint32, c_wchar_p, P, P),
    "Properties": (HRESULT, P, P),
    "CreateObjectWithPropertiesOnly": (HRESULT, P, P, P),
    "CreateObjectWithPropertiesAndData": (HRESULT, P, P, P, P, P),
    "Delete": (HRESULT, P, c_uint32, P, P),
    # enumerator
    "Next": (HRESULT, P, c_uint32, P, P),
    # properties
    "GetValues": (HRESULT, P, c_wchar_p, P, P),
    # stream
    "Write": (HRESULT, P, P, c_uint32, P),
    "Commit": (HRESULT, P, c_uint32),
    "Revert": (HRESULT, P),
    "GetObjectID": (HRESULT, P, P),
}


class _Obj(ctypes.Structure):
    _fields_ = [("vtbl", POINTER(c_void_p))]


class FakeCom:
    """One fake COM object. `methods` maps a method name to a Python
    function taking the same arguments as the C call minus `this`."""

    def __init__(self, server: Server, interface: str, methods: dict) -> None:
        self.server = server
        self.name = interface
        self.refs = 1
        self._callbacks = []
        slots = []
        handlers = {"AddRef": self._addref, "Release": self._release,
                    "QueryInterface": lambda riid, out: E_NOTIMPL, **methods}
        for name in table(interface):
            handler = handlers.get(name)
            signature = SIGNATURES.get(name, (HRESULT, P))
            if handler is None:
                def handler(*_args, _name=name):
                    server.errors.append(f"called {interface}.{_name}, which the fake "
                                         "does not expect: is a method in the wrong slot?")
                    return E_NOTIMPL
                signature = (HRESULT, P)            # never called with more in these tests
            callback = FUNCTYPE(*signature)(self._wrap(handler))
            self._callbacks.append(callback)
            slots.append(ctypes.cast(callback, c_void_p).value)
        self._table = (c_void_p * len(slots))(*slots)
        self._obj = _Obj(ctypes.cast(self._table, POINTER(c_void_p)))
        self.address = ctypes.addressof(self._obj)
        server.objects[self.address] = self

    def _wrap(self, handler):
        def call(_this, *args):
            try:
                return handler(*args)
            except Exception as exc:  # noqa: BLE001 - surfaced through server.errors
                self.server.errors.append(f"{self.name}: {type(exc).__name__}: {exc}")
                return E_FAIL
        return call

    def _addref(self) -> int:
        self.refs += 1
        return self.refs

    def _release(self) -> int:
        self.refs -= 1
        if self.refs < 0:
            self.server.errors.append(f"{self.name} released too often")
        return max(self.refs, 0)


@dataclass
class Node:
    object_id: str
    parent: str
    name: str
    kind: GUID
    data: bytearray = field(default_factory=bytearray)
    category: GUID | None = None
    capacity: int = 0


class Server:
    """The fake: its devices, its allocator, and what went wrong."""

    def __init__(self) -> None:
        self.objects: dict[int, FakeCom] = {}
        self.strings: dict[int, ctypes.Array] = {}
        self.errors: list[str] = []
        self.unimplemented: list[str] = []
        self.devices: dict[str, Device] = {}
        self._ids = itertools.count(1)

    # -- runtime interface used by the client
    def create(self, clsid: str, iid: str) -> int:
        clsid = clsid.upper()
        if clsid == wpd.CLSID_PortableDeviceManager:
            return self._manager().address
        if clsid == wpd.CLSID_PortableDeviceFTM:
            return self._device().address
        if clsid == wpd.CLSID_PortableDeviceValues:
            return self.values({}).address
        if clsid == wpd.CLSID_PortableDeviceKeyCollection:
            return self._keys().address
        if clsid == wpd.CLSID_PortableDevicePropVariantCollection:
            return self._variants().address
        raise AssertionError(f"unexpected class {clsid}")

    def free(self, address: int) -> None:
        if self.strings.pop(address, None) is None:
            self.errors.append(f"freed memory that was never handed out: {address:#x}")

    # -- helpers
    def string(self, text: str) -> int:
        buffer = ctypes.create_unicode_buffer(text)
        address = ctypes.addressof(buffer)
        self.strings[address] = buffer
        return address

    def put_pointer(self, out: int, address: int) -> None:
        ctypes.c_void_p.from_address(out).value = address

    def live(self) -> list[str]:
        return [o.name for o in self.objects.values() if o.refs > 0]

    def add_device(self, device_id: str, name: str) -> Device:
        device = Device(self, device_id, name)
        self.devices[device_id] = device
        return device

    # -- the classes
    def _manager(self) -> FakeCom:
        def get_devices(ids, count):
            listed = list(self.devices)
            pcount = c_uint32.from_address(count)
            if not ids:
                pcount.value = len(listed)
                return 0
            for index, device_id in enumerate(listed[: pcount.value]):
                c_void_p.from_address(ids + index * ctypes.sizeof(c_void_p)).value = \
                    self.string(device_id)
            pcount.value = min(pcount.value, len(listed))
            return 0

        def friendly(device_id, buffer, length):
            name = self.devices[device_id].name
            plen = c_uint32.from_address(length)
            if not buffer:
                plen.value = len(name) + 1
                return 0
            ctypes.memmove(buffer, ctypes.create_unicode_buffer(name),
                           (len(name) + 1) * ctypes.sizeof(ctypes.c_wchar))
            return 0

        return FakeCom(self, "IPortableDeviceManager", {
            "GetDevices": get_devices,
            "RefreshDeviceList": lambda: 0,
            "GetDeviceFriendlyName": friendly,
        })

    def values(self, store: dict) -> FakeCom:
        def set_string(prop, text):
            store[_key(prop)] = ("s", text)
            return 0

        def get_string(prop, out):
            found = store.get(_key(prop))
            if not found or found[0] != "s":
                return E_NOT_FOUND
            self.put_pointer(out, self.string(found[1]))
            return 0

        def set_u32(prop, value):
            store[_key(prop)] = ("u", int(value))
            return 0

        def set_u64(prop, value):
            store[_key(prop)] = ("u", int(value))
            return 0

        def get_u64(prop, out):
            found = store.get(_key(prop))
            if not found or found[0] != "u":
                return E_NOT_FOUND
            c_uint64.from_address(out).value = found[1]
            return 0

        def set_guid(prop, value):
            store[_key(prop)] = ("g", str(GUID.from_address(value)).upper())
            return 0

        def get_guid(prop, out):
            found = store.get(_key(prop))
            if not found or found[0] != "g":
                return E_NOT_FOUND
            ctypes.memmove(out, ctypes.byref(GUID.of(found[1])), ctypes.sizeof(GUID))
            return 0

        fake = FakeCom(self, "IPortableDeviceValues", {
            "SetStringValue": set_string, "GetStringValue": get_string,
            "SetUnsignedIntegerValue": set_u32, "SetUnsignedLargeIntegerValue": set_u64,
            "GetUnsignedLargeIntegerValue": get_u64,
            "SetGuidValue": set_guid, "GetGuidValue": get_guid,
        })
        fake.store = store
        return fake

    def _keys(self) -> FakeCom:
        keys: list[tuple[str, int]] = []
        fake = FakeCom(self, "IPortableDeviceKeyCollection", {
            "Add": lambda prop: keys.append(_key(prop)) or 0,
        })
        fake.keys = keys
        return fake

    def _variants(self) -> FakeCom:
        items: list[str] = []

        def add(variant):
            pv = PROPVARIANT.from_address(variant)
            if pv.vt != com.VT_LPWSTR:
                return E_FAIL
            items.append(ctypes.wstring_at(pv.pointer))   # copied, as the real one does
            return 0

        fake = FakeCom(self, "IPortableDevicePropVariantCollection", {"Add": add})
        fake.items = items
        return fake

    def _device(self) -> FakeCom:
        state: dict = {"device": None}

        def open_(device_id, client):
            device = self.devices.get(device_id)
            if device is None:
                return E_FAIL
            if device.locked:
                return E_ACCESSDENIED
            name = self.objects[client].store.get(_k(wpd.WPD_CLIENT_NAME))
            if name is None:
                self.errors.append("Open without a client name")
            state["device"] = device
            return 0

        def content(out):
            self.put_pointer(out, state["device"].content().address)
            return 0

        return FakeCom(self, "IPortableDevice", {
            "Open": open_, "Content": content, "Close": lambda: 0,
        })


class Device:
    """One fake device: a tree of objects under "DEVICE"."""

    def __init__(self, server: Server, device_id: str, name: str) -> None:
        self.server = server
        self.device_id = device_id
        self.name = name
        self.locked = False
        self.nodes: dict[str, Node] = {
            "DEVICE": Node("DEVICE", "", name, wpd.WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT)}
        self._ids = itertools.count(100)
        self.commits = 0

    # -- building the tree
    def storage(self, name: str, capacity: int) -> Node:
        node = Node(f"s{next(self._ids)}", "DEVICE", name,
                    wpd.WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT,
                    category=wpd.WPD_FUNCTIONAL_CATEGORY_STORAGE, capacity=capacity)
        self.nodes[node.object_id] = node
        return node

    def folder(self, parent: Node, name: str) -> Node:
        node = Node(f"o{next(self._ids)}", parent.object_id, name, wpd.WPD_CONTENT_TYPE_FOLDER)
        self.nodes[node.object_id] = node
        return node

    def file(self, parent: Node, name: str, data: bytes) -> Node:
        node = Node(f"o{next(self._ids)}", parent.object_id, name,
                    wpd.WPD_CONTENT_TYPE_GENERIC_FILE, bytearray(data))
        self.nodes[node.object_id] = node
        return node

    def find(self, *names: str) -> Node | None:
        node = self.nodes["DEVICE"]
        for name in names:
            node = next((n for n in self.nodes.values()
                         if n.parent == node.object_id and n.name == name), None)
            if node is None:
                return None
        return node

    def used(self, storage: Node) -> int:
        def under(object_id: str) -> int:
            total = 0
            for n in self.nodes.values():
                if n.parent == object_id:
                    total += len(n.data) + under(n.object_id)
            return total
        return under(storage.object_id)

    def storage_of(self, node: Node) -> Node:
        while node.parent != "DEVICE":
            node = self.nodes[node.parent]
        return node

    # -- the COM side
    def content(self) -> FakeCom:
        server = self.server

        def enum_objects(_flags, parent, _filter, out):
            children = [n.object_id for n in self.nodes.values() if n.parent == parent]
            server.put_pointer(out, self._enum(children).address)
            return 0

        def properties(out):
            server.put_pointer(out, self._properties().address)
            return 0

        def create_only(values, out_id):
            store = server.objects[values].store
            parent = store[_k(wpd.WPD_OBJECT_PARENT_ID)][1]
            name = store[_k(wpd.WPD_OBJECT_ORIGINAL_FILE_NAME)][1]
            kind = store[_k(wpd.WPD_OBJECT_CONTENT_TYPE)][1]
            if kind != str(wpd.WPD_CONTENT_TYPE_FOLDER).upper():
                return E_FAIL
            node = self.folder(self.nodes[parent], name)
            server.put_pointer(out_id, server.string(node.object_id))
            return 0

        def create_with_data(values, out_stream, optimal, cookie):
            store = dict(server.objects[values].store)
            server.put_pointer(out_stream, self._stream(store).address)
            c_uint32.from_address(optimal).value = 256 * 1024
            server.put_pointer(cookie, server.string("cookie"))
            return 0

        def delete(_options, ids, _results):
            for object_id in server.objects[ids].items:
                if object_id not in self.nodes:
                    return E_NOT_FOUND
                del self.nodes[object_id]
            return 0

        return FakeCom(server, "IPortableDeviceContent", {
            "EnumObjects": enum_objects, "Properties": properties,
            "CreateObjectWithPropertiesOnly": create_only,
            "CreateObjectWithPropertiesAndData": create_with_data,
            "Delete": delete,
        })

    def _enum(self, ids: list[str]) -> FakeCom:
        server = self.server
        remaining = list(ids)

        def next_(count, array, fetched):
            batch, remaining[:] = remaining[:count], remaining[count:]
            for index, object_id in enumerate(batch):
                c_void_p.from_address(array + index * ctypes.sizeof(c_void_p)).value = \
                    server.string(object_id)
            c_uint32.from_address(fetched).value = len(batch)
            return 0 if len(batch) == count else com.S_FALSE

        return FakeCom(server, "IEnumPortableDeviceObjectIDs", {"Next": next_})

    def _properties(self) -> FakeCom:
        server = self.server

        def get_values(object_id, keys, out):
            node = self.nodes.get(object_id)
            if node is None:
                return E_NOT_FOUND
            wanted = set(server.objects[keys].keys)
            store: dict = {}

            def put(prop, value):
                if _k(prop) in wanted:
                    store[_k(prop)] = value

            put(wpd.WPD_OBJECT_NAME, ("s", node.name))
            if node.kind != wpd.WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT:
                put(wpd.WPD_OBJECT_ORIGINAL_FILE_NAME, ("s", node.name))
            put(wpd.WPD_OBJECT_CONTENT_TYPE, ("g", str(node.kind).upper()))
            if node.kind == wpd.WPD_CONTENT_TYPE_GENERIC_FILE:
                put(wpd.WPD_OBJECT_SIZE, ("u", len(node.data)))
            if node.category is not None:
                put(wpd.WPD_FUNCTIONAL_OBJECT_CATEGORY, ("g", str(node.category).upper()))
                put(wpd.WPD_STORAGE_DESCRIPTION, ("s", node.name))
                put(wpd.WPD_STORAGE_CAPACITY, ("u", node.capacity))
                put(wpd.WPD_STORAGE_FREE_SPACE_IN_BYTES,
                    ("u", node.capacity - self.used(node)))
            server.put_pointer(out, server.values(store).address)
            return 0

        return FakeCom(server, "IPortableDeviceProperties", {"GetValues": get_values})

    def _stream(self, store: dict) -> FakeCom:
        server = self.server
        data = bytearray()
        state = {"id": ""}

        def write(buffer, count, written):
            data.extend(ctypes.string_at(buffer, count))
            c_uint32.from_address(written).value = count
            return 0

        def commit(_flags):
            declared = store[_k(wpd.WPD_OBJECT_SIZE)][1]
            if declared != len(data):
                return E_FAIL
            parent = self.nodes[store[_k(wpd.WPD_OBJECT_PARENT_ID)][1]]
            storage = self.storage_of(parent)
            if self.used(storage) + len(data) > storage.capacity:
                return E_FAIL
            node = self.file(parent, store[_k(wpd.WPD_OBJECT_ORIGINAL_FILE_NAME)][1], data)
            state["id"] = node.object_id
            self.commits += 1
            return 0

        def object_id(out):
            server.put_pointer(out, server.string(state["id"]))
            return 0

        return FakeCom(server, "IPortableDeviceDataStream", {
            "Write": write, "Commit": commit, "Revert": lambda: 0, "GetObjectID": object_id,
        })
