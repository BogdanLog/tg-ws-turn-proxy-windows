from __future__ import annotations

import html
import os
import threading

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLineEdit, QTextEdit,
                             QVBoxLayout, QWidget, QSizePolicy)

from gui import services
from gui import state
from gui.i18n import t
from gui.theme import PAL, open_tg_link
from gui.widgets import (Button, ChoiceCard, ChoiceGroup, Field, IconButton,
                         NeonProgress, Page, ScrollBody, Spinner, card,
                         divider, h1, h2, label, lead)


def _restore_scroll(bar, value: int) -> None:
    try:
        bar.setValue(value)
    except RuntimeError:
        pass


class WizardPage(Page):
    TITLE = ''
    LEAD = ''
    STEP = 0
    TOTAL = 4

    def __init__(self, shell):
        super().__init__(shell)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 2, 22, 0)
        root.setSpacing(0)

        self.head = QVBoxLayout()
        self.head.setContentsMargins(0, 0, 0, 0)
        self.head.setSpacing(7)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        self.title_lbl = h1(t(self.TITLE))
        self.title_lbl.setWordWrap(True)
        title_row.addWidget(self.title_lbl, 1)
        self.step_lbl = label('', 'Faint')
        title_row.addWidget(self.step_lbl, 0, Qt.AlignmentFlag.AlignTop)
        self.head.addLayout(title_row)
        self.lead_lbl = lead(t(self.LEAD))
        self.head.addWidget(self.lead_lbl)
        root.addLayout(self.head)
        root.addSpacing(13)

        self.scroll = ScrollBody()
        root.addWidget(self.scroll, 1)

        self.err_lbl = label('', 'Error', wrap=True)
        self.err_lbl.hide()
        root.addWidget(self.err_lbl)
        root.addSpacing(8)
        root.addWidget(divider())

        footer = QWidget()
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(0, 10, 0, 14)
        foot.setSpacing(10)
        self.back_btn = Button(t('btn.back'), 'ghost',
                               icon_name='chevron_left', height=38)
        self.back_btn.hide()
        self.next_btn = Button(t('btn.next'), 'primary', height=38)
        self.next_btn.setFixedWidth(126)
        foot.addWidget(self.back_btn)
        foot.addStretch(1)
        foot.addWidget(self.next_btn)
        root.addWidget(footer)

        if self.STEP:
            self.step_lbl.setText(t('step.of', n=self.STEP, m=self.TOTAL))
        self.build()

    def build(self) -> None:
        pass

    def set_back(self, callback) -> None:
        self.back_btn.clicked.connect(callback)
        self.back_btn.show()

    def set_next(self, callback) -> None:
        self.next_btn.clicked.connect(callback)

    def set_next_enabled(self, enabled: bool) -> None:
        self.next_btn.setEnabled(bool(enabled))

    def show_error(self, text: str) -> None:
        self.err_lbl.setText(text or '')
        self.err_lbl.setVisible(bool(text))


class LinkRow(QWidget):

    def __init__(self, shell, caption: str = ''):
        super().__init__()
        self.shell = shell
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if caption:
            layout.addWidget(label(caption, 'Faint'))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setObjectName('Mono')
        self.edit.setFixedHeight(36)
        self.copy_btn = IconButton('copy', t('btn.copy'), 36, 16,
                                   PAL['cyan'])
        self.copy_btn.clicked.connect(self._copy)
        row.addWidget(self.edit, 1)
        row.addWidget(self.copy_btn)
        layout.addLayout(row)

    def set_link(self, text: str) -> None:
        self.edit.setText(text)
        self.edit.setCursorPosition(len(text))

    def link(self) -> str:
        return self.edit.text()

    def _copy(self) -> None:
        copy_text(self.edit.text())
        self.shell.toast(t('btn.copied'), 'copy')


