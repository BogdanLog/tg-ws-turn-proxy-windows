from __future__ import annotations

import socket
import struct
from typing import Optional, Tuple

IPPROTO_UDP = 17

Datagram = Tuple[str, int, str, int, bytes]


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b'\x00'
    total = 0
    for word in struct.unpack(f'>{len(data) // 2}H', data):
        total += word
    total = (total & 0xFFFF) + (total >> 16)
    total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def parse_ipv4_udp(packet: bytes) -> Optional[Datagram]:
    if len(packet) < 28:
        return None
    ver_ihl = packet[0]
    if ver_ihl >> 4 != 4:
        return None
    ihl = (ver_ihl & 0x0F) * 4
    if ihl < 20 or len(packet) < ihl + 8:
        return None
    total_len = struct.unpack('>H', packet[2:4])[0]
    if total_len < ihl + 8 or total_len > len(packet):
        return None
    frag = struct.unpack('>H', packet[6:8])[0]
    if frag & 0x3FFF:
        return None
    if packet[9] != IPPROTO_UDP:
        return None
    src_ip = socket.inet_ntoa(packet[12:16])
    dst_ip = socket.inet_ntoa(packet[16:20])
    udp = packet[ihl:total_len]
    if len(udp) < 8:
        return None
    src_port, dst_port, udp_len, _csum = struct.unpack('>HHHH', udp[:8])
    if udp_len < 8 or udp_len > len(udp):
        return None
    payload = bytes(udp[8:udp_len])
    return src_ip, src_port, dst_ip, dst_port, payload


def describe_packet(packet: bytes) -> Optional[Tuple[str, str, str, int, int, int]]:
    if not packet:
        return None
    ver = packet[0] >> 4
    if ver == 4:
        if len(packet) < 20:
            return None
        ihl = (packet[0] & 0x0F) * 4
        if ihl < 20 or len(packet) < ihl:
            return None
        proto_num = packet[9]
        src = socket.inet_ntoa(packet[12:16])
        dst = socket.inet_ntoa(packet[16:20])
        sport = dport = 0
        frag = struct.unpack('>H', packet[6:8])[0]
        if proto_num in (6, 17) and frag & 0x1FFF == 0 and len(packet) >= ihl + 4:
            sport, dport = struct.unpack('>HH', packet[ihl:ihl + 4])
        proto = {6: 'tcp', 17: 'udp'}.get(proto_num, str(proto_num))
        return proto, src, dst, sport, dport, len(packet)
    if ver == 6:
        if len(packet) < 40:
            return None
        src = socket.inet_ntop(socket.AF_INET6, packet[8:24])
        dst = socket.inet_ntop(socket.AF_INET6, packet[24:40])
        nxt = packet[6]
        off = 40
        while nxt in (0, 43, 60) and off + 2 <= len(packet):
            nxt, size = packet[off], (packet[off + 1] + 1) * 8
            off += size
            if off > len(packet):
                break
        sport = dport = 0
        if nxt in (6, 17) and off + 4 <= len(packet):
            sport, dport = struct.unpack('>HH', packet[off:off + 4])
        proto = {6: 'tcp', 17: 'udp'}.get(nxt, str(nxt))
        return proto, src, dst, sport, dport, len(packet)
    return None


def build_udp_packet(src_ip: str, src_port: int, dst_ip: str, dst_port: int,
                     payload: bytes, *, ttl: int = 64,
                     ip_id: int = 0) -> bytes:
    if len(payload) > 65507:
        raise ValueError(f'UDP payload is too large: {len(payload)} bytes')
    udp_len = 8 + len(payload)
    udp_hdr = struct.pack('>HHHH', src_port, dst_port, udp_len, 0)
    pseudo = (socket.inet_aton(src_ip) + socket.inet_aton(dst_ip)
              + struct.pack('>BBH', 0, IPPROTO_UDP, udp_len))
    udp_csum = _checksum(pseudo + udp_hdr + payload)
    if udp_csum == 0:
        udp_csum = 0xFFFF
    udp_hdr = struct.pack('>HHHH', src_port, dst_port, udp_len, udp_csum)

    total_len = 20 + udp_len
    ip_hdr = struct.pack('>BBHHHBBH4s4s',
                         0x45, 0, total_len, ip_id, 0, ttl,
                         IPPROTO_UDP, 0,
                         socket.inet_aton(src_ip), socket.inet_aton(dst_ip))
    ip_csum = _checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('>H', ip_csum) + ip_hdr[12:]
    return ip_hdr + udp_hdr + payload


def build_stun_binding_request(txid: Optional[bytes] = None) -> bytes:
    import os
    from . import stun as stun_mod
    txid = txid or os.urandom(12)
    return struct.pack('>HH', 0x0001, 0) + stun_mod.MAGIC_BYTES + txid


def parse_stun_binding_response(data: bytes,
                                txid: bytes) -> Optional[Tuple[str, int]]:
    from . import stun as stun_mod
    try:
        msg = stun_mod.parse_message(data)
    except stun_mod.StunError:
        return None
    if msg.msg_type != 0x0101 or msg.txid != txid:
        return None
    value = msg.first(stun_mod.ATTR_XOR_MAPPED_ADDRESS)
    if value is None:
        value = msg.first(stun_mod.ATTR_MAPPED_ADDRESS)
        if value is None:
            return None
        if len(value) < 8 or value[1] != 1:
            return None
        port = struct.unpack('>H', value[2:4])[0]
        return socket.inet_ntoa(value[4:8]), port
    try:
        return stun_mod.unpack_xor_address(value)
    except stun_mod.StunError:
        return None