from __future__ import annotations

from PyQt6.QtCore import (QAbstractAnimation, QEasingCurve, QObject, QPoint,
                          QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                          QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import (QColor, QIcon, QLinearGradient,
                          QPainter, QPen)
from PyQt6.QtWidgets import (QButtonGroup, QFrame,
                             QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                             QLineEdit, QMainWindow, QMenu, QPushButton,
                             QScrollArea, QSizePolicy, QStackedWidget,
                             QVBoxLayout, QWidget, QSystemTrayIcon)

try:
    from PyQt6.QtWidgets import QApplication as _QApplication
except Exception:
    _QApplication = None

def qApp():
    if _QApplication is not None:
        return _QApplication.instance()
    return None

from gui import icons
from gui.i18n import t
from gui.theme import PAL, open_url, qfont


def card(padding: int = 16, spacing: int = 10,
         object_name: str = 'Card') -> QFrame:
    frame = QFrame()
    frame.setObjectName(object_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(padding, padding, padding, padding)
    layout.setSpacing(spacing)
    frame.body = layout
    return frame


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName('Divider')
    line.setFixedHeight(1)
    return line


def label(text: str = '', style: str = 'Muted', wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(style)
    if wrap:
        widget.setWordWrap(True)
    return widget


def h1(text: str) -> QLabel:
    return label(text, 'H1')


def h2(text: str) -> QLabel:
    return label(text, 'H2')


def lead(text: str, wrap: bool = True) -> QLabel:
    return label(text, 'Lead', wrap=wrap)


def row(*widgets, spacing: int = 10, margins=(0, 0, 0, 0)) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return holder


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class Dot(QWidget):

    COLORS = {
        'running': PAL['cyan'],
        'starting': PAL['orange'],
        'partial': PAL['orange'],
        'error': PAL['red'],
        'stopped': PAL['faint'],
    }

    def __init__(self, size: int = 9, parent=None):
        super().__init__(parent)
        self._size = size
        self._state = 'stopped'
        self._pulse = 0.0
        self.setFixedSize(size + 8, size + 8)
        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setDuration(1300)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse_anim.valueChanged.connect(self._on_pulse)

    def _on_pulse(self, value) -> None:
        self._pulse = float(value)
        self.update()

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        if state == 'starting':
            if self._pulse_anim.state() != QAbstractAnimation.State.Running:
                self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.COLORS.get(self._state, PAL['faint']))
        center = QRectF(self.rect()).center()
        radius = self._size / 2
        glow = QColor(color)
        glow.setAlpha(int(38 + 52 * self._pulse))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, radius + 3 + 2 * self._pulse,
                            radius + 3 + 2 * self._pulse)
        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)
        painter.end()


class Chip(QFrame):

    def __init__(self, text: str, state: str = 'stopped', parent=None):
        super().__init__(parent)
        self.setObjectName('Chip')
        self.setFixedHeight(27)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 2, 12, 2)
        layout.setSpacing(6)
        self.dot = Dot(8)
        self.label = QLabel(text)
        self.label.setFont(qfont(11))
        layout.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_state(state)

    def set_text(self, text: str) -> None:
        self.label.setText(text)

    def set_state(self, state: str) -> None:
        self.dot.set_state(state)
        self.setProperty('state', state)
        repolish(self)
        active = state in ('running', 'starting', 'error')
        color = PAL['text'] if active else PAL['muted']
        self.label.setStyleSheet(f'color: {color}; background: transparent;')


class Button(QPushButton):
    KINDS = {
        'primary': 'Primary',
        'ghost': 'Ghost',
        'cyan': 'Cyan',
        'danger': 'Danger',
        'link': 'Link',
    }

    def __init__(self, text: str = '', kind: str = 'primary',
                 icon_name: str = '', icon_color: str = '',
                 height: int = 38, parent=None):
        super().__init__(text, parent)
        self._kind = kind
        self.setObjectName(self.KINDS.get(kind, 'Primary'))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(height if kind != 'link' else 20)
        self._icon_name = icon_name
        self._icon_color = icon_color
        if icon_name:
            self.setIcon(icons.icon(icon_name,
                                    icon_color or PAL['text'], 16))
            self.setIconSize(QSize(16, 16))
        self.setFont(qfont(12, bold=True))

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.setObjectName(self.KINDS.get(kind, 'Primary'))
        repolish(self)

    def set_text(self, text: str) -> None:
        self.setText(text)

    def set_icon_name(self, name: str, color: str = '') -> None:
        self._icon_name = name
        self._icon_color = color
        if name:
            self.setIcon(icons.icon(name, color or PAL['text'], 16))


