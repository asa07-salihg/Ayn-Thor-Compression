"""Pick a folder, including a handheld Windows shows under This PC.

Qt's folder dialog asks for filesystem folders only. That flag hides a
device such as the AYN Thor, which File Explorer lists under This PC but
which has no drive letter. The dialog here is the same Windows picker
with that flag turned off, and it accepts the folder that is already open.
"""

from __future__ import annotations

import sys
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_long,
    c_ubyte,
    c_uint16,
    c_uint32,
    c_void_p,
    c_wchar_p,
    cast,
    sizeof,
    wstring_at,
)
from dataclasses import dataclass

# FILEOPENDIALOGOPTIONS. FOS_FORCEFILESYSTEM hides a handheld that has no
# drive letter. FOS_FILEMUSTEXIST makes Select Folder look for a child with
# the open folder's name ("ROMs. The folder name is not valid").
# FOS_PATHMUSTEXIST refuses a folder that has no drive letter, so the ROMs
# folder on the handheld can be seen and still cannot be chosen.
FOS_NOCHANGEDIR = 0x00000008
FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040
FOS_PATHMUSTEXIST = 0x00000800
FOS_FILEMUSTEXIST = 0x00001000

_SIGDN_NORMALDISPLAY = 0
_SIGDN_FILESYSPATH = 0x80058000
_SIGDN_PARSING = 0x80028000
_IID_IUnknown = "{00000000-0000-0000-C000-000000000046}"
_IID_IFileDialogEvents = "{973510DB-7D7F-452B-8975-74A85828D354}"
_E_NOINTERFACE = 0x80004002
_CANCELLED = 0x800704C7
_CLSCTX_INPROC_SERVER = 1
_THIS_PC = "20D04FE0-3AEA-1069-A2D8-08002B30309D"

_CLSID_FileOpenDialog = "{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}"
_IID_IFileOpenDialog = "{D57C7288-D4AD-4768-BE02-9D969532D960}"
_IID_IShellItem = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"

_HRESULT = c_long
_DWORD = c_uint32
_WORD = c_uint16
_BYTE = c_ubyte
_HWND = c_void_p


@dataclass(frozen=True)
class PickedFolder:
    """What the user chose.

    `path` is a normal folder on this PC. `names` is the display path under
    This PC when the folder has no drive letter, for example
    ("AYN Thor", "disk", "ROMs").
    """

    path: str = ""
    names: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.path or self.names)


class _GUID(Structure):
    _fields_ = [
        ("Data1", _DWORD),
        ("Data2", _WORD),
        ("Data3", _WORD),
        ("Data4", _BYTE * 8),
    ]


def folder_options(current: int) -> int:
    """Flags for a folder picker that lists a USB handheld and accepts it.

    `FOS_FORCEFILESYSTEM` is cleared so This PC shows the handheld.
    `FOS_FILEMUSTEXIST` is cleared so Select Folder accepts the open folder
    instead of looking for a child with the same name. `FOS_PATHMUSTEXIST`
    is cleared so a folder with no drive letter, such as ROMs on the
    handheld, can be the result.
    """
    options = current | FOS_PICKFOLDERS | FOS_NOCHANGEDIR
    return options & ~FOS_FORCEFILESYSTEM & ~FOS_FILEMUSTEXIST & ~FOS_PATHMUSTEXIST


def win_pick_folder(hwnd: int, title: str) -> PickedFolder | None:
    """The folder the user chose, or None if they cancelled.

    Raises OSError when the Windows dialog itself cannot be created.
    """
    if sys.platform != "win32":
        raise OSError("Windows folder dialog is only available on Windows")

    from ctypes import windll

    ole32 = windll.ole32
    shell32 = windll.shell32
    dialog = _create_dialog(ole32)
    try:
        _set_options(dialog, folder_options(_get_options(dialog)))
        _set_title(dialog, title)
        _set_folder(shell32, ole32, dialog, "::{" + _THIS_PC + "}")
        events, cookie = _advise(dialog)
        try:
            shown = _show(dialog, hwnd)
        finally:
            _unadvise(dialog, cookie)
            _drop_events(events)
        if shown & 0xFFFFFFFF == _CANCELLED:
            return None
        if shown != 0:
            raise OSError(f"The folder dialog failed ({shown & 0xFFFFFFFF:#x})")
        item = _result(dialog)
        try:
            filesystem = _display_name(item, _SIGDN_FILESYSPATH)
            if filesystem:
                return PickedFolder(path=filesystem)
            return PickedFolder(names=_breadcrumb(item))
        finally:
            _release(item)
    finally:
        _release(dialog)


def _guid(ole32, text: str) -> _GUID:
    value = _GUID()
    if ole32.CLSIDFromString(text, byref(value)) != 0:
        raise OSError(f"Bad COM id {text}")
    return value


def _vtable(unknown):
    return cast(cast(unknown, POINTER(c_void_p))[0], POINTER(c_void_p))


