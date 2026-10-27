"""Aussehen des Desktop-Fensters (PySide6): wie ein Windows-11-Programm.

Entscheidung des Nutzers vom 27.10.2026 (docs/todo.md, Phase 11): Das Fenster
soll nicht nach KI aussehen. Es nimmt deshalb den Grundstil des Systems -
unter Windows "windows11" (normale Windows-Knoepfe, Felder, Bildlaufleisten,
Akzentfarbe von Windows), sonst "Fusion" - und dessen Palette: hell oder
dunkel, wie Windows eingestellt ist, auch wenn das waehrend des Laufs
umgestellt wird. Schrift ist die des Systems (Segoe UI unter Windows).

Das Stylesheet unten setzt nur Schriftgroessen, Fettdruck und den gedaempften
Grauton fuer Hinweise - keine eigenen Farben, keine Schreibmaschinenschrift,
keine Ueberschriften in Grossbuchstaben. Der Grauton wird aus der Palette
gemischt, weil Qt-Stylesheets ihn nicht als Palettenrolle kennen.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QStyleFactory

STATIC = Path(__file__).resolve().parent / "static"


def grundstil() -> str:
    """Name des Qt-Grundstils: "windows11" unter Windows (seit Qt 6.7), sonst Fusion."""
    vorhanden = {k.lower() for k in QStyleFactory.keys()}
    if sys.platform.startswith("win"):
        for name in ("windows11", "windowsvista"):
            if name in vorhanden:
                return name
    return "fusion"


def _mischen(a: QColor, b: QColor, anteil_a: float) -> QColor:
    return QColor(
        round(a.red() * anteil_a + b.red() * (1 - anteil_a)),
        round(a.green() * anteil_a + b.green() * (1 - anteil_a)),
        round(a.blue() * anteil_a + b.blue() * (1 - anteil_a)),
    )


def gedaempft_farbe(pal: QPalette) -> str:
    """Grau fuer Hinweise: Text zu gut der Haelfte mit dem Fensterhintergrund
    gemischt - lesbar in hell und dunkel."""
    return _mischen(pal.color(QPalette.ColorRole.WindowText), pal.color(QPalette.ColorRole.Window), 0.6).name()


def grundschrift() -> QFont:
    """Die Schrift des Systems, in der Groesse, die Windows-11-Programme nutzen."""
    schrift = QFont(QApplication.font())
    if sys.platform.startswith("win"):
        schrift.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
    schrift.setPointSize(10)
    return schrift


def stylesheet(pal: QPalette) -> str:
    grau = gedaempft_farbe(pal)
    return f"""
QLabel[klasse="hinweis"], QLabel[klasse="gedaempft"], QLabel[klasse="leise"],
QLabel[klasse="kennzahl"], QLabel[klasse="zaehler-name"], QLabel[klasse="zaehler-null"],
QLabel[klasse="phase"], QLabel[klasse="kicker-gedaempft"], QLabel[klasse="pfeil"] {{ color: {grau}; }}
QLabel[klasse="titel"], QLabel[klasse="kicker"], QLabel[klasse="kicker-gedaempft"],
QLabel[klasse="feldname"] {{ font-weight: 600; }}
QLabel[klasse="dialog-titel"] {{ font-size: 13pt; font-weight: 600; }}
QLabel[klasse="seitentitel"] {{ font-size: 15pt; font-weight: 600; }}
QLabel[klasse="phase-aktiv"] {{ font-weight: 600; }}
QFrame[klasse="card"], QFrame[klasse="card-inaktiv"] {{
    background: palette(base); border: 1px solid palette(midlight); border-radius: 6px;
}}
QFrame[klasse="card-inaktiv"] QLabel {{ color: {grau}; }}
QPushButton[klasse="reiter"] {{
    border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 6px 10px; background: transparent;
}}
QPushButton[klasse="reiter"]:checked {{ border-bottom: 2px solid palette(highlight); font-weight: 600; }}
QPushButton[klasse="reiter"]:hover {{ background: palette(midlight); }}
"""


def einrichten(app: QApplication) -> None:
    """Grundstil, Schrift und Stylesheet setzen; bei einem Wechsel hell/dunkel
    in Windows das Stylesheet aus der neuen Palette neu bauen."""
    name = grundstil()
    app.setStyle(name)
    app.setProperty("fotosort_grundstil", name)
    app.setFont(grundschrift())
    app.setStyleSheet(stylesheet(app.palette()))
    if not getattr(app, "_fotosort_farben_verbunden", False):
        def neu() -> None:
            app.setStyleSheet(stylesheet(app.palette()))
        app.styleHints().colorSchemeChanged.connect(lambda _s: QTimer.singleShot(0, neu))
        app._fotosort_farben_verbunden = True


def symbol(groesse: int = 256) -> QPixmap:
    """Das Programmsymbol, gezeichnet statt geladen: ein Foto (Himmel, Berg,
    Sonne) auf einem zweiten - schlicht, wie die Symbole von Windows."""
    px = QPixmap(groesse, groesse)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = float(groesse)
    rund = g * 0.08
    # hinteres Bild, leicht versetzt
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#9bb7d4"))
    p.drawRoundedRect(QRectF(g * 0.20, g * 0.10, g * 0.72, g * 0.62), rund, rund)
    # vorderes Bild: weisser Rand, Himmel, Berg, Sonne
    vorn = QRectF(g * 0.08, g * 0.26, g * 0.76, g * 0.64)
    p.setBrush(QColor("#ffffff"))
    p.setPen(QPen(QColor("#5b7a99"), max(1.0, g / 64)))
    p.drawRoundedRect(vorn, rund, rund)
    innen = vorn.adjusted(g * 0.06, g * 0.06, -g * 0.06, -g * 0.06)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#4a90d9"))
    p.drawRect(innen)
    berg = QPainterPath()
    berg.moveTo(innen.bottomLeft())
    berg.lineTo(QPointF(innen.left() + innen.width() * 0.38, innen.top() + innen.height() * 0.40))
    berg.lineTo(QPointF(innen.left() + innen.width() * 0.58, innen.top() + innen.height() * 0.68))
    berg.lineTo(QPointF(innen.left() + innen.width() * 0.74, innen.top() + innen.height() * 0.52))
    berg.lineTo(innen.bottomRight())
    berg.closeSubpath()
    p.setBrush(QColor("#2f6b3a"))
    p.drawPath(berg)
    p.setBrush(QColor("#f2c94c"))
    r = innen.width() * 0.09
    p.drawEllipse(QPointF(innen.right() - innen.width() * 0.22, innen.top() + innen.height() * 0.28), r, r)
    p.end()
    return px


def programm_symbol() -> QIcon:
    icon = QIcon()
    for g in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(symbol(g))
    return icon
