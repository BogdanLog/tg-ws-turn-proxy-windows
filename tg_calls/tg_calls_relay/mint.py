from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional

from .config import RelayConfig, load_config, save_config

MINT_URL = 'https://rtc.live.cloudflare.com/v1/turn/keys/{key_id}/credentials/generate-ice-servers'
HF_MINT_URL = 'https://fastrtc-turn-service.hf.space/credentials'


def mint_huggingface(hf_token: str, ttl: int) -> dict:
    url = f'{HF_MINT_URL}?ttl={ttl}'
    req = urllib.request.Request(
        url, method='GET',
        headers={'Authorization': f'Bearer {hf_token}',
                 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:500]
        hint = ''
        if exc.code in (401, 403):
            hint = (' (check that the HF token exists, is not revoked and '
                    'has Read access)')
        raise SystemExit(
            f'HF mint failed: HTTP {exc.code}{hint}\n{detail}') from None
    except urllib.error.URLError as exc:
        raise SystemExit(f'HF mint failed: {exc.reason}') from None

    for entry in payload.get('iceServers', []):
        if entry.get('credential'):
            return {'urls': entry.get('urls') or [],
                    'username': entry['username'],
                    'credential': entry['credential']}
    raise SystemExit(
        f'HF mint response carried no TURN credentials: {payload}')


def mint_cloudflare(key_id: str, token: str, ttl: int) -> dict:
    url = MINT_URL.format(key_id=key_id)
    body = json.dumps({'ttl': ttl}).encode('utf-8')
    req = urllib.request.Request(
        url, data=body, method='POST',
        headers={'Authorization': f'Bearer {token}',
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:500]
        hint = ''
        if exc.code in (401, 403):
            hint = (' (check that the API token exists, is not expired and '
                    'has Realtime > TURN > Edit for this account)')
        elif exc.code == 404:
            hint = ' (check the TURN key id)'
        raise SystemExit(f'mint failed: HTTP {exc.code}{hint}\n{detail}') from None
    except urllib.error.URLError as exc:
        raise SystemExit(f'mint failed: {exc.reason}') from None

    for entry in payload.get('iceServers', []):
        if entry.get('credential'):
            return {'urls': entry.get('urls') or [],
                    'username': entry['username'],
                    'credential': entry['credential']}
    raise SystemExit(f'mint response carried no TURN credentials: {payload}')


def _prefer_tls(urls: List[str]) -> Optional[str]:
    best: Optional[str] = None
    best_rank: Optional[int] = None
    for candidate in urls:
        low = candidate.lower()
        if not (low.startswith('turn:') or low.startswith('turns:')):
            continue
        if 'transport=udp' in low:
            continue
        scheme = 'turns' if low.startswith('turns:') else 'turn'
        hostport = candidate.split(':', 1)[1].split('?', 1)[0]
        port_s = hostport.rsplit(':', 1)[1] if ':' in hostport else ''
        try:
            port = int(port_s)
        except ValueError:
            port = 5349 if scheme == 'turns' else 3478
        if scheme == 'turns' and port == 443:
            rank = 0
        elif scheme == 'turns':
            rank = 1
        elif port == 443:
            rank = 2
        else:
            rank = 3
        if best_rank is None or rank < best_rank:
            best = f'{scheme}://{hostport}'
            best_rank = rank
    return best


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog='python -m tg_calls_relay mint',
        description='Generate TURN credentials into tg_calls_relay/config.json')
    ap.add_argument('--key-id', default='',
                    help='Cloudflare TURN key id (RTC key, not the API token)')
    ap.add_argument('--token', default='',
                    help='Cloudflare API token with Realtime TURN edit rights')
    ap.add_argument('--username', default='', help='pre-made TURN username')
    ap.add_argument('--credential', default='',
                    help='pre-made TURN credential')
    ap.add_argument('--hf-token', default='',
                    help='Hugging Face access token (fastrtc TURN proxy: '
                         'free 10 GB/mo, no credit card)')
    ap.add_argument('--url', default='',
                    help='TURN URL to store (default: keep/choose a turns: '
                         'URL from the mint response)')
    ap.add_argument('--ttl', type=int, default=0,
                    help='credential lifetime in seconds, max 172800 '
                         '(default: the config mint_ttl; with HF 7200 is '
                         'recommended - the relay refreshes 1 h before '
                         'expiry)')
    ap.add_argument('--config', default='', help='path to config.json')
    ap.add_argument('--show', action='store_true',
                    help='print the stored username/credential for manual '
                         'use and exit (the token is never printed)')
    args = ap.parse_args(argv)

    cfg: RelayConfig = load_config(args.config or None)

    if args.show:
        if not cfg.turn.has_credentials:
            print('no credentials stored yet - run mint first')
            return 1
        print(f'url:      {cfg.turn.url}')
        print(f'username: {cfg.turn.username}')
        print(f'credential: {cfg.turn.credential}')
        return 0

    if args.username and args.credential:
        cfg.turn.username = args.username
        cfg.turn.credential = args.credential
        if args.url:
            cfg.turn.url = args.url
        path = save_config(cfg, args.config or None)
        print(f'saved hand-pasted credentials to {path}')
        print(f'url: {cfg.turn.url} username: {cfg.turn.username}')
        return 0

    if args.hf_token or (cfg.turn.can_mint_hf
                         and not (args.key_id or args.token)):
        hf_token = args.hf_token or cfg.turn.hf_token
        ttl = args.ttl or cfg.turn.mint_ttl
        ttl = min(ttl, 172800)
        result = mint_huggingface(hf_token, ttl)
        cfg.turn.hf_token = hf_token
        cfg.turn.mint_ttl = ttl
        cfg.turn.username = result['username']
        cfg.turn.credential = result['credential']
        chosen = args.url or _prefer_tls(result['urls'])
        if chosen:
            cfg.turn.url = chosen
        path = save_config(cfg, args.config or None)
        expires = time.strftime('%Y-%m-%d %H:%M UTC',
                                time.gmtime(time.time() + ttl))
        print(f'HF-minted TURN credentials, requested ttl={ttl}s '
              f'(assumed valid until {expires})')
        print(f'url: {cfg.turn.url}')
        print(f'username: {cfg.turn.username}')
        print(f'saved to {path} - the relay re-mints by itself before '
              f'expiry while the HF token stays stored there')
        return 0

    key_id = args.key_id or cfg.turn.key_id
    token = args.token or cfg.turn.api_token
    if not key_id or not token:
        ap.error('provide --hf-token (Hugging Face, free, no card), or '
                 '--key-id + --token (Cloudflare), or '
                 '--username + --credential (any TURN provider)')

    ttl = args.ttl or cfg.turn.mint_ttl
    ttl = min(ttl, 172800)
    result = mint_cloudflare(key_id, token, ttl)

    cfg.turn.key_id = key_id
    cfg.turn.api_token = token
    cfg.turn.mint_ttl = ttl
    cfg.turn.username = result['username']
    cfg.turn.credential = result['credential']
    chosen = args.url or _prefer_tls(result['urls'])
    if chosen:
        cfg.turn.url = chosen

    path = save_config(cfg, args.config or None)
    expires = time.strftime('%Y-%m-%d %H:%M UTC',
                            time.gmtime(time.time() + ttl))
    print(f'minted TURN credentials, valid until {expires} ({ttl} s)')
    print(f'url: {cfg.turn.url}')
    print(f'username: {cfg.turn.username}')
    print(f'saved to {path} - the relay re-mints automatically while '
          f'key id + token remain stored there')
    return 0


if __name__ == '__main__':
    sys.exit(main())