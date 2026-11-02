from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import sys
import threading
from typing import Optional

log = logging.getLogger('tg-calls-relay')

ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87
ERROR_DRIVER_FAILED_PRIOR_UNLOAD = 654
ERROR_DRIVER_BLOCKED = 1275

WINDIVERT_LAYER_NETWORK = 0

WINDIVERT_FLAG_SNIFF = 0x0001
WINDIVERT_FLAG_RECV_ONLY = 0x0004
WINDIVERT_FLAG_SEND_ONLY = 0x0008

WINDIVERT_PARAM_QUEUE_LENGTH = 0
WINDIVERT_PARAM_QUEUE_TIME = 1

WINDIVERT_HELPER_NO_IP_CHECKSUM = 1
WINDIVERT_HELPER_NO_TCP_CHECKSUM = 8
WINDIVERT_HELPER_NO_UDP_CHECKSUM = 16


class WinDivertError(OSError):

    def __init__(self, code: int, what: str):
        self.code = code
        super().__init__(code, f'{what} failed (Win32 error {code}: '
                               f'{_win32_message(code)})')


def _win32_message(code: int) -> str:
    if code == ERROR_ACCESS_DENIED:
        return ('administrator privileges are required - start the relay '
                'through tg-calls-relay.bat')
    if code == ERROR_INVALID_PARAMETER:
        return ('invalid parameter (bad filter string, or the DLL and driver '
                'versions disagree)')
    if code == ERROR_DRIVER_FAILED_PRIOR_UNLOAD:
        return (                'a different WinDivert driver version is loaded - make sure '
                'only zapret\\bin\\WinDivert.dll is used')
    if code == ERROR_DRIVER_BLOCKED:
        return 'the driver is blocked by security software'
    try:
        import winreg
    except ImportError:
        pass
    return 'see WinDivert documentation'


class WindivertAddress(ctypes.Structure):
    _fields_ = [
        ('Timestamp', ctypes.c_int64),
        ('Layer', ctypes.c_uint32, 8),
        ('Event', ctypes.c_uint32, 8),
        ('Sniffed', ctypes.c_uint32, 1),
        ('Outbound', ctypes.c_uint32, 1),
        ('Loopback', ctypes.c_uint32, 1),
        ('Impostor', ctypes.c_uint32, 1),
        ('IPv6', ctypes.c_uint32, 1),
        ('IPChecksum', ctypes.c_uint32, 1),
        ('TCPChecksum', ctypes.c_uint32, 1),
        ('UDPChecksum', ctypes.c_uint32, 1),
        ('Reserved1', ctypes.c_uint32, 8),
        ('Reserved2', ctypes.c_uint32),
        ('IfIdx', ctypes.c_uint32),
        ('SubIfIdx', ctypes.c_uint32),
        ('_union_pad', ctypes.c_uint8 * 56),
    ]


assert ctypes.sizeof(WindivertAddress) == 80, (
    f'WINDIVERT_ADDRESS size mismatch: {ctypes.sizeof(WindivertAddress)} != 80')


class _WinDivertDll:

    _instance: Optional['_WinDivertDll'] = None

    def __init__(self, dll_path: str):
        if not os.path.isfile(dll_path):
            raise WinDivertError(ERROR_INVALID_PARAMETER,
                                 f'loading {dll_path} (file not found)')
        self.dll = ctypes.WinDLL(dll_path, use_last_error=True)

        self.dll.WinDivertOpen.argtypes = [
            ctypes.c_char_p, ctypes.c_int, ctypes.c_int16, ctypes.c_uint64]
        self.dll.WinDivertOpen.restype = wintypes.HANDLE

        self.dll.WinDivertRecv.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_void_p, ctypes.POINTER(WindivertAddress)]
        self.dll.WinDivertRecv.restype = wintypes.BOOL

        self.dll.WinDivertSend.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_void_p, ctypes.POINTER(WindivertAddress)]
        self.dll.WinDivertSend.restype = wintypes.BOOL

        self.dll.WinDivertClose.argtypes = [wintypes.HANDLE]
        self.dll.WinDivertClose.restype = wintypes.BOOL

        self.dll.WinDivertShutdown.argtypes = [wintypes.HANDLE, ctypes.c_int]
        self.dll.WinDivertShutdown.restype = wintypes.BOOL

        self.dll.WinDivertSetParam.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_uint64]
        self.dll.WinDivertSetParam.restype = wintypes.BOOL

        self.dll.WinDivertHelperCalcChecksums.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(WindivertAddress),
            ctypes.c_uint64]
        self.dll.WinDivertHelperCalcChecksums.restype = wintypes.BOOL

    @classmethod
    def get(cls, dll_path: str) -> '_WinDivertDll':
        if cls._instance is None:
            cls._instance = cls(dll_path)
        return cls._instance


