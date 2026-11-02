from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

from gui import state

IS_WIN = os.name == 'nt'
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0

PROXY_MARKER = 'listening on'
RELAY_MARKER = 'relay live'
PROBE_OK = 'probe via TURN'
PROBE_FAIL = 'probe failed'
WINWS_EXE = os.path.join(state.BUNDLE, 'zapret', 'bin', 'winws.exe')

_SECRET_RE = re.compile(r'(?i)(secret[=:]\s*)(?:dd|ee)?[0-9a-f]{32,}')


def redact(text: str) -> str:
    return _SECRET_RE.sub(r'\1***', str(text))


def _redact_cmd(cmd) -> list:
    out = []
    hide = False
    for arg in cmd:
        text = str(arg)
        if hide:
            out.append('***')
            hide = False
        elif text == '--secret':
            out.append(text)
            hide = True
        elif text.startswith('--secret='):
            out.append('--secret=***')
        else:
            out.append(redact(text))
    return out


def decode_line(raw: bytes) -> str:
    if isinstance(raw, str):
        return raw.rstrip('\r\n')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        oem = any(0x80 <= b < 0xC0 and b not in (0xA8, 0xAB, 0xBB)
                  for b in raw)
        text = raw.decode('cp866' if oem else 'cp1251', errors='replace')
    return text.rstrip('\r\n')


def decode_blob(raw: bytes) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return '\n'.join(decode_line(part) for part in raw.split(b'\n'))


def build_env() -> dict:
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONWARNINGS'] = 'ignore'
    dll = os.path.join(state.BUNDLE, 'zapret', 'bin', 'WinDivert.dll')
    if os.path.isfile(dll):
        env['TG_CALLS_WINDIVERT_DLL'] = dll
    return env


def proxy_cmd(args: list) -> tuple:
    if state.FROZEN:
        return [state.launcher_exe(), '--run-proxy'] + [str(a) for a in args], None
    return [sys.executable, '-u', '-m', 'proxy.tg_ws_proxy'] + \
           [str(a) for a in args], state.PROXY_DIR


def relay_cmd(args: list) -> tuple:
    if state.FROZEN:
        return [state.launcher_exe(), '--run-relay'] + [str(a) for a in args], None
    return [sys.executable, '-u', '-m', 'tg_calls_relay'] + \
           [str(a) for a in args], state.RELAY_DIR


def winws_cmd() -> tuple:
    return ['cmd', '/c', state.ZAPRET_BAT], os.path.dirname(state.ZAPRET_BAT)


class Emitter:

    def __init__(self, q: 'queue.Queue'):
        self.q = q

    def _put(self, item) -> None:
        try:
            self.q.put_nowait(item)
        except queue.Full:
            pass

    def log(self, tag: str, line: str) -> None:
        if line:
            self._put(('log', tag, line))

    def state(self, tag: str, value: str) -> None:
        self._put(('state', tag, value))

    def call(self, fn: Callable[[], None]) -> None:
        self._put(('fn', fn))


def _popen(cmd, cwd: Optional[str], stdin_payload: Optional[bytes] = None,
           extra_env: Optional[dict] = None):
    stdin = subprocess.PIPE if stdin_payload is not None else subprocess.DEVNULL
    env = build_env()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        list(cmd), cwd=cwd, env=env, stdin=stdin,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW if IS_WIN else 0)
    if stdin_payload:
        try:
            proc.stdin.write(stdin_payload)
            proc.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass
    return proc


class Service:

    def __init__(self, tag: str, emitter: Emitter):
        self.tag = tag
        self.em = emitter
        self.proc: Optional[subprocess.Popen] = None
        self.state = 'stopped'
        self.marker = ''
        self._lock = threading.Lock()
        self._stopping = False

    def start(self, cmd, cwd: Optional[str] = None, marker: str = '',
              stdin_payload: Optional[bytes] = None) -> bool:
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return False
            self.marker = marker.lower()
            self._stopping = False
            self._set_state('starting')
            try:
                self.proc = _popen(cmd, cwd, stdin_payload)
            except OSError as exc:
                self.em.log(self.tag, f'failed to start: {exc}')
                self._set_state('error')
                return False
            proc = self.proc
        self.em.log(self.tag, '$ ' + ' '.join(
            _quote(a) for a in _redact_cmd(cmd)))
        threading.Thread(target=self._pump, args=(proc,),
                         daemon=True, name=f'{self.tag}-pump').start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            proc = self.proc
            self.proc = None
            self._stopping = True
        if proc is None or proc.poll() is not None:
            self._set_state('stopped')
            return
        try:
            proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._set_state('stopped')

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _pump(self, proc: subprocess.Popen) -> None:
        saw_marker = False
        try:
            for raw in proc.stdout:
                line = decode_line(raw)
                if not line:
                    continue
                if not saw_marker and self.marker \
                        and self.marker in line.lower():
                    saw_marker = True
                    self._set_state('running')
                self.em.log(self.tag, redact(line))
        except (OSError, ValueError):
            pass
        finally:
            try:
                rc = proc.wait()
            except OSError:
                rc = -1
            
            is_current = (proc is self.proc)
            if is_current:
                self.proc = None
                
            if self._stopping:
                self._set_state('stopped')
            elif is_current:
                self._set_state('stopped' if rc == 0 else 'error')

    def _set_state(self, value: str) -> None:
        if self.state == value:
            return
        self.state = value
        self.em.state(self.tag, value)


