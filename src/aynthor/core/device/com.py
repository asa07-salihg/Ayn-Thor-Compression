"""The small part of COM that Windows Portable Devices needs, over ctypes.

A phone or a handheld plugged in over USB shows up in Explorer under This PC
with no drive letter, because Windows talks to it over MTP. Nothing that works
on paths can reach it. Windows Portable Devices (WPD) is the API Explorer uses
for those, and it is COM.

This does not use comtypes. comtypes builds its wrappers from a type library at
run time and writes them to disk, which a one-file exe has nowhere to put, and
its generated signatures get the WPD out-arrays wrong. Calling through the
function table by position is a few lines and has no such surprises.

The method lists below are in table order. They were copied from Microsoft's
own metadata (win32metadata, as generated into the `windows` crate), and
tests/test_device_com.py holds the same lists so a slip shows up as a failure
rather than as a call into the wrong function.
"""

from __future__ import annotations

import ctypes
import sys
import uuid
from collections.abc import Sequence
from ctypes import POINTER, byref, c_int32, c_ubyte, c_uint16, c_uint32, c_void_p
from dataclasses import dataclass
from typing import Any, Protocol

IS_WINDOWS = sys.platform == "win32"

# x64 has one calling convention, so this matters only to 32-bit Windows,
# where COM is stdcall. Elsewhere it lets the tests stand up fake objects.
FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE) if IS_WINDOWS else ctypes.CFUNCTYPE
HRESULT = c_int32

S_OK = 0
S_FALSE = 1
E_NOTIMPL = -2147467263            # 0x80004001
E_FAIL = -2147467259               # 0x80004005
E_INVALIDARG = -2147024809         # 0x80070057
RPC_E_CHANGED_MODE = -2147417850   # 0x80010106
CLSCTX_INPROC_SERVER = 0x1
COINIT_MULTITHREADED = 0x0


class ComError(OSError):
    """A COM call returned a failure HRESULT."""

    def __init__(self, hresult: int, where: str) -> None:
        self.hresult = hresult & 0xFFFFFFFF
        super().__init__(f"{where} failed (0x{self.hresult:08X})")


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", c_uint32),
        ("Data2", c_uint16),
        ("Data3", c_uint16),
        ("Data4", c_ubyte * 8),
    ]

    @classmethod
    def of(cls, text: str) -> GUID:
        value = cls()
        ctypes.memmove(byref(value), uuid.UUID(text).bytes_le, 16)
        return value

    def __str__(self) -> str:
        return "{" + str(uuid.UUID(bytes_le=ctypes.string_at(byref(self), 16))) + "}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GUID) and str(self) == str(other)

    def __hash__(self) -> int:
        return hash(str(self))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_uint32)]

    @classmethod
    def of(cls, fmtid: str, pid: int) -> PROPERTYKEY:
        return cls(GUID.of(fmtid), pid)

    def same(self, other: PROPERTYKEY) -> bool:
        return self.pid == other.pid and self.fmtid == other.fmtid


class PROPVARIANT(ctypes.Structure):
    """Only the string case. The union is sixteen bytes on x64 and the type tag
    plus three reserved words take eight, so the whole thing is twenty-four."""

    _fields_ = [
        ("vt", c_uint16),
        ("reserved1", c_uint16),
        ("reserved2", c_uint16),
        ("reserved3", c_uint16),
        ("pointer", c_void_p),
        ("padding", c_void_p),
    ]


VT_LPWSTR = 31


@dataclass(frozen=True)
class Interface:
    """A COM interface: its IID and its methods in function-table order,
    after the three it inherits from IUnknown."""

    name: str
    iid: str
    methods: tuple[str, ...]
    base: Interface | None = None

    def table(self) -> tuple[str, ...]:
        inherited = self.base.table() if self.base else ("QueryInterface", "AddRef", "Release")
        return inherited + self.methods

    def index(self, method: str) -> int:
        return self.table().index(method)


IUnknown = Interface("IUnknown", "{00000000-0000-0000-C000-000000000046}", ())
ISequentialStream = Interface(
    "ISequentialStream", "{0C733A30-2A1C-11CE-ADE5-00AA0044773D}", ("Read", "Write"))
IStream = Interface(
    "IStream", "{0000000C-0000-0000-C000-000000000046}",
    ("Seek", "SetSize", "CopyTo", "Commit", "Revert", "LockRegion", "UnlockRegion",
     "Stat", "Clone"),
    base=ISequentialStream)


class Runtime(Protocol):
    """Where objects come from and where their memory goes back to. The real
    one is ole32; the tests hand in their own."""

    def create(self, clsid: str, iid: str) -> int: ...
    def free(self, address: int) -> None: ...


