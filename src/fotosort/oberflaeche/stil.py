"""Aussehen des Desktop-Fensters (PySide6): die Nocturne-Werte aus
docs/design/styles.css als Qt-Stylesheet, die Inter-Schrift aus dem Paket
und das Programmsymbol.

Farben, Abstaende und Rundungen sind hier einmal abgeschrieben (Qt kann kein
CSS lesen); die Zuordnung steht neben jedem Wert. Eine Akzentfarbe, nur fuer
Linien und Umrisse, nie als Flaeche - so, wie der Entwurf es verlangt.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap

STATIC = Path(__file__).resolve().parent / "static"

# --color-* aus styles.css
BG = "#161826"
SURFACE = "#232532"
TEXT = "#e9e9ed"
AKZENT = "#9184d9"
AKZENT_2 = "#a7a1db"
N100, N200, N300, N400 = "#f3f5fe", "#e4e7f5", "#cfd3e5", "#b2b6ca"
N500, N600, N700, N800, N900 = "#9397ab", "#75798c", "#595d6c", "#3f424d", "#292b31"
DIVIDER = "rgba(233,233,237,41)"      # color-mix(text 16%, transparent)
REGEL = "rgba(233,233,237,20)"        # color-mix(text 8%)  - Zeilenlinien
AKZENT_12 = "rgba(145,132,217,31)"    # Akzent 12 % (hover)
AKZENT_22 = "rgba(145,132,217,56)"    # Akzent 22 % (aktiv)
TEXT_7 = "rgba(233,233,237,18)"       # Text 7 % (hover sekundaer)
SCHRIFT = "Inter"
ERSATZ = '"Inter", "Segoe UI", "Noto Sans", sans-serif'
MONO = '"Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace'


def schriften_laden() -> bool:
    """Inter aus dem Paket in Qt anmelden. False, wenn keine Datei da war (dann Segoe UI)."""
    gefunden = False
    for name in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"):
        datei = STATIC / "fonts" / name
        if datei.is_file() and QFontDatabase.addApplicationFont(str(datei)) >= 0:
            gefunden = True
    return gefunden


def grundschrift() -> QFont:
    schrift = QFont(SCHRIFT if SCHRIFT in QFontDatabase.families() else "Segoe UI", 11)
    schrift.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return schrift


def symbol(groesse: int = 256) -> QPixmap:
    """Das Programmsymbol, gezeichnet statt geladen: dunkle Kachel, Akzentrahmen,
    eine Akzentlinie mit Fuellung wie die Phasenleiste."""
    px = QPixmap(groesse, groesse)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = groesse / 32.0
    p.setPen(QPen(QColor(AKZENT), max(1.0, r * 1.2)))
    p.setBrush(QColor(SURFACE))
    p.drawRoundedRect(QRectF(r * 1.5, r * 1.5, groesse - 3 * r, groesse - 3 * r), r * 6, r * 6)
    # Linie mit "Fortschritt"
    p.setPen(QPen(QColor(N800), max(1.0, r * 1.6), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QRectF(r * 7, groesse * 0.62, groesse - r * 14, 0).topLeft(), QRectF(r * 7, groesse * 0.62, groesse - r * 14, 0).topRight())
    p.setPen(QPen(QColor(AKZENT), max(1.0, r * 1.6), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QRectF(r * 7, groesse * 0.62, (groesse - r * 14) * 0.58, 0).topLeft(), QRectF(r * 7, groesse * 0.62, (groesse - r * 14) * 0.58, 0).topRight())
    # "f" in Inter
    schrift = QFont(SCHRIFT if SCHRIFT in QFontDatabase.families() else "Segoe UI")
    schrift.setPixelSize(int(groesse * 0.42))
    schrift.setWeight(QFont.Weight.DemiBold)
    p.setFont(schrift)
    p.setPen(QColor(TEXT))
    p.drawText(QRectF(0, groesse * 0.08, groesse, groesse * 0.5), Qt.AlignmentFlag.AlignCenter, "f")
    p.end()
    return px


def programm_symbol() -> QIcon:
    icon = QIcon()
    for g in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(symbol(g))
    return icon


STYLESHEET = f"""
* {{ font-family: {ERSATZ}; }}
QMainWindow, QWidget#inhalt, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {BG}; color: {TEXT};
}}
QWidget {{ color: {TEXT}; font-size: 15px; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {N700}; padding: 4px 8px; }}

