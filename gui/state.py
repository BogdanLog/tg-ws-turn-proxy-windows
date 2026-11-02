from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
import subprocess
import tempfile

FROZEN = bool(getattr(sys, 'frozen', False)) or \
    globals().get('__compiled__') is not None
GUI_DIR = os.path.dirname(os.path.abspath(__file__))

_LAYOUT_MARKERS = ('zapret', 'tg_calls', 'lists')


def _is_under_bundle(trial: str) -> bool:
    base = os.path.abspath(trial)
    for name in _LAYOUT_MARKERS:
        if os.path.isdir(os.path.join(base, name)):
            return True
    return False


def _discover_root(start: str) -> str:
    origin = os.path.abspath(start)
    for candidate in (origin, os.path.dirname(origin)):
        if _is_under_bundle(candidate):
            return candidate
    for candidate in (os.path.dirname(os.path.abspath(sys.executable)),
                      os.path.dirname(os.path.abspath(sys.argv[0]))):
        if candidate and _is_under_bundle(candidate):
            return candidate
    path = origin
    seen = set()
    for _ in range(6):
        if path in seen:
            break
        seen.add(path)
        if _is_under_bundle(path):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return origin


def _writable_root() -> str:
    home = os.path.expanduser('~')
    candidates = [os.path.join(home, 'tg-ws-turn-proxy-gui'),
                  os.path.join(os.environ.get('LOCALAPPDATA') or home,
                               'tg-ws-turn-proxy')]
    for root in candidates:
        probe = os.path.join(root, '.write-test')
        try:
            os.makedirs(root, exist_ok=True)
            with open(probe, 'w', encoding='ascii') as fh:
                fh.write('')
            os.remove(probe)
            return root
        except OSError:
            continue
    return candidates[0]


def _bundle_root() -> str:
    if FROZEN:
        compiled = globals().get('__compiled__')
        containing = getattr(compiled, 'containing_dir', None) if compiled else None
        if containing:
            root = os.path.abspath(containing)
            if _is_under_bundle(root):
                return root
        root = _discover_root(GUI_DIR)
        if _is_under_bundle(root):
            return root
    return ROOT


ROOT = _writable_root() if FROZEN else os.path.dirname(GUI_DIR)

BUNDLE = _bundle_root()


def _exe_abs_path() -> str:
    exe = os.path.abspath(sys.executable)
    argv0 = os.path.abspath(sys.argv[0])
    return argv0 if os.path.isfile(argv0) else exe


def startup_folder() -> str:
    home = os.path.expanduser('~')
    roaming = os.environ.get('APPDATA') \
        or os.path.join(home, 'AppData', 'Roaming')
    startup = os.path.join(roaming, 'Microsoft', 'Windows', 'Start Menu',
                           'Programs', 'Startup')
    os.makedirs(startup, exist_ok=True)
    return startup


def launcher_exe() -> str:
    if FROZEN:
        exe = sys.argv[0]
        if not exe.lower().endswith('.exe'):
            exe = sys.executable
        return os.path.abspath(exe)
    return os.path.abspath(sys.executable)


def _shortcut_target() -> str:
    if FROZEN:
        return _exe_abs_path()
    return os.path.abspath(sys.executable)


def _shortcut_args() -> list:
    if FROZEN:
        return []
    return ['-m', 'gui']


def log_paths(log) -> None:
    compiled = globals().get('__compiled__')
    log('app', f'FROZEN={FROZEN} ROOT={ROOT}')
    log('app', f'BUNDLE={BUNDLE}')
    log('app', f'ZAPRET_BAT={ZAPRET_BAT} exists={os.path.exists(ZAPRET_BAT)}')
    log('app', f'sys.executable={sys.executable}')
    log('app', f'sys.argv[0]={sys.argv[0]}')
    log('app', f'launcher_exe={launcher_exe()}')
    log('app', f'compiled.containing_dir={getattr(compiled, "containing_dir", None)}')


