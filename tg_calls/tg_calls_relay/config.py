from __future__ import annotations

import ipaddress
import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

log = logging.getLogger('tg-calls-relay')

CIDR_SOURCE_URL = 'https://core.telegram.org/resources/cidr.txt'

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PACKAGE_DIR)
DEFAULT_CONFIG_PATH = os.path.join(PACKAGE_DIR, 'config.json')
_DEFAULT_CIDR_PATHS = [
    os.path.join(ROOT_DIR, 'lists', 'ipset-telegram.txt'),
    os.path.join(os.path.dirname(ROOT_DIR), 'lists', 'ipset-telegram.txt'),
]
DEFAULT_CIDR_PATH = next(
    (p for p in _DEFAULT_CIDR_PATHS if os.path.exists(p)),
    _DEFAULT_CIDR_PATHS[0])

FALLBACK_CIDRS: List[str] = [
    '91.108.4.0/22',
    '91.108.8.0/22',
    '91.108.12.0/22',
    '91.108.16.0/22',
    '91.108.20.0/22',
    '91.108.56.0/22',
    '91.105.192.0/23',
    '149.154.160.0/20',
    '95.161.64.0/20',
    '185.76.151.0/24',
]


@dataclass
class TurnConfig:
    url: str = 'turns://turn.cloudflare.com:443'
    username: str = ''
    credential: str = ''
    key_id: str = ''
    api_token: str = ''
    hf_token: str = ''
    mint_ttl: int = 172800

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.credential)

    @property
    def can_mint_cf(self) -> bool:
        return bool(self.key_id and self.api_token)

    @property
    def can_mint_hf(self) -> bool:
        return bool(self.hf_token)

    @property
    def can_mint(self) -> bool:
        return self.can_mint_hf or self.can_mint_cf


@dataclass
class RelayConfig:
    turn: TurnConfig = field(default_factory=TurnConfig)
    config_path: str = ''
    cidr_file: str = DEFAULT_CIDR_PATH
    wd_priority: int = 100
    wd_queue_length: int = 4096
    wd_queue_time_ms: int = 4000
    permission_rate: float = 4.0
    permission_burst: float = 5.0
    permission_refresh_secs: float = 240.0
    peer_idle_ttl_secs: float = 300.0
    max_peers: int = 64
    stats_interval_secs: float = 30.0
    cidr_refresh_secs: float = 21600.0
    log_level: str = 'INFO'


def parse_cidr_text(text: str) -> Tuple[List[str], int]:
    ipv4: List[str] = []
    skipped = 0
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        try:
            net = ipaddress.ip_network(line, strict=True)
        except ValueError:
            skipped += 1
            log.warning('ignoring invalid CIDR entry %r', line)
            continue
        if net.version == 4:
            ipv4.append(str(net))
        else:
            skipped += 1
    return ipv4, skipped


def fetch_cidrs(url: str = CIDR_SOURCE_URL,
                timeout: float = 10.0) -> Optional[List[str]]:
    req = urllib.request.Request(url, headers={'User-Agent': 'tg-calls-relay'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, OSError) as exc:
        log.debug('CIDR fetch from %s failed: %s', url, exc)
        return None
    ipv4, skipped = parse_cidr_text(text)
    if len(ipv4) < 5:
        log.warning('CIDR fetch from %s looked implausible (%d IPv4 '
                    'networks) - ignoring it', url, len(ipv4))
        return None
    if skipped:
        log.debug('CIDR fetch: skipped %d non-IPv4/invalid entries', skipped)
    return ipv4


def update_cidr_file(path: str = DEFAULT_CIDR_PATH) -> Optional[List[str]]:
    fresh = fetch_cidrs()
    if fresh is None:
        return None
    current: Optional[List[str]] = None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            current, _skipped = parse_cidr_text(fh.read())
    except OSError:
        current = None
    if current is not None:
        for cidr in current:
            if cidr in fresh:
                continue
            try:
                net = ipaddress.ip_network(cidr, strict=True)
            except ValueError:
                continue
            if net.prefixlen < 8:
                log.warning('dropping too-wide local CIDR %s (/<8)', cidr)
                continue
            fresh.append(str(net))
    if current == fresh:
        return fresh
    stamp = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())
    lines = [
        '# Telegram networks - auto-managed by tg_calls_relay.',
        f'# Source: {CIDR_SOURCE_URL} (fetched {stamp}).',
        '# IPv4 only: the WinDivert capture filter is IPv4, and this line',
        '# has no IPv6 route. Local entries not published upstream are kept',
        '# (e.g. the test range 95.161.64.0/20).',
    ] + fresh
    tmp_path = ''
    try:
        directory = os.path.dirname(os.path.abspath(path)) or '.'
        fd, tmp_path = tempfile.mkstemp(prefix='.cidr-', suffix='.tmp',
                                        dir=directory)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        os.replace(tmp_path, path)
        tmp_path = ''
    except OSError as exc:
        log.warning('cannot rewrite %s: %s', path, exc)
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return fresh
    log.debug('Telegram CIDR list rewritten from core.telegram.org: %d '
              'networks (%s)', len(fresh), path)
    return fresh


