from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path
import subprocess as _subprocess

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'gui' / 'assets'
DIST = ROOT / 'dist'
EXE_NAME = 'tg-ws-turn-proxy.exe'

COMPANY = 'BogdanLog Inc.'
PRODUCT = 'tg-ws-turn-proxy'
APP_DIR = DIST / f'{PRODUCT}.dist'
VERSION = '1.0.0'
AUTHOR = 'Bogdan Logachev'
COPYRIGHT = f'Copyright (c) 2026 {COMPANY}. Author: {AUTHOR}.'
DESCRIPTION = 'tg-ws-turn-proxy - Telegram proxy and TURN call relay'

BUNDLED_FILES = [
    'gui/assets/logo.png',
    'lists/list-cloudflare.txt',
    'lists/ipset-telegram.txt',
    'zapret/winws-tg-calls-relay.bat',
    'zapret/bin/winws.exe',
    'zapret/bin/cygwin1.dll',
    'zapret/bin/WinDivert.dll',
    'zapret/bin/WinDivert64.sys',
    'zapret/bin/stun.bin',
    'zapret/bin/tls_clienthello_www_google_com.bin',
    'zapret/LICENSE',
    'licenses/LICENSE',
    'licenses/tg-ws-proxy-LICENSE.txt',
    'licenses/THIRD_PARTY_LICENSES.md',
]


def banner(text: str) -> None:
    print()
    print('=' * 66)
    print(text)
    print('=' * 66)


def ensure_assets() -> None:
    required = [
        ASSETS / 'icon.ico',
        ASSETS / 'logo.png',
        ROOT / 'zapret' / 'bin' / 'winws.exe',
        ROOT / 'zapret' / 'bin' / 'cygwin1.dll',
        ROOT / 'zapret' / 'bin' / 'WinDivert.dll',
        ROOT / 'zapret' / 'bin' / 'WinDivert64.sys',
        ROOT / 'zapret' / 'bin' / 'stun.bin',
        ROOT / 'zapret' / 'bin' / 'tls_clienthello_www_google_com.bin',
    ]
    missing = [p for p in required if not p.is_file()]
    if missing:
        names = '\n        '.join(str(p) for p in missing)
        raise SystemExit(
            f'[ERROR] missing required file(s):\n        {names}\n'
            '        Commit the GUI assets and the zapret/bin payload '
            'to the repository.')
    for path in required:
        print(f'asset: {path}')