class BootPage(WizardPage):
    TITLE = 'boot.title'
    LEAD = 'boot.desc'

    def build(self) -> None:
        self._finished = False
        self._seen_running = 0
        self._bat_rc = None
        self._probe_busy = False

        status = card(16)
        self.scroll.box.addWidget(status)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(11)
        self.spinner = Spinner(18)
        self.status_lbl = label(t('boot.status_starting'), 'H2')
        top.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.status_lbl, 1)
        status.body.addLayout(top)
        self.hint_lbl = label('', 'Faint', wrap=True)
        self.hint_lbl.hide()
        status.body.addWidget(self.hint_lbl)

        output = card(14, 8)
        self.scroll.box.addWidget(output)
        output.body.addWidget(label(t('boot.output'), 'Caption'))
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.out.document().setMaximumBlockCount(500)
        self.out.setFixedHeight(150)
        output.body.addWidget(self.out)
        self.scroll.box.addStretch(1)

        self.set_next(lambda: self.shell.show_page(WelcomePage))
        self.set_next_enabled(False)

    def on_show(self) -> None:
        self._start()

    def on_hide(self) -> None:
        super().on_hide()
        self.spinner.stop()
        if hasattr(self, '_timer'):
            self._timer.stop()

    def _start(self) -> None:
        if self._finished:
            return
        self.spinner.start()
        self.set_next_enabled(False)
        self.status_lbl.setStyleSheet(f'color: {PAL["text"]};')
        self._append(f'$ {state.ZAPRET_BAT}')
        if not os.path.exists(state.ZAPRET_BAT):
            self._finish(t('boot.not_found'), 'err')
            return
        self._probe(self._launch)

    def _launch(self, was_running: bool) -> None:
        if not self._alive or self._finished:
            return
        if was_running:
            self._finish(t('boot.status_already'), 'ok')
            return
        cmd, cwd = services.winws_cmd()
        services.run_bat(cmd, cwd, on_line=self._line, on_done=self._done)
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(lambda: self._probe(self._evaluate))
        self._timer.start()

    def _probe(self, callback) -> None:
        if self._probe_busy:
            return
        self._probe_busy = True

        def worker():
            running = services.winws_running()

            def deliver():
                self._probe_busy = False
                if self._alive:
                    callback(running)

            self.shell.em.call(deliver)
        threading.Thread(target=worker, daemon=True,
                         name='boot-winws-probe').start()

    def _evaluate(self, running: bool) -> None:
        if self._finished:
            return
        self._seen_running = self._seen_running + 1 if running else 0
        if self._seen_running >= 2 or (self._bat_rc is not None and running):
            self._finish(t('boot.status_ok'), 'ok')
        elif self._bat_rc is not None and not running:
            self._finish(t('boot.status_error'), 'err')

    def _line(self, text: str) -> None:
        self.shell.em.call(lambda: self._append(text))

    def _append(self, text: str) -> None:
        if not self._alive:
            return
        low = text.lower()
        color = PAL['muted']
        if low.startswith('[error]') or 'failed' in low or 'не найден' in text:
            color = PAL['red']
        elif low.startswith('[i]') or 'ok' in low:
            color = PAL['cyan']
        safe = html.escape(text).replace(' ', '&nbsp;')
        
        hbar = self.out.horizontalScrollBar()
        h_val = hbar.value() if hbar else 0
        
        self.out.append(f'<span style="color:{color};">{safe}</span>')
        
        bar = self.out.verticalScrollBar()
        bar.setValue(bar.maximum())
        
        if hbar:
            QTimer.singleShot(0, lambda: _restore_scroll(hbar, h_val))

    def _done(self, rc: int) -> None:
        def deliver():
            if not self._alive:
                return
            self._bat_rc = rc
            self._probe(self._after_bat)
        self.shell.em.call(deliver)

    def _after_bat(self, running: bool) -> None:
        if not self._alive:
            return
        if self._finished:
            if not running:
                self._finish(t('boot.status_stopped'), 'warn', ok=True)
            return
        self._evaluate(running)

    def _finish(self, text: str, kind: str, ok: bool = False) -> None:
        if not self._alive:
            return
        self._finished = True
        self.spinner.stop()
        if hasattr(self, '_timer'):
            self._timer.stop()
        color = {'ok': PAL['cyan'], 'warn': PAL['orange']}.get(kind, PAL['red'])
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f'color: {color};')
        if not ok:
            self.hint_lbl.setText(t('boot.hint'))
            self.hint_lbl.show()
        self.set_next_enabled(True)
        self.shell.refresh_winws_chip()


