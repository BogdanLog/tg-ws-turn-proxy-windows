from __future__ import annotations

import asyncio
import ipaddress
import logging
import queue
import socket
import struct
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from . import mint, packets, stun
from .config import (CIDR_SOURCE_URL, RelayConfig, load_cidrs, save_config,
                     update_cidr_file)
from .turn import TurnClient, TurnConfigError, TurnError, TurnUrl, allocate_and_start
from .windivert import (ERROR_ACCESS_DENIED, ERROR_DRIVER_BLOCKED,
                        ERROR_DRIVER_FAILED_PRIOR_UNLOAD,
                        ERROR_INVALID_PARAMETER, WinDivertError,
                        WinDivertHandle, WindivertAddress, open_handle)

FATAL_WINDIVERT_ERRORS = (ERROR_ACCESS_DENIED, ERROR_INVALID_PARAMETER,
                          ERROR_DRIVER_FAILED_PRIOR_UNLOAD,
                          ERROR_DRIVER_BLOCKED)

log = logging.getLogger('tg-calls-relay')

PEER_KEY = Tuple[str, int]
LOCAL_END = Tuple[str, int, int, int]


class TokenBucket:

    def __init__(self, rate: float, burst: float):
        self.rate = rate
        self.capacity = burst
        self.tokens = burst
        self.updated = time.monotonic()

    async def take(self) -> None:
        while True:
            now = time.monotonic()
            self.tokens = min(self.capacity,
                              self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            await asyncio.sleep((1 - self.tokens) / self.rate)


class PeerState:

    __slots__ = ('ip', 'ready', 'inflight', 'pending', 'last_seen',
                 'last_permission')

    def __init__(self, ip: str):
        self.ip = ip
        self.ready = False
        self.inflight = False
        self.pending: Deque[Tuple[int, bytes]] = deque(maxlen=1024)
        self.last_seen = time.monotonic()
        self.last_permission = 0.0


class Flow:

    __slots__ = ('local', 'client', 'peers', 'q', 'pump', 'keepalive',
                 'last_seen', 'ipkts', 'ibytes', 'imax', 'iremotes')

    def __init__(self, local: LOCAL_END):
        self.local = local
        self.client: Optional[TurnClient] = None
        self.peers: Dict[str, PeerState] = {}
        self.q: 'asyncio.Queue' = asyncio.Queue(maxsize=256)
        self.pump: Optional[asyncio.Task] = None
        self.keepalive: Optional[asyncio.Task] = None
        self.last_seen = time.monotonic()
        self.ipkts = 0
        self.ibytes = 0
        self.imax = 0
        self.iremotes: set = set()


class _AggTurn:

    def __init__(self, flow_map: Dict[Tuple[str, int], Flow]):
        self._flow_map = flow_map

    @property
    def connected(self) -> bool:
        return any(f.client is not None and f.client.connected
                   for f in self._flow_map.values())

    @property
    def stats(self) -> dict:
        sent = received = 0
        for f in self._flow_map.values():
            if f.client is not None:
                sent += f.client.stats['sent']
                received += f.client.stats['received']
        return {'sent': sent, 'received': received}

    @property
    def lifetime(self) -> int:
        return max((f.client.lifetime for f in self._flow_map.values()
                    if f.client is not None), default=0)


class Stats:
    def __init__(self) -> None:
        self.captured = 0
        self.parse_skipped = 0
        self.frag_skipped = 0
        self.sniff_dropped = 0
        self.dropped = 0
        self.forwarded = 0
        self.reply_pending_no_session = 0
        self.injected = 0
        self.inject_failed = 0
        self.bytes_up = 0
        self.bytes_down = 0
        self.started = time.monotonic()

    def line(self, client: Optional[object],
             extra: str = '') -> str:
        up = time.monotonic() - self.started
        turn = '-'
        if client is not None and client.connected:
            turn = (f'sent={client.stats["sent"]} recv={client.stats["received"]} '
                    f'life={client.lifetime}s')
        return (f'up={up:.0f}s captured={self.captured} fwd={self.forwarded} '
                f'replies={self.injected} parse_skip={self.parse_skipped} '
                f'frag_skip={self.frag_skipped} drop={self.dropped} '
                f'inject_fail={self.inject_failed} '
                f'KB up={self.bytes_up / 1024:.1f} '
                f'KB down={self.bytes_down / 1024:.1f} turn[{turn}] {extra}')


class CallRelay:
    def __init__(self, cfg: RelayConfig, *, dry_run: bool = False,
                 capture_only: bool = False, sniff_outbound: bool = False,
                 probe_target: Tuple[str, int] = ('stun.l.google.com', 19302)):
        self.cfg = cfg
        self.dry_run = dry_run
        self.capture_only = capture_only
        self.sniff_outbound = sniff_outbound
        self.probe_target = probe_target

        self._set_cidrs(load_cidrs(cfg.cidr_file))
        self.stats = Stats()

        self._turn: Optional[TurnClient] = None
        self._handle: Optional[WinDivertHandle] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._packet_q: Optional[asyncio.Queue] = None
        self._stop = asyncio.Event()

        self._flow_map: Dict[Tuple[str, int], Flow] = {}
        self.max_flows = 8
        self._bucket = TokenBucket(cfg.permission_rate, cfg.permission_burst)

        self._sniff_flows: Dict[Tuple[str, str, int], dict] = {}
        self._alloc_addrs: set = set()
        self._sniff_handle: Optional[WinDivertHandle] = None
        self._sniff_thread: Optional[threading.Thread] = None
        self._sniff_q: Optional[asyncio.Queue] = None

        self._creds_expire_at = 0.0
        self._creds_ttl = 0.0
        self._creds_next_try = 0.0
        self._mint_lock = asyncio.Lock()

        self._probe_txid: Optional[bytes] = None
        self._probe_sent_at = 0.0

    def _mint_margin(self) -> float:
        ttl = self._creds_ttl or float(self.cfg.turn.mint_ttl) or 7200.0
        return max(60.0, min(ttl * 0.5, max(3600.0, ttl / 4.0),
                             6 * 3600.0))

    def _mint_needed(self, now: float) -> bool:
        turn_cfg = self.cfg.turn
        if not turn_cfg.has_credentials:
            return True
        if self._creds_expire_at <= 0.0:
            return turn_cfg.can_mint
        if not turn_cfg.can_mint:
            return False
        return now > self._creds_expire_at - self._mint_margin()

    def _mint_failed(self, exc: BaseException) -> None:
        self._creds_next_try = time.time() + 120
        if self.cfg.turn.has_credentials:
            log.warning('mint failed (%s) - continuing with stored '
                        'credentials, retry in ~2 min', exc)
        else:
            log.warning('mint failed (%s) - retry in ~2 min', exc)

    async def _mint_now(self) -> bool:
        turn_cfg = self.cfg.turn
        if not turn_cfg.can_mint:
            return False
        if time.time() < self._creds_next_try:
            return False
        async with self._mint_lock:
            if not self._mint_needed(time.time()):
                return True
            ttl = max(60, min(int(turn_cfg.mint_ttl), 172800))
            loop = asyncio.get_running_loop()
            use_hf = turn_cfg.can_mint_hf
            log.info('minting %s TURN credentials (ttl=%ds)',
                     'HF' if use_hf else 'Cloudflare', ttl)
            try:
                if use_hf:
                    result = await loop.run_in_executor(
                        None, mint.mint_huggingface,
                        turn_cfg.hf_token, ttl)
                else:
                    result = await loop.run_in_executor(
                        None, mint.mint_cloudflare,
                        turn_cfg.key_id, turn_cfg.api_token, ttl)
            except SystemExit as exc:
                self._mint_failed(exc)
                return False
            except Exception as exc:
                self._mint_failed(exc)
                return False

            turn_cfg.username = result['username']
            turn_cfg.credential = result['credential']
            chosen = mint._prefer_tls(result['urls'])
            if chosen:
                turn_cfg.url = chosen
            self._creds_expire_at = time.time() + ttl
            self._creds_ttl = float(ttl)
            self._creds_next_try = 0.0
            try:
                save_config(self.cfg, self.cfg.config_path or None)
            except (OSError, ValueError) as exc:
                log.warning('could not persist refreshed credentials: %s', exc)
            expires = time.strftime('%Y-%m-%d %H:%M UTC',
                                    time.gmtime(self._creds_expire_at))
            log.info('TURN credentials refreshed, valid ~%ds (until %s)',
                     ttl, expires)
            clients = [f.client for f in self._flow_map.values()
                       if f.client is not None]
            if self._turn is not None:
                clients.append(self._turn)
            for client in clients:
                client.set_credentials(turn_cfg.username,
                                       turn_cfg.credential)
            failed = None
            for client in clients:
                try:
                    await client.refresh()
                except TurnError as exc:
                    failed = exc
                    break
            if failed is not None:
                raise TurnError(
                    f'new TURN credentials rejected by the server '
                    f'(reconnecting): {failed}') from failed
            if clients:
                log.info('live allocation(s) accepted the new credentials '
                         '(%d)', len(clients))
            return True

    async def _ensure_credentials(self) -> None:
        if self._mint_needed(time.time()):
            await self._mint_now()
        if not self.cfg.turn.has_credentials:
            raise TurnConfigError(
                'no TURN credentials: run '
                '"python -m tg_calls_relay mint --hf-token hf_..." '
                '(Hugging Face: free 10 GB/mo, no credit card), or '
                '"... mint --key-id <id> --token <token>" (Cloudflare), or '
                '"... mint --username U --credential C" (any TURN server)')

    async def _credential_watch_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            now = time.time()
            if now < self._creds_next_try or not self._mint_needed(now):
                continue
            await self._mint_now()

    @staticmethod
    def _cidr_to_range(cidr: str) -> Tuple[str, str]:
        if '/' in cidr:
            addr_s, bits_s = cidr.split('/', 1)
            bits = int(bits_s)
        else:
            addr_s, bits = cidr, 32
        if not 0 <= bits <= 32:
            raise ValueError(f'bad CIDR {cidr!r}')
        val = int.from_bytes(socket.inet_aton(addr_s), 'big')
        mask = ((0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF) if bits else 0
        lo = val & mask
        hi = lo | (~mask & 0xFFFFFFFF)
        return (socket.inet_ntoa(lo.to_bytes(4, 'big')),
                socket.inet_ntoa(hi.to_bytes(4, 'big')))

    def _set_cidrs(self, cidrs: List[str]) -> None:
        nets = []
        for cidr in cidrs:
            try:
                net = ipaddress.ip_network(cidr, strict=True)
            except ValueError:
                log.warning('ignoring invalid CIDR %r', cidr)
                continue
            if net.version != 4:
                log.debug('ignoring IPv6 CIDR %s (filter is IPv4)', cidr)
                continue
            nets.append(net)
        self._cidr_nets = nets
        self.cidrs = [str(net) for net in nets]

    async def _refresh_cidrs(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            fresh = await loop.run_in_executor(
                None, update_cidr_file, self.cfg.cidr_file)
        except Exception as exc:
            log.warning('CIDR refresh failed (%s) - keeping %d networks',
                        exc, len(self.cidrs))
            return
        if not fresh:
            log.warning('offline or untrusted answer from %s - keeping %d '
                        'networks from the stored list', CIDR_SOURCE_URL,
                        len(self.cidrs))
            return
        if fresh != self.cidrs:
            added = [c for c in fresh if c not in self.cidrs]
            removed = [c for c in self.cidrs if c not in fresh]
            log.info('Telegram CIDR list refreshed: +%s -%s (%d networks)',
                     ','.join(added) or '-', ','.join(removed) or '-',
                     len(fresh))
            self._set_cidrs(fresh)

    async def _cidr_watch_loop(self) -> None:
        while True:
            await asyncio.sleep(max(600.0, self.cfg.cidr_refresh_secs))
            loop = asyncio.get_running_loop()
            try:
                fresh = await loop.run_in_executor(
                    None, update_cidr_file, self.cfg.cidr_file)
            except Exception as exc:
                log.debug('CIDR re-check failed: %s', exc)
                continue
            if fresh and fresh != self.cidrs:
                log.info('Telegram CIDR list changed on disk - the new '
                         'capture filter applies on the next session start')

    def _build_filter(self) -> str:
        clauses = []
        for cidr in self.cidrs:
            lo, hi = self._cidr_to_range(cidr)
            if lo == hi:
                clauses.append(f'ip.DstAddr == {lo}')
            else:
                clauses.append(f'(ip.DstAddr >= {lo} and ip.DstAddr <= {hi})')
        return 'outbound and udp and (' + ' or '.join(clauses) + ')'

    def _open_capture(self, sniff: bool) -> WinDivertHandle:
        from .windivert import WINDIVERT_FLAG_SNIFF
        flags = WINDIVERT_FLAG_SNIFF if sniff else 0
        return open_handle(self._build_filter(), self.cfg.wd_priority,
                           flags=flags)

    def _start_capture_thread(self, sniff: bool) -> None:
        handle = self._handle
        assert handle is not None
        loop = asyncio.get_running_loop()
        packet_q = self._packet_q
        assert packet_q is not None
        stats = self.stats

        def enqueue(item) -> None:
            try:
                packet_q.put_nowait(item)
            except asyncio.QueueFull:
                stats.dropped += 1

        def worker() -> None:
            try:
                while not handle.closed:
                    got = handle.recv()
                    if got is None:
                        break
                    raw, ifidx, subifidx = got[0], got[1].IfIdx, got[1].SubIfIdx
                    parsed = packets.parse_ipv4_udp(raw)
                    if parsed is None:
                        if (len(raw) >= 8 and raw[0] >> 4 == 4
                                and struct.unpack('>H', raw[6:8])[0]
                                & 0x3FFF):
                            stats.frag_skipped += 1
                        else:
                            stats.parse_skipped += 1
                        continue
                    stats.captured += 1
                    stats.bytes_up += len(parsed[4])
                    try:
                        loop.call_soon_threadsafe(
                            enqueue, (parsed, ifidx, subifidx))
                    except RuntimeError:
                        break
            except WinDivertError as exc:
                log.error('capture failed: %s', exc)
                handle.close()
            log.debug('capture thread exiting (handle closed=%s)',
                      handle.closed)

        t = threading.Thread(target=worker, name='windivert-capture',
                             daemon=True)
        t.start()
        self._capture_thread = t

    async def _stop_capture(self) -> None:
        handle, t = self._handle, self._capture_thread
        self._handle = None
        self._capture_thread = None
        if handle is not None:
            handle.close()
        if t is not None and t.is_alive():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: t.join(timeout=3))

    def _on_data(self, peer_ip: str, peer_port: int, payload: bytes) -> None:
        if self._handle is None:
            if (self._probe_txid is not None
                    and packets.parse_stun_binding_response(
                        payload, self._probe_txid) is not None):
                rtt = (time.monotonic() - self._probe_sent_at) * 1000
                log.info('probe via TURN to %s:%d answered in %.0f ms '
                         '(full relay path OK)',
                         self.probe_target[0], self.probe_target[1], rtt)
                self._probe_txid = None
            return

        self.stats.reply_pending_no_session += 1

    def _on_flow_data(self, flow: Flow, peer_ip: str, peer_port: int,
                      payload: bytes) -> None:
        handle = self._handle
        if handle is None:
            self.stats.reply_pending_no_session += 1
            return
        local_ip, local_port, ifidx, subifidx = flow.local
        packet = bytearray(packets.build_udp_packet(
            peer_ip, peer_port, local_ip, local_port, payload))

        addr = WindivertAddress()
        addr.Layer = 0
        addr.Event = 0
        addr.Outbound = 0
        addr.Impostor = 0
        addr.IPv6 = 0
        addr.IfIdx = ifidx
        addr.SubIfIdx = subifidx
        try:
            handle.calc_checksums(packet, addr)
            if handle.send(bytes(packet), addr):
                self.stats.injected += 1
                self.stats.bytes_down += len(payload)
            else:
                self.stats.inject_failed += 1
        except WinDivertError as exc:
            self.stats.inject_failed += 1
            log.debug('inject failed: %s', exc)

    async def _make_flow_client(self, flow: Flow) -> TurnClient:
        await self._ensure_credentials()
        client = TurnClient(TurnUrl.parse(self.cfg.turn.url),
                            self.cfg.turn.username, self.cfg.turn.credential)
        client.on_data = lambda ip, port, payload, f=flow: \
            self._on_flow_data(f, ip, port, payload)
        try:
            await allocate_and_start(client)
        except BaseException:
            try:
                await client.close()
            except Exception:
                pass
            raise
        flow.client = client
        log.info('allocation for local %s:%d ready: relayed=%s lifetime=%ds',
                 flow.local[0], flow.local[1], client.relayed_addr or '?',
                 client.lifetime)
        return client

    async def _flow_pump(self, flow: Flow) -> None:
        await self._make_flow_client(flow)
        flow.keepalive = asyncio.create_task(flow.client.keepalive_loop(),
                                             name=f'turn-ka-{flow.local[1]}')
        while True:
            dst_ip, dst_port, payload = await flow.q.get()
            peer = flow.peers.get(dst_ip)
            now = time.monotonic()
            if peer is None:
                self._prune_peers(flow, now, want=self.cfg.max_peers)
                peer = flow.peers.get(dst_ip)
                if peer is None:
                    peer = PeerState(dst_ip)
                    flow.peers[dst_ip] = peer
            peer.last_seen = now
            if not peer.ready:
                if not peer.inflight:
                    peer.inflight = True
                    asyncio.create_task(
                        self._permission_worker(flow, peer, dst_port),
                        name=f'perm-{dst_ip}')
                peer.pending.append((dst_port, payload))
                continue
            await flow.client.send_datagram(dst_ip, dst_port, payload)
            self.stats.forwarded += 1

    async def _permission_worker(self, flow: Flow, peer: PeerState,
                                 port: int) -> None:
        if flow.client is None:
            peer.inflight = False
            return
        try:
            await self._bucket.take()
            if flow.client is None:
                return
            await flow.client.create_permission(peer.ip, port)
            peer.ready = True
            peer.last_permission = time.monotonic()
            while peer.pending:
                dst_port, payload = peer.pending.popleft()
                await flow.client.send_datagram(peer.ip, dst_port, payload)
                self.stats.forwarded += 1
        except TurnError as exc:
            peer.ready = False
            log.debug('CreatePermission %s failed: %s', peer.ip, exc)
        except Exception as exc:
            peer.ready = False
            log.warning('CreatePermission %s failed unexpectedly: %s',
                        peer.ip, exc, exc_info=True)
        finally:
            peer.inflight = False

    def _prune_peers(self, flow: Flow, now: float, want: int = 0) -> None:
        ttl = self.cfg.peer_idle_ttl_secs
        for ip in [ip for ip, p in flow.peers.items()
                   if now - p.last_seen > ttl]:
            del flow.peers[ip]
            log.debug('peer %s pruned (idle)', ip)
        if want and len(flow.peers) > want:
            ordered = sorted(flow.peers.values(), key=lambda p: p.last_seen)
            for peer in ordered[:len(flow.peers) - want]:
                del flow.peers[peer.ip]
                log.debug('peer %s evicted (table full)', peer.ip)

    async def _outbound_worker(self) -> None:
        assert self._packet_q is not None
        while True:
            parsed, ifidx, subifidx = await self._packet_q.get()
            src_ip, src_port, dst_ip, dst_port, payload = parsed
            key = (src_ip, src_port)
            flow = self._flow_map.get(key)
            if flow is None:
                flow = await self._new_flow(
                    key, (src_ip, src_port, ifidx, subifidx))
            flow.last_seen = time.monotonic()
            flow.ipkts += 1
            flow.ibytes += len(payload)
            if len(payload) > flow.imax:
                flow.imax = len(payload)
            flow.iremotes.add((dst_ip, dst_port))
            if len(self._alloc_addrs) < 4096:
                self._alloc_addrs.add((dst_ip, dst_port))
            try:
                flow.q.put_nowait((dst_ip, dst_port, payload))
            except asyncio.QueueFull:
                self.stats.dropped += 1

    async def _new_flow(self, key: Tuple[str, int], local: LOCAL_END) -> Flow:
        if len(self._flow_map) >= self.max_flows:
            vic_key = min(self._flow_map,
                          key=lambda k: self._flow_map[k].last_seen)
            victim = self._flow_map.pop(vic_key)
            log.warning('flow budget (%d) hit - closing the allocation of '
                        'local %s:%d', self.max_flows, victim.local[0],
                        victim.local[1])
            await self._close_flow(victim)
        flow = Flow(local)
        self._flow_map[key] = flow
        flow.pump = asyncio.create_task(self._flow_pump(flow),
                                        name=f'pump-{local[1]}')
        log.info('new local socket %s:%d -> its own TURN allocation '
                 '(replies stay separable per socket)', local[0], local[1])
        return flow

    async def _close_flow(self, flow: Flow) -> None:
        tasks = [t for t in (flow.pump, flow.keepalive) if t is not None]
        for task in tasks:
            task.cancel()
        if flow.client is not None:
            try:
                await flow.client.close()
            except Exception:
                pass
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _permission_refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.permission_refresh_secs)
            now = time.monotonic()
            ttl = self.cfg.peer_idle_ttl_secs
            for key, flow in list(self._flow_map.items()):
                if now - flow.last_seen > ttl:
                    log.debug('local %s:%d idle - closing its allocation',
                              flow.local[0], flow.local[1])
                    self._flow_map.pop(key)
                    await self._close_flow(flow)
                    continue
                if flow.client is None:
                    continue
                self._prune_peers(flow, now)
                for peer in list(flow.peers.values()):
                    if not peer.ready or peer.inflight:
                        continue
                    try:
                        await self._bucket.take()
                        if self._flow_map.get(key) is not flow \
                                or flow.client is None:
                            break
                        await flow.client.create_permission(peer.ip)
                        peer.last_permission = now
                    except TurnError as exc:
                        peer.ready = False
                        log.warning('permission refresh for %s failed: %s '
                                    '- will retry on the next packet',
                                    peer.ip, exc)
                    except Exception as exc:
                        peer.ready = False
                        log.warning('permission refresh for %s failed '
                                    'unexpectedly: %s', peer.ip, exc,
                                    exc_info=True)

    def _open_sniff(self) -> WinDivertHandle:
        from .windivert import WINDIVERT_FLAG_SNIFF
        return open_handle('outbound and (udp or tcp)',
                           self.cfg.wd_priority - 50,
                           flags=WINDIVERT_FLAG_SNIFF)

    def _start_sniff_thread(self) -> None:
        handle = self._sniff_handle
        assert handle is not None and self._sniff_q is not None
        loop = asyncio.get_running_loop()

        def worker() -> None:
            try:
                while not handle.closed:
                    got = handle.recv()
                    if got is None:
                        break
                    desc = packets.describe_packet(got[0])
                    if desc is None:
                        continue
                    try:
                        loop.call_soon_threadsafe(self._sniff_put, desc)
                    except RuntimeError:
                        break
            except WinDivertError as exc:
                log.error('sniff failed: %s', exc)
                handle.close()
            log.debug('sniff thread exiting (handle closed=%s)',
                      handle.closed)

        t = threading.Thread(target=worker, name='windivert-sniff',
                             daemon=True)
        t.start()
        self._sniff_thread = t

    def _sniff_put(self, desc: tuple) -> None:
        q = self._sniff_q
        if q is None:
            return
        if q.qsize() >= 4000:
            self.stats.sniff_dropped += 1
            return
        q.put_nowait(desc)

    async def _sniff_worker(self) -> None:
        assert self._sniff_q is not None
        while True:
            proto, _src, dst, _sport, dport, nbytes = \
                await self._sniff_q.get()
            key = (proto, dst, dport)
            f = self._sniff_flows.get(key)
            if f is None:
                f = self._sniff_flows[key] = {'pkts': 0, 'bytes': 0,
                                              'max': 0}
            f['pkts'] += 1
            f['bytes'] += nbytes
            if nbytes > f['max']:
                f['max'] = nbytes

    async def _stop_sniff(self) -> None:
        handle, t = self._sniff_handle, self._sniff_thread
        self._sniff_handle = None
        self._sniff_thread = None
        if handle is not None:
            handle.close()
        if t is not None and t.is_alive():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: t.join(timeout=3))

    async def _dry_run(self) -> None:
        assert self._turn is not None
        perm_ip = ''
        perm_at = 0.0
        while not self._stop.is_set():
            try:
                loop = asyncio.get_running_loop()
                infos = await loop.getaddrinfo(
                    self.probe_target[0], self.probe_target[1],
                    family=socket.AF_INET, type=socket.SOCK_DGRAM)
                ip = infos[0][4][0]
                now = time.monotonic()
                if ip != perm_ip or now - perm_at > 240.0:
                    await self._turn.create_permission(ip)
                    perm_ip, perm_at = ip, now
                txid = stun.new_txid()
                self._probe_txid = txid
                self._probe_sent_at = time.monotonic()
                await self._turn.send_datagram(
                    ip, self.probe_target[1],
                    packets.build_stun_binding_request(txid))
            except (TurnError, OSError) as exc:
                raise TurnError(f'probe failed: {exc}') from exc
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass

    async def _capture_only(self) -> None:
        packet_q: asyncio.Queue = asyncio.Queue(maxsize=4096)
        self._packet_q = packet_q
        await self._refresh_cidrs()
        self._handle = self._open_capture(sniff=True)
        self._start_capture_thread(sniff=True)
        shown = 0
        try:
            while not self._stop.is_set():
                try:
                    parsed = await asyncio.wait_for(packet_q.get(), 5)
                except asyncio.TimeoutError:
                    log.info('%s', self.stats.line(None, '(sniff mode)'))
                    continue
                if shown < 20:
                    src, sport, dst, dport, payload = parsed
                    log.info('would divert: %s:%d -> %s:%d (%d bytes, '
                             'first bytes %s)', src, sport, dst, dport,
                             len(payload), payload[:16].hex())
                    shown += 1
        finally:
            await self._stop_capture()

    async def _ensure_turn(self) -> TurnClient:
        await self._ensure_credentials()
        client = TurnClient(TurnUrl.parse(self.cfg.turn.url),
                            self.cfg.turn.username,
                            self.cfg.turn.credential)
        client.on_data = self._on_data
        await allocate_and_start(client)
        self._turn = client
        return client

    async def _session_full(self) -> None:
        await self._refresh_cidrs()
        self._packet_q = asyncio.Queue(maxsize=4096)
        self._handle = self._open_capture(sniff=False)
        self._start_capture_thread(sniff=False)
        self._alloc_addrs.clear()
        if self.sniff_outbound:
            self._sniff_q = asyncio.Queue()
            self._sniff_handle = self._open_sniff()
            self._start_sniff_thread()
            log.info('sniff-outbound active: logging every outbound UDP/TCP '
                     'flow the relay does NOT divert (priority %d)',
                     self.cfg.wd_priority - 50)

        tasks = [
            asyncio.create_task(self._outbound_worker(), name='outbound'),
            asyncio.create_task(self._permission_refresh_loop(),
                                name='perm-refresh'),
            asyncio.create_task(self._stats_loop(_AggTurn(self._flow_map)),
                                name='stats'),
            asyncio.create_task(self._credential_watch_loop(),
                                name='cred-refresh'),
            asyncio.create_task(self._cidr_watch_loop(), name='cidr-watch'),
        ]
        if self.sniff_outbound:
            tasks.append(asyncio.create_task(self._sniff_worker(),
                                             name='sniff'))
        log.info('relay live: diverting UDP to %s (priority %d)',
                 ', '.join(self.cidrs[:3]) + (' ...' if len(self.cidrs) > 3 else ''),
                 self.cfg.wd_priority)
        try:
            while True:
                flow_tasks = [t for f in self._flow_map.values()
                              for t in (f.pump, f.keepalive)
                              if t is not None]
                done, _pending = await asyncio.wait(
                    tasks + flow_tasks,
                    return_when=asyncio.FIRST_EXCEPTION, timeout=1.0)
                fatal = None
                for task in done:
                    if task.cancelled():
                        continue
                    exc = task.exception()
                    if exc is not None:
                        fatal = exc
                        break
                if fatal is not None:
                    raise fatal
                if self._stop.is_set():
                    break
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._stop_sniff()
            await self._stop_capture()
            flows = list(self._flow_map.values())
            self._flow_map.clear()
            for flow in flows:
                await self._close_flow(flow)

    async def _session(self) -> None:
        if not (self.dry_run or self.capture_only):
            await self._session_full()
            return
        client = await self._ensure_turn()

        if self.dry_run:
            keepalive = asyncio.create_task(client.keepalive_loop(),
                                            name='turn-keepalive')
            probe = asyncio.create_task(self._dry_run(), name='dry-run-probe')
            stats_task = asyncio.create_task(self._stats_loop(client),
                                             name='stats')
            cred_task = asyncio.create_task(self._credential_watch_loop(),
                                            name='cred-refresh')
            tasks = [keepalive, probe, stats_task, cred_task]
            try:
                await asyncio.wait(tasks,
                                   return_when=asyncio.FIRST_EXCEPTION)
                for task in tasks:
                    if task.exception():
                        raise task.exception()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await client.close()
                self._turn = None
            return

        if self.capture_only:
            stats_task = asyncio.create_task(self._stats_loop(client),
                                             name='stats')
            try:
                await self._capture_only()
            finally:
                stats_task.cancel()
                await asyncio.gather(stats_task, return_exceptions=True)
                await client.close()
                self._turn = None
            return


    async def _stats_loop(self, client) -> None:
        while True:
            await asyncio.sleep(self.cfg.stats_interval_secs)
            if (not self.dry_run and not self.capture_only
                    and self._capture_thread is not None
                    and not self._capture_thread.is_alive()
                    and not self._stop.is_set()):
                raise TurnError('WinDivert capture thread died - '
                                'restarting the session')
            extra = ''
            if not (self.dry_run or self.capture_only):
                peers = ready = 0
                for flow in self._flow_map.values():
                    peers += len(flow.peers)
                    ready += sum(1 for p in flow.peers.values() if p.ready)
                extra = (f'peers={peers} ready={ready} '
                         f'allocs={len(self._flow_map)} '
                         f'addrs={len(self._alloc_addrs)}')
                self._report_flows()
                self._report_sniff()
            if self.stats.sniff_dropped:
                extra += f' sniff_drop={self.stats.sniff_dropped}'
            log.info('%s', self.stats.line(client, extra))

    def _report_flows(self) -> None:
        parts = []
        interval = max(1.0, self.cfg.stats_interval_secs)
        for flow in self._flow_map.values():
            if not flow.ipkts:
                continue
            kbps = flow.ibytes * 8 / interval / 1000
            remotes = ','.join(f'{ip}:{p}' for ip, p in
                               sorted(flow.iremotes))
            parts.append(f'local:{flow.local[1]}->{remotes} '
                         f'{flow.ipkts}pkt {flow.ibytes}B '
                         f'max{flow.imax} {kbps:.1f}kbps')
            flow.ipkts = 0
            flow.ibytes = 0
            flow.imax = 0
            flow.iremotes = set()
        if parts:
            log.info('tunneled: %s', ' | '.join(parts))

    def _report_sniff(self) -> None:
        if not self._sniff_flows:
            return
        parts = []
        for (proto, ip, port), f in sorted(self._sniff_flows.items(),
                                           key=lambda kv: -kv[1]['bytes'])[:10]:
            try:
                addr = ipaddress.ip_address(ip)
                in_tg = addr.version == 4 and any(
                    addr in net for net in self._cidr_nets)
            except ValueError:
                in_tg = False
            mark = ('TG-BUT-NOT-DIVERTED!'
                    if in_tg and proto == 'udp' else 'outside-tg')
            parts.append(f'{proto} {ip}:{port} {f["pkts"]}pkt '
                         f'{f["bytes"]}B [{mark}]')
        log.info('NOT tunneled: %s', ' | '.join(parts))
        self._sniff_flows = {}

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except TurnConfigError as exc:
                if self.cfg.turn.can_mint:
                    log.warning('TURN credentials are not ready yet: %s', exc)
                else:
                    log.error('%s', exc)
                    raise SystemExit(2) from None
            except TurnError as exc:
                if '401' in str(exc) or '441' in str(exc):
                    self._creds_expire_at = 0.0
                log.error('%s', exc)
            except WinDivertError as exc:
                log.error('%s', exc)
                if exc.code in FATAL_WINDIVERT_ERRORS:
                    log.error(
                        'WinDivert cannot start: check that zapret\\bin '
                        'contains WinDivert.dll and WinDivert64.sys, reinstall '
                        'the app if they are missing, and run it as '
                        'administrator')
                    raise SystemExit(3) from None
            except OSError as exc:
                log.error('network error: %s', exc)
            finally:
                await self._stop_capture()
                for flow in list(self._flow_map.values()):
                    await self._close_flow(flow)
                self._flow_map.clear()
                if self._turn is not None:
                    try:
                        await self._turn.close()
                    except Exception:
                        pass
                    self._turn = None
            if self._stop.is_set():
                break
            log.info('reconnecting in %.0fs', backoff)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(30.0, backoff * 2)
        log.info('relay stopped: %s', self.stats.line(None))

    def stop(self) -> None:
        self._stop.set()
        handle = self._handle
        if handle is not None:
            handle.shutdown_recv()
        sniff = self._sniff_handle
        if sniff is not None:
            sniff.shutdown_recv()