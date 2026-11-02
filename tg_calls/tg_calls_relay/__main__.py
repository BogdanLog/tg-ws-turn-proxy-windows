from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import List, Optional

from .config import load_config

log = logging.getLogger('tg-calls-relay')


def _setup_logging(level: str, log_file: Optional[str]) -> None:
    root = logging.getLogger('tg-calls-relay')
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter('%(asctime)s %(levelname)-7s %(message)s',
                            datefmt='%H:%M:%S')
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    if log_file:
        fh = logging.FileHandler(log_file, encoding='utf-8', errors='replace')
        fh.setFormatter(fmt)
        root.addHandler(fh)


def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_mint(argv: List[str]) -> int:
    from . import mint
    return mint.main(argv)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == 'mint':
        return _run_mint(argv[1:])

    ap = argparse.ArgumentParser(
        prog='python -m tg_calls_relay',
        description='Telegram call UDP relay through Cloudflare TURN')
    ap.add_argument('--dry-run', action='store_true',
                    help='no WinDivert: allocate on TURN and probe through it')
    ap.add_argument('--capture-only', action='store_true',
                    help='sniff matching Telegram UDP and log, never divert')
    ap.add_argument('--sniff-outbound', action='store_true',
                    help='full relay + log every outbound UDP/TCP flow that '
                         'is NOT diverted (diagnostic)')
    ap.add_argument('--probe-target', default='stun.l.google.com:19302',
                    help='dry-run STUN target host:port')
    ap.add_argument('--turn-url', default='',
                    help='TURN URL, e.g. turns://turn.cloudflare.com:443')
    ap.add_argument('--username', default='', help='TURN username')
    ap.add_argument('--credential', default='', help='TURN credential')
    ap.add_argument('--cidr-file', default='',
                    help='Telegram CIDR list (default lists/ipset-telegram.txt)')
    ap.add_argument('--priority', type=int, default=None,
                    help='WinDivert priority (default from config, 100)')
    ap.add_argument('--log-level', default='',
                    help='DEBUG / INFO / WARNING')
    ap.add_argument('--log-file', default='',
                    help='also append logs to this file')
    ap.add_argument('--config', default='',
                    help='path to config.json')
    ap.add_argument('--stats-interval', type=float, default=0,
                    help='seconds between stats lines (0 = from config)')
    args = ap.parse_args(argv)

    cfg = load_config(args.config or None)
    if args.turn_url:
        cfg.turn.url = args.turn_url
    if args.username:
        cfg.turn.username = args.username
    if args.credential:
        cfg.turn.credential = args.credential
    if args.cidr_file:
        cfg.cidr_file = args.cidr_file
    if args.priority is not None:
        cfg.wd_priority = args.priority
    if args.log_level:
        cfg.log_level = args.log_level
    if args.stats_interval > 0:
        cfg.stats_interval_secs = args.stats_interval

    _setup_logging(cfg.log_level, args.log_file or None)

    if not (args.dry_run or args.capture_only) and not _is_admin():
        log.error('Administrator privileges are required to open WinDivert - '
                  'start the relay with tg-calls-relay.bat (it asks for UAC '
                  'itself), or use --dry-run / --capture-only which do not '
                  'need them.')
        return 1

    try:
        host, port_s = args.probe_target.rsplit(':', 1)
        probe_target = (host, int(port_s))
    except ValueError:
        ap.error('--probe-target must be host:port')

    from .relay import CallRelay

    relay = CallRelay(cfg, dry_run=args.dry_run,
                      capture_only=args.capture_only,
                      sniff_outbound=args.sniff_outbound,
                      probe_target=probe_target)
    if args.dry_run:
        mode = 'DRY-RUN (TURN path probe only)'
    elif args.capture_only:
        mode = 'CAPTURE-ONLY (sniff, originals keep flowing)'
    else:
        mode = 'FULL RELAY (divert Telegram UDP through TURN)'
        if args.sniff_outbound:
            mode += ' + SNIFF-OUTBOUND (log undiverted flows)'
    log.info('tg_calls_relay starting in mode: %s', mode)
    log.info('turn url: %s | cidr file: %s | priority: %d',
             cfg.turn.url, cfg.cidr_file, cfg.wd_priority)

    try:
        asyncio.run(relay.run())
    except KeyboardInterrupt:
        relay.stop()
        log.info('interrupted - handle released, Telegram UDP flows direct')
    return 0


if __name__ == '__main__':
    sys.exit(main())