/* Titelzeile und Statusleiste (40 px, Flaeche bzw. Trennlinie) */
QFrame#titelzeile {{ background: {SURFACE}; }}
QFrame#titelzeile QLabel {{ font-size: 12px; color: {N500}; }}
QFrame#titelzeile QLabel#marke {{ color: {TEXT}; font-weight: 500; }}
QFrame#statusleiste {{ background: {BG}; border-top: 1px solid {DIVIDER}; }}
QFrame#statusleiste QLabel {{ font-family: {MONO}; font-size: 11px; color: {N500}; }}
QLabel[klasse="hell"] {{ color: {N300}; }}
QLabel[klasse="gedaempft"] {{ color: {N500}; }}
QLabel[klasse="leise"] {{ color: {N600}; }}
QLabel[klasse="hinweis"] {{ font-size: 12px; color: {N500}; }}
QLabel[klasse="feldname"] {{ font-size: 12px; color: {N500}; }}
QLabel[klasse="mono"] {{ font-family: {MONO}; }}
QLabel[klasse="mono-hell"] {{ font-family: {MONO}; color: {N300}; font-size: 12px; }}
QLabel[klasse="mono-leise"] {{ font-family: {MONO}; color: {N600}; font-size: 12px; }}
QLabel[klasse="kicker"] {{ font-size: 10px; letter-spacing: 1px; color: {AKZENT}; }}
QLabel[klasse="kicker-gedaempft"] {{ font-size: 10px; letter-spacing: 1px; color: {N500}; }}
QLabel[klasse="kennzahl"] {{ font-size: 13px; color: {N400}; }}
QLabel[klasse="zaehler-name"] {{ font-size: 14px; color: {N400}; }}
QLabel[klasse="zaehler-wert"] {{ font-size: 14px; color: {TEXT}; }}
QLabel[klasse="zaehler-null"] {{ font-size: 14px; color: {N600}; }}
QLabel[klasse="titel"] {{ font-size: 14px; color: {TEXT}; font-weight: 500; }}
QLabel[klasse="dialog-titel"] {{ font-size: 20px; font-weight: 500; }}
QLabel[klasse="dialog-text"] {{ font-size: 14px; color: {N300}; }}
QLabel[klasse="phase"] {{ font-size: 13px; color: {N600}; }}
QLabel[klasse="phase-fertig"] {{ font-size: 13px; color: {N500}; }}
QLabel[klasse="phase-aktiv"] {{ font-size: 13px; color: {AKZENT}; }}
QLabel[klasse="pfeil"] {{ color: {N600}; font-size: 13px; }}

/* Tags */
QLabel[klasse="tag"] {{ background: {N800}; color: {N100}; font-size: 11px; padding: 3px 10px; border-radius: 6px; }}
QLabel[klasse="tag-mono"] {{ background: {N800}; color: {N100}; font-family: {MONO}; font-size: 11px; padding: 3px 10px; border-radius: 6px; }}
QLabel[klasse="tag-outline"] {{ background: transparent; color: {AKZENT}; font-family: {MONO}; font-size: 11px; padding: 2px 9px; border: 1px solid {AKZENT}; border-radius: 6px; }}
QFrame[klasse="tagzeile"] {{ background: {N800}; border-radius: 6px; }}
QFrame[klasse="tagzeile"] QLabel {{ color: {N100}; font-family: {MONO}; font-size: 11px; background: transparent; }}
QFrame[klasse="tagzeile"] QPushButton {{ color: {N400}; font-size: 12px; padding: 0 4px; min-height: 16px; border: none; }}
QFrame[klasse="tagzeile"] QPushButton:hover {{ color: {TEXT}; background: transparent; }}

