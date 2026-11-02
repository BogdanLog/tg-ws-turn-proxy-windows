from __future__ import annotations

import hmac
import hashlib
import struct
import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

MAGIC = 0x2112A442
MAGIC_BYTES = struct.pack('>I', MAGIC)

MSG_BINDING = 0x0001
MSG_ALLOCATE = 0x0003
MSG_ALLOCATE_OK = 0x0103
MSG_ALLOCATE_ERR = 0x0113
MSG_REFRESH = 0x0004
MSG_REFRESH_OK = 0x0104
MSG_REFRESH_ERR = 0x0114
MSG_SEND_IND = 0x0016
MSG_DATA_IND = 0x0017
MSG_CREATE_PERMISSION = 0x0008
MSG_CREATE_PERMISSION_OK = 0x0108
MSG_CREATE_PERMISSION_ERR = 0x0118
MSG_CHANNEL_BIND = 0x0009
MSG_CHANNEL_BIND_OK = 0x0109

ATTR_MAPPED_ADDRESS = 0x0001
ATTR_USERNAME = 0x0006
ATTR_MESSAGE_INTEGRITY = 0x0008
ATTR_ERROR_CODE = 0x0009
ATTR_UNKNOWN_ATTRIBUTES = 0x000A
ATTR_CHANNEL_NUMBER = 0x000C
ATTR_LIFETIME = 0x000D
ATTR_XOR_PEER_ADDRESS = 0x0012
ATTR_DATA = 0x0013
ATTR_REALM = 0x0014
ATTR_NONCE = 0x0015
ATTR_XOR_RELAYED_ADDRESS = 0x0016
ATTR_REQUESTED_TRANSPORT = 0x0019
ATTR_DONT_FRAGMENT = 0x001A
ATTR_XOR_MAPPED_ADDRESS = 0x0020
ATTR_SOFTWARE = 0x8022
ATTR_FINGERPRINT = 0x8028

TRANSPORT_UDP = 17
TRANSPORT_TCP = 6

ERR_UNAUTHORIZED = 401
ERR_STALE_NONCE = 438
ERR_WRONG_CREDENTIALS = 441
ERR_UNSUPPORTED_TRANSPORT = 442
ERR_CONNECTION_TIMEOUT = 437


class StunError(Exception):
    pass


@dataclass
class StunMessage:
    msg_type: int
    txid: bytes
    attrs: Dict[int, List[bytes]]

    @property
    def is_error(self) -> bool:
        return bool(self.attrs.get(ATTR_ERROR_CODE))

    @property
    def error_code(self) -> Optional[int]:
        values = self.attrs.get(ATTR_ERROR_CODE)
        if not values:
            return None
        value = values[0]
        if len(value) < 4:
            return None
        return value[2] * 100 + value[3]

    @property
    def error_reason(self) -> str:
        values = self.attrs.get(ATTR_ERROR_CODE)
        if not values or len(values[0]) < 4:
            return ''
        return values[0][4:].decode('utf-8', errors='replace')

    def first(self, attr: int) -> Optional[bytes]:
        values = self.attrs.get(attr)
        return values[0] if values else None

    def lifetime(self) -> int:
        value = self.first(ATTR_LIFETIME)
        if value is None or len(value) < 4:
            return 600
        return struct.unpack('>I', value[:4])[0]

    def realm(self) -> str:
        value = self.first(ATTR_REALM)
        return value.decode('utf-8', errors='replace') if value else ''

    def nonce(self) -> str:
        value = self.first(ATTR_NONCE)
        return value.decode('utf-8', errors='replace') if value else ''


def new_txid() -> bytes:
    import os
    return os.urandom(12)


def _pad4(n: int) -> int:
    return (4 - (n % 4)) % 4


def _attr(atype: int, value: bytes) -> bytes:
    return struct.pack('>HH', atype, len(value)) + value + b'\x00' * _pad4(len(value))


def pack_xor_address(ipv4: str, port: int) -> bytes:
    import socket
    addr = socket.inet_aton(ipv4)
    xport = port ^ (MAGIC >> 16)
    xaddr = struct.pack('>I', struct.unpack('>I', addr)[0] ^ MAGIC)
    return struct.pack('>BBH', 0, 1, xport) + xaddr


