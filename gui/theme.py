from __future__ import annotations

import os
import webbrowser

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPixmap

PAL = {
    'bg': '#0a1c32',
    'bg_deep': '#071527',
    'surface': '#0e2540',
    'surface_2': '#112c4a',
    'surface_3': '#153657',
    'border': '#1e4368',
    'border_soft': '#173852',
    'text': '#ffffff',
    'muted': '#9db5cd',
    'faint': '#6b89a6',
    'orange': '#f97020',
    'orange_soft': '#ff8b45',
    'cyan': '#1ed7e4',
    'cyan_soft': '#6eeaf3',
    'red': '#ff5f6d',
}

SANS = 'Segoe UI'
MONO = 'Consolas'

_SANS_CANDIDATES = ('Segoe UI Variable Text', 'Segoe UI', 'Inter', 'Arial')
_MONO_CANDIDATES = ('Cascadia Mono', 'Cascadia Code', 'Consolas',
                    'JetBrains Mono', 'Courier New')

STYLE = 'Fusion'


def qfont(size: int = 13, bold: bool = False, mono: bool = False,
          weight: int = 0) -> QFont:
    font = QFont(MONO if mono else SANS)
    font.setPixelSize(int(size))
    if bold:
        font.setWeight(QFont.Weight.DemiBold)
    if weight:
        font.setWeight(QFont.Weight(weight))
    if mono:
        font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def _pick_family(candidates, fallback: str) -> str:
    try:
        families = set(QFontDatabase.families())
    except Exception:
        return fallback
    for name in candidates:
        if name in families:
            return name
    return fallback


def _logo_path() -> str:
    from gui import state
    for base in (state.ASSET_DIR, state.BUNDLE, state.ROOT):
        path = os.path.join(base, 'gui', 'assets', 'logo.png') \
            if base != state.ASSET_DIR else os.path.join(base, 'logo.png')
        if os.path.isfile(path):
            return path
    return ''


def logo_pixmap(size: int = 28) -> QPixmap:
    path = _logo_path()
    pixmap = QPixmap(path) if path else QPixmap()
    if pixmap.isNull():
        return pixmap
    from PyQt6.QtCore import Qt
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


def logo_icon():
    from PyQt6.QtGui import QIcon
    pixmap = logo_pixmap(256)
    return QIcon(pixmap) if not pixmap.isNull() else QIcon()