def _create_dialog(ole32):
    ole32.CoInitialize(None)
    ole32.CLSIDFromString.argtypes = [c_wchar_p, POINTER(_GUID)]
    ole32.CLSIDFromString.restype = _HRESULT
    ole32.CoCreateInstance.argtypes = [
        POINTER(_GUID), c_void_p, _DWORD, POINTER(_GUID), POINTER(c_void_p)]
    ole32.CoCreateInstance.restype = _HRESULT
    clsid = _guid(ole32, _CLSID_FileOpenDialog)
    iid = _guid(ole32, _IID_IFileOpenDialog)
    dialog = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(clsid), None, _CLSCTX_INPROC_SERVER, byref(iid), byref(dialog))
    if hr != 0 or not dialog.value:
        raise OSError(f"Could not open the Windows folder dialog ({hr & 0xFFFFFFFF:#x})")
    return dialog


def _get_options(dialog) -> int:
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, POINTER(_DWORD))(_vtable(dialog)[10])
    value = _DWORD()
    if fn(dialog, byref(value)) != 0:
        raise OSError("Could not read the folder dialog options")
    return int(value.value)


def _set_options(dialog, options: int) -> None:
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, _DWORD)(_vtable(dialog)[9])
    if fn(dialog, _DWORD(options)) != 0:
        raise OSError("Could not set the folder dialog options")


def _set_title(dialog, title: str) -> None:
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, c_wchar_p)(_vtable(dialog)[17])
    fn(dialog, title)


def _set_file_name(dialog, name: str) -> None:
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, c_wchar_p)(_vtable(dialog)[15])
    fn(dialog, name)


def _dialog_item(dialog, index: int):
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, POINTER(c_void_p))(_vtable(dialog)[index])
    item = c_void_p()
    if fn(dialog, byref(item)) != 0 or not item.value:
        return None
    return item


def _parent(item):
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, POINTER(c_void_p))(_vtable(item)[4])
    parent = c_void_p()
    if fn(item, byref(parent)) != 0 or not parent.value:
        return None
    return parent


def _display_name(item, kind: int) -> str:
    if not item:
        return ""
    from ctypes import WINFUNCTYPE, windll

    ole32 = windll.ole32
    ole32.CoTaskMemFree.argtypes = [c_void_p]
    ole32.CoTaskMemFree.restype = None
    fn = WINFUNCTYPE(_HRESULT, c_void_p, _DWORD, POINTER(c_void_p))(_vtable(item)[5])
    raw = c_void_p()
    if fn(item, _DWORD(kind), byref(raw)) != 0 or not raw.value:
        return ""
    try:
        return wstring_at(raw.value)
    finally:
        ole32.CoTaskMemFree(raw)


def _breadcrumb(item) -> tuple[str, ...]:
    """Display names from the device down to the chosen folder.

    This PC itself is not included. The first name is the device, then the
    storage, then the folders under it.
    """
    names: list[str] = []
    current = item
    opened: list = []
    for _level in range(16):
        parsing = _display_name(current, _SIGDN_PARSING).upper()
        if _THIS_PC in parsing:
            break
        name = _display_name(current, _SIGDN_NORMALDISPLAY)
        if name:
            names.append(name)
        parent = _parent(current)
        if parent is None:
            break
        opened.append(parent)
        current = parent
    for parent in opened:
        _release(parent)
    names.reverse()
    return tuple(names)


def _clear_name_if_it_names_the_open_folder(dialog) -> None:
    """Select Folder was treating the open folder's name as a child folder.

    Navigating into ROMs left "ROMs" in the box. Select Folder then looked
    for ROMs\\ROMs and said the name was not valid. An empty box means the
    folder that is already open. A different name is a child the user
    clicked, and that one is kept.
    """
    current = _dialog_item(dialog, 13)
    selected = _dialog_item(dialog, 14)
    try:
        current_name = _display_name(current, _SIGDN_NORMALDISPLAY)
        selected_name = _display_name(selected, _SIGDN_NORMALDISPLAY)
    finally:
        _release(current)
        _release(selected)
    if current_name and selected_name and current_name.casefold() == selected_name.casefold():
        _set_file_name(dialog, "")


def _on_ok(_this, dialog) -> int:
    _clear_name_if_it_names_the_open_folder(dialog)
    return 0


def _on_folder_changing(_this, _dialog, _item) -> int:
    return 0


def _on_folder_change(_this, dialog) -> int:
    _set_file_name(dialog, "")
    return 0


def _on_selection_change(_this, dialog) -> int:
    _clear_name_if_it_names_the_open_folder(dialog)
    return 0


def _on_share(_this, _dialog, _item, response) -> int:
    if response:
        cast(response, POINTER(_DWORD))[0] = 0
    return 0


def _on_type(_this, _dialog) -> int:
    return 0


def _on_overwrite(_this, _dialog, _item, response) -> int:
    if response:
        cast(response, POINTER(_DWORD))[0] = 0
    return 0