def default_dll_path() -> str:
    override = os.environ.get('TG_CALLS_WINDIVERT_DLL', '')
    if override:
        override = os.path.abspath(override)
        if os.path.isfile(override):
            return override

    here = os.path.dirname(os.path.abspath(__file__))
    frozen = (bool(getattr(sys, 'frozen', False))
              or globals().get('__compiled__') is not None)
    if frozen:
        bundle = os.path.dirname(here)
        candidates = [
            os.path.join(bundle, 'zapret', 'bin', 'WinDivert.dll'),
        ]
    else:
        repo = os.path.dirname(os.path.dirname(here))
        candidates = [
            os.path.join(repo, 'zapret', 'bin', 'WinDivert.dll'),
            os.path.join(repo, 'tg_calls', 'bin', 'WinDivert.dll'),
            os.path.join(repo, 'bin', 'WinDivert.dll'),
        ]
    meipass = getattr(sys, '_MEIPASS', '')
    if meipass:
        candidates.insert(
            0, os.path.join(meipass, 'zapret', 'bin', 'WinDivert.dll'))
    return next((p for p in candidates if os.path.isfile(p)), candidates[0])


class WinDivertHandle:

    def __init__(self, dll: _WinDivertDll, filter_text: str, priority: int,
                 flags: int = 0, queue_length: int = 4096,
                 queue_time_ms: int = 4000):
        self._dll = dll
        self._closed = threading.Event()
        handle = dll.dll.WinDivertOpen(
            filter_text.encode('ascii'), WINDIVERT_LAYER_NETWORK,
            priority, flags)
        if not handle or handle == wintypes.HANDLE(-1).value:
            raise WinDivertError(ctypes.get_last_error(),
                                 f'WinDivertOpen({filter_text!r}, '
                                 f'priority={priority})')
        self.handle = handle
        dll.dll.WinDivertSetParam(handle, WINDIVERT_PARAM_QUEUE_LENGTH,
                                  queue_length)
        dll.dll.WinDivertSetParam(handle, WINDIVERT_PARAM_QUEUE_TIME,
                                  queue_time_ms)
        log.info('WinDivert open: priority=%d flags=0x%x filter=%s',
                 priority, flags, filter_text)

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def recv(self, bufsize: int = 65575) -> Optional[tuple]:
        if self._closed.is_set():
            return None
        buf = (ctypes.c_uint8 * bufsize)()
        recv_len = ctypes.c_uint(0)
        addr = WindivertAddress()
        ok = self._dll.dll.WinDivertRecv(
            self.handle, buf, bufsize, ctypes.byref(recv_len),
            ctypes.byref(addr))
        if not ok:
            code = ctypes.get_last_error()
            if self._closed.is_set() or code in (232, 995):
                return None
            raise WinDivertError(code, 'WinDivertRecv')
        return bytes(buf[:recv_len.value]), addr

    def send(self, packet: bytes, addr: WindivertAddress) -> bool:
        if self._closed.is_set():
            return False
        buf = (ctypes.c_uint8 * len(packet)).from_buffer_copy(packet)
        ok = self._dll.dll.WinDivertSend(
            self.handle, buf, len(packet), None, ctypes.byref(addr))
        if not ok:
            code = ctypes.get_last_error()
            log.debug('WinDivertSend failed (error %d)', code)
            return False
        return True

    def calc_checksums(self, packet: bytearray,
                       addr: WindivertAddress) -> None:
        buf = (ctypes.c_uint8 * len(packet)).from_buffer(packet)
        ok = self._dll.dll.WinDivertHelperCalcChecksums(
            buf, len(packet), ctypes.byref(addr), 0)
        if not ok:
            raise WinDivertError(ctypes.get_last_error(),
                                 'WinDivertHelperCalcChecksums')
        addr.IPChecksum = 1
        addr.UDPChecksum = 1

    def shutdown_recv(self) -> None:
        if not self._closed.is_set():
            self._dll.dll.WinDivertShutdown(self.handle, 0x1)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._dll.dll.WinDivertClose(self.handle)
        except Exception:
            log.debug('WinDivertClose raised', exc_info=True)


def open_handle(filter_text: str, priority: int, flags: int = 0,
                dll_path: Optional[str] = None) -> WinDivertHandle:
    dll = _WinDivertDll.get(dll_path or default_dll_path())
    return WinDivertHandle(dll, filter_text, priority, flags=flags)