class WelcomePage(WizardPage):
    TITLE = 'welcome.title'
    LEAD = 'welcome.lead'

    def build(self) -> None:
        box = card(18, 16)
        self.scroll.box.addWidget(box)
        features = (
            ('welcome.f1_title', 'welcome.f1_desc', PAL['cyan']),
            ('welcome.f2_title', 'welcome.f2_desc', PAL['orange']),
            ('welcome.f3_title', 'welcome.f3_desc', PAL['cyan_soft']),
        )
        for index, (title_key, desc_key, color) in enumerate(features):
            if index:
                box.body.addWidget(divider())
            item = QHBoxLayout()
            item.setContentsMargins(0, 2, 0, 2)
            item.setSpacing(12)
            bar = QWidget()
            bar.setFixedSize(3, 34)
            bar.setStyleSheet(f'background: {color}; border-radius: 1px;')
            item.addWidget(bar, 0, Qt.AlignmentFlag.AlignTop)
            text = QVBoxLayout()
            text.setContentsMargins(0, 0, 0, 0)
            text.setSpacing(4)
            title_lbl = h2(t(title_key))
            title_lbl.setWordWrap(True)
            title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.addWidget(title_lbl)
            text.addWidget(lead(t(desc_key)))
            item.addLayout(text, 1)
            box.body.addLayout(item)

        note = QFrame()
        note.setObjectName('NoteBox')
        note_layout = QHBoxLayout(note)
        note_layout.setContentsMargins(14, 11, 14, 11)
        note_layout.addWidget(label(t('welcome.note'), 'Lead', wrap=True))
        self.scroll.box.addWidget(note)
        self.scroll.box.addStretch(1)

        self.set_next(lambda: self.shell.show_page(SourcePage))


class SourcePage(WizardPage):
    TITLE = 'source.title'
    LEAD = 'source.lead'
    STEP = 1

    def __init__(self, shell):
        self._touched = False
        super().__init__(shell)

    def build(self) -> None:
        box = card(14, 10)
        self.scroll.box.addWidget(box)
        self.mode = ChoiceGroup()
        self.mode.changed.connect(lambda _v: self._validate())

        self.workers = ChoiceCard(t('source.workers_title'),
                                  t('source.workers_desc'),
                                  t('source.workers_link'), state.DOCS_WORKER)
        box.body.addWidget(self.workers)
        self.mode.add(self.workers, state.SOURCE_WORKERS)
        self.worker_fields = []
        for index, value in enumerate(self._worker_values()):
            field = Field(t(f'field.worker{index + 1}'), value)
            field.edit.textChanged.connect(self._touch)
            self.worker_fields.append(field)
            self.workers.body_layout.addWidget(field)

        self.domain = ChoiceCard(t('source.domain_title'),
                                 t('source.domain_desc'),
                                 t('source.domain_link'), state.DOCS_CFPROXY)
        box.body.addWidget(self.domain)
        self.mode.add(self.domain, state.SOURCE_DOMAIN)
        self.domain_field = Field(t('field.domain'), self.settings.custom_domain)
        self.domain_field.edit.textChanged.connect(self._touch)
        self.domain.body_layout.addWidget(self.domain_field)

        self.public = ChoiceCard(t('source.public_title'),
                                 t('source.public_desc'),
                                 t('source.public_link'),
                                 state.CFPROXY_DOMAINS_URL)
        box.body.addWidget(self.public)
        self.mode.add(self.public, state.SOURCE_PUBLIC)
        self.scroll.box.addStretch(1)

        self.mode.set_value(self.settings.source_mode, notify=False,
                            animate=False)

        self.set_back(lambda: self.shell.show_page(WelcomePage))
        self.set_next(self._next)
        self._validate()

    def _worker_values(self) -> list:
        values = list(self.settings.worker_domains[:3])
        while len(values) < 3:
            values.append('')
        return values

    def _touch(self) -> None:
        self._touched = True
        self._validate()

    def _validate(self) -> bool:
        mode = self.mode.value()
        ok, text = True, ''
        if mode == state.SOURCE_WORKERS:
            filled = [f.text() for f in self.worker_fields if f.text()]
            if not filled:
                ok, text = False, t('source.workers_hint')
            else:
                for value in filled:
                    if not state.is_valid_domain(value):
                        ok, text = False, t('err.domain')
                        break
        elif mode == state.SOURCE_DOMAIN:
            ok = state.is_valid_domain(self.domain_field.text())
            text = '' if ok else t('err.domain')
        self.show_error(text if self._touched else '')
        self.set_next_enabled(ok)
        return ok

    def _next(self) -> None:
        if not self._validate():
            return
        settings = self.settings
        settings.source_mode = self.mode.value()
        settings.worker_domains = [f.text() for f in self.worker_fields]
        settings.custom_domain = self.domain_field.text()
        self.shell.save_settings()
        self.shell.show_page(MtprotoPage)


