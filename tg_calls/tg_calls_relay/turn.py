from __future__ import annotations

import asyncio
import logging
import ssl
import struct
import time
from typing import Awaitable, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from . import stun
from .stun import StunError, StunMessage

log = logging.getLogger('tg-calls-relay')

DataCallback = Callable[[str, int, bytes], Awaitable[None]]

DEFAULT_REQUEST_TIMEOUT = 10.0


class TurnError(Exception):
    pass


class TurnConfigError(TurnError):
    pass


class TurnUrl:

    def __init__(self, host: str, port: int, tls: bool, url: str):
        self.host = host
        self.port = port
        self.tls = tls
        self.url = url

    @classmethod
    def parse(cls, url: str) -> 'TurnUrl':
        raw = url.strip()
        if '://' not in raw:
            raw = 'turn://' + raw
        parsed = urlparse(raw)
        scheme = (parsed.scheme or '').lower()
        if scheme == 'stun':
            raise TurnError(f'{url!r} is a STUN URL - a TURN URL is required')
        if scheme not in ('turn', 'turns'):
            raise TurnError(f'unsupported TURN URL scheme in {url!r}')
        host = parsed.hostname
        if not host:
            raise TurnError(f'no host in TURN URL {url!r}')
        tls = scheme == 'turns'
        try:
            port = parsed.port or (5349 if tls else 3478)
        except ValueError as exc:
            raise TurnError(f'bad port in TURN URL {url!r}: {exc}') from exc
        return cls(host=host, port=port, tls=tls, url=url.strip())

    def __str__(self) -> str:
        scheme = 'turns' if self.tls else 'turn'
        return f'{scheme}://{self.host}:{self.port}'


def _xor_peer(ip: str, port: int) -> bytes:
    return stun.pack_xor_address(ip, port)