TASK_NAME = 'tg-ws-turn-proxy'
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def _is_elevated() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _task_xml(target: str, args: list, workdir: str) -> str:
    def esc(s: str) -> str:
        return (s.replace('&', '&amp;').replace('<', '&lt;')
                 .replace('>', '&gt;').replace('"', '&quot;'))

    user = os.environ.get('USERNAME', '')
    domain = os.environ.get('USERDOMAIN', '')
    user_id = esc(f'{domain}\\{user}' if domain else user)
    args_str = subprocess.list2cmdline([str(a) for a in args]) if args else ''

    parts = [
        '<?xml version="1.0" encoding="UTF-16"?>',
        '<Task version="1.2" '
        'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">',
        '  <Triggers>',
        '    <LogonTrigger>',
        '      <Enabled>true</Enabled>',
        f'      <UserId>{user_id}</UserId>',
        '    </LogonTrigger>',
        '  </Triggers>',
        '  <Principals>',
        '    <Principal id="Author">',
        f'      <UserId>{user_id}</UserId>',
        '      <LogonType>InteractiveToken</LogonType>',
        '      <RunLevel>HighestAvailable</RunLevel>',
        '    </Principal>',
        '  </Principals>',
        '  <Settings>',
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>',
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>',
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>',
        '    <AllowHardTerminate>true</AllowHardTerminate>',
        '    <StartWhenAvailable>false</StartWhenAvailable>',
        '    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>',
        '    <IdleSettings>',
        '      <StopOnIdleEnd>false</StopOnIdleEnd>',
        '      <RestartOnIdle>false</RestartOnIdle>',
        '    </IdleSettings>',
        '    <AllowStartOnDemand>true</AllowStartOnDemand>',
        '    <Enabled>true</Enabled>',
        '    <Hidden>false</Hidden>',
        '    <RunOnlyIfIdle>false</RunOnlyIfIdle>',
        '    <WakeToRun>false</WakeToRun>',
        '    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>',
        '    <Priority>7</Priority>',
        '  </Settings>',
        '  <Actions Context="Author">',
        '    <Exec>',
        f'      <Command>{esc(target)}</Command>',
    ]
    if args_str:
        parts.append(f'      <Arguments>{esc(args_str)}</Arguments>')
    parts.extend([
        f'      <WorkingDirectory>{esc(workdir)}</WorkingDirectory>',
        '    </Exec>',
        '  </Actions>',
        '</Task>',
        '',
    ])
    return '\n'.join(parts)