class IconButton(QPushButton):
    def __init__(self, icon_name: str, tooltip: str = '', size: int = 30,
                 icon_size: int = 17, color: str = '', role: str = '',
                 parent=None):
        super().__init__(parent)
        self.setObjectName('Icon')
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icons.icon(icon_name, color or PAL['muted'], icon_size))
        self.setIconSize(QSize(icon_size, icon_size))
        if tooltip:
            self.setToolTip(tooltip)
        if role:
            self.setProperty('role', role)


class Segmented(QFrame):

    changed = pyqtSignal(str)

    def __init__(self, items, height: int = 32, parent=None):
        super().__init__(parent)
        self.setObjectName('SegBg')
        self.setFixedHeight(height)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for index, (key, text) in enumerate(items):
            button = QPushButton(text)
            button.setObjectName('SegBtn')
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(qfont(11))
            button.setFixedHeight(height - 6)
            self.group.addButton(button, index)
            self.buttons[key] = button
            button.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))
            layout.addWidget(button, 1)
        if items:
            self.buttons[items[0][0]].setChecked(True)
        self._current = items[0][0] if items else ''

    def set_current(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._current = key

    def current(self) -> str:
        return self._current

    def set_text(self, key: str, text: str) -> None:
        if key in self.buttons:
            self.buttons[key].setText(text)

    def set_enabled(self, key: str, enabled: bool) -> None:
        if key in self.buttons:
            self.buttons[key].setEnabled(enabled)


class Field(QWidget):
    def __init__(self, caption: str, value: str = '', password: bool = False,
                 mono: bool = False, read_only: bool = False,
                 placeholder: str = '', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.caption = label(caption, 'Faint')
        self.edit = QLineEdit(value)
        self.edit.setFixedHeight(36)
        if mono:
            self.edit.setObjectName('Mono')
        if password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        if read_only:
            self.edit.setReadOnly(True)
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        layout.addWidget(self.caption)
        layout.addWidget(self.edit)

    def text(self) -> str:
        return self.edit.text().strip()

    def raw(self) -> str:
        return self.edit.text()

    def set_text(self, value: str) -> None:
        self.edit.setText(value)

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)


class RadioMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self._active = False
        self._fill = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_value)

    def _on_value(self, value) -> None:
        self._fill = float(value)
        self.update()

    def set_active(self, active: bool, animate: bool = True) -> None:
        self._active = active
        self._anim.stop()
        if not animate:
            self._fill = 1.0 if active else 0.0
            self.update()
            return
        self._anim.setStartValue(self._fill)
        self._anim.setEndValue(1.0 if active else 0.0)
        self._anim.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(PAL['cyan'] if (self._active or self._fill > 0)
                       else PAL['border'])
        if not self._active:
            color = QColor(PAL['cyan'])
            color.setAlphaF(max(0.0, self._fill))
        pen = QPen(color)
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(2, 2, 16, 16)
        painter.drawEllipse(rect)
        if self._fill > 0.01:
            inner = QColor(PAL['cyan'])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(inner)
            radius = 4.6 * self._fill
            painter.drawEllipse(rect.center(), radius, radius)
        painter.end()


