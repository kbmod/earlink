"""Windows Bluetooth discovery and RFCOMM using the Microsoft Bluetooth stack.

No COM port, BlueZ, administrator access, or third-party Bluetooth library is
required. Pairing and audio routing are managed by Windows Settings.
"""

from __future__ import annotations

import ctypes as C
import os
import re
import select
import socket
import uuid
from dataclasses import dataclass

DWORD = C.c_uint32
BOOL = C.c_int32


class DeviceInfo(C.Structure):
    _fields_ = [
        ("size", DWORD), ("address", C.c_uint64), ("device_class", DWORD),
        ("connected", BOOL), ("remembered", BOOL), ("authenticated", BOOL),
        ("last_seen", C.c_uint16 * 8), ("last_used", C.c_uint16 * 8),
        ("name", C.c_uint16 * 248),
    ]


class SearchParams(C.Structure):
    _fields_ = [
        ("size", DWORD), ("authenticated", BOOL), ("remembered", BOOL),
        ("unknown", BOOL), ("connected", BOOL), ("inquiry", BOOL),
        ("timeout_multiplier", C.c_ubyte), ("radio", C.c_void_p),
    ]


class SockaddrBth(C.Structure):
    # ws2bth.h uses pshpack1.h: the socket address is 30 bytes, not 40.
    _pack_ = 1
    _fields_ = [
        ("family", C.c_uint16), ("address", C.c_uint64),
        ("service", C.c_ubyte * 16), ("port", DWORD),
    ]


@dataclass(frozen=True)
class Device:
    address: str
    name: str
    paired: bool
    connected: bool


def address_number(address: str) -> int:
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", address):
        raise ValueError("Choose a Bluetooth device with a valid MAC address.")
    return int(address.replace(":", ""), 16)


def address_text(number: int) -> str:
    digits = f"{number:012X}"
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


def devices(*, inquiry: bool = False) -> list[Device]:
    api = C.WinDLL("bthprops.cpl", use_last_error=True)
    api.BluetoothFindFirstDevice.argtypes = [C.POINTER(SearchParams), C.POINTER(DeviceInfo)]
    api.BluetoothFindFirstDevice.restype = C.c_void_p
    api.BluetoothFindNextDevice.argtypes = [C.c_void_p, C.POINTER(DeviceInfo)]
    api.BluetoothFindNextDevice.restype = BOOL
    api.BluetoothFindDeviceClose.argtypes = [C.c_void_p]
    api.BluetoothFindDeviceClose.restype = BOOL
    params = SearchParams(C.sizeof(SearchParams), 1, 1, 1, 1, int(inquiry), 8, None)
    info = DeviceInfo()
    info.size = C.sizeof(DeviceInfo)
    handle = api.BluetoothFindFirstDevice(C.byref(params), C.byref(info))
    if not handle:
        error = C.get_last_error()
        if error == 259:  # ERROR_NO_MORE_ITEMS
            return []
        if error == 1238:  # ERROR_CONNECTION_COUNT_LIMIT, e.g. competing inquiries
            raise OSError(error, "Windows Bluetooth discovery is busy. Close other Bluetooth scans, then try again.")
        raise OSError(error, "Bluetooth scan failed. Turn on Bluetooth in Windows Settings. " + C.FormatError(error))
    found = []
    try:
        while True:
            name = bytes(info.name).decode("utf-16-le").split("\0", 1)[0]
            address = address_text(info.address)
            found.append(Device(address, name or address, bool(info.authenticated), bool(info.connected)))
            if not api.BluetoothFindNextDevice(handle, C.byref(info)):
                error = C.get_last_error()
                if error != 259:
                    raise C.WinError(error)
                break
    finally:
        api.BluetoothFindDeviceClose(handle)
    return sorted(found, key=lambda d: (not d.connected, not d.paired, d.name.casefold()))


def bluetooth_settings() -> None:
    os.startfile("ms-settings:bluetooth")


def sound_settings() -> None:
    os.startfile("ms-settings:sound")


def connect_socket(address: str, channel: int, *, service: str | None = None,
                   timeout: float = 4) -> socket.socket:
    """Connect via native sockaddr; Python's Windows build lacks BTH addresses.

    The Python socket still owns the handle and implements timed send/receive.
    A zero port plus service UUID lets Winsock resolve the RFCOMM channel by SDP.
    """
    target = SockaddrBth()
    target.family = 32  # AF_BTH
    target.address = address_number(address)
    target.port = channel
    if service:
        target.service[:] = uuid.UUID(service).bytes_le
    ws = C.WinDLL("ws2_32", use_last_error=True)
    ws.connect.argtypes = [C.c_size_t, C.POINTER(SockaddrBth), C.c_int]
    ws.connect.restype = C.c_int
    ws.WSAGetLastError.restype = C.c_int
    sock = socket.socket(32, socket.SOCK_STREAM, 3)  # BTHPROTO_RFCOMM
    try:
        sock.setblocking(False)
        if ws.connect(sock.fileno(), C.byref(target), C.sizeof(target)) != 0:
            error = ws.WSAGetLastError()
            if error not in (10035, 10036, 10037):
                raise OSError(error, C.FormatError(error))
            _, writable, exceptional = select.select([], [sock], [sock], timeout)
            if not writable and not exceptional:
                raise socket.timeout("The earbuds did not connect. Open the case and try again.")
            error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if error:
                raise OSError(error, C.FormatError(error))
        sock.settimeout(0.25)
        return sock
    except BaseException:
        sock.close()
        raise