class TurnClient:

    def __init__(self, url: TurnUrl, username: str, credential: str,
                 *, request_timeout: float = DEFAULT_REQUEST_TIMEOUT):
        self.url = url
        self.username = username
        self.credential = credential
        self.request_timeout = request_timeout

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._closed = False

        self._realm = ''
        self._nonce = ''
        self._key: Optional[bytes] = None
        self._pending: Dict[bytes, asyncio.Future] = {}
        self._expected: Dict[bytes, Tuple[int, ...]] = {}

        self.relayed_addr: Optional[Tuple[str, int]] = None
        self.lifetime = 600
        self.on_data: Optional[DataCallback] = None

        self.stats = {'sent': 0, 'received': 0, 'allocations': 0,
                      'permission_ok': 0, 'refresh_ok': 0, 'errors': 0}

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._closed

    def set_credentials(self, username: str, credential: str) -> None:
        if username == self.username and credential == self.credential:
            return
        self.username = username
        self.credential = credential
        self._key = None
        log.info('TURN credentials rotated for the live allocation')

    async def connect(self) -> None:
        ssl_ctx: Optional[ssl.SSLContext] = None
        server_hostname: Optional[str] = None
        if self.url.tls:
            ssl_ctx = ssl.create_default_context()
            server_hostname = self.url.host
        log.info('connecting to %s%s', self.url,
                 ' (TLS)' if self.url.tls else '')
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.url.host, self.url.port,
                    ssl=ssl_ctx, server_hostname=server_hostname),
                timeout=self.request_timeout)
        except asyncio.TimeoutError:
            raise TurnError(
                f'connect to {self.url} timed out at the TCP/TLS stage'
            ) from None
        except (OSError, ssl.SSLError) as exc:
            raise TurnError(f'connect to {self.url} failed: {exc}') from exc

        self._closed = False
        self._recv_task = asyncio.create_task(self._recv_loop(),
                                              name='turn-recv')

    async def close(self) -> None:
        self._closed = True
        task = self._recv_task
        self._recv_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        writer = self._writer
        if writer is not None:
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), 3)
            except (asyncio.TimeoutError, OSError, RuntimeError):
                transport = getattr(writer, 'transport', None)
                if transport is not None:
                    try:
                        transport.abort()
                    except Exception:
                        pass
            except Exception:
                pass
            self._writer = None
            self._reader = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(TurnError('connection closed'))
        self._pending.clear()
        self._expected.clear()

    async def _recv_loop(self) -> None:
        assert self._reader is not None
        buf = bytearray()
        try:
            while not self._closed:
                chunk = await self._reader.read(65536)
                if not chunk:
                    raise TurnError('TURN control connection closed by peer')
                buf += chunk
                while True:
                    raw = stun.parse_stream_chunk(buf)
                    if raw is None:
                        break
                    if raw[0] & 0xC0 == 0x40:
                        log.warning('unexpected ChannelData on control conn')
                        continue
                    self._dispatch(stun.parse_message(raw))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err = exc if isinstance(exc, TurnError) else TurnError(str(exc))
            log.warning('TURN read loop stopped: %s', err, exc_info=True)
            self._closed = True
            self._fail_pending(err)
            if self._writer is not None:
                try:
                    self._writer.close()
                except Exception:
                    pass

    def _fail_pending(self, exc: TurnError) -> None:
        self.stats['errors'] += 1
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    def _dispatch(self, msg: StunMessage) -> None:
        if msg.msg_type == stun.MSG_DATA_IND:
            self.stats['received'] += 1
            peer = msg.first(stun.ATTR_XOR_PEER_ADDRESS)
            data = msg.first(stun.ATTR_DATA)
            if peer is None or data is None:
                log.debug('Data indication without peer/data, ignored')
                return
            try:
                ip, port = stun.unpack_xor_address(peer)
            except StunError as exc:
                log.debug('bad peer address in Data indication: %s', exc)
                return
            if self.on_data is not None:
                try:
                    result = self.on_data(ip, port, data)
                    if asyncio.iscoroutine(result):
                        task = asyncio.ensure_future(result)
                        task.add_done_callback(_log_callback_error)
                except Exception:
                    log.warning('TURN data callback failed', exc_info=True)
            return

        fut = self._pending.pop(msg.txid, None)
        expected = self._expected.pop(msg.txid, None)
        if fut is None or fut.done():
            log.debug('unmatched STUN response type=0x%04x', msg.msg_type)
            return
        if expected is not None and msg.msg_type not in expected:
            if not msg.is_error:
                fut.set_exception(TurnError(
                    f'expected types {[hex(t) for t in expected]}, '
                    f'got 0x{msg.msg_type:04x}'))
                return
        fut.set_result(msg)

    async def _request(self, builder: 'stun.StunBuilder',
                       expected: Tuple[int, ...],
                       *, timeout: Optional[float] = None,
                       auth: bool = True) -> StunMessage:
        if self._writer is None or self._closed:
            raise TurnError('not connected')
        if auth:
            if not self._realm or not self._nonce:
                raise TurnError('no realm/nonce yet - Allocate first')
            if self._key is None:
                self._key = stun.integrity_key(
                    self.username, self._realm, self.credential)
            builder.add(stun.ATTR_USERNAME, self.username.encode('utf-8'))
            builder.add(stun.ATTR_REALM, self._realm.encode('utf-8'))
            builder.add(stun.ATTR_NONCE, self._nonce.encode('utf-8'))
            builder.add_message_integrity(self._key)
        builder.add_fingerprint()

        fut = asyncio.get_running_loop().create_future()
        self._pending[builder.txid] = fut
        self._expected[builder.txid] = expected
        data = builder.build()
        self._writer.write(data)
        try:
            await self._writer.drain()
        except (ConnectionError, OSError) as exc:
            self._pending.pop(builder.txid, None)
            self._expected.pop(builder.txid, None)
            raise TurnError(f'send failed: {exc}') from exc
        try:
            return await asyncio.wait_for(fut, timeout or self.request_timeout)
        except asyncio.TimeoutError:
            raise TurnError(
                f'no response to STUN type 0x{builder.msg_type:04x} '
                f'within {timeout or self.request_timeout:.0f}s') from None
        finally:
            self._pending.pop(builder.txid, None)
            self._expected.pop(builder.txid, None)

    async def _request_with_nonce_refresh(self, builder_factory: Callable[[], 'stun.StunBuilder'],
                                          expected: Tuple[int, ...]) -> StunMessage:
        msg = await self._request(builder_factory(), expected)
        if msg.error_code == stun.ERR_STALE_NONCE:
            log.info('stale nonce, refreshing')
            self._capture_nonce(msg)
            msg = await self._request(builder_factory(), expected)
        if msg.is_error and msg.error_code == stun.ERR_STALE_NONCE:
            raise TurnError('nonce still stale after refresh')
        return msg

    def _capture_nonce(self, msg: StunMessage) -> None:
        realm = msg.realm()
        nonce = msg.nonce()
        if realm:
            if realm != self._realm:
                self._key = None
            self._realm = realm
        if nonce:
            self._nonce = nonce

    async def allocate(self) -> None:

        def factory() -> stun.StunBuilder:
            b = stun.StunBuilder(stun.MSG_ALLOCATE)
            b.add(stun.ATTR_REQUESTED_TRANSPORT,
                  bytes([stun.TRANSPORT_UDP, 0, 0, 0]))
            return b

        msg = await self._request(
            factory(), (stun.MSG_ALLOCATE_OK,),
            auth=False)
        if msg.error_code not in (stun.ERR_UNAUTHORIZED, None) and msg.is_error:
            raise TurnError(
                f'Allocate rejected: {msg.error_code} {msg.error_reason}')
        if msg.msg_type != stun.MSG_ALLOCATE_OK:
            self._capture_nonce(msg)
            msg = await self._request_with_nonce_refresh(
                factory, (stun.MSG_ALLOCATE_OK,))
        if msg.is_error:
            code = msg.error_code
            hint = ''
            if code == stun.ERR_WRONG_CREDENTIALS:
                hint = ' (wrong username/credential)'
            elif code == stun.ERR_UNSUPPORTED_TRANSPORT:
                hint = ' (server refused a UDP relay allocation)'
            raise TurnError(
                f'Allocate failed: {code} {msg.error_reason}{hint}')

        self.lifetime = msg.lifetime()
        relayed = msg.first(stun.ATTR_XOR_RELAYED_ADDRESS)
        if relayed:
            try:
                self.relayed_addr = stun.unpack_xor_address(relayed)
            except StunError:
                self.relayed_addr = None
        self.stats['allocations'] += 1
        log.info('allocation ready: relayed=%s lifetime=%ds',
                 self.relayed_addr or '?', self.lifetime)

    async def create_permission(self, ip: str, port: int = 0) -> None:

        def factory() -> stun.StunBuilder:
            b = stun.StunBuilder(stun.MSG_CREATE_PERMISSION)
            b.add(stun.ATTR_XOR_PEER_ADDRESS, _xor_peer(ip, port))
            return b

        msg = await self._request_with_nonce_refresh(
            factory, (stun.MSG_CREATE_PERMISSION_OK,))
        if msg.is_error:
            raise TurnError(
                f'CreatePermission {ip} failed: '
                f'{msg.error_code} {msg.error_reason}')
        self.stats['permission_ok'] += 1

    async def send_datagram(self, ip: str, port: int, payload: bytes) -> None:
        if self._writer is None or self._closed:
            raise TurnError('not connected')
        b = stun.StunBuilder(stun.MSG_SEND_IND)
        b.add(stun.ATTR_XOR_PEER_ADDRESS, _xor_peer(ip, port))
        b.add(stun.ATTR_DATA, payload)
        self._writer.write(b.build())
        try:
            await self._writer.drain()
            self.stats['sent'] += 1
        except (ConnectionError, OSError) as exc:
            raise TurnError(f'send failed: {exc}') from exc

    async def refresh(self) -> None:
        if self.lifetime <= 0:
            raise TurnError(f'invalid allocation lifetime: {self.lifetime}')

        def factory() -> stun.StunBuilder:
            b = stun.StunBuilder(stun.MSG_REFRESH)
            b.add_u32(stun.ATTR_LIFETIME, self.lifetime)
            return b

        msg = await self._request_with_nonce_refresh(
            factory, (stun.MSG_REFRESH_OK,))
        if msg.is_error:
            if msg.error_code == stun.ERR_CONNECTION_TIMEOUT:
                raise TurnError('allocation expired (437)')
            raise TurnError(
                f'Refresh failed: {msg.error_code} {msg.error_reason}')
        self.lifetime = msg.lifetime()
        self.stats['refresh_ok'] += 1

    async def keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(max(30.0, self.lifetime / 2))
                started = time.monotonic()
                await self.refresh()
                log.debug('Refresh ok in %.0f ms, lifetime=%ds',
                          (time.monotonic() - started) * 1000, self.lifetime)
        except asyncio.CancelledError:
            raise
        except TurnError as exc:
            log.warning('TURN keepalive failed (%s) - closing the '
                        'allocation', exc)
            self._closed = True
            self._fail_pending(exc)
            try:
                await self.close()
            except Exception:
                log.debug('closing a failed TURN client raised', exc_info=True)
            raise


def _log_callback_error(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        log.warning('TURN data callback failed: %s', exc, exc_info=exc)


async def allocate_and_start(client: TurnClient) -> None:
    await client.connect()
    try:
        await client.allocate()
    except BaseException:
        await client.close()
        raise