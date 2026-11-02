from __future__ import annotations

import html

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QHBoxLayout, QSizePolicy, QStackedWidget,
                             QTextEdit, QVBoxLayout)

from gui.i18n import t
from gui.theme import PAL, copy_text, open_tg_link
from gui.widgets import (Button, Chip, Dot, IconButton, Page, Segmented, card,
                         h1, h2, label, lead)

MAX_LINES = 2000
JOURNALS = ('proxy', 'relay', 'winws')
ROUTE = {'proxy': 'proxy', 'relay': 'relay', 'check': 'relay',
         'winws': 'winws', 'app': 'proxy'}
SOURCE_COLORS = {
    'proxy': PAL['cyan'],
    'relay': PAL['orange'],
    'winws': PAL['muted'],
    'check': PAL['orange_soft'],
    'app': PAL['faint'],
}
ERR_MARKERS = ('error', 'traceback', 'exception', 'critical', 'fatal')
WARN_MARKERS = ('warning', 'warn ', '[i]')


def _restore_scroll(bar, value: int) -> None:
    try:
        bar.setValue(value)
    except RuntimeError:
        pass


def level_color(line: str) -> str:
    low = line.lower()
    if any(marker in low for marker in ERR_MARKERS):
        return PAL['red']
    if any(marker in low for marker in WARN_MARKERS):
        return PAL['orange_soft']
    return PAL['muted']