/* Knoepfe */
QPushButton {{
    background: transparent; color: {TEXT}; border: 1px solid transparent; border-radius: 8px;
    padding: 6px 12px; min-height: 22px; font-size: 14px; font-weight: 500;
}}
QPushButton[klasse="primary"] {{ color: {AKZENT}; border-color: {AKZENT}; }}
QPushButton[klasse="primary"]:hover {{ background: {AKZENT_12}; }}
QPushButton[klasse="primary"]:pressed {{ background: {AKZENT_22}; }}
QPushButton[klasse="secondary"] {{ border-color: {DIVIDER}; }}
QPushButton[klasse="secondary"]:hover {{ background: {TEXT_7}; }}
QPushButton[klasse="ghost"] {{ color: {AKZENT}; padding: 6px 4px; }}
QPushButton[klasse="ghost"]:hover {{ background: {AKZENT_12}; }}
QPushButton:disabled {{ color: {N700}; border-color: {N800}; }}
QPushButton[klasse="primary"]:disabled {{ color: {N700}; border-color: {N800}; }}
QPushButton[klasse="ghost"]:disabled {{ color: {N700}; }}
QPushButton[klasse="seg-opt"] {{ border: 1px solid transparent; border-radius: 7px; padding: 6px 12px; font-size: 13px; font-weight: 400; color: {TEXT}; }}
QPushButton[klasse="seg-opt"]:hover {{ background: {TEXT_7}; }}
QPushButton[klasse="seg-opt"]:checked {{ color: {AKZENT}; border: 1px solid {AKZENT}; background: transparent; }}
QPushButton[klasse="seg-opt"]:disabled {{ color: {N700}; }}
QFrame[klasse="seg"] {{ border: 1px solid {DIVIDER}; border-radius: 8px; background: transparent; }}

/* Felder */
QLineEdit {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {DIVIDER}; border-radius: 8px;
    padding: 6px 10px; min-height: 22px; font-size: 14px; selection-background-color: {AKZENT_22};
}}
QLineEdit[klasse="mono"] {{ font-family: {MONO}; }}
QLineEdit:hover {{ border-color: {N600}; }}
QLineEdit:focus {{ border-color: {AKZENT}; }}
QLineEdit:disabled {{ color: {N700}; border-color: {N800}; }}
QLineEdit:read-only {{ color: {N300}; }}

/* Karten */
QFrame[klasse="card"] {{ background: {SURFACE}; border: 1px solid {N800}; border-radius: 8px; }}
QFrame[klasse="card"] QLabel {{ background: transparent; }}
QFrame[klasse="card"] QLineEdit {{ background: {BG}; }}
QFrame[klasse="card-inaktiv"] {{ background: {SURFACE}; border: 1px solid {N900}; border-radius: 8px; }}
QFrame[klasse="card-inaktiv"] QLabel {{ background: transparent; color: {N600}; }}
QFrame[klasse="card-inaktiv"] QLineEdit {{ background: {BG}; }}

/* Tabellen */
QTableWidget {{
    background: transparent; alternate-background-color: transparent; border: none;
    gridline-color: transparent; font-size: 14px; selection-background-color: {TEXT_7}; selection-color: {TEXT};
    outline: none;
}}
QTableWidget::item {{ padding: 5px 6px; border-bottom: 1px solid {REGEL}; }}
QTableWidget::item:selected {{ background: {TEXT_7}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; color: {N500}; font-size: 11px; letter-spacing: 1px; font-weight: 500;
    padding: 5px 6px; border: none; border-bottom: 1px solid {DIVIDER};
}}
QTableCornerButton::section {{ background: transparent; border: none; }}
QTableWidget QLineEdit {{ min-height: 18px; padding: 3px 8px; font-size: 13px; }}

/* Protokoll */
QPlainTextEdit {{ background: {SURFACE}; color: {N400}; border: none; border-radius: 8px; font-family: {MONO}; font-size: 11px; padding: 8px; }}

/* Dialog */
QDialog {{ background: {SURFACE}; }}
QDialog QLabel {{ background: transparent; }}

/* Bildlaufleisten */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {N800}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {N700}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {N800}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""
