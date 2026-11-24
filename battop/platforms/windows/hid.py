"""Minimal HID access through hid.dll / SetupAPI (no third-party packages)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from .power import GUID

_hid = ctypes.WinDLL("hid", use_last_error=True)
_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_DIGCF_PRESENT = 0x2
_DIGCF_DEVICEINTERFACE = 0x10
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_HIDP_STATUS_SUCCESS = 0x110000


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_size_t),
    ]


class _HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class _HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


_hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
_hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_HIDD_ATTRIBUTES)]
_hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(_HIDP_CAPS)]
_hid.HidP_GetCaps.restype = wintypes.LONG
_hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_char_p, wintypes.ULONG]
_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
]
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True)
class HidInterface:
    path: str
    vendor_id: int
    product_id: int
    usage_page: int
    usage: int
    feature_report_length: int
    output_report_length: int


def _interface_paths() -> list[str]:
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = _setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE)
    if info in (None, _INVALID_HANDLE):
        raise ctypes.WinError(ctypes.get_last_error())
    paths = []
    try:
        index = 0
        while True:
            data = _SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not _setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(guid), index, ctypes.byref(data)):
                break
            index += 1
            needed = wintypes.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(data), None, 0, ctypes.byref(needed), None)
            buffer = ctypes.create_string_buffer(needed.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize is 8 on 64-bit Windows and 6 on 32-bit.
            ctypes.c_uint32.from_buffer(buffer).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(
                info, ctypes.byref(data), buffer, needed.value, None, None
            ):
                paths.append(ctypes.wstring_at(ctypes.addressof(buffer) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info)
    return paths


class HidDevice:
    """An open HID interface that can send feature reports."""

    def __init__(self, handle):
        self._handle = handle

    @classmethod
    def open(cls, path: str) -> HidDevice:
        handle = _kernel32.CreateFileW(
            path, _GENERIC_READ | _GENERIC_WRITE, _FILE_SHARE_READ | _FILE_SHARE_WRITE, None, _OPEN_EXISTING, 0, None
        )
        if handle in (None, _INVALID_HANDLE):
            raise ctypes.WinError(ctypes.get_last_error())
        return cls(handle)

    def close(self) -> None:
        if self._handle is not None:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def set_feature(self, report: bytes) -> None:
        if not _hid.HidD_SetFeature(self._handle, report, len(report)):
            raise ctypes.WinError(ctypes.get_last_error())


def find_interfaces(vendor_id: int, product_id: int) -> list[HidInterface]:
    """Describe every present HID interface of a device (opened with no access rights)."""
    found = []
    for path in _interface_paths():
        # Access 0 is enough to query attributes and works even if another app holds the device.
        handle = _kernel32.CreateFileW(path, 0, _FILE_SHARE_READ | _FILE_SHARE_WRITE, None, _OPEN_EXISTING, 0, None)
        if handle in (None, _INVALID_HANDLE):
            continue
        try:
            attrs = _HIDD_ATTRIBUTES()
            attrs.Size = ctypes.sizeof(attrs)
            if not _hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                continue
            if (attrs.VendorID, attrs.ProductID) != (vendor_id, product_id):
                continue
            preparsed = ctypes.c_void_p()
            if not _hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
                continue
            try:
                caps = _HIDP_CAPS()
                if _hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != _HIDP_STATUS_SUCCESS:
                    continue
            finally:
                _hid.HidD_FreePreparsedData(preparsed)
            found.append(
                HidInterface(
                    path, attrs.VendorID, attrs.ProductID, caps.UsagePage, caps.Usage,
                    caps.FeatureReportByteLength, caps.OutputReportByteLength,
                )
            )
        finally:
            _kernel32.CloseHandle(handle)
    return found
