from __future__ import annotations

import threading
from dataclasses import asdict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QStackedWidget,
                             QVBoxLayout, QWidget)

from gui import __version__, services, state
from gui.i18n import get_lang, set_lang, t
from gui.theme import PAL
from gui.widgets import (Button, ChoiceCard, ChoiceGroup, Field, IconButton,
                         ScrollBody, Segmented, Spinner, card, divider, h2,
                         label, Switch)

PROXY_KEYS = ('host', 'port', 'secret', 'source_mode', 'worker_domains',
              'custom_domain')
TURN_KEYS = ('turn_provider', 'hf_token', 'cf_key_id', 'cf_api_token',
             'turn_username', 'turn_credential', 'turn_url')


class _Header(QWidget):
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                return
        super().mousePressEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.settings = shell.settings
        self.before = asdict(self.settings)
        self._busy = False
        self._alive = True
        self._texts = []
        self._fields = []
        self._choices = []

        self.setWindowTitle(t('set.title'))
        self.setWindowFlags(Qt.WindowType.Dialog
                            | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(620, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        panel = QFrame()
        panel.setObjectName('Shell')
        outer.addWidget(panel)
        root = QVBoxLayout(panel)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = _Header()
        head = QHBoxLayout(header)
        head.setContentsMargins(20, 14, 10, 12)
        head.setSpacing(8)
        self.title_lbl = h2(t('set.title'))
        head.addWidget(self.title_lbl, 1)
        self.close_btn = IconButton('close', t('btn.close'), 28, 14,
                                    role='close')
        self.close_btn.clicked.connect(self._cancel)
        head.addWidget(self.close_btn)
        root.addWidget(header)
        root.addWidget(divider())

        tabs_wrap = QWidget()
        tabs_layout = QHBoxLayout(tabs_wrap)
        tabs_layout.setContentsMargins(18, 11, 18, 2)
        self.tabs = Segmented([('proxy', t('set.tab_proxy')),
                               ('calls', t('set.tab_calls')),
                               ('general', t('set.tab_general'))], height=34)
        self.tabs.changed.connect(self._switch_tab)
        tabs_layout.addWidget(self.tabs)
        root.addWidget(tabs_wrap)

        stack_wrap = QWidget()
        stack_layout = QVBoxLayout(stack_wrap)
        stack_layout.setContentsMargins(18, 14, 18, 0)
        stack_layout.setSpacing(0)
        self.stack = QStackedWidget()
        stack_layout.addWidget(self.stack)
        root.addWidget(stack_wrap, 1)

        self._build_proxy_tab()
        self._build_calls_tab()
        self._build_general_tab()

        proxy_ready = self.settings.proxy_configured()
        turn_ready = self.settings.turn_configured()

        if not proxy_ready:
            self.tabs.set_enabled('proxy', False)
            self.tabs.buttons['proxy'].setToolTip(t('set.tab_locked'))
            self.tabs.set_enabled('calls', False)
            self.tabs.buttons['calls'].setToolTip(t('set.tab_locked'))
            self.tabs.set_current('general')
            self.stack.setCurrentIndex(2)
        elif not turn_ready:
            self.tabs.set_enabled('calls', False)
            self.tabs.buttons['calls'].setToolTip(t('set.tab_locked'))

        root.addWidget(divider())
        footer = QWidget()
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(18, 11, 18, 14)
        foot.setSpacing(8)
        self.err_lbl = label('', 'Error', wrap=True)
        self.err_lbl.hide()
        self.spinner = Spinner(16)
        self.spinner.hide()
        self.cancel_btn = Button(t('btn.cancel'), 'ghost', height=36)
        self.cancel_btn.setFixedWidth(112)
        self.cancel_btn.clicked.connect(self._cancel)
        self.save_btn = Button(t('btn.save'), 'primary', height=36)
        self.save_btn.setFixedWidth(124)
        self.save_btn.clicked.connect(self._save)
        foot.addWidget(self.err_lbl, 1)
        foot.addStretch(1)
        foot.addWidget(self.spinner)
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.save_btn)
        root.addWidget(footer)



    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        parent = self.shell.frameGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(parent.center())
        self.move(frame.topLeft())

    def _text(self, key: str, style: str = 'Muted', wrap: bool = True):
        widget = label(t(key), style, wrap=wrap)
        self._texts.append((widget, key))
        return widget

    def _field(self, parent_layout, key: str, value: str, **kwargs) -> Field:
        field = Field(t(key), value, **kwargs)
        self._fields.append((field, key))
        parent_layout.addWidget(field)
        return field

    def _choice(self, title_key: str, desc_key: str = '', link_key: str = '',
                link_url: str = '') -> ChoiceCard:
        card_widget = ChoiceCard(t(title_key), t(desc_key) if desc_key else '',
                                 t(link_key) if link_key else '', link_url)
        self._choices.append((card_widget, title_key, desc_key, link_key))
        return card_widget

    def _page(self, title_key: str = '', hint_key: str = '') -> ScrollBody:
        page = ScrollBody()
        if title_key:
            page.box.addWidget(self._text(title_key, 'H2'))
        if hint_key:
            page.box.addWidget(self._text(hint_key, 'Faint', wrap=True))
        return page

    def _build_proxy_tab(self) -> None:
        settings = self.settings
        page = self._page()
        box = card(14, 10)
        page.box.addWidget(box)
        self.mode = ChoiceGroup()
        self.mode.changed.connect(lambda _v: self._clear_error())

        self.workers_card = self._choice('source.workers_title',
                                         'source.workers_desc',
                                         'source.workers_link',
                                         state.DOCS_WORKER)
        box.body.addWidget(self.workers_card)
        self.mode.add(self.workers_card, state.SOURCE_WORKERS)
        values = list(settings.worker_domains[:3])
        while len(values) < 3:
            values.append('')
        self.worker_fields = []
        for index, value in enumerate(values):
            field = self._field(self.workers_card.body_layout,
                                f'field.worker{index + 1}', value)
            self.worker_fields.append(field)

        self.domain_card = self._choice('source.domain_title',
                                        'source.domain_desc',
                                        'source.domain_link',
                                        state.DOCS_CFPROXY)
        box.body.addWidget(self.domain_card)
        self.mode.add(self.domain_card, state.SOURCE_DOMAIN)
        self.domain_field = self._field(self.domain_card.body_layout,
                                        'field.domain',
                                        settings.custom_domain)

        self.public_card = self._choice('source.public_title',
                                        'source.public_desc')
        box.body.addWidget(self.public_card)
        self.mode.add(self.public_card, state.SOURCE_PUBLIC)
        self.mode.set_value(settings.source_mode, notify=False, animate=False)

        conn = card(16, 10)
        page.box.addWidget(conn)
        conn.body.addWidget(self._text('set.conn_title', 'H2'))
        conn.body.addWidget(self._text('set.conn_hint', 'Faint', wrap=True))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.host_field = self._field(row, 'field.host', str(settings.host))
        self.host_field.setFixedWidth(158)
        self.port_field = self._field(row, 'field.port', str(settings.port))
        self.port_field.setFixedWidth(96)
        row.addStretch(1)
        conn.body.addLayout(row)

        secret_row = QHBoxLayout()
        secret_row.setContentsMargins(0, 0, 0, 0)
        secret_row.setSpacing(8)
        self.secret_field = self._field(
            secret_row, 'field.secret',
            'dd' + state.normalize_secret(settings.secret), mono=True)
        self.refresh_btn = Button(t('btn.refresh'), 'ghost',
                                  icon_name='refresh', icon_color=PAL['cyan'],
                                  height=36)
        self.refresh_btn.setFixedWidth(124)
        self.refresh_btn.clicked.connect(
            lambda: self.secret_field.set_text('dd' + state.gen_secret()))
        secret_row.addWidget(self.refresh_btn, 0,
                             Qt.AlignmentFlag.AlignBottom)
        conn.body.addSpacing(2)
        conn.body.addLayout(secret_row)
        conn.body.addWidget(self._text('mtproto.secret_hint', 'Faint',
                                       wrap=True))
        page.box.addStretch(1)
        self.stack.addWidget(page)

    def _build_calls_tab(self) -> None:
        settings = self.settings
        page = self._page()
        box = card(14, 10)
        page.box.addWidget(box)
        self.provider = ChoiceGroup()
        self.provider.changed.connect(lambda _v: self._clear_error())

        hf = self._choice('turn.hf_title', 'turn.hf_desc', 'turn.hf_link',
                          state.HF_TOKENS_URL)
        box.body.addWidget(hf)
        self.provider.add(hf, state.TURN_HF)
        self.hf_field = self._field(hf.body_layout, 'field.hf_token',
                                    settings.hf_token, mono=True)

        cf = self._choice('turn.cf_title', 'turn.cf_desc', 'turn.cf_link',
                          state.CF_TURN_DOCS)
        box.body.addWidget(cf)
        self.provider.add(cf, state.TURN_CF)
        self.key_field = self._field(cf.body_layout, 'field.cf_key',
                                     settings.cf_key_id, mono=True)
        self.token_field = self._field(cf.body_layout, 'field.cf_token',
                                       settings.cf_api_token, password=True,
                                       mono=True)

        custom = self._choice('turn.custom_title', 'turn.custom_desc')
        box.body.addWidget(custom)
        self.provider.add(custom, state.TURN_CUSTOM)
        self.user_field = self._field(custom.body_layout, 'field.turn_user',
                                      settings.turn_username, mono=True)
        self.cred_field = self._field(custom.body_layout, 'field.turn_cred',
                                      settings.turn_credential, password=True,
                                      mono=True)
        self.url_field = self._field(custom.body_layout, 'field.turn_url',
                                     settings.turn_url, mono=True,
                                     placeholder='turns://host:443')

        public = self._choice('turn.public_title', 'turn.public_desc')
        box.body.addWidget(public)
        self.provider.add(public, state.TURN_PUBLIC)
        self.public_field = self._field(public.body_layout, 'field.hf_token',
                                        state.PUBLIC_HF_TOKEN, mono=True,
                                        read_only=True)
        self.provider.set_value(settings.turn_provider, notify=False,
                                animate=False)
        page.box.addStretch(1)
        self.stack.addWidget(page)

    def _build_general_tab(self) -> None:
        page = self._page()
        
        lang_box = card(16, 10)
        page.box.addWidget(lang_box)
        lang_box.body.addWidget(self._text('set.lang', 'H2'))
        lang_box.body.addWidget(self._text('set.lang_hint', 'Faint', wrap=True))
        self.lang_seg = Segmented([('ru', t('lang.ru')),
                                   ('en', t('lang.en'))], height=34)
        self.lang_seg.setFixedWidth(260)
        self.lang_seg.set_current(get_lang())
        self.lang_seg.changed.connect(self._set_lang)
        lang_box.body.addWidget(self.lang_seg, 0, Qt.AlignmentFlag.AlignLeft)

        self.startup_launch_enabled = getattr(self.settings, 'startup_launch', False)
        self.startup_switch = Switch()
        self.startup_switch.setChecked(self.startup_launch_enabled)
        self.startup_switch.toggled.connect(self._startup_changed)
        self.startup_box = card(16, 8)
        self.startup_box.body.addWidget(self._text('set.startup_title', 'H2'))
        self.startup_box.body.addWidget(self._text('set.startup_hint', 'Faint', wrap=True))
        self.startup_box.body.addWidget(self.startup_switch)
        self.startup_box.body.addStretch(1)
        page.box.addWidget(self.startup_box)

        about = card(16, 8)
        page.box.addWidget(about)
        about.body.addWidget(self._text('set.about_title', 'H2'))
        about_text = t('set.about_text', version=__version__)
        about.body.addWidget(label(about_text, 'Lead', wrap=True))
        about.body.addWidget(label(f'tg-ws-turn-proxy  v{__version__}', 'Mono'))
        
        page.box.addStretch(1)
        self.stack.addWidget(page)

    def _switch_tab(self, key: str) -> None:
        self.stack.setCurrentIndex({'proxy': 0, 'calls': 1,
                                    'general': 2}.get(key, 0))

    def _set_lang(self, lang: str) -> None:
        if lang == get_lang():
            return
        set_lang(lang)
        self.settings.lang = lang
        self.shell.save_settings()
        self.retranslate()
        self.shell.retranslate()

    def _startup_changed(self, enabled: bool) -> None:
        if self._busy:
            return
        if enabled == self.startup_launch_enabled:
            return
        self.startup_launch_enabled = enabled
        worked = state.add_startup_launch(enabled)
        if not worked:
            self.startup_launch_enabled = not enabled
            self.startup_switch.blockSignals(True)
            self.startup_switch.setChecked(not enabled)
            self.startup_switch.blockSignals(False)
            self._set_error(t('set.startup_failed'))
            return
        self.settings.startup_launch = enabled
        self.shell.save_settings()
        self._clear_error()

    def retranslate(self) -> None:
        self.setWindowTitle(t('set.title'))
        self.title_lbl.setText(t('set.title'))
        self.close_btn.setToolTip(t('btn.close'))
        self.cancel_btn.setText(t('btn.cancel'))
        self.save_btn.setText(t('btn.save'))
        self.refresh_btn.setText(t('btn.refresh'))
        self.tabs.set_text('proxy', t('set.tab_proxy'))
        self.tabs.set_text('calls', t('set.tab_calls'))
        self.tabs.set_text('general', t('set.tab_general'))
        self.lang_seg.set_text('ru', t('lang.ru'))
        self.lang_seg.set_text('en', t('lang.en'))
        for widget, key in self._texts:
            widget.setText(t(key))
        for field, key in self._fields:
            field.set_caption(t(key))
        for card_widget, title_key, desc_key, link_key in self._choices:
            card_widget.set_title(t(title_key))
            if desc_key:
                card_widget.set_desc(t(desc_key))
            if link_key:
                card_widget.set_link_text(t(link_key))
        self._clear_error()

    def _clear_error(self) -> None:
        self.err_lbl.setText('')
        self.err_lbl.hide()
        if hasattr(self, 'startup_switch'):
            self.startup_switch.blockSignals(True)
            self.startup_switch.setChecked(self.startup_launch_enabled)
            self.startup_switch.blockSignals(False)

    def _set_error(self, text: str) -> None:
        self.err_lbl.setText(text)
        self.err_lbl.setVisible(bool(text))

    def _collect(self) -> state.Settings:
        data = asdict(self.shell.settings)
        data.update({
            'source_mode': self.mode.value(),
            'worker_domains': [f.text() for f in self.worker_fields],
            'custom_domain': self.domain_field.text(),
            'host': self.host_field.text(),
            'port': self.port_field.text(),
            'secret': state.normalize_secret(self.secret_field.raw()),
            'turn_provider': self.provider.value(),
            'hf_token': self.hf_field.text(),
            'cf_key_id': self.key_field.text(),
            'cf_api_token': self.token_field.raw().strip(),
            'turn_username': self.user_field.text(),
            'turn_credential': self.cred_field.raw().strip(),
            'turn_url': self.url_field.text(),
        })
        raw_port = str(data['port']).strip()
        data['port'] = int(raw_port) if raw_port.isdigit() else 0
        return state.Settings(**data)

    @staticmethod
    def _validate_proxy(settings: state.Settings) -> str:
        if not state.is_valid_ip(settings.host):
            return t('mtproto.host_bad')
        try:
            port = int(settings.port)
        except (TypeError, ValueError):
            return t('mtproto.port_bad')
        if not (1 <= port <= 65535):
            return t('mtproto.port_bad')
        if not state.is_hex_secret(settings.secret):
            return t('mtproto.secret_bad')
        if settings.source_mode == state.SOURCE_WORKERS:
            if not settings.workers():
                return t('source.workers_hint')
            if any(not state.is_valid_domain(d) for d in settings.workers()):
                return t('err.domain')
        elif settings.source_mode == state.SOURCE_DOMAIN:
            if not state.is_valid_domain(settings.custom_domain):
                return t('err.domain')
        return ''

    @staticmethod
    def _validate_turn(settings: state.Settings) -> str:
        if settings.turn_provider == state.TURN_HF and not settings.hf_token:
            return t('err.token')
        if settings.turn_provider == state.TURN_CF and not (
                settings.cf_key_id and settings.cf_api_token):
            return t('err.cf_key')
        if settings.turn_provider == state.TURN_CUSTOM:
            if not (settings.turn_username and settings.turn_credential):
                return t('err.creds')
            if not state.is_valid_turn_url(settings.turn_url):
                return t('err.turn_url')
        return ''

    def _save(self) -> None:
        if self._busy:
            return
        new = self._collect()
        
        error = ''
        if self.tabs.buttons['proxy'].isEnabled():
            error = self._validate_proxy(new)
        
        if not error and self.tabs.buttons['calls'].isEnabled():
            error = self._validate_turn(new)
        
        if error:
            self._set_error(error)
            return
        self._clear_error()
        
        after = asdict(new)
        proxy_changed = any(self.before[key] != after[key]
                            for key in PROXY_KEYS)
        turn_changed = any(self.before[key] != after[key]
                           for key in TURN_KEYS)
        for key, value in after.items():
            setattr(self.shell.settings, key, value)
        self.shell.save_settings()
        self.shell.retranslate()

        if proxy_changed and self.shell.services['proxy'].running:
            self.shell.restart_proxy()
        if not turn_changed:
            self.shell.toast(t('set.saved'), 'check', PAL['cyan'])
            self.accept()
            return

        self._busy = True
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.spinner.show()
        self.spinner.start()
        threading.Thread(target=self._mint_worker, daemon=True,
                         name='settings-mint').start()

    def _mint_worker(self) -> None:
        cmd, cwd = services.relay_cmd(state.mint_args(self.shell.settings))
        rc, out = services.run_capture(cmd, cwd, timeout=90)
        if rc == 0:
            state.sanitize_relay_config(self.shell.settings)
        self.shell.em.call(lambda: self._minted(rc, out))

    def _minted(self, rc: int, out: str) -> None:
        if not self._alive:
            return
        for line in out.splitlines():
            if line.strip():
                self.shell.log('check', line)
        if rc != 0:
            self._busy = False
            self.spinner.stop()
            self.spinner.hide()
            self.save_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            lines = [line for line in out.splitlines() if line.strip()]
            self._set_error(lines[-1] if lines else t('check.fail'))
            return
        if self.shell.services['relay'].running:
            self.shell.restart_relay()
        self.spinner.stop()
        self.spinner.hide()
        self.shell.toast(t('set.restarted'), 'check', PAL['cyan'])
        self.accept()

    def _cancel(self) -> None:
        if self._busy:
            return
        self.reject()

    def closeEvent(self, event) -> None:
        self._alive = False
        super().closeEvent(event)