_PROTOTYPES: dict[tuple[Any, ...], Any] = {}


def _prototype(argtypes: Sequence[Any]) -> Any:
    key = tuple(argtypes)
    found = _PROTOTYPES.get(key)
    if found is None:
        found = FUNCTYPE(HRESULT, c_void_p, *argtypes)
        _PROTOTYPES[key] = found
    return found


class Com:
    """One owned reference to a COM interface. Released once, on `release` or
    when the `with` block ends."""

    def __init__(self, address: int, interface: Interface, runtime: Runtime) -> None:
        if not address:
            raise ComError(E_FAIL, f"{interface.name} (null pointer)")
        self.address = address
        self.interface = interface
        self.runtime = runtime

    def __enter__(self) -> Com:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def call(self, method: str, argtypes: Sequence[Any], *args: Any) -> int:
        """Call by name, raise on a failure HRESULT, return the HRESULT (so a
        caller can tell S_OK from S_FALSE)."""
        hr = self.raw(method, argtypes, *args)
        if hr < 0:
            raise ComError(hr, f"{self.interface.name}.{method}")
        return hr

    def raw(self, method: str, argtypes: Sequence[Any], *args: Any) -> int:
        if not self.address:
            raise ComError(E_FAIL, f"{self.interface.name}.{method} after release")
        table = ctypes.cast(self.address, POINTER(POINTER(c_void_p)))[0]
        function = _prototype(argtypes)(table[self.interface.index(method)])
        return int(function(self.address, *args))

    def get(self, method: str, interface: Interface, argtypes: Sequence[Any] = (),
            *args: Any) -> Com:
        """Call a method whose last argument receives an interface pointer."""
        out = c_void_p()
        self.call(method, (*argtypes, c_void_p), *args, byref(out))
        return Com(out.value or 0, interface, self.runtime)

    def cast(self, interface: Interface) -> Com:
        """QueryInterface. The result is a separate reference."""
        out = c_void_p()
        iid = GUID.of(interface.iid)
        self.call("QueryInterface", (c_void_p, c_void_p), byref(iid), byref(out))
        return Com(out.value or 0, interface, self.runtime)

    def release(self) -> None:
        if self.address:
            address, self.address = self.address, 0
            table = ctypes.cast(address, POINTER(POINTER(c_void_p)))[0]
            FUNCTYPE(c_uint32, c_void_p)(table[2])(address)

    def take_string(self, address: int | None) -> str:
        """Read a string the callee allocated with CoTaskMemAlloc, then free it."""
        if not address:
            return ""
        try:
            return ctypes.wstring_at(address)
        finally:
            self.runtime.free(address)


def create(runtime: Runtime, clsid: str, interface: Interface) -> Com:
    return Com(runtime.create(clsid, interface.iid), interface, runtime)


class Ole32:
    """The real runtime. Windows only; constructing it elsewhere raises."""

    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise OSError("Portable devices are a Windows feature.")
        ole32 = ctypes.WinDLL("ole32")  # type: ignore[attr-defined]
        self._create_instance = ole32.CoCreateInstance
        self._create_instance.argtypes = [c_void_p, c_void_p, c_uint32, c_void_p, c_void_p]
        self._create_instance.restype = HRESULT
        self._free = ole32.CoTaskMemFree
        self._free.argtypes = [c_void_p]
        self._free.restype = None
        self._initialize = ole32.CoInitializeEx
        self._initialize.argtypes = [c_void_p, c_uint32]
        self._initialize.restype = HRESULT
        self._uninitialize = ole32.CoUninitialize
        self._uninitialize.argtypes = []
        self._uninitialize.restype = None
        self._initialized = False

    def initialize(self) -> None:
        """Join the thread to the multithreaded apartment. A thread already in
        one (Qt puts its main thread in a single-threaded one) can still make
        these calls, so "changed mode" is not a failure."""
        hr = self._initialize(None, COINIT_MULTITHREADED)
        if hr in (S_OK, S_FALSE):
            self._initialized = True
        elif hr != RPC_E_CHANGED_MODE:
            raise ComError(hr, "CoInitializeEx")

    def uninitialize(self) -> None:
        if self._initialized:
            self._initialized = False
            self._uninitialize()

    def create(self, clsid: str, iid: str) -> int:
        out = c_void_p()
        hr = self._create_instance(
            byref(GUID.of(clsid)), None, CLSCTX_INPROC_SERVER, byref(GUID.of(iid)), byref(out))
        if hr < 0:
            raise ComError(hr, f"CoCreateInstance {clsid}")
        return out.value or 0

    def free(self, address: int) -> None:
        self._free(address)