class ChoiceCard(QFrame):

    clicked = pyqtSignal()

    def __init__(self, title: str, desc: str = '', link_text: str = '',
                 link_url: str = '', parent=None, title_size: int = 13):
        super().__init__(parent)
        self.setObjectName('Choice')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._selected = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(9)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(11)
        self.mark = RadioMark()
        head.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(4)
        self.title = QLabel(title)
        self.title.setFont(qfont(title_size, bold=True))
        self.title.setWordWrap(True)
        text_col.addWidget(self.title)
        self.desc = QLabel(desc)
        self.desc.setObjectName('Lead')
        self.desc.setWordWrap(True)
        if desc:
            text_col.addWidget(self.desc)
        head.addLayout(text_col, 1)
        layout.addLayout(head)

        self.link = None
        if link_text and link_url:
            self.link = Button(link_text, 'link', height=20)
            self.link.setFont(qfont(11, bold=True))
            self.link.clicked.connect(lambda: open_url(link_url))
            layout.addWidget(self.link, 0, Qt.AlignmentFlag.AlignLeft)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(31, 2, 0, 0)
        self.body_layout.setSpacing(9)
        self.body.setMaximumHeight(0)
        self.body.setVisible(False)
        layout.addWidget(self.body)
        self._anim = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return,
                           Qt.Key.Key_Enter):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def set_desc(self, text: str) -> None:
        self.desc.setText(text)

    def set_link_text(self, text: str) -> None:
        if self.link is not None:
            self.link.setText(text)

    def set_selected(self, selected: bool, animate: bool = True) -> None:
        selected = bool(selected)
        if selected == self._selected and animate:
            return
        self._selected = selected
        self.mark.set_active(selected, animate)
        self.setProperty('selected', selected)
        repolish(self)
        if selected:
            self._expand(animate)
        else:
            self._collapse(animate)

    def _expand(self, animate: bool) -> None:
        self.body.setVisible(True)
        target = self.body.sizeHint().height()
        if not animate:
            self.body.setMaximumHeight(16777215)
            return
        self._animate_height(0, target, hide=False)

    def _collapse(self, animate: bool) -> None:
        if not animate:
            self.body.setVisible(False)
            self.body.setMaximumHeight(0)
            return
        current = self.body.maximumHeight()
        if current >= 16777215:
            current = self.body.height()
        self._animate_height(current, 0, hide=True)

    def _animate_height(self, start: int, end: int, hide: bool) -> None:
        if self._anim is not None:
            self._anim.stop()
        anim = QPropertyAnimation(self.body, b'maximumHeight', self)
        anim.setDuration(190)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(max(0, int(start)))
        anim.setEndValue(max(0, int(end)))
        self._anim = anim

        def finished():
            if hide:
                self.body.setVisible(False)
            else:
                self.body.setMaximumHeight(16777215)
            if self._anim is anim:
                self._anim = None
                
        anim.finished.connect(finished)
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class ChoiceGroup(QObject):
    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = {}
        self._value = ''

    def add(self, card: ChoiceCard, value: str) -> ChoiceCard:
        self._cards[value] = card
        card.clicked.connect(lambda v=value: self.set_value(v))
        card.set_selected(False, animate=False)
        return card

    def value(self) -> str:
        return self._value

    def set_value(self, value: str, notify: bool = True,
                  animate: bool = True) -> None:
        if value not in self._cards:
            return
        if value == self._value and animate:
            return
        self._value = value
        for key, card in self._cards.items():
            card.set_selected(key == value, animate=animate)
        if notify:
            self.changed.emit(value)

    def card(self, value: str) -> ChoiceCard:
        return self._cards[value]


class AnimatedStack(QStackedWidget):
    def show_page(self, widget: QWidget, animate: bool = True) -> None:
        if widget is self.currentWidget():
            return
        if animate:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b'opacity', self)
            anim.setDuration(220)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            def clear():
                widget.setGraphicsEffect(None)
            anim.finished.connect(clear)
            self._fade = anim
        self.setCurrentWidget(widget)
        if animate:
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class Spinner(QWidget):
    def __init__(self, size: int = 18, color: str = '', parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._color = color or PAL['cyan']
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._angle = (self._angle + 16) % 360
        self.update()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5)
        pen = QPen(QColor(self._color))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(rect, -self._angle * 16, 270 * 16)
        painter.end()


class NeonProgress(QWidget):

    def __init__(self, height: int = 6, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._value = None
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(18)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._offset = (self._offset + 0.012) % 1.4
        self.update()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self, value: float = 1.0) -> None:
        self._timer.stop()
        self._value = value
        self.update()

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        radius = rect.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PAL['bg_deep']))
        painter.drawRoundedRect(rect, radius, radius)

        gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
        gradient.setColorAt(0.0, QColor(PAL['orange']))
        gradient.setColorAt(0.55, QColor(PAL['orange_soft']))
        gradient.setColorAt(1.0, QColor(PAL['cyan']))
        painter.setBrush(gradient)
        if self._value is None:
            span = rect.width() * 0.34
            start = rect.left() + (rect.width() + span) * (self._offset % 1.0) \
                - span
            bar = QRectF(max(rect.left(), start), rect.top(),
                         min(span, rect.right() - start), rect.height())
            if bar.width() > 1:
                painter.drawRoundedRect(bar, radius, radius)
        else:
            width = max(rect.height(), rect.width() * self._value)
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top(), width, rect.height()),
                radius, radius)
        painter.end()


