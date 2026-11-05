"""Reiter „Wohin?“: die Fluss-Grafik im Fenster (v0.14, SPEC §8).

Gerechnet wird in wohin.py (Ebenen, Lage der Baender, Treffer unter dem
Zeiger); hier wird nur gezeichnet - mit QPainter, denn im Windows-Paket stecken
nur QtCore, QtGui und QtWidgets - und bedient.

Gestaltung (Regeln fuer Diagramme, Farben mit dem Pruefskript geprueft):
- Farbe heisst Schicksal: Blau im Archiv, Orange doppelt, Gruenblau war schon
  im Archiv - die ersten drei Stufen der geprueften Palette, die auch fuer
  Farbenblinde jedes Paar trennen. Geplant ist derselbe Blauton als Schleier
  mit Kante: noch nicht geschehen. Hell und dunkel haben je eigene Stufen.
- Grau fuer die Kaesten ohne Archivordner, Rot nur fuer Fehler und Gelb fuer
  "Archiv an anderem Ort" - immer mit Zeichen und Wort, nie Farbe allein.
- Schmale Knoten, 2 px Luft zwischen den Baendern eines Knotens, Beschriftung
  gekuerzt statt abgeschnitten, Text in Textfarben (nie in Bandfarbe).
- Legende immer da; darunter dieselben Stroeme als Tabelle, sortierbar und
  per Tastatur erreichbar.
"""

from __future__ import annotations

import html
import sqlite3
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFontMetrics, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from .. import FotosortFehler, db, meldungen, wohin
from . import stil

# Gepruefte Farben (scripts/validate_palette.js, Pruefung v0.14): hell auf
# #ffffff, dunkel auf #1a1a19 und #2b2b2b. Geplant: der Blauton als Schleier.
FARBEN = {
    "hell": {
        wohin.KOPIERT: "#2a78d6", wohin.GEPLANT: "#2a78d6", wohin.DOPPELT: "#eb6834", wohin.SCHON_DA: "#1baf7a",
        wohin.BLEIBT: "#898781", wohin.OFFEN: "#898781", wohin.FEHLER: "#d03b3b", wohin.ANDERSWO: "#fab219",
        "knoten": "#52514e",
    },
    "dunkel": {
        wohin.KOPIERT: "#3987e5", wohin.GEPLANT: "#3987e5", wohin.DOPPELT: "#d95926", wohin.SCHON_DA: "#199e70",
        wohin.BLEIBT: "#898781", wohin.OFFEN: "#898781", wohin.FEHLER: "#d03b3b", wohin.ANDERSWO: "#fab219",
        "knoten": "#c3c2b7",
    },
}
# Deckkraft der Baender: normal, hervorgehoben, zurueckgenommen.
DECKKRAFT = (0.42, 0.82, 0.10)
DECKKRAFT_GEPLANT = (0.16, 0.30, 0.06)
ZEICHEN = {wohin.FEHLER: "⚠", wohin.ANDERSWO: "⚠"}


def dunkel(pal: QPalette) -> bool:
    return pal.color(QPalette.ColorRole.Base).lightness() < 128


def farbe(pal: QPalette, schluessel: str) -> QColor:
    return QColor(FARBEN["dunkel" if dunkel(pal) else "hell"][schluessel])