class MainView(Page):
    def __init__(self, shell):
        super().__init__(shell)
        self.active = 'proxy'
        self.winws_state = 'stopped'
        self.journals = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 0, 22, 0)
        root.setSpacing(11)

        header = QHBoxLayout()
        header.setContentsMargins(0, 2, 0, 0)
        header.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(3)
        self.title_lbl = h1(t('main.title'))
        self.sub_lbl = label(t('main.subtitle'), 'Lead', wrap=True)
        title_col.addWidget(self.title_lbl)
        title_col.addWidget(self.sub_lbl)
        header.addLayout(title_col, 1)
        root.addLayout(header)

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(7)
        self.chips = {
            'proxy': Chip(t('pill.proxy')),
            'relay': Chip(t('pill.calls')),
            'winws': Chip(t('pill.winws')),
        }
        for key in ('proxy', 'relay', 'winws'):
            chips.addWidget(self.chips[key])
        chips.addStretch(1)
        root.addLayout(chips)

        hero = card(17, 11, 'Hero')
        hero_row = QHBoxLayout()
        hero_row.setContentsMargins(0, 0, 0, 0)
        hero_row.setSpacing(9)
        self.dot = Dot(10)
        self.status_lbl = label('', 'StatusBig')
        hero_row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        hero_row.addWidget(self.status_lbl, 1)
        hero.body.addLayout(hero_row)
        self.hint_lbl = lead('')
        hero.body.addWidget(self.hint_lbl)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)
        self.action_btn = Button(t('btn.start'), 'primary',
                                 icon_name='play', height=42)
        self.action_btn.clicked.connect(self._action)
        self.connect_btn = Button(t('btn.connect'), 'cyan',
                                  icon_name='telegram',
                                  icon_color=PAL['cyan'], height=42)
        self.connect_btn.setFixedWidth(154)
        self.connect_btn.clicked.connect(self._connect)
        actions.addWidget(self.action_btn, 1)
        actions.addWidget(self.connect_btn)
        hero.body.addLayout(actions)
        root.addWidget(hero)

        log_card = card(12, 9)
        log_card.setSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Expanding)
        root.addWidget(log_card, 1)

        log_head = QHBoxLayout()
        log_head.setContentsMargins(2, 0, 2, 0)
        log_head.setSpacing(8)
        self.log_lbl = h2(t('main.log'))
        log_head.addWidget(self.log_lbl)
        log_head.addStretch(1)
        self.tabs = Segmented([('proxy', t('main.tab_proxy')),
                               ('relay', t('main.tab_relay')),
                               ('winws', t('main.tab_winws'))])
        self.tabs.setFixedWidth(228)
        self.tabs.changed.connect(self._switch)
        log_head.addWidget(self.tabs)
        self.clear_btn = IconButton('trash', t('btn.clear'), 28, 15)
        self.clear_btn.clicked.connect(self.clear)
        log_head.addWidget(self.clear_btn)
        log_card.body.addLayout(log_head)

        self.stack = QStackedWidget()
        for name in JOURNALS:
            text = QTextEdit()
            text.setReadOnly(True)
            text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
            text.document().setMaximumBlockCount(MAX_LINES)
            text.setMinimumHeight(180)
            self.journals[name] = text
            self.stack.addWidget(text)
        log_card.body.addWidget(self.stack, 1)
        self._show_journal('proxy')

        root.addSpacing(2)
        self.refresh_action()

    def _show_journal(self, name: str) -> None:
        self.active = name
        target = self.journals[name]
        self.stack.setCurrentWidget(target)
        target.horizontalScrollBar().setValue(0)

    def _switch(self, name: str) -> None:
        if name in self.journals:
            self._show_journal(name)

    @staticmethod
    def _line_html(tag: str, line: str) -> str:
        tag = tag if tag in SOURCE_COLORS else 'app'
        safe = html.escape(line).replace(' ', '&nbsp;')
        color = level_color(line)
        return (
            f'<p style="margin:0;">'
            f'<span style="color:{SOURCE_COLORS[tag]}; font-weight:600;">'
            f'[{html.escape(tag)}]</span>'
            f'<span style="color:{color};">&nbsp;{safe}</span></p>')

    def append(self, tag: str, line: str) -> None:
        self.append_many(((tag, line),))

    def append_many(self, items) -> None:
        """Append a whole batch with one QTextEdit.append per journal.

        Each append at maximumBlockCount costs ~2.4 ms, so a 400-line drain
        tick used to freeze the UI for nearly a second.
        """
        grouped = {}
        for tag, line in items:
            if not line:
                continue
            tag = tag if tag in SOURCE_COLORS else 'app'
            grouped.setdefault(ROUTE.get(tag, 'proxy'), []).append((tag, line))
        for name, entries in grouped.items():
            target = self.journals[name]
            bar = target.verticalScrollBar()
            at_bottom = bar.value() >= bar.maximum() - 6
            hbar = target.horizontalScrollBar()
            h_val = hbar.value() if hbar else 0
            target.append(''.join(
                self._line_html(tag, line) for tag, line in entries))
            if at_bottom:
                bar.setValue(bar.maximum())
            if hbar:
                QTimer.singleShot(
                    0, lambda bar=hbar, value=h_val: _restore_scroll(bar, value))

    def clear(self) -> None:
        self.journals[self.active].clear()

    def set_winws_state(self, state: str) -> None:
        self.winws_state = state
        self.chips['winws'].set_state(state)

    def refresh_action(self) -> None:
        app = self.shell
        proxy = app.services['proxy']
        relay = app.services['relay']
        settings = app.settings
        states = (proxy.state, relay.state)
        starting = 'starting' in states
        errored = 'error' in states
        running = proxy.running or relay.running
        both = proxy.running and relay.running
        ready = settings.ready()
        addr = f'{settings.link_host()}:{settings.port}'

        if starting:
            status, dot_state = t('main.status_starting'), 'starting'
            hint, color = t('main.hint_starting'), PAL['orange']
        elif errored:
            status, dot_state = t('main.status_error'), 'error'
            hint, color = t('main.hint_error'), PAL['red']
        elif both:
            status, dot_state = t('main.status_running'), 'running'
            hint, color = t('main.hint_running', addr=addr), PAL['cyan']
        elif running:
            status, dot_state = t('main.status_partial'), 'partial'
            hint, color = t('main.hint_partial'), PAL['orange']
        elif not ready:
            status, dot_state = t('main.status_setup'), 'stopped'
            hint, color = t('main.hint_setup'), PAL['orange']
        else:
            status, dot_state = t('main.status_stopped'), 'stopped'
            hint, color = t('main.hint_stopped'), PAL['muted']

        self.dot.set_state(dot_state)
        self.status_lbl.setText(status)
        self.status_lbl.setStyleSheet(f'color: {color};')
        self.hint_lbl.setText(hint)

        self.chips['proxy'].set_state(proxy.state)
        self.chips['relay'].set_state(relay.state)
        self.chips['winws'].set_state(self.winws_state)

        active = running or starting
        self.action_btn.set_kind('danger' if active else 'primary')
        self.action_btn.set_icon_name('stop' if active else 'play',
                                      '#2a0b10' if active else PAL['text'])
        self.action_btn.setText(t('btn.stop') if active else t('btn.start'))
        self.action_btn.setEnabled(ready or active)
        self.connect_btn.setEnabled(proxy.running)

    def _action(self) -> None:
        app = self.shell
        running = (app.services['proxy'].running
                   or app.services['relay'].running
                   or app.services['proxy'].state == 'starting'
                   or app.services['relay'].state == 'starting')
        if running:
            app.stop_services()
        else:
            if not app.settings.ready():
                app.toast(t('main.hint_setup'), 'shield', PAL['orange'])
                return
            app.start_services()
        self.refresh_action()

    def _connect(self) -> None:
        link = self.settings.proxy_link()
        if not open_tg_link(link):
            copy_text(link)
            self.shell.toast(t('btn.copied'), 'copy')

    def retranslate(self) -> None:
        self.title_lbl.setText(t('main.title'))
        self.sub_lbl.setText(t('main.subtitle'))
        self.log_lbl.setText(t('main.log'))
        self.tabs.set_text('proxy', t('main.tab_proxy'))
        self.tabs.set_text('relay', t('main.tab_relay'))
        self.tabs.set_text('winws', t('main.tab_winws'))
        for key in ('proxy', 'relay', 'winws'):
            text = {'proxy': t('pill.proxy'), 'relay': t('pill.calls'),
                    'winws': t('pill.winws')}[key]
            self.chips[key].set_text(text)
        self.connect_btn.setText(t('btn.connect'))
        self.refresh_action()