class MtprotoPage(WizardPage):
    TITLE = 'mtproto.title'
    LEAD = 'mtproto.lead'
    STEP = 2

    def build(self) -> None:
        settings = self.settings
        box = card(18, 12)
        self.scroll.box.addWidget(box)

        conn = QHBoxLayout()
        conn.setContentsMargins(0, 0, 0, 0)
        conn.setSpacing(10)
        self.host_field = Field(t('field.host'), settings.host)
        self.host_field.setFixedWidth(150)
        self.port_field = Field(t('field.port'), str(settings.port))
        self.port_field.setFixedWidth(92)
        conn.addWidget(self.host_field)
        conn.addWidget(self.port_field)
        conn.addStretch(1)
        box.body.addLayout(conn)

        secret_row = QHBoxLayout()
        secret_row.setContentsMargins(0, 0, 0, 0)
        secret_row.setSpacing(8)
        self.secret_field = Field(t('field.secret'),
                                  'dd' + state.normalize_secret(settings.secret),
                                  mono=True)
        secret_row.addWidget(self.secret_field, 1)
        self.refresh_btn = Button(t('btn.refresh'), 'ghost',
                                  icon_name='refresh', icon_color=PAL['cyan'],
                                  height=36)
        self.refresh_btn.setFixedWidth(124)
        secret_row.addWidget(self.refresh_btn, 0,
                             Qt.AlignmentFlag.AlignBottom)
        box.body.addSpacing(2)
        box.body.addLayout(secret_row)
        box.body.addWidget(label(t('mtproto.secret_hint'), 'Faint', wrap=True))

        for widget in (self.host_field.edit, self.port_field.edit,
                       self.secret_field.edit):
            widget.textChanged.connect(self._validate)
        self.refresh_btn.clicked.connect(self._refresh_secret)

        link_box = card(16, 8)
        self.scroll.box.addWidget(link_box)
        self.link_row = LinkRow(self.shell, t('mtproto.link_preview'))
        link_box.body.addWidget(self.link_row)
        self.scroll.box.addStretch(1)

        self.set_back(lambda: self.shell.show_page(SourcePage))
        self.set_next(self._next)
        self._validate()

    def _link(self) -> str:
        host = self.host_field.text() or '127.0.0.1'
        if host in ('0.0.0.0', '::'):
            host = '127.0.0.1'
        secret = state.normalize_secret(self.secret_field.raw())
        port = self.port_field.text() or '1443'
        return f'tg://proxy?server={host}&port={port}&secret=dd{secret}'

    def _refresh_secret(self) -> None:
        self.secret_field.set_text('dd' + state.gen_secret())
        self._validate()

    def _validate(self) -> bool:
        ok, text = True, ''
        if not state.is_valid_ip(self.host_field.text()):
            ok, text = False, t('mtproto.host_bad')
        elif not self.port_field.text().isdigit() or not (
                1 <= int(self.port_field.text()) <= 65535):
            ok, text = False, t('mtproto.port_bad')
        elif not state.is_hex_secret(self.secret_field.raw()):
            ok, text = False, t('mtproto.secret_bad')
        self.show_error(text)
        self.link_row.set_link(self._link())
        self.set_next_enabled(ok)
        return ok

    def _next(self) -> None:
        if not self._validate():
            return
        settings = self.settings
        settings.host = self.host_field.text()
        settings.port = int(self.port_field.text())
        settings.secret = state.normalize_secret(self.secret_field.raw())
        self.shell.save_settings()
        self.shell.show_page(ProxyRunPage)


