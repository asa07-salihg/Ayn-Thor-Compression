"""Pick a folder, including a handheld Windows shows under This PC.

Why
    Qt's folder dialog asks Windows for filesystem folders only. That flag
    hides a device such as the AYN Thor, which File Explorer lists under
    This PC but which has no drive letter. The dialog here is the same
    Windows picker with that flag turned off.

Used by
    `ui.folder_dialog`.
"""

from __future__ import annotations

import sys
from ctypes import (
    HRESULT,
    POINTER,
    WINFUNCTYPE,
    Structure,
    byref,
    c_void_p,
    c_wchar_p,
    cast,
    sizeof,
    windll,
    wstring_at,
)
from ctypes.wintypes import BYTE, DWORD, HWND, WORD

# FILEOPENDIALOGOPTIONS. FOS_FORCEFILESYSTEM is the one that hides the device.
FOS_NOCHANGEDIR = 0x00000008
FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040
FOS_PATHMUSTEXIST = 0x00000800

_SIGDN_FILESYSPATH = 0x80058000
_CANCELLED = 0x800704C7
_CLSCTX_INPROC_SERVER = 1

_CLSID_FileOpenDialog = "{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}"
_IID_IFileOpenDialog = "{D57C7288-D4AD-4768-BE02-9D969532D960}"
_IID_IShellItem = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
# This PC. The dialog opens here, where Explorer puts the handheld.
_THIS_PC = "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}"


class _GUID(Structure):
    _fields_ = [
        ("Data1", DWORD),
        ("Data2", WORD),
        ("Data3", WORD),
        ("Data4", BYTE * 8),
    ]


def folder_options(current: int) -> int:
    """Flags for a folder picker that still lists connected devices.

    `FOS_FORCEFILESYSTEM` is cleared even if Windows turned it on. With it
    set, This PC shows drives only and a handheld connected over USB is gone.
    """
    options = current | FOS_PICKFOLDERS | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR
    return options & ~FOS_FORCEFILESYSTEM


def win_pick_folder(hwnd: int, title: str) -> str | None:
    """A normal folder path, '' if the choice is not one, None if cancelled.

    Raises OSError when the Windows dialog itself cannot be created.
    """
    if sys.platform != "win32":
        raise OSError("Windows folder dialog is only available on Windows")

    ole32 = windll.ole32
    shell32 = windll.shell32
    dialog = _create_dialog(ole32)
    try:
        _set_options(dialog, folder_options(_get_options(dialog)))
        _set_title(dialog, title)
        _set_folder(shell32, ole32, dialog, _THIS_PC)
        shown = _show(dialog, hwnd)
        if shown & 0xFFFFFFFF == _CANCELLED:
            return None
        if shown != 0:
            raise OSError(f"The folder dialog failed ({shown & 0xFFFFFFFF:#x})")
        item = _result(dialog)
        try:
            return _filesystem_path(ole32, item)
        finally:
            _release(item)
    finally:
        _release(dialog)


def _guid(ole32, text: str) -> _GUID:
    value = _GUID()
    if ole32.CLSIDFromString(text, byref(value)) != 0:
        raise OSError(f"Bad COM id {text}")
    return value


def _vtable(unknown: c_void_p):
    return cast(cast(unknown, POINTER(c_void_p))[0], POINTER(c_void_p))


def _create_dialog(ole32):
    ole32.CoInitialize(None)
    ole32.CLSIDFromString.argtypes = [c_wchar_p, POINTER(_GUID)]
    ole32.CLSIDFromString.restype = HRESULT
    ole32.CoCreateInstance.argtypes = [
        POINTER(_GUID), c_void_p, DWORD, POINTER(_GUID), POINTER(c_void_p)]
    ole32.CoCreateInstance.restype = HRESULT
    clsid = _guid(ole32, _CLSID_FileOpenDialog)
    iid = _guid(ole32, _IID_IFileOpenDialog)
    dialog = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(clsid), None, _CLSCTX_INPROC_SERVER, byref(iid), byref(dialog))
    if hr != 0 or not dialog.value:
        raise OSError(f"Could not open the Windows folder dialog ({hr & 0xFFFFFFFF:#x})")
    return dialog


def _get_options(dialog) -> int:
    fn = WINFUNCTYPE(HRESULT, c_void_p, POINTER(DWORD))(_vtable(dialog)[10])
    value = DWORD()
    if fn(dialog, byref(value)) != 0:
        raise OSError("Could not read the folder dialog options")
    return int(value.value)


def _set_options(dialog, options: int) -> None:
    fn = WINFUNCTYPE(HRESULT, c_void_p, DWORD)(_vtable(dialog)[9])
    if fn(dialog, DWORD(options)) != 0:
        raise OSError("Could not set the folder dialog options")


def _set_title(dialog, title: str) -> None:
    fn = WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p)(_vtable(dialog)[17])
    fn(dialog, title)


def _set_folder(shell32, ole32, dialog, parsing_name: str) -> None:
    shell32.SHCreateItemFromParsingName.argtypes = [
        c_wchar_p, c_void_p, POINTER(_GUID), POINTER(c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = HRESULT
    iid = _guid(ole32, _IID_IShellItem)
    folder = c_void_p()
    if shell32.SHCreateItemFromParsingName(parsing_name, None, byref(iid), byref(folder)) != 0:
        return
    try:
        fn = WINFUNCTYPE(HRESULT, c_void_p, c_void_p)(_vtable(dialog)[12])
        fn(dialog, folder)
    finally:
        _release(folder)


def _show(dialog, hwnd: int) -> int:
    fn = WINFUNCTYPE(HRESULT, c_void_p, HWND)(_vtable(dialog)[3])
    return int(fn(dialog, HWND(hwnd)))


def _result(dialog):
    fn = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))(_vtable(dialog)[20])
    item = c_void_p()
    hr = fn(dialog, byref(item))
    if hr != 0 or not item.value:
        raise OSError(f"The folder dialog returned nothing ({hr & 0xFFFFFFFF:#x})")
    return item


def _filesystem_path(ole32, item) -> str:
    ole32.CoTaskMemFree.argtypes = [c_void_p]
    ole32.CoTaskMemFree.restype = None
    fn = WINFUNCTYPE(HRESULT, c_void_p, DWORD, POINTER(c_void_p))(_vtable(item)[5])
    raw = c_void_p()
    hr = fn(item, DWORD(_SIGDN_FILESYSPATH), byref(raw))
    if hr != 0 or not raw.value:
        return ""
    try:
        return wstring_at(raw.value)
    finally:
        ole32.CoTaskMemFree(raw)


def _release(unknown) -> None:
    if not unknown or not unknown.value:
        return
    WINFUNCTYPE(c_void_p, c_void_p)(_vtable(unknown)[2])(unknown)


# Keep the GUID layout honest if ctypes packing ever changes.
assert sizeof(_GUID) == 16