def _startup_task_exists() -> bool:
    try:
        return subprocess.run(
            ['schtasks', '/Query', '/TN', TASK_NAME],
            capture_output=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _delete_startup_task() -> bool:
    if not _startup_task_exists():
        return True
    try:
        return subprocess.run(
            ['schtasks', '/Delete', '/TN', TASK_NAME, '/F'],
            capture_output=True, timeout=15,
            creationflags=CREATE_NO_WINDOW,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _create_startup_task() -> bool:
    target = _shortcut_target()
    args = list(_shortcut_args() or [])
    for flag in ('--minimized', '--autostart'):
        if flag not in args:
            args.append(flag)
    workdir = os.path.dirname(target) or '.'
    if not FROZEN:
        workdir = ROOT
    xml = _task_xml(target, args, workdir)

    fd, xml_path = tempfile.mkstemp(suffix='.xml',
                                    prefix='tg-ws-startup-task-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-16') as fh:
            fh.write(xml)
        result = subprocess.run(
            ['schtasks', '/Create', '/TN', TASK_NAME, '/XML', xml_path, '/F'],
            capture_output=True, timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass


def add_startup_launch(enabled: bool) -> bool:
    if os.name != 'nt':
        return True

    try:
        old_link = os.path.join(startup_folder(), 'tg-ws-turn-proxy.lnk')
        if os.path.exists(old_link):
            os.remove(old_link)
    except OSError:
        pass

    if not enabled:
        _delete_startup_task()
        return not _startup_task_exists()

    if not _create_startup_task():
        return False
    return _startup_task_exists()


def sync_startup_state(settings: 'Settings') -> bool:
    if os.name != 'nt':
        return True
    want = bool(getattr(settings, 'startup_launch', False))
    if not _is_elevated():
        return _startup_task_exists() == want
    return add_startup_launch(want)


SETTINGS_PATH = os.path.join(ROOT, 'gui_settings.json')
ASSET_DIR = os.path.join(GUI_DIR, 'assets')
ZAPRET_BAT = os.path.join(BUNDLE, 'zapret', 'winws-tg-calls-relay.bat')
PROXY_DIR = os.path.join(BUNDLE, 'tg_ws_proxy')
RELAY_DIR = os.path.join(BUNDLE, 'tg_calls')
RELAY_CONFIG = os.path.join(ROOT, 'tg_calls', 'tg_calls_relay', 'config.json')
CIDR_FILE = os.path.join(ROOT, 'lists', 'ipset-telegram.txt')

DOCS_WORKER = ('https://github.com/Flowseal/tg-ws-proxy/blob/main'
               '/docs/RU/CfWorker.md')
DOCS_CFPROXY = ('https://github.com/Flowseal/tg-ws-proxy/blob/main'
                '/docs/RU/CfProxy.md')
CFPROXY_DOMAINS_URL = ('https://raw.githubusercontent.com/Flowseal/'
                       'tg-ws-proxy/main/.github/cfproxy-domains.txt')
HF_TOKENS_URL = 'https://huggingface.co/settings/tokens'
CF_TURN_DOCS = 'https://developers.cloudflare.com/realtime/turn/'

PUBLIC_HF_TOKEN = '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'

SOURCE_WORKERS = 'workers'
SOURCE_DOMAIN = 'domain'
SOURCE_PUBLIC = 'public'

TURN_HF = 'hf'
TURN_CF = 'cf'
TURN_CUSTOM = 'custom'
TURN_PUBLIC = 'public'


def gen_secret() -> str:
    return secrets.token_hex(16)


def normalize_secret(raw: str) -> str:
    value = (raw or '').strip().lower()
    if value[:2] in ('dd', 'ee') and len(value) == 34:
        value = value[2:]
    return value


def is_hex_secret(raw: str) -> bool:
    value = normalize_secret(raw)
    return len(value) == 32 and re.fullmatch(r'[0-9a-f]{32}', value) is not None


def is_valid_ip(raw: str) -> bool:
    try:
        ipaddress.ip_address((raw or '').strip())
    except ValueError:
        return False
    return True


_DOMAIN_RE = re.compile(
    r'^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$')


def is_valid_domain(raw: str) -> bool:
    value = (raw or '').strip().lower().rstrip('.')
    if '://' in value or '/' in value or ':' in value or ' ' in value:
        return False
    return _DOMAIN_RE.match(value) is not None


def normalize_domain(raw: str) -> str:
    return (raw or '').strip().lower().rstrip('.')


def is_valid_turn_url(raw: str) -> bool:
    value = (raw or '').strip().lower()
    if not (value.startswith('turn://') or value.startswith('turns://')):
        return False
    rest = value.split('://', 1)[1]
    return bool(rest) and ' ' not in rest


@dataclass
class Settings:
    lang: str = 'ru'
    source_mode: str = SOURCE_WORKERS
    worker_domains: list = field(default_factory=lambda: ['', '', ''])
    custom_domain: str = ''
    host: str = '127.0.0.1'
    port: int = 1443
    secret: str = ''
    turn_provider: str = TURN_HF
    hf_token: str = ''
    cf_key_id: str = ''
    cf_api_token: str = ''
    turn_username: str = ''
    turn_credential: str = ''
    turn_url: str = ''
    setup_done: bool = False
    startup_launch: bool = False

    def workers(self) -> list:
        return [normalize_domain(d) for d in self.worker_domains
                if normalize_domain(d)]

    def link_host(self) -> str:
        host = (self.host or '').strip()
        return '127.0.0.1' if host in ('', '0.0.0.0', '::') else host

    def proxy_link(self) -> str:
        return (f'tg://proxy?server={self.link_host()}'
                f'&port={self.port}&secret=dd{normalize_secret(self.secret)}')

    def turn_configured(self) -> bool:
        if self.turn_provider == TURN_CUSTOM:
            return bool(self.turn_username.strip()
                        and self.turn_credential.strip()
                        and is_valid_turn_url(self.turn_url))
        if self.turn_provider == TURN_PUBLIC:
            return True
        if self.turn_provider == TURN_CF:
            return bool(self.cf_key_id.strip()
                        and self.cf_api_token.strip())
        return bool(self.hf_token.strip())

    def proxy_configured(self) -> bool:
        try:
            port = int(self.port)
        except (TypeError, ValueError):
            port = 0
        if not is_hex_secret(self.secret) or not (1 <= port <= 65535):
            return False
        if not is_valid_ip(self.host):
            return False
        if self.source_mode == SOURCE_WORKERS:
            return bool(self.workers())
        if self.source_mode == SOURCE_DOMAIN:
            return is_valid_domain(self.custom_domain)
        return True

    def ready(self) -> bool:
        return self.proxy_configured() and self.turn_configured()


def _note(message: str) -> None:
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass
    try:
        with open(os.path.join(ROOT, 'gui-errors.log'), 'a',
                  encoding='utf-8') as fh:
            fh.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {message}\n')
    except OSError:
        pass


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def load_settings(path: str = SETTINGS_PATH) -> Settings:
    settings = Settings()
    if not settings.secret:
        settings.secret = gen_secret()
    if not os.path.exists(path):
        return settings
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError('top-level JSON value is not an object')
    except (OSError, ValueError) as exc:
        raw = ''
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                raw = fh.read()
        except OSError:
            pass
        match = re.search(r'"secret"\s*:\s*"([0-9a-fA-F]{32})"', raw)
        if match:
            settings.secret = match.group(1).lower()
        backup = f'{path}.bad-{time.strftime("%Y%m%d-%H%M%S")}'
        try:
            os.replace(path, backup)
            _note(f'settings file {path} is unreadable ({exc}); '
                  f'backed up to {backup}')
        except OSError as move_exc:
            _note(f'settings file {path} is unreadable ({exc}); '
                  f'backup failed: {move_exc}')
        return settings
    for key in Settings.__dataclass_fields__:
        if key not in data:
            continue
        value = data[key]
        default = getattr(settings, key)
        if isinstance(default, bool):
            setattr(settings, key, _as_bool(value))
        elif isinstance(default, int):
            try:
                setattr(settings, key, int(value))
            except (TypeError, ValueError):
                pass
        elif isinstance(default, list):
            if isinstance(value, list):
                items = [str(v) for v in value[:3]]
                setattr(settings, key, items + [''] * (3 - len(items)))
        elif isinstance(default, str):
            setattr(settings, key, str(value))
    if settings.port < 1 or settings.port > 65535:
        settings.port = 1443
    if not is_hex_secret(settings.secret):
        settings.secret = gen_secret()
    return settings


def save_settings(settings: Settings, path: str = SETTINGS_PATH) -> bool:
    payload = asdict(settings)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write('\n')
        os.replace(tmp, path)
    except OSError as exc:
        _note(f'cannot save settings to {path}: {exc}')
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    return True


def proxy_args(settings: Settings) -> list:
    args = [
        '--host', settings.host.strip(),
        '--port', str(settings.port),
        '--secret', normalize_secret(settings.secret),
        '-q',
        '--log-clear-min', '0',
    ]
    if settings.source_mode == SOURCE_WORKERS:
        for domain in settings.workers():
            args += ['--cfproxy-worker-domain', domain]
    elif settings.source_mode == SOURCE_DOMAIN:
        args += ['--no-worker-only', '--pool-size', '0',
                 '--cfproxy-domain', normalize_domain(settings.custom_domain)]
    else:
        args += ['--no-worker-only', '--pool-size', '0']
    return args


def _frozen_relay_args() -> list:
    if not FROZEN:
        return []
    try:
        os.makedirs(os.path.dirname(RELAY_CONFIG), exist_ok=True)
    except OSError:
        pass
    return ['--config', RELAY_CONFIG]


def ensure_cidr_file() -> str:
    if os.path.exists(CIDR_FILE):
        return CIDR_FILE
    source = os.path.join(BUNDLE, 'lists', 'ipset-telegram.txt')
    try:
        os.makedirs(os.path.dirname(CIDR_FILE), exist_ok=True)
        if os.path.isfile(source):
            shutil.copyfile(source, CIDR_FILE)
    except OSError as exc:
        _note(f'cannot seed the writable CIDR list {CIDR_FILE}: {exc}')
    return CIDR_FILE


def relay_args(settings: Settings) -> list:
    args = _frozen_relay_args()
    if not args:
        return args
    ensure_cidr_file()
    return args + ['--cidr-file', CIDR_FILE]


def mint_args(settings: Settings) -> list:
    args = ['mint'] + _frozen_relay_args()
    if settings.turn_provider == TURN_CUSTOM:
        args += ['--username', settings.turn_username.strip(),
                 '--credential', settings.turn_credential.strip()]
        url = settings.turn_url.strip()
        if url:
            args += ['--url', url]
    elif settings.turn_provider == TURN_CF:
        args += ['--key-id', settings.cf_key_id.strip(),
                 '--token', settings.cf_api_token.strip()]
    elif settings.turn_provider == TURN_PUBLIC:
        args += ['--hf-token', PUBLIC_HF_TOKEN, '--ttl', '7200']
    else:
        args += ['--hf-token', settings.hf_token.strip(), '--ttl', '7200']
    return args


def sanitize_relay_config(settings: Settings) -> None:
    try:
        with open(RELAY_CONFIG, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    turn = data.get('turn')
    if not isinstance(turn, dict):
        return
    provider = settings.turn_provider
    if provider in (TURN_CF, TURN_PUBLIC, TURN_CUSTOM):
        turn['hf_token'] = ''
    if provider in (TURN_HF, TURN_PUBLIC, TURN_CUSTOM):
        turn['key_id'] = ''
        turn['api_token'] = ''
    if provider in (TURN_HF, TURN_CF, TURN_PUBLIC):
        turn['username'] = ''
        turn['credential'] = ''
        turn['url'] = ''
    tmp = RELAY_CONFIG + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write('\n')
        os.replace(tmp, RELAY_CONFIG)
    except OSError:
        pass