def _quote(arg: str) -> str:
    return arg if (' ' not in arg and '"' not in arg) else f'"{arg}"'


def run_capture(cmd, cwd: Optional[str] = None,
                timeout: float = 90.0,
                on_line: Optional[Callable[[str], None]] = None) -> tuple:
    try:
        proc = _popen(cmd, cwd)
    except OSError as exc:
        return 1, f'failed to start: {exc}'
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            proc.kill()
            out, _ = proc.communicate(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            out = exc.output or b''
        text = decode_blob(out or b'')
        return 124, f'{text.rstrip()}\n--- timeout ---'.lstrip()
    text = decode_blob(out or b'')
    if on_line:
        for line in text.splitlines():
            on_line(line)
    return proc.returncode if proc.returncode is not None else 1, text


WINWS_GUI_ENV = {'TG_CALLS_GUI': '1'}


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Stop a `cmd /c` wrapper together with the child it launched."""
    if IS_WIN:
        try:
            result = subprocess.run(
                ['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                capture_output=True, timeout=5,
                creationflags=CREATE_NO_WINDOW)
            if result.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        proc.terminate()
    except OSError:
        pass


def run_bat(cmd, cwd: Optional[str], on_line: Callable[[str], None],
            on_done: Callable[[int], None],
            stdin_payload: bytes = b'\r\n' * 8) -> None:
    def worker():
        proc = None
        rc = 1
        try:
            proc = _popen(cmd, cwd, stdin_payload,
                          extra_env=WINWS_GUI_ENV)
            for raw in proc.stdout:
                on_line(decode_line(raw))
            rc = proc.wait()
        except (OSError, ValueError) as exc:
            on_line(f'failed to read winws output: {exc}')
            rc = 1
        finally:
            if proc is not None and proc.poll() is None:
                _terminate_tree(proc)
                try:
                    proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        proc.kill()
                    except OSError:
                        pass
            on_done(rc)

    threading.Thread(target=worker, daemon=True, name='winws-bat').start()


class Probe:

    def __init__(self, emitter: Emitter, tag: str = 'check'):
        self.em = emitter
        self.tag = tag
        self.proc: Optional[subprocess.Popen] = None

    def start(self, cmd, cwd: Optional[str],
              on_done: Callable[[bool, str], None],
              timeout: float = 45.0) -> None:
        def worker():
            try:
                proc = _popen(cmd, cwd)
            except OSError as exc:
                on_done(False, str(exc))
                return
            self.proc = proc
            result = {'ok': False, 'detail': ''}
            last = {'line': ''}

            def reader():
                try:
                    for raw in proc.stdout:
                        line = decode_line(raw)
                        if not line:
                            continue
                        last['line'] = line
                        self.em.log(self.tag, redact(line))
                        low = line.lower()
                        if PROBE_OK.lower() in low:
                            result.update(ok=True, detail=line)
                            return
                        if PROBE_FAIL.lower() in low:
                            result['detail'] = line
                            return
                except (OSError, ValueError):
                    pass

            thread = threading.Thread(target=reader, daemon=True,
                                      name='probe-reader')
            thread.start()
            thread.join(timeout)
            timed_out = thread.is_alive()
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if not result['detail']:
                result['detail'] = ('timeout - no answer from the TURN server'
                                   if timed_out else (last['line'] or 'no output'))
            on_done(bool(result['ok']), result['detail'])

        threading.Thread(target=worker, daemon=True, name='turn-probe').start()

    def cancel(self) -> None:
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass


def _winws_pids(own_only: bool = True) -> list:
    if not IS_WIN:
        return []
    script = "Get-CimInstance Win32_Process -Filter \"Name='winws.exe'\" | "
    if own_only:
        exe = os.path.abspath(WINWS_EXE).replace("'", "''")
        script += f"Where-Object {{ $_.ExecutablePath -eq '{exe}' }} | "
    script += "ForEach-Object { $_.ProcessId }"
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command',
             script],
            capture_output=True, timeout=6,
            creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(part) for part in out.stdout.split() if part.isdigit()]


def winws_running() -> bool:
    return bool(_winws_pids(own_only=False))


def stop_winws() -> None:
    for pid in _winws_pids():
        try:
            subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                           capture_output=True, timeout=5,
                           creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass


def is_elevated() -> bool:
    if not IS_WIN:
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False