def ordner_oeffnen(pfad: Path) -> None:
    """Einen Ordner im Explorer (Finder, Dateimanager) zeigen."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(pfad)))


def _mit_alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


# ================================================================ Grafik ====


class FlussGrafik(QWidget):
    """Links die Quellordner, rechts die Ordner im Archiv, dazwischen die Baender."""

    band_geklickt = Signal(int)
    knoten_geklickt = Signal(str, int)

    RAND = 12.0        # Luft oben und unten
    LUFT = 8.0         # zwischen Beschriftung und Knoten

    def __init__(self, eltern=None) -> None:
        super().__init__(eltern)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ansicht: wohin.Ansicht | None = None
        self.lage: wohin.Lage | None = None
        self._lage_fuer: tuple | None = None
        self.ueber: tuple[str, int] | None = None     # ("band", i), ("links", i), ("rechts", i)
        self.gewaehlt: int | None = None
        self.leer_text = ""
        self.spalte_links = self.spalte_rechts = 0.0
        self.setFixedHeight(self._hoehe())

    # -- Daten -------------------------------------------------------------

    def setzen(self, ansicht: wohin.Ansicht | None, leer_text: str = "") -> None:
        self.ansicht = ansicht
        self.leer_text = leer_text
        self.gewaehlt = None
        self.ueber = None
        self.lage = None
        self.setFixedHeight(self._hoehe())
        self.update()

    def waehlen(self, band: int | None) -> None:
        self.gewaehlt = band
        self.update()

    def _hoehe(self) -> int:
        if not self.ansicht or not self.ansicht.baender:
            return 160
        zeile = max(wohin.ZEILE, QFontMetrics(self.font()).height() + 2)
        return int(max(420.0, wohin.mindesthoehe(self.ansicht, zeile=zeile) + 2 * self.RAND))

    def sizeHint(self) -> QSize:
        return QSize(900, self._hoehe())

    # -- Lage ----------------------------------------------------------------

    def beschriftung(self, k: wohin.Knoten) -> tuple[str, str]:
        name = f"{ZEICHEN[k.art]} {k.name}" if k.art in ZEICHEN else k.name
        return name, meldungen.anzahl(k.n) + (" ›" if k.tiefer else "")

    LUECKE = 6.0       # Luft in der Spalte: nie auf den Pixel genau

    def _spalte(self, fm: QFontMetrics, knoten: list[wohin.Knoten]) -> float:
        breiteste = 0.0
        for k in knoten:
            name, zahl = self.beschriftung(k)
            breiteste = max(breiteste, fm.horizontalAdvance(name) + fm.horizontalAdvance("  " + zahl) + self.LUECKE)
        return min(breiteste, max(120.0, self.width() * 0.30))

    def text_fuer(self, k: wohin.Knoten, seite: str) -> tuple[str, str]:
        """Was neben einem Knoten steht: der Name - in der Mitte gekuerzt nur,
        wenn er nicht in die Spalte passt - und die Zahl."""
        fm = QFontMetrics(self.font())
        name, zahl = self.beschriftung(k)
        spalte = self.spalte_links if seite == "links" else self.spalte_rechts
        platz = int(max(20.0, spalte - fm.horizontalAdvance("  " + zahl)))
        if fm.horizontalAdvance(name) > platz:
            name = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, platz)
        return name, zahl

    def lage_holen(self) -> wohin.Lage | None:
        if not self.ansicht or not self.ansicht.baender:
            return None
        schluessel = (self.width(), self.height(), id(self.ansicht))
        if self.lage is not None and self._lage_fuer == schluessel:
            return self.lage
        fm = QFontMetrics(self.font())
        self.spalte_links = self._spalte(fm, self.ansicht.links)
        self.spalte_rechts = self._spalte(fm, self.ansicht.rechts)
        x_links = self.spalte_links + self.LUFT + wohin.KNOTEN_BREITE
        x_rechts = self.width() - self.spalte_rechts - self.LUFT - wohin.KNOTEN_BREITE
        zeile = max(wohin.ZEILE, fm.height() + 2)
        self.lage = wohin.lage(self.ansicht, self.width(), self.height() - 2 * self.RAND, x_links, x_rechts, zeile=zeile)
        self._lage_fuer = schluessel
        return self.lage

    def treffer(self, x: float, y: float) -> tuple[str, int] | None:
        """Was liegt unter dem Zeiger (Koordinaten des Widgets)?"""
        lage = self.lage_holen()
        if lage is None:
            return None
        y -= self.RAND
        for seite, knoten in (("links", lage.links), ("rechts", lage.rechts)):
            for i, k in enumerate(knoten):
                oben, unten = min(k.y, k.mitte - wohin.ZEILE / 2), max(k.y + k.h, k.mitte + wohin.ZEILE / 2)
                if seite == "links":
                    links_x, rechts_x = k.x - self.LUFT - self.spalte_links, k.x + k.b + 2
                else:
                    links_x, rechts_x = k.x - 2, k.x + k.b + self.LUFT + self.spalte_rechts
                if links_x <= x <= rechts_x and oben <= y <= unten:
                    return seite, i
        band = wohin.band_bei(lage, x, y)
        return ("band", band) if band is not None else None

    def _hervorgehoben(self) -> set[int] | None:
        if self.ansicht is None:
            return None
        if self.gewaehlt is not None:
            return {self.gewaehlt}
        if self.ueber is None:
            return None
        art, i = self.ueber
        if art == "band":
            return {i}
        return {j for j, b in enumerate(self.ansicht.baender) if (b.links if art == "links" else b.rechts) == i}

    # -- Zeichnen ----------------------------------------------------------------

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(QPalette.ColorRole.Base))
        lage = self.lage_holen()
        if lage is None or self.ansicht is None:
            p.setPen(QColor(stil.gedaempft_farbe(pal)))
            p.drawText(self.rect().adjusted(16, 0, -16, 0), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                       self.leer_text)
            p.end()
            return
        p.translate(0, self.RAND)
        hervor = self._hervorgehoben()
        reihe = [i for i in range(len(lage.baender)) if not hervor or i not in hervor] + sorted(hervor or ())
        for i in reihe:
            self._band(p, pal, i, lage.baender[i], hervor)
        self._knoten(p, pal, lage)
        p.end()

    def _band(self, p: QPainter, pal: QPalette, i: int, b: wohin.BandLage, hervor: set[int] | None) -> None:
        schicksal = self.ansicht.baender[i].schicksal
        stufe = 0 if hervor is None else (1 if i in hervor else 2)
        c = farbe(pal, schicksal)
        # 2 px Luft zwischen den Baendern eines Knotens: jedes Band verliert oben
        # und unten einen Pixel, wenn es dick genug ist.
        rand = 1.0 if (b.y0u - b.y0o) >= 4 else 0.0
        y0o, y0u, y1o, y1u = b.y0o + rand, b.y0u - rand, b.y1o + rand, b.y1u - rand
        dx = b.x1 - b.x0
        weg = QPainterPath(QPointF(b.x0, y0o))
        weg.cubicTo(QPointF(b.x0 + dx / 3, y0o), QPointF(b.x0 + 2 * dx / 3, y1o), QPointF(b.x1, y1o))
        weg.lineTo(QPointF(b.x1, y1u))
        weg.cubicTo(QPointF(b.x0 + 2 * dx / 3, y1u), QPointF(b.x0 + dx / 3, y0u), QPointF(b.x0, y0u))
        weg.closeSubpath()
        if schicksal == wohin.GEPLANT:
            p.fillPath(weg, _mit_alpha(c, DECKKRAFT_GEPLANT[stufe]))
            kante = QPen(_mit_alpha(c, 0.9 if stufe < 2 else 0.25), 1.2)
            p.setPen(kante)
            for (ya, yb) in ((y0o, y1o), (y0u, y1u)):
                linie = QPainterPath(QPointF(b.x0, ya))
                linie.cubicTo(QPointF(b.x0 + dx / 3, ya), QPointF(b.x0 + 2 * dx / 3, yb), QPointF(b.x1, yb))
                p.drawPath(linie)
        else:
            p.fillPath(weg, _mit_alpha(c, DECKKRAFT[stufe]))

    def _knoten(self, p: QPainter, pal: QPalette, lage: wohin.Lage) -> None:
        fm = QFontMetrics(self.font())
        text = pal.color(QPalette.ColorRole.WindowText)
        grau = QColor(stil.gedaempft_farbe(pal))
        p.setPen(Qt.PenStyle.NoPen)
        for seite, knoten, lagen in (("links", self.ansicht.links, lage.links), ("rechts", self.ansicht.rechts, lage.rechts)):
            for i, (k, kl) in enumerate(zip(knoten, lagen)):
                c = farbe(pal, k.art if k.art in wohin.KAESTEN else "knoten")
                if self.ueber == (seite, i):
                    c = c.darker(130) if not dunkel(pal) else c.lighter(130)
                p.setBrush(c)
                h = max(kl.h, 2.0)
                p.drawRoundedRect(QRectF(kl.x, kl.mitte - h / 2 if kl.h < 2 else kl.y, kl.b, h), 2, 2)
                name, zahl = self.text_fuer(k, seite)
                breite = fm.horizontalAdvance(name) + fm.horizontalAdvance("  " + zahl)
                y = kl.mitte + (fm.ascent() - fm.descent()) / 2
                x = kl.x - self.LUFT - breite if seite == "links" else kl.x + kl.b + self.LUFT
                p.setPen(text)
                p.drawText(QPointF(x, y), name)
                p.setPen(grau)
                p.drawText(QPointF(x + fm.horizontalAdvance(name), y), "  " + zahl)
                p.setPen(Qt.PenStyle.NoPen)

    # -- Zeiger --------------------------------------------------------------

    def tipp_text(self, ziel: tuple[str, int] | None) -> str:
        if ziel is None or self.ansicht is None:
            return ""
        art, i = ziel
        if art == "band":
            b = self.ansicht.baender[i]
            return meldungen.wohin_band_text(b.n, b.bytes, self.ansicht.links[b.links].name,
                                             self.ansicht.rechts[b.rechts].name, b.schicksal)
        k = (self.ansicht.links if art == "links" else self.ansicht.rechts)[i]
        name = k.name
        if art == "links" and k.art == wohin.ORDNER and k.schluessel:
            name = str(Path(db.text_pfad(k.schluessel[0]), *k.schluessel[1:]))
        return meldungen.wohin_knoten_text(name, k.n, k.bytes, k.tiefer)

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        ziel = self.treffer(pos.x(), pos.y())
        if ziel != self.ueber:
            self.ueber = ziel
            self.update()
        anklickbar = ziel is not None and (ziel[0] == "band" or self._knoten_von(ziel).tiefer)
        self.setCursor(Qt.CursorShape.PointingHandCursor if anklickbar else Qt.CursorShape.ArrowCursor)
        text = self.tipp_text(ziel)
        if text:
            QToolTip.showText(ev.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()

    def _knoten_von(self, ziel: tuple[str, int]) -> wohin.Knoten:
        return (self.ansicht.links if ziel[0] == "links" else self.ansicht.rechts)[ziel[1]]

    def leaveEvent(self, _ev) -> None:
        self.ueber = None
        QToolTip.hideText()
        self.update()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.position()
        ziel = self.treffer(pos.x(), pos.y())
        if ziel is None:
            return
        if ziel[0] == "band":
            self.band_geklickt.emit(ziel[1])
        else:
            self.knoten_geklickt.emit(ziel[0], ziel[1])


# ===================================================== Balken fuer die Uebersicht ====


class Segmentbalken(QWidget):
    """Ein Ganzes in Teilen: schmal (8 px), runde Enden, 2 px Luft zwischen den
    Teilen, keine Schrift - die Zahlen stehen in der Legende darunter."""

    def __init__(self, eltern=None) -> None:
        super().__init__(eltern)
        self.teile: list[tuple[str, int]] = []
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setzen(self, teile: list[tuple[str, int]]) -> None:
        self.teile = [(s, n) for s, n in teile if n > 0]
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        gesamt = sum(n for _s, n in self.teile)
        if not gesamt:
            p.end()
            return
        luft = 2.0
        breite = self.width() - luft * (len(self.teile) - 1)
        x = 0.0
        for s, n in self.teile:
            w = max(2.0, breite * n / gesamt)
            r = QRectF(x, 0, w, self.height())
            c = farbe(pal, s)
            if s == wohin.GEPLANT:
                p.setBrush(_mit_alpha(c, 0.25))
                p.setPen(QPen(c, 1))
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(r, 4, 4)
            x += w + luft
        p.end()


class Farbmarke(QWidget):
    """Die Farbe eines Schicksals neben seinem Namen (Legende)."""

    def __init__(self, schicksal: str, eltern=None) -> None:
        super().__init__(eltern)
        self.schicksal = schicksal
        self.setFixedSize(12, 12)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = farbe(self.palette(), self.schicksal)
        r = QRectF(0.5, 0.5, 11, 11)
        if self.schicksal == wohin.GEPLANT:
            p.setBrush(_mit_alpha(c, 0.25))
            p.setPen(QPen(c, 1))
        else:
            p.setBrush(c)
            p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 3, 3)
        p.end()


def legende_eintrag(schicksal: str, text: str) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(Farbmarke(schicksal))
    name = f"{ZEICHEN[schicksal]} {text}" if schicksal in ZEICHEN else text
    lay.addWidget(QLabel(name))
    return w


class WohinBalken(QFrame):
    """In der Uebersicht (Reiter „Archiv“): Wohin kam was - Balken, Legende mit
    Zahlen und der Weg zum Reiter „Wohin?“."""

    genauer = Signal()

    def __init__(self, eltern=None) -> None:
        super().__init__(eltern)
        self.setMaximumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        kopf = QHBoxLayout()
        titel = QLabel(meldungen.WOHIN_BALKEN_TITEL)
        titel.setProperty("klasse", "kicker")
        kopf.addWidget(titel)
        kopf.addStretch(1)
        self.knopf = QPushButton(meldungen.WOHIN_GENAUER)
        self.knopf.setProperty("klasse", "ghost")
        self.knopf.setFlat(True)
        self.knopf.setAutoDefault(False)
        self.knopf.clicked.connect(self.genauer.emit)
        kopf.addWidget(self.knopf)
        lay.addLayout(kopf)
        self.balken = Segmentbalken()
        lay.addWidget(self.balken)
        self.legende = QVBoxLayout()
        self.legende.setSpacing(4)
        lay.addLayout(self.legende)
        self.zeilen: list[tuple[str, int]] = []
        self.hide()

    def setzen(self, daten: wohin.Daten | None) -> None:
        while self.legende.count():
            e = self.legende.takeAt(0)
            if e.widget() is not None:
                e.widget().deleteLater()
        if daten is None or not daten.n:
            self.zeilen = []
            self.hide()
            return
        self.zeilen = [(s, daten.je_schicksal.get(s, 0)) for s in wohin.SCHICKSALE if daten.je_schicksal.get(s, 0)]
        self.balken.setzen(self.zeilen)
        for s, n in self.zeilen:
            zeile = QHBoxLayout()
            zeile.addWidget(legende_eintrag(s, meldungen.WOHIN_SCHICKSAL[s]))
            zeile.addStretch(1)
            wert = QLabel(meldungen.anzahl(n))
            wert.setProperty("klasse", "zaehler-wert")
            zeile.addWidget(wert)
            halter = QWidget()
            halter.setLayout(zeile)
            zeile.setContentsMargins(0, 0, 0, 0)
            self.legende.addWidget(halter)
        self.show()


# ========================================================== Tabellen ====


class _ZahlItem(QTableWidgetItem):
    """Zelle mit einer Zahl: angezeigt mit Tausenderpunkt, sortiert nach Wert."""

    def __init__(self, wert: int, text: str) -> None:
        super().__init__(text)
        self.wert = wert
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, anderes) -> bool:
        if isinstance(anderes, _ZahlItem):
            return self.wert < anderes.wert
        return super().__lt__(anderes)


def _tabelle(spalten: tuple[str, ...], dehnen: tuple[int, ...] = (0,)) -> QTableWidget:
    """Schlichte Tabelle: ganze Zeilen waehlen, nichts bearbeiten; die Spalten
    in dehnen teilen sich den freien Platz und kuerzen lange Pfade in der Mitte."""
    t = QTableWidget(0, len(spalten))
    t.setHorizontalHeaderLabels(list(spalten))
    t.verticalHeader().hide()
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setWordWrap(False)
    t.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    kopf = t.horizontalHeader()
    kopf.setStretchLastSection(False)
    kopf.setMinimumSectionSize(60)
    for i in range(len(spalten)):
        kopf.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    for i in dehnen:
        kopf.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
    return t


# ============================================================ Die Seite ====


class WohinSeite(QWidget):
    """Der Reiter „Wohin?“. fenster ist das Hauptfenster (Ablauf: fenster.ab)."""

    def __init__(self, fenster) -> None:
        super().__init__()
        self.f = fenster
        self.daten: wohin.Daten | None = None
        self.ansicht: wohin.Ansicht | None = None
        self.links: tuple[str, ...] = ()
        self.rechts: tuple[str, ...] = ()
        self.band: int | None = None
        self.band_liste: list[wohin.Datei] = []
        self.treffer_liste: list[wohin.Datei] = []

        aussen = QVBoxLayout(self)
        aussen.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        aussen.addWidget(self.scroll)
        inhalt = QWidget()
        self.scroll.setWidget(inhalt)
        lay = QVBoxLayout(inhalt)
        lay.setContentsMargins(40, 24, 40, 24)
        lay.setSpacing(16)

        self.titel = QLabel(meldungen.WOHIN_TITEL)
        self.titel.setProperty("klasse", "seitentitel")
        lay.addWidget(self.titel)
        self.stand = QLabel("")
        self.stand.setProperty("klasse", "hinweis")
        self.stand.setWordWrap(True)
        lay.addWidget(self.stand)
        self.laeuft = QLabel(meldungen.WOHIN_LAEUFT)
        self.laeuft.setProperty("klasse", "hinweis")
        self.laeuft.setWordWrap(True)
        self.laeuft.hide()
        lay.addWidget(self.laeuft)

        self.kennzahlen = QHBoxLayout()
        self.kennzahlen.setSpacing(32)
        self.kachel: dict[str, QLabel] = {}
        self.kachel_rahmen: dict[str, QWidget] = {}
        for schluessel, text in meldungen.WOHIN_KENNZAHLEN:
            rahmen = QWidget()
            k = QVBoxLayout(rahmen)
            k.setContentsMargins(0, 0, 0, 0)
            k.setSpacing(2)
            name = QLabel(text)
            name.setProperty("klasse", "zaehler-name")
            wert = QLabel("0")
            wert.setProperty("klasse", "kennzahl-gross")
            k.addWidget(name)
            k.addWidget(wert)
            self.kachel[schluessel] = wert
            self.kachel_rahmen[schluessel] = rahmen
            self.kennzahlen.addWidget(rahmen)
        self.kennzahlen.addStretch(1)
        lay.addLayout(self.kennzahlen)

        self.legende = QHBoxLayout()
        self.legende.setSpacing(18)
        lay.addLayout(self.legende)

        pfadzeile = QHBoxLayout()
        self.pfad_links = QLabel("")
        self.pfad_links.setTextFormat(Qt.TextFormat.RichText)
        self.pfad_links.linkActivated.connect(lambda ziel: self.pfad_klick("links", int(ziel)))
        self.pfad_rechts = QLabel("")
        self.pfad_rechts.setTextFormat(Qt.TextFormat.RichText)
        self.pfad_rechts.linkActivated.connect(lambda ziel: self.pfad_klick("rechts", int(ziel)))
        pfadzeile.addWidget(self.pfad_links)
        pfadzeile.addStretch(1)
        pfadzeile.addWidget(self.pfad_rechts)
        lay.addLayout(pfadzeile)

        karte = QFrame()
        karte.setProperty("klasse", "card")
        kl = QVBoxLayout(karte)
        kl.setContentsMargins(8, 8, 8, 8)
        self.grafik = FlussGrafik()
        self.grafik.band_geklickt.connect(self.band_waehlen)
        self.grafik.knoten_geklickt.connect(self.knoten_klick)
        kl.addWidget(self.grafik)
        lay.addWidget(karte)
        hilfe = QLabel(meldungen.WOHIN_HILFE)
        hilfe.setProperty("klasse", "hinweis")
        hilfe.setWordWrap(True)
        lay.addWidget(hilfe)

        # Das gewaehlte Band: seine Dateien
        self.band_karte = QFrame()
        self.band_karte.setProperty("klasse", "card")
        bl = QVBoxLayout(self.band_karte)
        bl.setContentsMargins(16, 12, 16, 12)
        self.band_titel = QLabel("")
        self.band_titel.setProperty("klasse", "titel")
        self.band_titel.setWordWrap(True)
        bl.addWidget(self.band_titel)
        self.band_tabelle = _tabelle(meldungen.WOHIN_DATEI_SPALTEN, dehnen=(1, 2))
        self.band_tabelle.setMinimumHeight(200)
        bl.addWidget(self.band_tabelle)
        self.band_hinweis = QLabel("")
        self.band_hinweis.setProperty("klasse", "hinweis")
        bl.addWidget(self.band_hinweis)
        knoepfe = QHBoxLayout()
        self.k_archiv = QPushButton(meldungen.WOHIN_ORDNER_OEFFNEN)
        self.k_archiv.clicked.connect(lambda: self._oeffnen("rechts"))
        self.k_quelle = QPushButton(meldungen.WOHIN_QUELLE_OEFFNEN)
        self.k_quelle.clicked.connect(lambda: self._oeffnen("links"))
        self.k_sichten = QPushButton(meldungen.WOHIN_IN_SICHTEN)
        self.k_sichten.clicked.connect(self._in_sichten)
        self.k_weg = QPushButton(meldungen.WOHIN_AUSWAHL_WEG)
        self.k_weg.clicked.connect(lambda: self.band_waehlen(None))
        for k in (self.k_archiv, self.k_quelle, self.k_sichten):
            knoepfe.addWidget(k)
        knoepfe.addStretch(1)
        knoepfe.addWidget(self.k_weg)
        bl.addLayout(knoepfe)
        self.band_karte.hide()
        lay.addWidget(self.band_karte)

        # Dieselben Stroeme als Tabelle
        self.tabelle = _tabelle(meldungen.WOHIN_SPALTEN)
        self.tabelle.setSortingEnabled(True)
        self.tabelle.setMinimumHeight(220)
        self.tabelle.itemSelectionChanged.connect(self._tabelle_gewaehlt)
        lay.addWidget(self.tabelle)

        # Datei suchen
        such = QLabel(meldungen.WOHIN_SUCHEN)
        such.setProperty("klasse", "titel")
        lay.addWidget(such)
        self.suche = QLineEdit()
        self.suche.setPlaceholderText(meldungen.WOHIN_SUCHEN_HINWEIS)
        self.suche.returnPressed.connect(lambda: self.suchen(self.suche.text()))
        lay.addWidget(self.suche)
        self.treffer_info = QLabel("")
        self.treffer_info.setProperty("klasse", "hinweis")
        lay.addWidget(self.treffer_info)
        self.treffer = _tabelle(meldungen.WOHIN_DATEI_SPALTEN, dehnen=(1, 2))
        self.treffer.setMinimumHeight(160)
        self.treffer.hide()
        lay.addWidget(self.treffer)
        lay.addStretch(1)

    # -- Laden -------------------------------------------------------------

    def aktualisieren(self) -> None:
        """Neu aus dem Archiv lesen (zwischengespeichert im Ablauf). Laeuft ein
        Schritt, bleibt der letzte Stand stehen - mit Hinweis."""
        try:
            daten = self.f.ab.wohin_lesen()
        except FotosortFehler as fehler:
            if str(fehler) == meldungen.ob_datenbank_belegt():
                self.schritt_laeuft()
                return
            self._ohne_daten(str(fehler) if self.f.ab.ziel else meldungen.WOHIN_KEIN_ARCHIV)
            return
        except (OSError, sqlite3.Error) as fehler:
            self._ohne_daten(meldungen.wohin_lesefehler(fehler))
            return
        self.laeuft.hide()
        if self.daten is not None and daten.ziel != self.daten.ziel:
            self.links, self.rechts = (), ()
        self.daten = daten
        self._zeigen()

    def schritt_laeuft(self) -> None:
        """Ein Schritt laeuft: der letzte Stand bleibt stehen, mit Hinweis."""
        self.laeuft.show()
        if self.daten is None:
            self.grafik.setzen(None, meldungen.WOHIN_LAEUFT)

    def _ohne_daten(self, text: str) -> None:
        self.daten = None
        self.links, self.rechts = (), ()
        self.laeuft.hide()
        self.stand.setText(text)
        self._zeigen(text)

    def _zeigen(self, leer_text: str = "") -> None:
        d = self.daten
        if d is None:
            self.ansicht = None
            self.grafik.setzen(None, leer_text or meldungen.WOHIN_KEIN_ARCHIV)
            self._kennzahlen(None)
            self._legende(None)
            self._tabelle_fuellen()
            self._pfade()
            self.band_waehlen(None)
            return
        self.stand.setText(meldungen.WOHIN_STAND[d.stand])
        self.ansicht = wohin.ansicht(d, self.links, self.rechts)
        if not self.ansicht.baender and (self.links or self.rechts):
            self.links, self.rechts = (), ()          # Ordner gibt es nicht mehr
            self.ansicht = wohin.ansicht(d, (), ())
        self.grafik.setzen(self.ansicht, meldungen.WOHIN_STAND["leer"])
        self._kennzahlen(d)
        self._legende(d)
        self._tabelle_fuellen()
        self._pfade()
        self.band_waehlen(None)

    def _kennzahlen(self, d: wohin.Daten | None) -> None:
        je = d.je_schicksal if d is not None else {}
        werte = {"gesamt": d.n if d is not None else 0, "kopiert": je.get(wohin.KOPIERT, 0),
                 "geplant": je.get(wohin.GEPLANT, 0), "doppelt": je.get(wohin.DOPPELT, 0),
                 "schon_da": je.get(wohin.SCHON_DA, 0), "fehler": je.get(wohin.FEHLER, 0)}
        for schluessel, w in self.kachel.items():
            w.setText(meldungen.anzahl(werte[schluessel]))
        # "Geplant" nur, solange etwas geplant ist.
        self.kachel_rahmen["geplant"].setVisible(bool(werte["geplant"]))

    def _legende(self, d: wohin.Daten | None) -> None:
        while self.legende.count():
            e = self.legende.takeAt(0)
            if e.widget() is not None:
                e.widget().deleteLater()
        if d is None:
            return
        for s in wohin.SCHICKSALE:
            if d.je_schicksal.get(s, 0):
                self.legende.addWidget(legende_eintrag(s, meldungen.WOHIN_SCHICKSAL[s]))
        self.legende.addStretch(1)

    def _pfade(self) -> None:
        def zeile(wurzel_text: str, weg: tuple[str, ...], seite: str) -> str:
            teile = [f'<a href="0">{html.escape(wurzel_text)}</a>' if weg else html.escape(wurzel_text)]
            for i, teil in enumerate(weg, start=1):
                if seite == "links" and i == 1:
                    name = Path(db.text_pfad(teil)).name or db.text_pfad(teil)
                else:
                    name = teil
                teile.append(f'<a href="{i}">{html.escape(name)}</a>' if i < len(weg) else html.escape(name))
            return " › ".join(teile)
        self.pfad_links.setText(zeile(meldungen.WOHIN_QUELLEN, self.links, "links"))
        self.pfad_rechts.setText(zeile(meldungen.WOHIN_ARCHIV, self.rechts, "rechts"))

    def _tabelle_fuellen(self) -> None:
        t = self.tabelle
        t.blockSignals(True)
        t.setSortingEnabled(False)
        t.setRowCount(0)
        a = self.ansicht
        if a is not None:
            t.setRowCount(len(a.baender))
            for zeile, b in enumerate(a.baender):
                von = QTableWidgetItem(a.links[b.links].name)
                von.setData(Qt.ItemDataRole.UserRole, zeile)
                t.setItem(zeile, 0, von)
                t.setItem(zeile, 1, QTableWidgetItem(a.rechts[b.rechts].name))
                t.setItem(zeile, 2, QTableWidgetItem(meldungen.WOHIN_SCHICKSAL[b.schicksal]))
                t.setItem(zeile, 3, _ZahlItem(b.n, meldungen.anzahl(b.n)))
                t.setItem(zeile, 4, _ZahlItem(b.bytes, meldungen.groesse(b.bytes)))
        t.setSortingEnabled(True)
        t.blockSignals(False)

    # -- Bedienen ------------------------------------------------------------

    def knoten_klick(self, seite: str, i: int) -> None:
        if self.ansicht is None:
            return
        k = (self.ansicht.links if seite == "links" else self.ansicht.rechts)[i]
        if k.art != wohin.ORDNER or not k.tiefer or k.schluessel is None:
            return
        if seite == "links":
            self.links = k.schluessel
        else:
            self.rechts = k.schluessel
        self._zeigen()

    def pfad_klick(self, seite: str, tiefe: int) -> None:
        if seite == "links":
            self.links = self.links[:tiefe]
        else:
            self.rechts = self.rechts[:tiefe]
        self._zeigen()

    def band_waehlen(self, band: int | None) -> None:
        self.band = band
        self.grafik.waehlen(band)
        if band is None or self.ansicht is None:
            self.band_karte.hide()
            self.tabelle.blockSignals(True)
            self.tabelle.clearSelection()
            self.tabelle.blockSignals(False)
            return
        a = self.ansicht
        b = a.baender[band]
        self.band_titel.setText(meldungen.wohin_band_titel(a.links[b.links].name, a.rechts[b.rechts].name,
                                                           b.schicksal, b.n))
        try:
            dateien, gesamt = self.f.ab.wohin_band(a, band)
        except FotosortFehler as fehler:
            dateien, gesamt = [], 0
            self.band_hinweis.setText(str(fehler))
        else:
            self.band_hinweis.setText(meldungen.wohin_liste_gekuerzt(len(dateien), gesamt) if gesamt > len(dateien) else "")
        self.band_liste = dateien
        self._dateien_zeigen(self.band_tabelle, dateien)
        self.k_archiv.setEnabled(self._ordner("rechts") is not None)
        self.k_sichten.setEnabled(self._ordner("rechts") is not None)
        self.k_quelle.setEnabled(self._ordner("links") is not None)
        self.band_karte.show()
        # Die Tabelle zeigt dasselbe Band.
        t = self.tabelle
        t.blockSignals(True)
        for zeile in range(t.rowCount()):
            if t.item(zeile, 0).data(Qt.ItemDataRole.UserRole) == band:
                t.selectRow(zeile)
                break
        t.blockSignals(False)

    def _tabelle_gewaehlt(self) -> None:
        zeilen = self.tabelle.selectionModel().selectedRows()
        if not zeilen:
            return
        band = self.tabelle.item(zeilen[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if band is not None and band != self.band:
            self.band_waehlen(int(band))

    def _dateien_zeigen(self, tabelle: QTableWidget, dateien: list[wohin.Datei]) -> None:
        """Eine Zeile je Datei: Name, Quellordner, Ort im Archiv (ab dem
        Archivordner), was passiert. Die ganzen Pfade stehen im Hinweis."""
        basis = Path(db.text_pfad(self.daten.ziel)) if self.daten is not None else None
        tabelle.setRowCount(len(dateien))
        for zeile, x in enumerate(dateien):
            text = meldungen.WOHIN_SCHICKSAL[x.schicksal] + (f" – {x.grund}" if x.grund else "")
            im_archiv = x.ziel
            if x.ziel and basis is not None:
                try:
                    im_archiv = str(Path(x.ziel).relative_to(basis))
                except ValueError:
                    im_archiv = x.ziel           # liegt anderswo: ganzer Pfad
            for spalte, (wert, tipp) in enumerate(((Path(x.quelle).name, x.quelle), (str(Path(x.quelle).parent), x.quelle),
                                                   (im_archiv, x.ziel), (text, text))):
                item = QTableWidgetItem(wert)
                item.setToolTip(tipp)
                tabelle.setItem(zeile, spalte, item)

    def _ordner(self, seite: str) -> Path | None:
        """Der Ordner hinter dem gewaehlten Band: rechts im Archiv, links in der Quelle."""
        if self.ansicht is None or self.band is None or self.daten is None:
            return None
        a = self.ansicht
        b = a.baender[self.band]
        if seite == "rechts":
            k = a.rechts[b.rechts]
            if k.art in wohin.KAESTEN:
                return None
            weg = k.schluessel if k.art == wohin.ORDNER else a.pfad_rechts
            return Path(db.text_pfad(self.daten.ziel), *weg)
        k = a.links[b.links]
        weg = k.schluessel if k.art == wohin.ORDNER else a.pfad_links
        if not weg:
            return None
        return Path(db.text_pfad(weg[0]), *weg[1:])

    def _oeffnen(self, seite: str) -> None:
        pfad = self._ordner(seite)
        if pfad is not None:
            ordner_oeffnen(pfad)

    def _in_sichten(self) -> None:
        pfad = self._ordner("rechts")
        if pfad is not None:
            self.f.sichten_ordner_zeigen(pfad)

    def suchen(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.treffer.hide()
            self.treffer_info.setText("")
            return
        try:
            dateien, gesamt = self.f.ab.wohin_suchen(text)
        except FotosortFehler as fehler:
            self.treffer_info.setText(str(fehler))
            self.treffer.hide()
            return
        self.treffer_liste = dateien
        self.treffer_info.setText(meldungen.wohin_treffer(len(dateien), gesamt))
        self._dateien_zeigen(self.treffer, dateien)
        self.treffer.setVisible(bool(dateien))
