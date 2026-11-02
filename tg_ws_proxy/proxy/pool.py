import asyncio
import logging
import random
import time

from collections import deque
from urllib.parse import urlencode
from typing import Dict, List, Optional, Tuple

from .raw_websocket import RawWebSocket, WsHandshakeError
from .stats import stats
from .config import proxy_config
from .utils import ws_domains, DC_DEFAULT_IPS, WS_PATH, WS_PATH_TEST

log = logging.getLogger('tg-mtproto-proxy')


class _WsPool:
    WS_POOL_MAX_AGE = 120.0
    WS_POOL_CHECK_INTERVAL = 5.0
    REFILL_BACKOFF_INITIAL = 1.0
    REFILL_BACKOFF_MAX = 3600.0
    
    def __init__(self):
        self._idle: Dict[Tuple[int, bool, bool], deque] = {}
        self._refilling: Dict[Tuple[int, bool, bool], asyncio.Task] = {}
        self._rotating: Dict[Tuple[int, bool, bool], asyncio.Task] = {}
        self._refill_failures: Dict[Tuple[int, bool, bool], int] = {}
        self._refill_after: Dict[Tuple[int, bool, bool], float] = {}
        self.try_fronting_first = False

    async def get(self, dc: int, is_media: bool, *, is_test_dc: bool = False
                  ) -> Optional[RawWebSocket]:
        target_ip = proxy_config.dc_redirects.get(dc)
        if not target_ip or proxy_config.pool_size <= 0:
            return None
        key = (dc, is_media, is_test_dc)
        domains = ws_domains(dc, is_media)
        now = time.monotonic()

        bucket = self._idle.get(key)
        if bucket is None:
            bucket = deque()
            self._idle[key] = bucket
        while bucket:
            ws, created = bucket.popleft()
            age = now - created
            if self._is_stale(ws, created, now):
                asyncio.create_task(self._quiet_close(ws))
                continue
            stats.pool_hits += 1
            log.debug("WS pool hit DC%d%s%s (age=%.1fs, left=%d)",
                      dc, 't' if is_test_dc else '', 'm' if is_media else '', age, len(bucket))
            self._schedule_refill(key, target_ip, domains)
            return ws

        stats.pool_misses += 1
        self._schedule_refill(key, target_ip, domains)
        return None

    def _is_stale(self, ws, created, now):
        return (now - created >= self.WS_POOL_MAX_AGE or ws._closed
                or ws.writer.transport.is_closing() or ws.reader.at_eof()
                or ws.reader.exception() is not None)

    def _schedule_refill(self, key, target_ip, domains):
        if proxy_config.pool_size <= 0:
            return
        self._schedule_rotation(key, target_ip, domains)
        if (key in self._refilling
                or time.monotonic() < self._refill_after.get(key, 0)):
            return
        self._refilling[key] = asyncio.create_task(
            self._refill(key, target_ip, domains))

    async def _refill(self, key, target_ip, domains):
        dc, is_media, is_test_dc = key
        tasks = []
        adopted = set()
        try:
            bucket = self._idle.setdefault(key, deque())
            needed = proxy_config.pool_size - len(bucket)
            if needed <= 0:
                return
            connected = 0
            tasks = [asyncio.create_task(
                self._connect_one(target_ip, domains,
                                  WS_PATH_TEST if is_test_dc else WS_PATH))
                for _ in range(needed)]
            for t in asyncio.as_completed(tasks):
                try:
                    ws = await t
                    if ws:
                        if self._refilling.get(key) is not asyncio.current_task():
                            return
                        bucket.append((ws, time.monotonic()))
                        adopted.add(ws)
                        connected += 1
                except Exception as exc:
                    log.debug("WS pool connect failed: %r", exc)
            if connected:
                self._refill_failures.pop(key, None)
                self._refill_after.pop(key, None)
            else:
                failures = self._refill_failures.get(key, 0) + 1
                self._refill_failures[key] = failures
                delay = min(
                    self.REFILL_BACKOFF_INITIAL
                    * (2 ** min(failures - 1, 12)),
                    self.REFILL_BACKOFF_MAX,
                )
                self._refill_after[key] = time.monotonic() + delay
                log.info(
                    "WS pool refill failed for DC%d%s%s, retry in %.0fs",
                    dc, 't' if is_test_dc else '', 'm' if is_media else '', delay)
            log.debug("WS pool refilled DC%d%s%s: %d ready",
                      dc, 't' if is_test_dc else '', 'm' if is_media else '', len(bucket))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for ws in results:
                if ws is not None and not isinstance(ws, BaseException) and ws not in adopted:
                    await self._quiet_close(ws)
            if self._refilling.get(key) is asyncio.current_task():
                self._refilling.pop(key, None)

    def _schedule_rotation(self, key, target_ip, domains):
        if key in self._rotating:
            return
        self._rotating[key] = asyncio.create_task(
            self._rotate(key, target_ip, domains))

    async def _rotate(self, key, target_ip, domains):
        dc, is_media, is_test_dc = key
        try:
            while proxy_config.pool_size > 0:
                bucket = self._idle.setdefault(key, deque())
                now = time.monotonic()
                expired = []
                ready = deque()
                while bucket:
                    ws, created = bucket.popleft()
                    if self._is_stale(ws, created, now):
                        expired.append(ws)
                    else:
                        ready.append((ws, created))
                bucket.extend(ready)

                if expired:
                    for ws in expired:
                        asyncio.create_task(self._quiet_close(ws))
                    log.debug(
                        "WS pool rotated DC%d%s%s: %d stale, %d ready",
                        dc, 't' if is_test_dc else '', 'm' if is_media else '',
                        len(expired), len(bucket))

                if len(bucket) < proxy_config.pool_size:
                    self._schedule_refill(key, target_ip, domains)

                wake_at = now + self.WS_POOL_CHECK_INTERVAL
                if bucket:
                    wake_at = min(wake_at, min(
                        created + self.WS_POOL_MAX_AGE for _, created in bucket))
                if key not in self._refilling and self._refill_after.get(key, 0) > now:
                    wake_at = min(wake_at, self._refill_after[key])
                await asyncio.sleep(max(0, wake_at - time.monotonic()))
        finally:
            if self._rotating.get(key) is asyncio.current_task():
                self._rotating.pop(key, None)

    async def _connect_one(self, target_ip, domains, path=WS_PATH) -> Optional[RawWebSocket]:
        for domain in domains:
            modes = (True, False) if self.try_fronting_first else (False, True)
            for fronted in modes:
                try:
                    ws = await RawWebSocket.connect(
                        target_ip, domain, timeout=7 if fronted else 8, path=path,
                        sni="sprinthost.ru" if fronted else None)
                except Exception as exc:
                    stats.ws_errors += 1
                    log.debug("WS pool connect %s%s via %s (fronting=%s): %r",
                              domain, path, target_ip, fronted, exc)
                    continue
                self.try_fronting_first = fronted
                if fronted:
                    stats.connections_fronting += 1
                log.debug("WS pool connected %s%s via %s (fronting=%s)",
                          domain, path, target_ip, fronted)
                return ws
        return None

    async def _quiet_close(self, ws):
        try:
            await ws.close()
        except Exception:
            pass

    async def warmup(self):
        if proxy_config.pool_size <= 0:
            log.info("Direct WS pool disabled (pool_size=0)")
            return
        for dc, target_ip in proxy_config.dc_redirects.items():
            if target_ip is None:
                continue
            for is_media in (False, True):
                domains = ws_domains(dc, is_media)
                key = (dc, is_media, proxy_config.force_test_dc)
                self._schedule_refill(key, target_ip, domains)
        log.info("WS pool warmup started for %d DC(s)", len(proxy_config.dc_redirects))

    def reset(self):
        loop = asyncio.get_running_loop()
        for task in list(self._rotating.values()) + list(self._refilling.values()):
            if not task.done() and task.get_loop() is loop:
                task.cancel()
        for bucket in self._idle.values():
            for ws, _ in bucket:
                try:
                    ws.writer.close()
                except Exception as exc:
                    log.debug("WS pool close failed: %r", exc)
        self._idle.clear()
        self._refilling.clear()
        self._rotating.clear()
        self._refill_failures.clear()
        self._refill_after.clear()
        self.try_fronting_first = False

    async def close(self):
        tasks = list(self._rotating.values()) + list(self._refilling.values())
        self.reset()
        await asyncio.gather(*tasks, return_exceptions=True)