def unpack_xor_address(value: bytes) -> Tuple[str, int]:
    import socket
    if len(value) < 8:
        raise StunError(f'XOR address too short: {len(value)}')
    family = value[1]
    if family != 1:
        raise StunError(f'unsupported address family {family} (IPv6 not used by the relay)')
    xport, xaddr = struct.unpack('>HI', value[2:8])
    port = xport ^ (MAGIC >> 16)
    addr = struct.pack('>I', xaddr ^ MAGIC)
    return socket.inet_ntoa(addr), port


def error_code_value(code: int, reason: str = '') -> bytes:
    if not 0 <= code <= 699:
        raise StunError(f'bad error code {code}')
    return (b'\x00\x00' + bytes([code // 100, code % 100])
            + reason.encode('utf-8'))


def integrity_key(username: str, realm: str, password: str) -> bytes:
    return hashlib.md5(
        f'{username}:{realm}:{password}'.encode('utf-8')).digest()


class StunBuilder:

    def __init__(self, msg_type: int, txid: Optional[bytes] = None):
        self.msg_type = msg_type
        self.txid = txid if txid is not None else new_txid()
        self._attrs = bytearray()

    def add(self, atype: int, value: bytes) -> 'StunBuilder':
        self._attrs += _attr(atype, value)
        return self

    def add_u32(self, atype: int, value: int) -> 'StunBuilder':
        return self.add(atype, struct.pack('>I', value))

    def add_message_integrity(self, key: bytes) -> 'StunBuilder':
        header = struct.pack('>HH', self.msg_type, len(self._attrs) + 4 + 20)
        header += MAGIC_BYTES + self.txid
        mac = hmac.new(key, header + bytes(self._attrs), hashlib.sha1).digest()
        self._attrs += _attr(ATTR_MESSAGE_INTEGRITY, mac)
        return self

    def add_fingerprint(self) -> 'StunBuilder':
        header = struct.pack('>HH', self.msg_type, len(self._attrs) + 8)
        header += MAGIC_BYTES + self.txid
        crc = (zlib.crc32(header + bytes(self._attrs))
               & 0xFFFFFFFF) ^ 0x5354554E
        self._attrs += _attr(ATTR_FINGERPRINT, struct.pack('>I', crc))
        return self

    def build(self) -> bytes:
        header = struct.pack('>HH', self.msg_type, len(self._attrs))
        header += MAGIC_BYTES + self.txid
        return header + bytes(self._attrs)


def parse_message(data: bytes) -> StunMessage:
    if len(data) < 20:
        raise StunError(f'STUN message too short: {len(data)} bytes')
    msg_type, length = struct.unpack('>HH', data[:4])
    magic = struct.unpack('>I', data[4:8])[0]
    if magic != MAGIC:
        raise StunError(f'bad magic cookie 0x{magic:08x}')
    if length % 4 != 0:
        raise StunError(f'bad STUN length {length}')
    if 20 + length > len(data):
        raise StunError(f'truncated STUN message: need {20 + length}, got {len(data)}')
    txid = data[8:20]
    attrs: Dict[int, List[bytes]] = {}
    offset = 20
    end = 20 + length
    while offset + 4 <= end:
        atype, alen = struct.unpack('>HH', data[offset:offset + 4])
        value_start = offset + 4
        value_end = value_start + alen
        if value_end > end:
            raise StunError(f'attribute 0x{atype:04x} overruns message')
        attrs.setdefault(atype, []).append(data[value_start:value_end])
        offset = value_end + _pad4(alen)
    return StunMessage(msg_type=msg_type, txid=txid, attrs=attrs)


def parse_stream_chunk(buf: bytearray) -> Optional[bytes]:
    if len(buf) < 20:
        return None
    first2 = struct.unpack('>H', buf[:2])[0]
    if first2 & 0xC000 == 0x4000:
        if len(buf) < 4:
            return None
        clen = struct.unpack('>H', buf[2:4])[0]
        total = 4 + clen + _pad4(clen)
        if len(buf) < total:
            return None
        raw = bytes(buf[:total])
        del buf[:total]
        return raw
    msg_type, length = struct.unpack('>HH', buf[:4])
    if msg_type == 0:
        raise StunError('zero message type on the TURN control connection')
    if length > 0xFFFF:
        raise StunError(f'implausible STUN length {length} - not a STUN stream?')
    total = 20 + length
    if len(buf) < total:
        return None
    raw = bytes(buf[:total])
    del buf[:total]
    return raw