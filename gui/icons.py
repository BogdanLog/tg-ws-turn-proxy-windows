from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen,
                         QPixmap, QPolygonF)

GRID = 24.0


def _pen(color: str, width: float = 1.7) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _polygon(*points) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def draw(painter: QPainter, name: str, rect: QRectF, color: str,
         width: float = 1.7) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    side = min(rect.width(), rect.height())
    painter.translate(rect.center().x() - side / 2,
                      rect.center().y() - side / 2)
    painter.scale(side / GRID, side / GRID)
    pen = _pen(color, width)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == 'close':
        painter.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
        painter.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))
    elif name == 'minimize':
        painter.drawLine(QPointF(6, 12), QPointF(18, 12))
    elif name == 'gear':
        painter.drawEllipse(QPointF(12, 12), 6.1, 6.1)
        painter.drawEllipse(QPointF(12, 12), 2.3, 2.3)
        for index in range(8):
            angle = math.radians(index * 45)
            dx, dy = math.cos(angle), math.sin(angle)
            painter.drawLine(QPointF(12 + dx * 7.2, 12 + dy * 7.2),
                             QPointF(12 + dx * 9.2, 12 + dy * 9.2))
    elif name == 'play':
        painter.setBrush(QColor(color))
        painter.drawPolygon(_polygon((8.5, 5.5), (19.0, 12.0), (8.5, 18.5)))
    elif name == 'stop':
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(7, 7, 10, 10), 2.4, 2.4)
    elif name == 'copy':
        painter.drawRoundedRect(QRectF(4.5, 4.5, 11.5, 11.5), 2.5, 2.5)
        path = QPainterPath()
        path.moveTo(8.5, 19.0)
        path.lineTo(17.0, 19.0)
        path.quadTo(19.5, 19.0, 19.5, 16.5)
        path.lineTo(19.5, 8.5)
        painter.drawPath(path)
    elif name == 'check':
        painter.setPen(_pen(color, 2.1))
        painter.drawPolyline(_polygon((5.5, 12.5), (10.0, 17.2), (18.5, 6.8)))
    elif name == 'chevron_left':
        painter.drawPolyline(_polygon((14.5, 5.5), (7.5, 12.0), (14.5, 18.5)))
    elif name == 'chevron_right':
        painter.drawPolyline(_polygon((9.5, 5.5), (16.5, 12.0), (9.5, 18.5)))
    elif name == 'chevron_down':
        painter.drawPolyline(_polygon((5.5, 9.0), (12.0, 15.5), (18.5, 9.0)))
    elif name == 'telegram':
        painter.setPen(_pen(color, 1.6))
        painter.drawPolygon(_polygon((3.4, 11.3), (20.8, 3.7), (17.4, 20.3),
                                     (11.5, 14.8), (8.7, 19.5), (8.3, 12.7)))
        painter.drawLine(QPointF(8.3, 12.7), QPointF(17.4, 5.6))
    elif name == 'trash':
        painter.drawLine(QPointF(4.5, 7), QPointF(19.5, 7))
        painter.drawLine(QPointF(9.5, 7), QPointF(9.5, 4.8))
        painter.drawLine(QPointF(9.5, 4.8), QPointF(14.5, 4.8))
        painter.drawLine(QPointF(14.5, 4.8), QPointF(14.5, 7))
        painter.drawPolyline(_polygon((6.3, 7.0), (7.4, 20.0),
                                      (16.6, 20.0), (17.7, 7.0)))
        painter.drawLine(QPointF(10.4, 10.5), QPointF(10.9, 16.5))
        painter.drawLine(QPointF(13.6, 10.5), QPointF(13.1, 16.5))
    elif name == 'shield':
        path = QPainterPath()
        path.moveTo(12, 3.2)
        path.lineTo(19.2, 6.0)
        path.lineTo(19.2, 11.2)
        path.cubicTo(19.2, 16.0, 16.0, 19.4, 12, 21.0)
        path.cubicTo(8.0, 19.4, 4.8, 16.0, 4.8, 11.2)
        path.lineTo(4.8, 6.0)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setPen(_pen(color, 1.8))
        painter.drawPolyline(_polygon((8.7, 11.7), (11.2, 14.3), (15.6, 9.2)))
    elif name == 'power':
        painter.drawArc(QRectF(5.2, 5.2, 13.6, 13.6), 40 * 16, 280 * 16)
        painter.drawLine(QPointF(12, 3.2), QPointF(12, 11.0))
    elif name == 'refresh':
        painter.drawArc(QRectF(4.6, 4.6, 14.8, 14.8), 30 * 16, 280 * 16)
        painter.drawPolyline(_polygon((17.0, 3.6), (19.6, 8.3),
                                      (14.6, 8.7)))
    elif name == 'dot':
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(8.5, 8.5, 7, 7))
    painter.restore()


def pixmap(name: str, size: int, color: str, width: float = 1.7) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw(painter, name, QRectF(0, 0, size, size), color, width)
    painter.end()
    return pixmap


def icon(name: str, color: str, size: int = 18,
         width: float = 1.7) -> QIcon:
    result = QIcon()
    scale = 2
    result.addPixmap(pixmap(name, size * scale, color, width))
    return result


def icon_size(size: int):
    from PyQt6.QtCore import QSize
    return QSize(size, size)