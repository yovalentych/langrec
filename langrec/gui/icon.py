"""Application icon drawn in code: a heart with a pressure trace.

Drawing it in code keeps binary image files out of the repository. For builds,
build_app.py calls save_icon_png() and PyInstaller turns the PNG into .icns / .ico.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


def _paint(p: QPainter, s: float):
    p.setRenderHint(QPainter.Antialiasing)
    # rounded square background
    r = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor("#1e3a8a"))
    g.setColorAt(1, QColor("#2563eb"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(r, s * 0.22, s * 0.22)

    # heart
    heart = QPainterPath()
    cx, top = s * 0.5, s * 0.33
    heart.moveTo(cx, s * 0.80)
    heart.cubicTo(s * 0.12, s * 0.55, s * 0.18, s * 0.18, cx, top)
    heart.cubicTo(s * 0.82, s * 0.18, s * 0.88, s * 0.55, cx, s * 0.80)
    p.setBrush(QColor("#ef4444"))
    p.drawPath(heart)

    # pressure trace over the heart
    pen = QPen(QColor("white"), s * 0.045)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    pts = [(0.16, 0.55), (0.33, 0.55), (0.40, 0.40), (0.47, 0.68), (0.54, 0.30),
           (0.61, 0.60), (0.67, 0.55), (0.84, 0.55)]
    path = QPainterPath(QPointF(pts[0][0] * s, pts[0][1] * s))
    for x, y in pts[1:]:
        path.lineTo(x * s, y * s)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


def make_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        _paint(p, size)
        p.end()
        icon.addPixmap(pm)
    return icon


def save_icon_png(path: str, size: int = 1024) -> None:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    _paint(p, size)
    p.end()
    img.save(path)
