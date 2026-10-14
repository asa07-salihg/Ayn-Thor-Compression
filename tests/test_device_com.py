"""The COM layer under the device support: tables, ids and struct layouts.

A COM method is called by its position in the interface's function table, so
one name out of place calls the wrong function with the wrong arguments. The
lists in `fake_wpd` are copied from Microsoft's metadata (win32metadata, as
generated into the `windows` crate, Windows.Win32.Devices.PortableDevices and
Windows.Win32.System.Com), independently of the module under test.
"""

from __future__ import annotations

import ctypes

import pytest

import fake_wpd
from aynthor.core.device import com, wpd

TRUTH = {name: methods for name, methods in fake_wpd.TRUTH.items()}
TRUTH["IPortableDeviceDataStream"] = ("GetObjectID", "Cancel")

IIDS = {
    "IPortableDeviceManager": "{a1567595-4c2f-4574-a6fa-ecef917b9a40}",
    "IPortableDevice": "{625e2df8-6392-4cf0-9ad1-3cfa5f17775c}",
    "IPortableDeviceContent": "{6a96ed84-7c73-4480-9938-bf5af477d426}",
    "IEnumPortableDeviceObjectIDs": "{10ece955-cf41-4728-bfa0-41eedf1bbf19}",
    "IPortableDeviceProperties": "{7f6d695c-03df-4439-a809-59266beee3a6}",
    "IPortableDeviceValues": "{6848f6f2-3155-4f86-b6f5-263eeeab3143}",
    "IPortableDeviceKeyCollection": "{dada2357-e0ad-492e-98db-dd61c53ba353}",
    "IPortableDevicePropVariantCollection": "{89b2e422-4f1b-4316-bcef-a44afea83eb3}",
    "IPortableDeviceDataStream": "{88e04db3-1012-4d64-9996-f703a950d3f4}",
}


@pytest.mark.parametrize("interface", wpd.INTERFACES, ids=lambda i: i.name)
def test_every_method_sits_where_windows_puts_it(interface):
    assert interface.methods == TRUTH[interface.name]
    assert interface.iid.lower() == IIDS[interface.name]


def test_a_data_stream_is_a_stream_first():
    """The device's data stream inherits IStream, which inherits
    ISequentialStream. Write is slot 4 and Commit slot 8 because of that."""
    table = wpd.IPortableDeviceDataStream.table()
    assert table[:3] == ("QueryInterface", "AddRef", "Release")
    assert table.index("Write") == 4
    assert table.index("Commit") == 8
    assert table.index("Revert") == 9
    assert table.index("GetObjectID") == 14


def test_a_guid_has_the_windows_memory_layout():
    """`Data1..Data3` are little-endian and `Data4` is bytes, which is
    `uuid.bytes_le`; the text form must survive the round trip."""
    text = "{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}"
    guid = com.GUID.of(text)
    assert guid.Data1 == 0xEF6B490D
    assert guid.Data2 == 0x5CD8
    assert bytes(guid.Data4) == bytes.fromhex("AFFCDA8B60EE4A3C")
    assert str(guid).upper() == text
    assert ctypes.sizeof(com.GUID) == 16


def test_struct_sizes_match_the_c_definitions():
    assert ctypes.sizeof(com.PROPERTYKEY) == 20
    assert ctypes.sizeof(com.PROPVARIANT) == 8 + 2 * ctypes.sizeof(ctypes.c_void_p)


def test_property_keys_are_the_documented_ones():
    assert (str(wpd.WPD_OBJECT_ORIGINAL_FILE_NAME.fmtid).upper(),
            wpd.WPD_OBJECT_ORIGINAL_FILE_NAME.pid) == (
        "{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 12)
    assert (str(wpd.WPD_STORAGE_FREE_SPACE_IN_BYTES.fmtid).upper(),
            wpd.WPD_STORAGE_FREE_SPACE_IN_BYTES.pid) == (
        "{01A3057A-74D6-4E80-BEA7-DC4C212CE50A}", 5)
    assert wpd.WPD_OBJECT_SIZE.pid == 11
    assert wpd.WPD_STORAGE_DESCRIPTION.pid == 7


def test_the_real_runtime_refuses_to_start_off_windows():
    if com.IS_WINDOWS:
        pytest.skip("this is the Windows path")
    with pytest.raises(OSError):
        com.Ole32()


@pytest.mark.skipif(not com.IS_WINDOWS, reason="needs the real Windows Portable Devices API")
def test_the_real_device_manager_answers_on_windows():
    """Every other test talks to a fake built from the published function
    tables. This one goes through Windows itself, so a wrong slot or a wrong
    GUID shows up on the Windows CI runner and not on someone's handheld. A
    build machine has nothing plugged in, so an empty list is the answer."""
    from aynthor.core.device import com_thread, scan

    class_not_registered = 0x80040154
    with com_thread() as runtime:
        try:
            found = scan(runtime)
        except com.ComError as exc:
            if exc.hresult == class_not_registered:
                pytest.skip("this Windows has no Portable Devices support installed")
            raise
    assert isinstance(found, list)