class _CfWorkerPool:

    WS_POOL_MAX_AGE = 100.0
    PER_DC_LIMIT = 6
    SOFT_COOLDOWN = 60.0
    SOFT_COOLDOWN_MAX = 1800.0
    HARD_COOLDOWN = 600.0
    DAILY_COOLDOWN = 86400.0

    def __init__(self):
        self._idle: Dict[int, deque] = {}
        self._refilling: Dict[int, asyncio.Task] = {}
        self._exhausted_until: Dict[str, float] = {}
        self._soft_failures: Dict[str, int] = {}
        self._rr_index: Dict[int, int] = {}

    async def get(self, dc: int, fallback_dst: str,
                  worker_domains: List[str]
                  ) -> Optional[Tuple[RawWebSocket, str]]:
        now = time.monotonic()

        bucket = self._idle.get(dc)
        if bucket is None:
            bucket = deque()
            self._idle[dc] = bucket
        while bucket:
            ws, created, worker_domain = bucket.popleft()
            age = now - created
            if (age > self.WS_POOL_MAX_AGE or ws._closed
                    or ws.writer.transport.is_closing()
                    or not await self._is_alive(ws)):
                asyncio.create_task(self._quiet_close(ws))
                continue
            stats.cf_pool_hits += 1
            log.debug(
                "CF worker pool hit DC%d via %s (age=%.1fs, left=%d)",
                dc, worker_domain, age, len(bucket))
            self._schedule_refill(dc, fallback_dst, worker_domains)
            return ws, worker_domain

        stats.cf_pool_misses += 1
        self._schedule_refill(dc, fallback_dst, worker_domains)
        return None

    async def _is_alive(self, ws) -> bool:
        if ws._closed or ws.writer.transport.is_closing():
            return False
        if ws.reader.at_eof() or ws.reader.exception() is not None:
            return False
        return not getattr(ws.reader, '_buffer', b'')

    def _schedule_refill(self, dc, fallback_dst, worker_domains):
        if dc in self._refilling:
            return
        self._refilling[dc] = asyncio.create_task(self._refill(
            dc, fallback_dst, list(worker_domains)))

    async def _refill(self, dc, fallback_dst, worker_domains):
        tasks = []
        adopted = set()
        try:
            bucket = self._idle.setdefault(dc, deque())
            target_size = min(max(1, proxy_config.worker_pool_size),
                              self.PER_DC_LIMIT)
            needed = target_size - len(bucket)
            if needed <= 0:
                return

            tasks = [asyncio.create_task(
                self._connect_one(worker_domains, fallback_dst, dc))
                for _ in range(needed)]
            for connect in asyncio.as_completed(tasks):
                try:
                    connected = await connect
                except Exception as exc:
                    log.debug("CF worker connect failed: %r", exc)
                    continue
                if connected is None:
                    continue
                ws, worker_domain = connected
                if self._refilling.get(dc) is not asyncio.current_task():
                    return
                bucket.append((ws, time.monotonic(), worker_domain))
                adopted.add(ws)
            log.debug("CF worker pool refilled DC%d: %d ready (%s)",
                      dc, len(bucket),
                      ", ".join(sorted({d for _, _, d in bucket})) or "none")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                try:
                    connected = await task
                except BaseException:
                    continue
                if (connected is not None and connected[0] not in adopted
                        and all(connected[0] is not ws for ws, _, _ in
                                self._idle.get(dc, ()))):
                    await self._quiet_close(connected[0])
            if self._refilling.get(dc) is asyncio.current_task():
                self._refilling.pop(dc, None)

    async def _connect_one(self, worker_domains, fallback_dst, dc):
        query = urlencode({
            'dst': fallback_dst,
            'dc': str(dc),
        })
        path = f'/apiws?{query}'
        ordered = self._ordered_domains(dc, worker_domains)
        now = time.time()
        live = [d for d in ordered
                if self._exhausted_until.get(d, 0) <= now]
        for worker_domain in (live or ordered):
            try:
                ws = await RawWebSocket.connect(
                    worker_domain, worker_domain, timeout=4, path=path,
                    secure=not proxy_config.disable_secure)
                log.debug("CF worker connect DC%d via %s", dc, worker_domain)
                self.report_success(worker_domain)
                return ws, worker_domain
            except Exception as exc:
                self.report_failure(worker_domain, exc)
        return None

    def is_parked(self, worker_domain: str) -> bool:
        return self._exhausted_until.get(worker_domain, 0) > time.time()

    def _ordered_domains(self, dc: int, worker_domains: List[str]) -> List[str]:
        now = time.time()
        live: List[str] = []
        cooling: List[str] = []
        for domain in worker_domains:
            if domain in live or domain in cooling:
                continue
            if self._exhausted_until.get(domain, 0) > now:
                cooling.append(domain)
            else:
                live.append(domain)
        if not live:
            live, cooling = cooling, []
        if not live:
            return []
        start = self._rr_index.get(dc, 0) % len(live)
        self._rr_index[dc] = start + 1
        return live[start:] + live[:start] + cooling

    def available_domains(self, worker_domains: List[str],
                          dc: Optional[int] = None) -> List[str]:
        if dc is not None:
            return self._ordered_domains(dc, worker_domains)
        now = time.time()
        domains = []
        for domain in worker_domains:
            if domain in domains:
                continue
            if self._exhausted_until.get(domain, 0) > now:
                continue
            domains.append(domain)
        random.shuffle(domains)
        return domains

    def report_failure(self, worker_domain: str, exc: Exception) -> None:
        now = time.time()
        status = exc.status_code if isinstance(exc, WsHandshakeError) else None
        if status == 429:
            until = now + (self.DAILY_COOLDOWN - (now % self.DAILY_COOLDOWN))
            self._park(worker_domain, until)
            self._soft_failures.pop(worker_domain, None)
            log.warning(
                "CF worker %s reached its daily request limit (429), "
                "disabled until %s", worker_domain,
                time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(until)))
            return
        if status in (403, 1015):
            self._park(worker_domain, now + self.HARD_COOLDOWN)
            self._soft_failures.pop(worker_domain, None)
            log.warning("CF worker %s answered HTTP %s, paused for %.0fs",
                        worker_domain, status, self.HARD_COOLDOWN)
            return
        failures = self._soft_failures.get(worker_domain, 0) + 1
        self._soft_failures[worker_domain] = failures
        delay = min(self.SOFT_COOLDOWN * (2 ** (failures - 1)),
                    self.SOFT_COOLDOWN_MAX)
        self._park(worker_domain, now + delay)
        log.debug("CF worker %s failed (%s) x%d, paused for %.0fs",
                  worker_domain, type(exc).__name__, failures, delay)

    def report_success(self, worker_domain: str) -> None:
        self._soft_failures.pop(worker_domain, None)

    def _park(self, worker_domain: str, until: float) -> None:
        self._exhausted_until[worker_domain] = max(
            self._exhausted_until.get(worker_domain, 0), until)

    def snapshot(self, worker_domains: List[str]
                 ) -> List[Tuple[str, int, float]]:
        now = time.time()
        warm: Dict[str, int] = {}
        for bucket in self._idle.values():
            for _, _, domain in bucket:
                warm[domain] = warm.get(domain, 0) + 1
        return [
            (domain, warm.get(domain, 0),
             max(0.0, self._exhausted_until.get(domain, 0) - now))
            for domain in dict.fromkeys(worker_domains)
        ]

    def pool_sizes(self) -> Dict[int, int]:
        return {dc: len(bucket) for dc, bucket in sorted(self._idle.items())}

    async def _quiet_close(self, ws):
        try:
            await ws.close()
        except Exception:
            pass

    async def warmup(self):
        if not proxy_config.cfproxy_worker_domains:
            return

        if proxy_config.worker_only:
            targets = dict(DC_DEFAULT_IPS)
            targets.update(proxy_config.dc_redirects)
            targets = {dc: ip for dc, ip in targets.items() if ip}
        else:
            targets = {
                dc: ip for dc, ip in DC_DEFAULT_IPS.items()
                if dc not in proxy_config.dc_redirects
            }

        if not targets:
            return

        worker_domains = list(proxy_config.cfproxy_worker_domains)
        for dc, fallback_dst in targets.items():
            self._schedule_refill(dc, fallback_dst, worker_domains)

        log.info("CF worker pool warmup for %d DC(s): %d warm socket(s) each "
                 "over %d worker(s)", len(targets),
                 min(max(1, proxy_config.worker_pool_size), self.PER_DC_LIMIT),
                 len(worker_domains))

    def reset(self):
        loop = asyncio.get_running_loop()
        for task in self._refilling.values():
            if not task.done() and task.get_loop() is loop:
                task.cancel()
        for bucket in self._idle.values():
            for ws, _, _ in bucket:
                try:
                    ws.writer.close()
                except Exception as exc:
                    log.debug("CF worker pool close failed: %r", exc)
        self._idle.clear()
        self._refilling.clear()
        self._exhausted_until.clear()
        self._soft_failures.clear()
        self._rr_index.clear()

    async def close(self):
        tasks = list(self._refilling.values())
        self.reset()
        await asyncio.gather(*tasks, return_exceptions=True)


ws_pool = _WsPool()
cf_worker_pool = _CfWorkerPool()