def check_package(package: str, expected: Path, env: dict) -> str:
    code = ('import importlib.util\n'
            f'spec = importlib.util.find_spec({package!r})\n'
            'print(spec.origin if spec else "")\n')
    try:
        probe = subprocess.run([sys.executable, '-c', code], cwd=str(ROOT),
                               env=env, capture_output=True, text=True,
                               timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f'cannot resolve package {package}: {exc}'
    origin = (probe.stdout or '').strip()
    if not origin:
        return f'package {package} not found in the build environment'
    if Path(origin).resolve().is_relative_to(expected.resolve()):
        return ''
    return (f'package {package} resolves to {origin}, expected inside '
            f'{expected}. A directory named {package} in the project root '
            'shadows the real sources; move it out of the import path.')


def find_signtool() -> str:
    override = os.environ.get('SIGNTOOL')
    if override and Path(override).is_file():
        return override
    found = shutil.which('signtool')
    if found:
        return found
    patterns = [
        r'C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe',
        r'C:\Program Files\Windows Kits\10\bin\*\x64\signtool.exe',
        r'C:\Program Files (x86)\Windows Kits\11\bin\*\x64\signtool.exe',
    ]
    candidates = []
    for pattern in patterns:
        candidates.extend(glob.glob(pattern))
    if not candidates:
        return ''
    return sorted(candidates)[-1]


def sign(exe: Path) -> int:
    pfx = os.environ.get('SIGN_PFX') or os.environ.get('SIGN_CERT') or ''
    password = os.environ.get('SIGN_PFX_PASSWORD', '')
    thumbprint = os.environ.get('SIGN_THUMBPRINT', '')
    if not pfx and not thumbprint:
        print()
        print('Not signed: no code-signing certificate configured.')
        print('Defender will still treat this exe as an unknown publisher.')
        print('With an OV/EV certificate run:')
        print('  set SIGN_PFX=C:\\path\\cert.pfx')
        print('  set SIGN_PFX_PASSWORD=...')
        print('  gui\\build.bat')
        return 0

    tool = find_signtool()
    if not tool:
        print('[ERROR] signtool.exe not found. Install the Windows SDK or '
              'set SIGNTOOL to its path.')
        return 1

    command = [tool, 'sign', '/fd', 'SHA256', '/td', 'SHA256',
               '/tr', 'http://timestamp.digicert.com']
    if pfx:
        if not Path(pfx).is_file():
            print(f'[ERROR] certificate not found: {pfx}')
            return 1
        command += ['/f', pfx]
        if password:
            command += ['/p', password]
    else:
        command += ['/sha1', thumbprint]
        command += ['/sm'] if os.environ.get('SIGN_MACHINE_STORE') else []
    command.append(str(exe))

    print()
    print('Signing with Authenticode ...')
    result = _subprocess.run(command)
    if result.returncode != 0:
        print('[ERROR] signtool sign failed')
        return result.returncode

    verify = [tool, 'verify', '/pa', '/all', str(exe)]
    result = _subprocess.run(verify)
    if result.returncode != 0:
        print('[ERROR] signature verification failed')
        return result.returncode
    print('Signature verified and timestamped.')
    return 0


def build() -> int:
    ensure_assets()

    icon = ASSETS / 'icon.ico'
    logo = ASSETS / 'logo.png'
    DIST.mkdir(exist_ok=True)

    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(
        [str(ROOT / 'tg_ws_proxy'), str(ROOT / 'tg_calls'), str(ROOT)])
    env['PYTHONUTF8'] = '1'

    problems = [text for text in (
        check_package('proxy', ROOT / 'tg_ws_proxy', env),
        check_package('tg_calls_relay', ROOT / 'tg_calls', env)) if text]
    if problems:
        print()
        for text in problems:
            print(f'[ERROR] {text}')
        print()
        return 1

    command = [
        sys.executable, '-m', 'nuitka',
        '--mode=standalone',
        f'--output-folder-name={PRODUCT}',
        '--windows-console-mode=disable',
        '--enable-plugins=pyqt6',
        f'--jobs={max(1, os.cpu_count() or 4)}',
        '--assume-yes-for-downloads',
        '--remove-output',
        f'--output-dir={DIST}',
        f'--output-filename={EXE_NAME}',
        f'--windows-icon-from-ico={icon}',
        f'--company-name={COMPANY}',
        f'--product-name={PRODUCT}',
        f'--file-version={VERSION}',
        f'--product-version={VERSION}',
        f'--file-description={DESCRIPTION}',
        f'--copyright={COPYRIGHT}',
        f'--include-raw-dir={ROOT / "zapret" / "bin"}=zapret/bin',
        f'--include-data-files={ROOT / "zapret" / "winws-tg-calls-relay.bat"}'
        '=zapret/winws-tg-calls-relay.bat',
        f'--include-data-files={ROOT / "zapret" / "LICENSE"}=zapret/LICENSE',
        f'--include-data-files={ROOT / "LICENSE"}=licenses/LICENSE',
        f'--include-data-files={ROOT / "tg_ws_proxy" / "LICENSE"}'
        '=licenses/tg-ws-proxy-LICENSE.txt',
        f'--include-data-files={ROOT / "THIRD_PARTY_LICENSES.md"}'
        '=licenses/THIRD_PARTY_LICENSES.md',
        f'--include-data-dir={ROOT / "lists"}=lists',
        f'--include-data-files={logo}=gui/assets/logo.png',
        '--include-package=cryptography',
        '--include-package=proxy',
        '--include-package=tg_calls_relay',
        '--include-package=httpx',
        '--include-package=httpcore',
        '--include-package=anyio',
        '--include-package=hpack',
        '--include-package=hyperframe',
        '--include-package=h2',
        '--include-package=python_socks',
        '--include-package=certifi',
        '--nofollow-import-to=tkinter',
        '--nofollow-import-to=unittest',
        '--nofollow-import-to=pydoc',
        str(ROOT / 'gui' / 'app.py'),
    ]

    banner(f'Building {EXE_NAME} with Nuitka')
    print(' '.join(f'"{part}"' if ' ' in str(part) else str(part)
                   for part in command))
    print()
    result = _subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode != 0:
        print('\n[ERROR] Nuitka build failed - see the output above.')
        return result.returncode

    exe = APP_DIR / EXE_NAME
    if not exe.is_file():
        print(f'\n[ERROR] expected {exe} was not produced.')
        return 1

    missing = [rel for rel in BUNDLED_FILES
               if not (APP_DIR / rel).is_file()]
    if missing:
        print('\n[ERROR] the build is missing bundled files:')
        for rel in missing:
            print(f'        {APP_DIR / rel}')
        print('        winws, the call relay and the installer would be broken;')
        print('        refusing to finish the build.')
        return 1

    size = sum(p.stat().st_size for p in APP_DIR.rglob('*')
               if p.is_file()) / (1024 * 1024)
    banner(f'Built: {APP_DIR}   ({size:.1f} MB)')
    print(f'Company : {COMPANY}')
    print(f'Product : {PRODUCT}   version {VERSION}')
    print(f'Author  : {AUTHOR}')
    print('Bundled : zapret/bin (winws + WinDivert), lists/, licenses/, '
          'gui/assets/logo.png')
    print(f'Verified: {len(BUNDLED_FILES)} bundled files present')
    print('Runtime : settings live in %USERPROFILE%\\tg-ws-turn-proxy-gui')
    print(f'Portable: run {exe}')
    print('Installer: dist\\tg-ws-turn-proxy-setup.exe (built by build.bat)')
    return sign(exe)


def main() -> int:
    if sys.version_info < (3, 9):
        print('[ERROR] Python 3.9+ is required')
        return 1
    return build()


if __name__ == '__main__':
    sys.exit(main())