class ProxyRunPage(WizardPage):
    TITLE = 'run.title'
    STEP = 3

    def build(self) -> None:
        self._requested = False
        self._ticks = 0
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._tick)

        hero = card(18, 11, 'Hero')
        self.scroll.box.addWidget(hero)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(11)
        self.spinner = Spinner(18)
        self.status_lbl = label(t('run.starting'), 'H2')
        self.state_lbl = label('', 'Faint')
        top.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.status_lbl, 1)
        top.addWidget(self.state_lbl)
        hero.body.addLayout(top)

        self.details = QWidget()
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(0, 2, 0, 0)
        details_layout.setSpacing(10)
        details_layout.addWidget(lead(t('run.connect_hint')))
        self.link_row = LinkRow(self.shell)
        details_layout.addWidget(self.link_row)
        self.connect_btn = Button(t('btn.connect'), 'cyan',
                                  icon_name='telegram',
                                  icon_color=PAL['cyan'], height=40)
        self.connect_btn.clicked.connect(self._connect)
        details_layout.addWidget(self.connect_btn,
                                 0, Qt.AlignmentFlag.AlignLeft)
        self.details.hide()
        hero.body.addWidget(self.details)

        self.fail_box = QWidget()
        fail_layout = QVBoxLayout(self.fail_box)
        fail_layout.setContentsMargins(0, 0, 0, 0)
        fail_layout.setSpacing(8)
        self.fail_lbl = label(t('run.err_hint'), 'Error', wrap=True)
        self.retry_btn = Button(t('btn.retry'), 'ghost',
                                icon_name='refresh', icon_color=PAL['cyan'],
                                height=36)
        self.retry_btn.clicked.connect(self._start_proxy)
        fail_layout.addWidget(self.fail_lbl)
        fail_layout.addWidget(self.retry_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.fail_box.hide()
        self.scroll.box.addWidget(self.fail_box)
        self.scroll.box.addStretch(1)

        self.set_back(self._back)
        self.set_next(lambda: self.shell.show_page(TurnPage))
        self.set_next_enabled(False)

    def on_show(self) -> None:
        self.link_row.set_link(self.settings.proxy_link())
        self._start_proxy()

    def on_hide(self) -> None:
        super().on_hide()
        self._poll.stop()
        self.spinner.stop()

    def _start_proxy(self) -> None:
        if not self._alive:
            return
        self.fail_box.hide()
        self.details.hide()
        self.set_next_enabled(False)
        self.spinner.start()
        self.status_lbl.setText(t('run.starting'))
        self.status_lbl.setStyleSheet(f'color: {PAL["text"]};')
        self.state_lbl.setText(t('run.waiting'))
        if not self.shell.start_proxy():
            self._show_fail()
            return
        self._requested = True
        self._ticks = 0
        self._poll.start()
        self._tick()

    def _tick(self) -> None:
        if not self._alive:
            self._poll.stop()
            return
        self._ticks += 1
        proxy = self.shell.services['proxy']
        if proxy.state == 'running':
            self._poll.stop()
            self.spinner.stop()
            self.status_lbl.setText(t('run.ok'))
            self.status_lbl.setStyleSheet(f'color: {PAL["cyan"]};')
            self.state_lbl.setText(str(self.settings.port))
            self.details.show()
            self.set_next_enabled(True)
            return
        if (proxy.state in ('error', 'stopped') and self._requested
                and not proxy.running) or self._ticks > 80:
            self._show_fail()

    def _show_fail(self) -> None:
        self._poll.stop()
        self.spinner.stop()
        self.status_lbl.setText(t('run.fail'))
        self.status_lbl.setStyleSheet(f'color: {PAL["red"]};')
        self.state_lbl.setText('')
        self.fail_box.show()

    def _connect(self) -> None:
        link = self.settings.proxy_link()
        if not open_tg_link(link):
            copy_text(link)
            self.shell.toast(t('btn.copied'), 'copy')

    def _back(self) -> None:
        self.shell.stop_proxy()
        self.shell.show_page(MtprotoPage)


class TurnPage(WizardPage):
    TITLE = 'turn.title'
    LEAD = 'turn.lead'
    STEP = 4

    def __init__(self, shell):
        self._touched = False
        super().__init__(shell)

    def build(self) -> None:
        settings = self.settings
        box = card(14, 10)
        self.scroll.box.addWidget(box)
        self.provider = ChoiceGroup()
        self.provider.changed.connect(lambda _v: self._validate())

        hf = ChoiceCard(t('turn.hf_title'), t('turn.hf_desc'),
                        t('turn.hf_link'), state.HF_TOKENS_URL)
        box.body.addWidget(hf)
        self.provider.add(hf, state.TURN_HF)
        self.hf_field = Field(t('field.hf_token'), settings.hf_token, mono=True)
        hf.body_layout.addWidget(self.hf_field)

        cf = ChoiceCard(t('turn.cf_title'), t('turn.cf_desc'),
                        t('turn.cf_link'), state.CF_TURN_DOCS)
        box.body.addWidget(cf)
        self.provider.add(cf, state.TURN_CF)
        self.key_field = Field(t('field.cf_key'), settings.cf_key_id, mono=True)
        self.token_field = Field(t('field.cf_token'), settings.cf_api_token,
                                 password=True, mono=True)
        cf.body_layout.addWidget(self.key_field)
        cf.body_layout.addWidget(self.token_field)

        custom = ChoiceCard(t('turn.custom_title'), t('turn.custom_desc'))
        box.body.addWidget(custom)
        self.provider.add(custom, state.TURN_CUSTOM)
        self.user_field = Field(t('field.turn_user'), settings.turn_username,
                                mono=True)
        self.cred_field = Field(t('field.turn_cred'),
                                settings.turn_credential, password=True,
                                mono=True)
        self.url_field = Field(t('field.turn_url'), settings.turn_url,
                               mono=True, placeholder='turns://host:443')
        custom.body_layout.addWidget(self.user_field)
        custom.body_layout.addWidget(self.cred_field)
        custom.body_layout.addWidget(self.url_field)

        public = ChoiceCard(t('turn.public_title'), t('turn.public_desc'))
        box.body.addWidget(public)
        self.provider.add(public, state.TURN_PUBLIC)
        self.public_field = Field(t('field.hf_token'), state.PUBLIC_HF_TOKEN,
                                  mono=True, read_only=True)
        public.body_layout.addWidget(self.public_field)
        self.scroll.box.addStretch(1)

        for field in (self.hf_field, self.key_field, self.token_field,
                      self.user_field, self.cred_field, self.url_field):
            field.edit.textChanged.connect(self._touch)
        self.provider.set_value(settings.turn_provider, notify=False,
                                animate=False)

        self.set_back(lambda: self.shell.show_page(ProxyRunPage))
        self.set_next(self._next)
        self._validate()

    def _touch(self) -> None:
        self._touched = True
        self._validate()

    def _validate(self) -> bool:
        provider = self.provider.value()
        ok, text = True, ''
        if provider == state.TURN_HF:
            ok = bool(self.hf_field.text())
            text = '' if ok else t('err.token')
        elif provider == state.TURN_CF:
            ok = bool(self.key_field.text() and self.token_field.text())
            text = '' if ok else t('err.cf_key')
        elif provider == state.TURN_CUSTOM:
            if not (self.user_field.text() and self.cred_field.text()):
                ok, text = False, t('err.creds')
            elif not state.is_valid_turn_url(self.url_field.text()):
                ok, text = False, t('err.turn_url')
        self.show_error(text if self._touched else '')
        self.set_next_enabled(ok)
        return ok

    def _next(self) -> None:
        if not self._validate():
            return
        settings = self.settings
        settings.turn_provider = self.provider.value()
        settings.hf_token = self.hf_field.text()
        settings.cf_key_id = self.key_field.text()
        settings.cf_api_token = self.token_field.raw().strip()
        settings.turn_username = self.user_field.text()
        settings.turn_credential = self.cred_field.raw().strip()
        settings.turn_url = self.url_field.text()
        self.shell.save_settings()
        self.shell.show_page(CheckPage)


class CheckPage(WizardPage):
    TITLE = 'check.title'
    LEAD = 'check.lead'

    def build(self) -> None:
        self._busy = False
        box = card(18, 12, 'Hero')
        self.scroll.box.addWidget(box)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(11)
        self.spinner = Spinner(18)
        self.status_lbl = label(t('check.working'), 'H2')
        top.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.status_lbl, 1)
        box.body.addLayout(top)

        self.step_lbl = label(t('check.step_mint'), 'Lead', wrap=True)
        box.body.addWidget(self.step_lbl)
        self.progress = NeonProgress(6)
        box.body.addWidget(self.progress)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFixedHeight(118)
        self.detail.hide()
        box.body.addWidget(self.detail)

        self.fail_lbl = label(t('check.err_hint'), 'Error', wrap=True)
        self.fail_lbl.hide()
        self.scroll.box.addWidget(self.fail_lbl)
        self.retry_btn = Button(t('btn.retry'), 'ghost',
                                icon_name='refresh', icon_color=PAL['cyan'],
                                height=36)
        self.retry_btn.clicked.connect(self._run)
        self.retry_btn.hide()
        self.scroll.box.addWidget(self.retry_btn, 0,
                                  Qt.AlignmentFlag.AlignLeft)
        self.scroll.box.addStretch(1)

        self.set_back(lambda: self.shell.show_page(TurnPage))
        self.next_btn.hide()
        self.spinner.start()

    def on_show(self) -> None:
        self._run()

    def on_hide(self) -> None:
        super().on_hide()
        self._busy = False
        self.spinner.stop()
        self.progress.stop(1.0)
        try:
            self.shell.probe.cancel()
        except Exception:
            pass

    def _run(self) -> None:
        if not self._alive or self._busy:
            return
        self._busy = True
        self.retry_btn.setEnabled(False)
        self.fail_lbl.hide()
        self.retry_btn.hide()
        self.detail.hide()
        self.spinner.start()
        self.status_lbl.setText(t('check.working'))
        self.status_lbl.setStyleSheet(f'color: {PAL["text"]};')
        self.step_lbl.setText(t('check.step_mint'))
        self.progress.set_value(0.25)
        self.progress.start()
        settings = self.settings

        def worker():
            try:
                cmd, cwd = services.relay_cmd(state.mint_args(settings))
                rc, out = services.run_capture(cmd, cwd, timeout=90)
            except Exception as exc:
                rc, out = 1, f'failed to start mint: {exc}'
            self.shell.em.call(lambda: self._minted(rc, out))

        threading.Thread(target=worker, daemon=True, name='mint').start()

    def _minted(self, rc: int, out: str) -> None:
        if not self._alive:
            return
        if rc != 0:
            self._fail(out)
            return
        state.sanitize_relay_config(self.settings)
        self.step_lbl.setText(t('check.step_probe'))
        self.progress.set_value(0.62)
        if out.strip():
            self._show_detail(out)
        cmd, cwd = services.relay_cmd(['--dry-run']
                                      + state.relay_args(self.settings))
        self.shell.probe = services.Probe(self.shell.em)
        self.shell.probe.start(cmd, cwd, self._probed, timeout=45.0)

    def _probed(self, ok: bool, detail: str) -> None:
        self.shell.em.call(lambda: self._probed_ui(ok, detail))

    def _probed_ui(self, ok: bool, detail: str) -> None:
        if not self._alive:
            return
        if not ok:
            self._fail(detail)
            return
        self.step_lbl.setText(t('check.step_relay'))
        self.progress.stop(1.0)
        self.shell.start_relay()
        self.spinner.stop()
        self.status_lbl.setText(t('check.success'))
        self.status_lbl.setStyleSheet(f'color: {PAL["cyan"]};')
        self.step_lbl.setText(t('check.success_hint'))
        self.settings.setup_done = True
        self.shell.save_settings()
        QTimer.singleShot(900, self._show_main)

    def _show_main(self) -> None:
        try:
            if self._alive:
                self.shell.show_main()
        except RuntimeError:
            pass

    def _show_detail(self, text: str) -> None:
        self.detail.setPlainText(text.rstrip())
        self.detail.show()

    def _fail(self, detail: str) -> None:
        if not self._alive:
            return
        self._busy = False
        self.retry_btn.setEnabled(True)
        self.spinner.stop()
        self.progress.set_value(0.62)
        self.progress.stop(0.62)
        self.status_lbl.setText(t('check.fail'))
        self.status_lbl.setStyleSheet(f'color: {PAL["red"]};')
        self.step_lbl.setText(t('check.err_hint'))
        self.fail_lbl.show()
        self.retry_btn.show()
        if detail:
            self._show_detail(detail)