class Toast(QFrame):

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName('Toast')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 16, 9)
        layout.setSpacing(9)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.text = QLabel('')
        self.text.setFont(qfont(11, bold=True))
        layout.addWidget(self.icon)
        layout.addWidget(self.text)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self.hide()
        self._token = 0
        self._anim_in = None
        self._anim_out = None
        self._alert = QTimer(self)
        self._alert.setSingleShot(True)
        self._alert.timeout.connect(lambda: self._hide_token(self._token))

    def show_message(self, text: str, icon_name: str = 'check',
                     color: str = '', duration: int = 2200) -> None:
        color = color or PAL['cyan']
        self.icon.setPixmap(icons.pixmap(icon_name, 16, color))
        self.text.setText(text)
        self.text.setStyleSheet(f'color: {PAL["text"]}; background: transparent;')
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._token += 1
        token = self._token

        target_x = (self.parentWidget().width() - self.width()) // 2
        end = QPoint(target_x, self.parentWidget().height() - self.height() - 41)
        
        self._animate(self._effect, b'opacity', 0.0, 1.0, 180)
        anim = QPropertyAnimation(self, b'pos', self)
        anim.setDuration(220)
        anim.setStartValue(QPoint(target_x, end.y() + 12))
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._anim_in = anim
        self._alert.stop()
        self._alert.start(duration)

    def _hide_token(self, token: int) -> None:
        if token != self._token:
            return
        self._animate(self._effect, b'opacity', 1.0, 0.0, 200,
                      self.hide)

    @staticmethod
    def _animate(target, prop, start, end, duration, on_done=None):
        anim = QPropertyAnimation(target, prop, target)
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if on_done is not None:
            anim.finished.connect(on_done)
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        return anim

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        self.move(max(12, x), parent.height() - self.height() - 41)


class Page(QWidget):

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.settings = shell.settings
        self._alive = True

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        self._alive = False


class ScrollBody(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.viewport().setAutoFillBackground(False)
        self.content = QWidget()
        self.content.setObjectName('ScrollContent')
        self.box = QVBoxLayout(self.content)
        self.box.setContentsMargins(0, 0, 6, 0)
        self.box.setSpacing(12)
        self.setWidget(self.content)
        self.setStyleSheet('QScrollArea { background: transparent; }')


class Switch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = False
        self._pos = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, value):
        try:
            self._pos = float(value)
        except (TypeError, ValueError):
            self._pos = 0.0
        self.update()

    def setChecked(self, on: bool) -> None:
        on = bool(on)
        if on == self._on:
            return
        self._on = on
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()
        self.toggled.emit(self._on)

    def isOn(self) -> bool:
        return self._on

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._on)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            radius = r.height() / 2.0
            bg = QColor(PAL['cyan'] if self._on else PAL['border_soft'])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(r, radius, radius)
            knob_x = r.left() + (r.width() - r.height()) * self._pos
            knob_r = QRectF(knob_x, r.top(), r.height(), r.height()).adjusted(2, 2, -2, -2)
            painter.setBrush(QColor(PAL['text']))
            painter.drawEllipse(knob_r)
        finally:
            painter.end()


class TrayMenu(QSystemTrayIcon):
    show_requested = pyqtSignal()
    exit_requested = pyqtSignal()

    def __init__(self, icon: QIcon, parent=None):
        super().__init__(icon, parent)
        self.setToolTip(t('app.name'))
        self._menu = QMenu()
        self._menu.setStyleSheet(f"""
            QMenu {{
                background-color: {PAL['surface_3']};
                color: {PAL['text']};
                border: 1px solid {PAL['border']};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 18px;
                border-radius: 6px;
            }}
            QMenu::item:selected {{
                background-color: {PAL['surface_2']};
                color: {PAL['cyan']};
            }}
        """)
        self._open_action = self._menu.addAction(t('tray.open'))
        self._open_action.triggered.connect(self.show_requested.emit)
        self._exit_action = self._menu.addAction(t('tray.exit'))
        self._exit_action.triggered.connect(self.exit_requested.emit)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_requested.emit()