def load_cidrs(path: str = DEFAULT_CIDR_PATH) -> List[str]:
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            text = fh.read()
    except OSError:
        return list(FALLBACK_CIDRS)
    cidrs, skipped = parse_cidr_text(text)
    if skipped:
        log.debug('%s: ignored %d invalid/non-IPv4 entries', path, skipped)
    return cidrs or list(FALLBACK_CIDRS)


def _apply_env(cfg: RelayConfig) -> None:
    env = os.environ
    if env.get('TG_CALLS_TURN_URL'):
        cfg.turn.url = env['TG_CALLS_TURN_URL']
    if env.get('TG_CALLS_TURN_USER'):
        cfg.turn.username = env['TG_CALLS_TURN_USER']
    if env.get('TG_CALLS_TURN_PASS'):
        cfg.turn.credential = env['TG_CALLS_TURN_PASS']
    if env.get('TG_CALLS_KEY_ID'):
        cfg.turn.key_id = env['TG_CALLS_KEY_ID']
    if env.get('TG_CALLS_API_TOKEN'):
        cfg.turn.api_token = env['TG_CALLS_API_TOKEN']
    if env.get('TG_CALLS_HF_TOKEN'):
        cfg.turn.hf_token = env['TG_CALLS_HF_TOKEN']
    if env.get('TG_CALLS_CIDR_FILE'):
        cfg.cidr_file = env['TG_CALLS_CIDR_FILE']
    if env.get('TG_CALLS_LOG_LEVEL'):
        cfg.log_level = env['TG_CALLS_LOG_LEVEL']


def load_config(path: Optional[str] = None) -> RelayConfig:
    cfg = RelayConfig()
    config_path = path or DEFAULT_CONFIG_PATH
    try:
        with open(config_path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as exc:
        raise SystemExit(f'cannot read {config_path}: {exc}') from None
    if not isinstance(data, dict):
        data = {}

    turn_data = data.get('turn')
    if not isinstance(turn_data, dict):
        turn_data = {}
    for key in ('url', 'username', 'credential', 'key_id', 'api_token',
                'hf_token'):
        value = turn_data.get(key)
        if isinstance(value, str) and value:
            setattr(cfg.turn, key, value)
    if isinstance(turn_data.get('mint_ttl'), int):
        cfg.turn.mint_ttl = turn_data['mint_ttl']

    for key in ('cidr_file', 'wd_priority', 'wd_queue_length',
                'wd_queue_time_ms', 'permission_rate', 'permission_burst',
                'permission_refresh_secs', 'peer_idle_ttl_secs', 'max_peers',
                'stats_interval_secs', 'cidr_refresh_secs', 'log_level'):
        if key in data and data[key] is not None:
            setattr(cfg, key, data[key])

    if cfg.cidr_file and not os.path.isabs(cfg.cidr_file):
        cfg.cidr_file = os.path.join(ROOT_DIR, cfg.cidr_file)

    cfg.config_path = config_path
    _apply_env(cfg)
    return cfg


def save_config(cfg: RelayConfig, path: Optional[str] = None) -> str:
    config_path = path or DEFAULT_CONFIG_PATH
    data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError('top-level JSON value is not an object')
        except (OSError, ValueError) as exc:
            backup = (config_path + '.bad-'
                      + time.strftime('%Y%m%d-%H%M%S'))
            try:
                os.replace(config_path, backup)
                log.warning('cannot read %s (%s); moved it to %s and '
                            'writing a fresh config',
                            config_path, exc, backup)
            except OSError as move_exc:
                raise ValueError(
                    f'cannot read {config_path} ({exc}) and cannot back it '
                    f'up ({move_exc}); refusing to overwrite it') from exc
            data = {}
    if not isinstance(data.get('turn'), dict):
        data['turn'] = {}
    data['turn'].update({
        'url': cfg.turn.url,
        'username': cfg.turn.username,
        'credential': cfg.turn.credential,
        'key_id': cfg.turn.key_id,
        'api_token': cfg.turn.api_token,
        'hf_token': cfg.turn.hf_token,
        'mint_ttl': cfg.turn.mint_ttl,
    })
    tmp_path = config_path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    os.replace(tmp_path, config_path)
    return config_path