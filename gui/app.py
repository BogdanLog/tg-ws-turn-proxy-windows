from __future__ import annotations

import io
import os
import queue
import subprocess
import sys
import threading

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect,
                             QHBoxLayout, QLabel, QVBoxLayout, QWidget,
                             QSystemTrayIcon)

from gui import __version__ as VERSION
from gui import icons, services, state
from gui import theme
from gui.i18n import set_lang, t
from gui.main_view import MainView
from gui.screens import (BootPage, CheckPage, MtprotoPage, ProxyRunPage,
                         SourcePage, TurnPage, WelcomePage)
from gui.settings_dialog import SettingsDialog
from gui.theme import PAL
from gui.widgets import (AnimatedStack, IconButton, Page, Toast, Switch,
                         TrayMenu, divider, label)

DRAIN_MS = 70
WINWS_POLL_MS = 5000
WINDOW_SIZE = (560, 720)
MIN_SIZE = (520, 630)


def _fix_stdio() -> None:
    for name, fd in (('stdout', 1), ('stderr', 2)):
        current = getattr(sys, name, None)
        broken = current is None or not hasattr(current, 'write')
        if not broken:
            try:
                current.fileno()
            except Exception:
                broken = True
        if not broken:
            continue
        try:
            raw = os.fdopen(fd, 'wb')
            setattr(sys, name,
                    io.TextIOWrapper(raw, encoding='utf-8', errors='replace',
                                     line_buffering=True))
        except Exception:
            pass


def _add_source_path(directory: str, package: str) -> None:
    if not os.path.isfile(os.path.join(directory, package, '__init__.py')):
        return
    target = os.path.abspath(directory)
    sys.path[:] = [entry for entry in sys.path
                   if os.path.abspath(entry or '.') != target]
    sys.path.insert(0, target)


def _run_child(argv) -> int:
    _fix_stdio()
    mode, rest = argv[0], argv[1:]
    if mode == '--run-proxy':
        try:
            _add_source_path(state.PROXY_DIR, 'proxy')
            sys.argv = ['tg_ws_proxy.py'] + list(rest)
            try:
                from proxy import tg_ws_proxy
            except ImportError as exc:
                _log_child_error(f'proxy package missing from bundle: {exc}')
                return 1
            return int(tg_ws_proxy.main() or 0)
        except SystemExit as exc:
            return int(exc.code or 0)
        except BaseException:
            _dump_child_crash(mode)
            return 1
    if mode == '--run-relay':
        try:
            _add_source_path(state.RELAY_DIR, 'tg_calls_relay')
            try:
                from tg_calls_relay import __main__ as relay_main
            except ImportError as exc:
                _log_child_error(f'tg_calls_relay package missing from bundle: {exc}')
                return 1
            return int(relay_main.main(list(rest)) or 0)
        except SystemExit as exc:
            return int(exc.code or 0)
        except BaseException:
            _dump_child_crash(mode)
            return 1
    return 2


def _dump_child_crash(mode: str) -> None:
    import traceback
    text = traceback.format_exc()
    try:
        if sys.stderr is not None and hasattr(sys.stderr, 'write'):
            sys.stderr.write(text)
    except Exception:
        pass
    try:
        path = os.path.join(state.ROOT, 'child-crash.log')
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(f'\n=== {mode} ===\n{text}\n')
    except OSError:
        pass


def _log_exception(where: str, exc: BaseException) -> None:
    import traceback
    text = (f'{where}: {type(exc).__name__}: {exc}\n'
            + ''.join(traceback.format_exception(
                type(exc), exc, exc.__traceback__)))
    try:
        if sys.stderr is not None and hasattr(sys.stderr, 'write'):
            sys.stderr.write(text)
    except Exception:
        pass
    try:
        path = os.path.join(state.ROOT, 'gui-errors.log')
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(f'\n=== {where} ===\n{text}\n')
    except OSError:
        pass