def stylesheet() -> str:
    p = PAL
    return f"""
    QWidget {{
        color: {p['text']};
        font-family: "{SANS}";
        font-size: 13px;
    }}
    QLabel {{ background: transparent; }}
    QLabel#H1 {{ font-size: 22px; font-weight: 700; }}
    QLabel#StatusBig {{ font-size: 19px; font-weight: 700; }}
    QLabel#H2 {{ font-size: 15px; font-weight: 600; }}
    QLabel#H3 {{ font-size: 13px; font-weight: 600; }}
    QLabel#Lead {{ color: {p['muted']}; font-size: 12px; }}
    QLabel#Muted {{ color: {p['muted']}; font-size: 12px; }}
    QLabel#Faint {{ color: {p['faint']}; font-size: 11px; }}
    QLabel#Value {{ font-size: 15px; font-weight: 600; }}
    QLabel#Tiny {{ color: {p['faint']}; font-size: 10px; }}
    QLabel#Caption {{
        color: {p['faint']};
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#Cyan {{ color: {p['cyan']}; }}
    QLabel#Orange {{ color: {p['orange']}; }}
    QLabel#Error {{ color: {p['red']}; font-size: 11px; }}
    QLabel#Mono {{ font-family: "{MONO}"; font-size: 11px; color: {p['muted']}; }}

    #Shell {{
        background: {p['bg']};
        border: 1px solid {p['border']};
        border-radius: 16px;
    }}
    #ShellBody {{ background: transparent; }}

    QFrame#Card, QFrame#Hero, QFrame#Choice, QFrame#Chip, QFrame#SegBg,
    QFrame#Toast, QFrame#WarnBox {{
        background: {p['surface']};
        border: 1px solid {p['border']};
        border-radius: 12px;
    }}
    QFrame#Hero {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p['surface_2']},
                                    stop:1 {p['surface']});
    }}
    QFrame#Choice[selected="true"] {{
        border: 1px solid {p['cyan']};
        background: #102b49;
    }}
    QFrame#Chip {{ border-radius: 13px; background: rgba(255,255,255,0.035); }}
    QFrame#Chip[state="running"] {{
        border-color: rgba(30,215,228,0.55);
        background: rgba(30,215,228,0.08);
    }}
    QFrame#Chip[state="starting"], QFrame#Chip[state="partial"] {{
        border-color: rgba(249,112,32,0.55);
        background: rgba(249,112,32,0.08);
    }}
    QFrame#Chip[state="error"] {{
        border-color: rgba(255,95,109,0.55);
        background: rgba(255,95,109,0.08);
    }}
    QFrame#SegBg {{ background: {p['bg_deep']}; border-radius: 10px; }}
    QFrame#Toast {{ background: {p['surface_3']}; border-radius: 10px; }}
    QFrame#WarnBox {{
        background: rgba(249,112,32,0.10);
        border: 1px solid rgba(249,112,32,0.40);
        border-radius: 10px;
    }}
    QFrame#NoteBox {{
        background: rgba(30,215,228,0.07);
        border: 1px solid rgba(30,215,228,0.25);
        border-radius: 10px;
    }}
    QFrame#Divider {{ background: {p['border_soft']}; border: none; }}

    QPushButton {{
        background: transparent;
        border: none;
        border-radius: 9px;
        padding: 0 16px;
        color: {p['text']};
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#Primary {{
        background: {p['orange']};
        color: {p['text']};
        font-size: 13px;
    }}
    QPushButton#Primary:hover {{ background: {p['orange_soft']}; }}
    QPushButton#Primary:pressed {{ background: #e2601a; }}
    QPushButton#Primary:disabled {{
        background: {p['surface_3']};
        color: {p['faint']};
    }}
    QPushButton#Ghost {{
        background: transparent;
        border: 1px solid {p['border']};
        color: {p['text']};
    }}
    QPushButton#Ghost:hover {{
        border-color: rgba(30,215,228,0.65);
        background: rgba(30,215,228,0.08);
        color: {p['cyan']};
    }}
    QPushButton#Ghost:pressed {{ background: rgba(30,215,228,0.14); }}
    QPushButton#Ghost:disabled {{
        border-color: {p['border_soft']};
        color: {p['faint']};
    }}
    QPushButton#Cyan {{
        background: rgba(30,215,228,0.12);
        border: 1px solid rgba(30,215,228,0.40);
        color: {p['cyan']};
    }}
    QPushButton#Cyan:hover {{
        background: rgba(30,215,228,0.20);
        border-color: {p['cyan']};
    }}
    QPushButton#Cyan:disabled {{
        background: rgba(30,215,228,0.05);
        border-color: rgba(30,215,228,0.16);
        color: {p['faint']};
    }}
    QPushButton#Danger {{ background: {p['red']}; color: #2a0b10; }}
    QPushButton#Danger:hover {{ background: #ff7a86; }}
    QPushButton#Icon {{
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 0;
    }}
    QPushButton#Icon:hover {{ background: rgba(255,255,255,0.07); }}
    QPushButton#Icon:pressed {{ background: rgba(255,255,255,0.12); }}
    QPushButton#Icon[role="close"]:hover {{
        background: rgba(255,95,109,0.85);
    }}
    QPushButton#Link {{
        background: transparent;
        border: none;
        padding: 0 2px;
        color: {p['cyan']};
        font-size: 11px;
        font-weight: 600;
        text-align: left;
    }}
    QPushButton#Link:hover {{ color: {p['cyan_soft']}; text-decoration: underline; }}
    QPushButton#SegBtn {{
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 0 12px;
        color: {p['muted']};
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#SegBtn:hover {{ color: {p['text']}; }}
    QPushButton#SegBtn:checked {{
        background: rgba(30,215,228,0.14);
        color: {p['cyan']};
    }}
    QPushButton#SegBtn:disabled {{
        color: rgba(157, 181, 205, 0.35);
        background: transparent;
    }}
    QPushButton#SegBtn:checked:disabled {{
        background: transparent;
        color: rgba(157, 181, 205, 0.35);
    }}

    QLineEdit {{
        background: {p['bg_deep']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 8px 10px;
        color: {p['text']};
        selection-background-color: {p['orange']};
        selection-color: {p['text']};
    }}
    QLineEdit:focus {{ border: 1px solid {p['cyan']}; }}
    QLineEdit:read-only {{ color: {p['muted']}; }}
    QLineEdit#Mono {{ font-family: "{MONO}"; font-size: 11px; }}

    QPlainTextEdit, QTextEdit {{
        background: {p['bg_deep']};
        border: none;
        border-radius: 10px;
        color: {p['muted']};
        font-family: "{MONO}";
        font-size: 11px;
        padding: 8px;
    }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p['border']};
        border-radius: 3px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #2a557f; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 9px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p['border']};
        border-radius: 3px;
        min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: #2a557f; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal
    {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}

    QToolTip {{
        background: {p['surface_3']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 6px;
        padding: 6px 9px;
    }}
    """


def apply(app) -> None:
    global SANS, MONO
    SANS = _pick_family(_SANS_CANDIDATES, 'Segoe UI')
    MONO = _pick_family(_MONO_CANDIDATES, 'Consolas')
    try:
        app.setStyle(STYLE)
    except Exception:
        pass
    app.setFont(qfont(13))
    app.setStyleSheet(stylesheet())


def mix(color: str, other: str, amount: float) -> str:
    a, b = QColor(color), QColor(other)
    if not a.isValid() or not b.isValid():
        return color
    ratio = max(0.0, min(1.0, amount))
    out = QColor(
        round(a.red() + (b.red() - a.red()) * ratio),
        round(a.green() + (b.green() - a.green()) * ratio),
        round(a.blue() + (b.blue() - a.blue()) * ratio),
    )
    return out.name()


def open_url(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


def open_tg_link(link: str) -> bool:
    try:
        os.startfile(link)
        return True
    except Exception:
        return False


def copy_text(text: str) -> None:
    try:
        from PyQt6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            QApplication.clipboard().setText(text)
    except Exception:
        pass