def _iid_text(riid) -> str:
    guid = cast(riid, POINTER(_GUID)).contents
    data = bytes(guid.Data4)
    tail = data[:2].hex().upper() + "-" + data[2:].hex().upper()
    return f"{{{guid.Data1:08X}-{guid.Data2:04X}-{guid.Data3:04X}-{tail}}}"


def _query_interface(this, riid, out) -> int:
    name = _iid_text(riid)
    if name in (_IID_IUnknown.upper(), _IID_IFileDialogEvents.upper()):
        cast(out, POINTER(c_void_p))[0] = this
        _add_ref(this)
        return 0
    cast(out, POINTER(c_void_p))[0] = None
    return _E_NOINTERFACE


class _EventObject(Structure):
    _fields_ = [("vtbl", POINTER(c_void_p)), ("refs", c_long)]


def _event(this) -> _EventObject:
    return cast(this, POINTER(_EventObject)).contents


def _add_ref(this) -> int:
    obj = _event(this)
    obj.refs += 1
    return int(obj.refs)


def _release_events(this) -> int:
    obj = _event(this)
    obj.refs -= 1
    return int(obj.refs)


# The callbacks and the vtable have to stay alive until Unadvise, or Windows
# calls into freed memory when the user changes folder.
_PINNED: dict[int, tuple] = {}


def _advise(dialog) -> tuple[int, int]:
    from ctypes import WINFUNCTYPE, addressof

    specs = (
        (WINFUNCTYPE(_HRESULT, c_void_p, POINTER(_GUID), POINTER(c_void_p)), _query_interface),
        (WINFUNCTYPE(c_uint32, c_void_p), _add_ref),
        (WINFUNCTYPE(c_uint32, c_void_p), _release_events),
        (WINFUNCTYPE(_HRESULT, c_void_p, c_void_p), _on_ok),
        (WINFUNCTYPE(_HRESULT, c_void_p, c_void_p, c_void_p), _on_folder_changing),
        (WINFUNCTYPE(_HRESULT, c_void_p, c_void_p), _on_folder_change),
        (WINFUNCTYPE(_HRESULT, c_void_p, c_void_p), _on_selection_change),
        (WINFUNCTYPE(_HRESULT, c_void_p, c_void_p, c_void_p, POINTER(_DWORD)), _on_share),
        (WINFUNCTYPE(_HRESULT, c_void_p, c_void_p), _on_type),
        (WINFUNCTYPE(_HRESULT, c_void_p, c_void_p, c_void_p, POINTER(_DWORD)), _on_overwrite),
    )
    table = (c_void_p * len(specs))()
    callbacks = []
    for index, (proto, func) in enumerate(specs):
        callback = proto(func)
        callbacks.append(callback)
        table[index] = cast(callback, c_void_p).value
    obj = _EventObject()
    obj.vtbl = cast(table, POINTER(c_void_p))
    obj.refs = 1
    key = addressof(obj)
    _PINNED[key] = (obj, table, callbacks)
    cookie = _DWORD()
    advise = WINFUNCTYPE(_HRESULT, c_void_p, c_void_p, POINTER(_DWORD))(_vtable(dialog)[7])
    if advise(dialog, c_void_p(key), byref(cookie)) != 0:
        _PINNED.pop(key, None)
        return 0, 0
    return key, int(cookie.value)


def _unadvise(dialog, cookie: int) -> None:
    if not cookie:
        return
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, _DWORD)(_vtable(dialog)[8])
    fn(dialog, _DWORD(cookie))


def _drop_events(key: int) -> None:
    _PINNED.pop(key, None)


def _set_folder(shell32, ole32, dialog, parsing_name: str) -> None:
    from ctypes import WINFUNCTYPE

    shell32.SHCreateItemFromParsingName.argtypes = [
        c_wchar_p, c_void_p, POINTER(_GUID), POINTER(c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = _HRESULT
    iid = _guid(ole32, _IID_IShellItem)
    folder = c_void_p()
    if shell32.SHCreateItemFromParsingName(parsing_name, None, byref(iid), byref(folder)) != 0:
        return
    try:
        fn = WINFUNCTYPE(_HRESULT, c_void_p, c_void_p)(_vtable(dialog)[12])
        fn(dialog, folder)
    finally:
        _release(folder)


def _show(dialog, hwnd: int) -> int:
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, _HWND)(_vtable(dialog)[3])
    return int(fn(dialog, _HWND(hwnd)))


def _result(dialog):
    from ctypes import WINFUNCTYPE

    fn = WINFUNCTYPE(_HRESULT, c_void_p, POINTER(c_void_p))(_vtable(dialog)[20])
    item = c_void_p()
    hr = fn(dialog, byref(item))
    if hr != 0 or not item.value:
        raise OSError(f"The folder dialog returned nothing ({hr & 0xFFFFFFFF:#x})")
    return item


def _release(unknown) -> None:
    if not unknown or not getattr(unknown, "value", None):
        return
    from ctypes import WINFUNCTYPE

    WINFUNCTYPE(c_void_p, c_void_p)(_vtable(unknown)[2])(unknown)


assert sizeof(_GUID) == 16