def _log_child_error(text: str) -> None:
    try:
        if sys.stderr is not None and hasattr(sys.stderr, 'write'):
            sys.stderr.write(text + '\n')
    except Exception:
        pass
    try:
        path = os.path.join(state.ROOT, 'child-crash.log')
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(f'\n=== error ===\n{text}\n')
    except OSError:
        pass


def _gui_command() -> tuple:
    if state.FROZEN:
        return state.launcher_exe(), list(sys.argv[1:])
    exe = sys.executable
    if os.path.basename(exe).lower() == 'python.exe':
        pythonw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
        if os.path.exists(pythonw):
            exe = pythonw
    return exe, [os.path.abspath(__file__)] + list(sys.argv[1:])


def _relaunch_elevated() -> bool:
    if os.name != 'nt' or services.is_elevated():
        return False
    exe, args = _gui_command()
    try:
        import ctypes
        result = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', exe, subprocess.list2cmdline(args),
            os.path.dirname(os.path.abspath(exe)) or None, 1)
    except Exception:
        return False
    return int(result) > 32


class TitleBar(QWidget):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.setFixedHeight(54)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 9, 10, 9)
        layout.setSpacing(9)

        self.logo = QLabel()
        pixmap = theme.logo_pixmap(28)
        if not pixmap.isNull():
            self.logo.setPixmap(pixmap)
        self.logo.setFixedSize(28, 28)
        layout.addWidget(self.logo)
        self.name = QLabel(t('app.name'))
        self.name.setStyleSheet('font-size: 13px; font-weight: 700;')
        layout.addWidget(self.name)
        self.version = QLabel(f'v{VERSION}')
        self.version.setObjectName('Tiny')
        layout.addWidget(self.version, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        self.settings_btn = IconButton('gear', t('btn.settings'), 30, 16)
        self.settings_btn.clicked.connect(shell.open_settings)
        self.minimize_btn = IconButton('minimize', t('btn.minimize'), 30, 15)
        self.minimize_btn.clicked.connect(shell.showMinimized)
        self.close_btn = IconButton('close', t('btn.close'), 30, 14,
                                    role='close')
        self.close_btn.clicked.connect(shell.close)
        layout.addWidget(self.settings_btn)
        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.close_btn)
        self._drag_offset = None

    def retranslate(self) -> None:
        self.name.setText(t('app.name'))
        self.settings_btn.setToolTip(t('btn.settings'))
        self.minimize_btn.setToolTip(t('btn.minimize'))
        self.close_btn.setToolTip(t('btn.close'))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                return
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.window().frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            self.window().move(
                event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class Shell(QWidget):
    EDGE = 7

    def __init__(self, elevated: bool = True):
        super().__init__()
        self.elevated = elevated
        self.settings = state.load_settings()
        set_lang(self.settings.lang)

        self._autostart = '--autostart' in sys.argv

        self.queue: queue.Queue = queue.Queue(maxsize=10000)
        self.em = services.Emitter(self.queue)
        self.services = {
            'proxy': services.Service('proxy', self.em),
            'relay': services.Service('relay', self.em),
        }
        self.probe = services.Probe(self.em)
        self.log_buffer: list = []
        self.page: Page = None
        self.main: MainView = None
        self._winws_state = 'stopped'
        self._dialog = None
        self._closing = False

        state.log_paths(self.log)

        self._setup_tray()

        self.setWindowTitle(f'{t("app.name")}   v{VERSION}')
        self.setWindowIcon(theme.logo_icon())
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.resize(*WINDOW_SIZE)
        self.setMinimumSize(*MIN_SIZE)

        self._build()
        self._center()
        self._update_warn()

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(DRAIN_MS)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start()
        self._winws_timer = QTimer(self)
        self._winws_timer.setInterval(WINWS_POLL_MS)
        self._winws_timer.timeout.connect(self.refresh_winws_chip)
        self._winws_timer.start()

        QTimer.singleShot(90, self._startup)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 26)
        outer.setSpacing(0)
        self.panel = QFrame()
        self.panel.setObjectName('Shell')
        shadow = QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 9)
        shadow.setColor(QColor(0, 0, 0, 165))
        self.panel.setGraphicsEffect(shadow)
        outer.addWidget(self.panel)

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self)
        root.addWidget(self.titlebar)
        root.addWidget(divider())

        self.stack = AnimatedStack()
        root.addWidget(self.stack, 1)

        self.warn_wrap = QWidget()
        warn_layout = QHBoxLayout(self.warn_wrap)
        warn_layout.setContentsMargins(18, 8, 18, 12)
        warn = QFrame()
        warn.setObjectName('WarnBox')
        inner = QHBoxLayout(warn)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(9)
        shield = QLabel()
        shield.setPixmap(icons.pixmap('shield', 16, PAL['orange']))
        shield.setFixedSize(16, 16)
        self.warn_lbl = label(t('main.no_admin'), 'Muted', wrap=True)
        self.warn_lbl.setStyleSheet(f'color: {PAL["orange"]};')
        inner.addWidget(shield, 0, Qt.AlignmentFlag.AlignTop)
        inner.addWidget(self.warn_lbl, 1)
        warn_layout.addWidget(warn)
        root.addWidget(self.warn_wrap)
        self.warn_wrap.hide()

        self._toast = Toast(self)
        self._opacity_anim = None

    def _center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  max(area.top() + 8,
                      area.center().y() - self.height() // 2))

    def _update_warn(self) -> None:
        self.warn_wrap.setVisible(not self.elevated)

    def _startup(self) -> None:
        if self.settings.setup_done:
            self.run_winws_profile()
            self.show_main()
            if self._autostart:
                QTimer.singleShot(200, self._autostart_services)
        else:
            self.show_page(BootPage)

    def _autostart_services(self) -> None:
        if self.main is None:
            return
        if not self.settings.ready():
            self.log('app', 'autostart skipped: setup incomplete')
            return
        self.log('app', 'autostart: starting services')
        self.start_services()

    def _replace_page(self, page: Page) -> None:
        old = self.page
        if old is not None:
            old.on_hide()
            self.stack.removeWidget(old)
            old.deleteLater()
        self.page = page
        self.main = None
        self.stack.addWidget(page)
        self.stack.show_page(page)

    def show_page(self, cls) -> None:
        page = cls(self)
        self._replace_page(page)
        page.on_show()

    def show_main(self) -> None:
        main = MainView(self)
        self._replace_page(main)
        self.main = main
        main.set_winws_state(self._winws_state)
        main.append_many(self.log_buffer)
        main.refresh_action()

    def _remember_log(self, tag: str, line: str) -> None:
        self.log_buffer.append((tag, line))
        if len(self.log_buffer) > 4000:
            del self.log_buffer[:1000]

    def log(self, tag: str, line: str) -> None:
        if not line:
            return
        self._remember_log(tag, line)
        if self.main is not None:
            self.main.append(tag, line)

    def _drain(self) -> None:
        batch = []
        for _ in range(400):
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            try:
                kind = item[0]
                if kind == 'log':
                    if item[2]:
                        self._remember_log(item[1], item[2])
                        batch.append((item[1], item[2]))
                    continue
                if batch:
                    if self.main is not None:
                        self.main.append_many(batch)
                    batch = []
                if kind == 'state':
                    self._state_changed(item[1], item[2])
                elif kind == 'fn':
                    item[1]()
            except BaseException as exc:
                _log_exception('ui-callback', exc)
        if batch and self.main is not None:
            self.main.append_many(batch)

    def _state_changed(self, tag: str, value: str) -> None:
        if value in ('starting', 'running', 'error'):
            self.log('app', f'{tag} state: {value}')
        if self.main is not None:
            self.main.refresh_action()

    def start_proxy(self) -> bool:
        if not self.settings.proxy_configured():
            self.log('app', t('main.need_setup'))
            return False
        service = self.services['proxy']
        if service.running:
            return True
        cmd, cwd = services.proxy_cmd(state.proxy_args(self.settings))
        started = service.start(cmd, cwd, marker=services.PROXY_MARKER)
        if self.main is not None:
            self.main.refresh_action()
        return started

    def stop_proxy(self) -> None:
        self.services['proxy'].stop()
        if self.main is not None:
            self.main.refresh_action()

    def restart_proxy(self) -> None:
        self.stop_proxy()
        self.start_proxy()

    def start_relay(self) -> bool:
        if not self.settings.turn_configured():
            self.log('relay', t('main.need_setup'))
            return False
        service = self.services['relay']
        if service.running:
            return True
        state.sanitize_relay_config(self.settings)
        cmd, cwd = services.relay_cmd(state.relay_args(self.settings))
        started = service.start(cmd, cwd, marker=services.RELAY_MARKER)
        if self.main is not None:
            self.main.refresh_action()
        return started

    def stop_relay(self) -> None:
        self.services['relay'].stop()
        if self.main is not None:
            self.main.refresh_action()

    def restart_relay(self) -> None:
        self.stop_relay()
        self.start_relay()

    def start_services(self) -> None:
        if self._winws_state not in ('running', 'starting'):
            self.run_winws_profile()
        if not self.start_proxy():
            return
        if self.settings.turn_configured():
            self.start_relay()
        if self.main is not None:
            self.main.refresh_action()

    def stop_services(self) -> None:
        self.stop_relay()
        self.stop_proxy()
        services.stop_winws()
        self._set_winws('stopped')
        if self.main is not None:
            self.main.refresh_action()
        self.refresh_winws_chip()

    def run_winws_profile(self) -> None:
        if not os.path.exists(state.ZAPRET_BAT):
            self.log('winws', t('boot.not_found'))
            self._set_winws('error')
            return
        self.log('winws', f'$ {state.ZAPRET_BAT}')
        self._set_winws('starting')
        cmd, cwd = services.winws_cmd()
        services.run_bat(
            cmd, cwd,
            on_line=lambda text: self.em.call(
                lambda text=text: self.log('winws', text)),
            on_done=lambda rc: self.em.call(
                lambda rc=rc: self._winws_done(rc)))

    def _winws_done(self, rc: int) -> None:
        if rc != 0:
            self._set_winws('error')
            return
        self.refresh_winws_chip()

    def _set_winws(self, value: str) -> None:
        self._winws_state = value
        if self.main is not None:
            self.main.set_winws_state(value)

    def refresh_winws_chip(self) -> None:
        if not self.isVisible():
            return

        def worker():
            running = services.winws_running()
            self.em.call(lambda: self._set_winws(
                'running' if running else 'stopped'))

        threading.Thread(target=worker, daemon=True,
                         name='winws-poll').start()

    def connect_proxy(self) -> None:
        link = self.settings.proxy_link()
        if theme.open_tg_link(link):
            self.log('app', f'$ {services.redact(link)}')
        else:
            theme.copy_text(link)
            self.toast(t('btn.copied'), 'copy')

    def open_settings(self) -> None:
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_()
            return
        self._dialog = SettingsDialog(self)
        self._dialog.exec()
        self._dialog.deleteLater()
        self._dialog = None

    def toast(self, text: str, icon_name: str = 'check',
              color: str = '') -> None:
        self._toast.show_message(text, icon_name, color)

    def save_settings(self) -> None:
        state.save_settings(self.settings)

    def retranslate(self) -> None:
        self.setWindowTitle(f'{t("app.name")}   v{VERSION}')
        self.titlebar.retranslate()
        self.warn_lbl.setText(t('main.no_admin'))
        if self.main is not None:
            self.main.retranslate()
        elif self.page is not None:
            if not isinstance(self.page, (BootPage, CheckPage, SourcePage,
                                          MtprotoPage, TurnPage,
                                          ProxyRunPage)):
                self.show_page(type(self.page))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, '_toast', None) is not None:
            self._toast.reposition()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._opacity_anim is None:
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b'windowOpacity', self)
            anim.setDuration(260)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
            self._opacity_anim = anim

    def _edges(self, pos) -> Qt.Edge:
        edges = Qt.Edge(0)
        if pos.x() <= self.EDGE:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - self.EDGE:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= self.EDGE:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - self.EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges(event.position().toPoint())
            if edges:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemResize(edges):
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        edges = self._edges(event.position().toPoint())
        cursor = Qt.CursorShape.ArrowCursor
        if (edges & Qt.Edge.LeftEdge and edges & Qt.Edge.TopEdge) or \
                (edges & Qt.Edge.RightEdge and edges & Qt.Edge.BottomEdge):
            cursor = Qt.CursorShape.SizeFDiagCursor
        elif (edges & Qt.Edge.RightEdge and edges & Qt.Edge.TopEdge) or \
                (edges & Qt.Edge.LeftEdge and edges & Qt.Edge.BottomEdge):
            cursor = Qt.CursorShape.SizeBDiagCursor
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            cursor = Qt.CursorShape.SizeHorCursor
        elif edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            cursor = Qt.CursorShape.SizeVerCursor
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def closeEvent(self, event) -> None:
        if not self._closing:
            event.ignore()
            self.hide()
            self.tray.showMessage(t('app.name'), t('tray.minimized'), QSystemTrayIcon.MessageIcon.Information, 2000)
            return

        try:
            self.probe.cancel()
        except Exception:
            pass
        try:
            self.stop_services()
        finally:
            services.stop_winws()
            event.accept()

    def _setup_tray(self) -> None:
        self.tray = TrayMenu(theme.logo_icon(), self)
        self.tray.show_requested.connect(self._restore_window)
        self.tray.exit_requested.connect(self._quit_app)
        self.tray.show()

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self) -> None:
        self._closing = True
        self.close()
        QApplication.quit()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ('--run-proxy', '--run-relay'):
        return _run_child(sys.argv[1:])

    elevated = services.is_elevated()
    if os.name == 'nt' and not elevated and '--no-elevate' not in sys.argv:
        if _relaunch_elevated():
            return 0
        elevated = False

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)

    def _qt_excepthook(exc_type, exc, tb) -> None:
        if exc is None:
            exc = exc_type()
        _log_exception('qt-slot', exc)

    sys.excepthook = _qt_excepthook
    app.setApplicationName('tg-ws-turn-proxy')
    _early_settings = state.load_settings()
    set_lang(_early_settings.lang)
    app.setApplicationDisplayName(t('app.name'))
    app.setApplicationVersion(VERSION)
    app.setOrganizationName('BogdanLog.Inc')
    app.setWindowIcon(theme.logo_icon())
    theme.apply(app)

    from PyQt6.QtNetwork import QLocalServer, QLocalSocket

    single_key = 'tg-ws-turn-proxy-single-instance'

    def _notify_existing() -> bool:
        sock = QLocalSocket()
        sock.connectToServer(single_key)
        if not sock.waitForConnected(400):
            return False
        sock.write(b'show')
        sock.flush()
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        return True

    if _notify_existing():
        return 0

    state.sync_startup_state(_early_settings)

    server = QLocalServer()
    QLocalServer.removeServer(single_key)
    if not server.listen(single_key):
        if _notify_existing():
            return 0
        _log_exception('single-instance', OSError(
            f'cannot listen on {single_key}: {server.errorString()}'))

    shell_holder = {}

    def _activate_existing() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.disconnectFromServer()
        target = shell_holder.get('shell')
        if target is not None:
            target._restore_window()
            target.show()

    server.newConnection.connect(_activate_existing)

    minimized = '--minimized' in sys.argv
    shell = Shell(elevated=elevated)
    shell_holder['shell'] = shell
    if server.hasPendingConnections():
        _activate_existing()
    if minimized:
        shell._minimized_start = True
        shell.hide()
    else:
        shell.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())