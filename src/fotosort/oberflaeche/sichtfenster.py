"""Reiter „Sichten“ im Desktop-Fenster (SPEC §8 seit v0.8, Ausbau v0.11).

Links die Ordner des Archivs (neueste zuerst, erst beim Aufklappen gelesen),
rechts die Bilder des gewaehlten Ordners als Vorschau; Eingabe oeffnet die
grosse Ansicht (mit Kameradaten), Z oder ein Klick zeigt dort das Bild in
voller Groesse (Lupe), C vergleicht zwei bis vier gewaehlte Bilder. Tasten
0-5 vergeben Sterne, P/X/U markieren, 6-9 setzen eine Farbe - fuer alle
gewaehlten Bilder; dasselbe geht ueber die Knopfleiste. Die Bewertungen
stehen in bewertungen.db (sichten.py); vorhandene XMP-Dateien werden gelesen.

Das Fenster liest die Bilder nur. Es veraendert, verschiebt und loescht
nichts - Ausschuss ist eine Markierung, keine Anweisung. Einzige Ausnahme:
der Knopf „XMP-Dateien anlegen…“ (nach Rueckfrage, nur neue Dateien,
sichten.xmp_anlegen). Vorschaubilder entstehen im Speicher und werden im
lokalen Archiv-Ordner zwischengespeichert, nie im Archiv. Gelesen wird im
Hintergrund (hoechstens LESER Dateien gleichzeitig - eine Festplatte liest
mit vielen Lesern nur langsamer), die Oberflaeche bleibt bedienbar; die
Nachbarn des grossen Bilds werden vorab geladen.
"""

from __future__ import annotations

import contextlib
import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QImageReader, QPainter, QPalette, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QListView, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import FotosortFehler, dateitypen, hashes, meldungen, pfade, sichten, vorschau

KACHEL = 180          # Kantenlaenge der Vorschaubilder in Pixeln
GROSS = 2560          # groesste Kante in der grossen Ansicht
LESER = 3             # gleichzeitig gelesene Dateien auf Festplatte und Netzlaufwerk
VORAB = 2             # so viele Bilder vor und hinter dem grossen Bild vorab laden
ZWISCHENSPEICHER = 8  # so viele grosse Bilder im Speicher behalten
VERGLEICH_HOECHSTENS = 4
ZWISCHENORDNER = "vorschau"   # im lokalen Archiv-Ordner, nie im Archiv

# Arten einer Ladeanfrage
KLEIN, GROSS_ART, VOLL = 0, 1, 2


def leser_fuer(laufwerksart: str) -> int:
    """Auf einer SSD liest und rechnet jeder Kern ein Vorschaubild (seit v0.9);
    eine Festplatte liest mit vielen Lesern nur langsamer."""
    if laufwerksart == "ssd":
        return max(LESER, os.cpu_count() or 1)
    return LESER
ROLLE_NR = Qt.ItemDataRole.UserRole
ROLLE_PFAD = Qt.ItemDataRole.UserRole + 1

#: EXIF-Drehung (1-8) als Folge einfacher Abbildungen - wie
#: QImageReader.setAutoTransform. Nur Spiegeln und Vierteldrehungen: Qt
#: rechnet sie verlustfrei und im Format des Bilds (5 und 7 sind eine
#: Drehung mit anschliessendem Spiegeln).
_RECHTS = QTransform(0, 1, -1, 0, 0, 0)          # 90 Grad im Uhrzeigersinn
_LINKS = QTransform(0, -1, 1, 0, 0, 0)
_WAAGRECHT = QTransform(-1, 0, 0, 1, 0, 0)       # links und rechts tauschen
_SENKRECHT = QTransform(1, 0, 0, -1, 0, 0)
_DREHUNG: dict[int, tuple[QTransform, ...]] = {
    2: (_WAAGRECHT,), 3: (QTransform(-1, 0, 0, -1, 0, 0),), 4: (_SENKRECHT,),
    5: (_RECHTS, _WAAGRECHT), 6: (_RECHTS,), 7: (_RECHTS, _SENKRECHT), 8: (_LINKS,),
}


def gedreht(bild: QImage, drehung: int) -> QImage:
    for t in _DREHUNG.get(drehung, ()):
        bild = bild.transformed(t)
    return bild


def aus_daten(daten: bytes, groesse: int, drehung: int | None = None) -> QImage | None:
    """JPEG/PNG/... aus dem Speicher, verkleinert auf groesse. drehung None:
    die Drehung aus der Datei selbst (EXIF) anwenden."""
    ba = QByteArray(daten)
    puffer = QBuffer(ba)
    puffer.open(QIODevice.OpenModeFlag.ReadOnly)
    leser = QImageReader(puffer)
    leser.setAutoTransform(drehung is None)
    masse = leser.size()
    if groesse and masse.isValid() and max(masse.width(), masse.height()) > groesse:
        masse.scale(groesse, groesse, Qt.AspectRatioMode.KeepAspectRatio)
        leser.setScaledSize(masse)
    bild = leser.read()
    puffer.close()
    if bild.isNull():
        return None
    return gedreht(bild, drehung) if drehung else bild


def bild_laden(b: sichten.Bild, groesse: int, leser: vorschau.Vorschauleser | None, gross: bool = False) -> QImage | None:
    """Das Bild lesen (nur lesen) und verkleinern; None, wenn es nicht geht."""
    if b.art == dateitypen.VIDEO:
        return None
    if b.anzeige.suffix.lower().lstrip(".") in sichten.QT_LESBAR:
        try:
            with open(pfade.lang(b.anzeige), "rb") as f:
                daten = f.read()
        except OSError:
            return None
        return aus_daten(daten, groesse)
    if leser is None:
        return None
    daten, drehung = leser.lesen(b.anzeige, gross=gross)
    return aus_daten(daten, groesse, drehung) if daten else None


class _Signale(QObject):
    fertig = Signal(int, int, int, QImage)   # Durchgang, Nummer des Bilds, Art (KLEIN/GROSS_ART/VOLL), Bild
    daten = Signal(int, int, str)            # Durchgang, Nummer, Kameradaten als Text


def zwischen_datei(ordner: Path | None, b: sichten.Bild) -> Path | None:
    """Wo das Vorschaubild dieses Bilds zwischengespeichert wird: im lokalen
    Archiv-Ordner, benannt nach Schluessel, Groesse und Aenderungszeit - eine
    veraenderte Datei bekommt also ein neues. Endung ".vorschau", damit es nie
    als Foto zaehlt (Archiv verwerfen prueft auf Fotos)."""
    if ordner is None:
        return None
    try:
        st = os.stat(pfade.lang(b.anzeige))
    except OSError:
        return None
    h = hashes._neuer_hash()
    h.update(f"{b.schluessel}|{st.st_size}|{st.st_mtime_ns}|{KACHEL}".encode("utf-8"))
    name = h.hexdigest()
    return Path(ordner) / name[:2] / f"{name}.vorschau"


def _zwischen_lesen(datei: Path) -> QImage | None:
    bild = QImage()
    if datei.is_file() and bild.load(str(pfade.lang(datei)), "JPG") and not bild.isNull():
        return bild
    return None


def _zwischen_schreiben(datei: Path, bild: QImage) -> None:
    """Exklusiv anlegen und nie ueberschreibend umbenennen - wie ueberall.
    Scheitert etwas, gibt es eben keinen Zwischenspeicher."""
    with contextlib.suppress(OSError):
        datei.parent.mkdir(parents=True, exist_ok=True)
        ba = QByteArray()
        puffer = QBuffer(ba)
        puffer.open(QIODevice.OpenModeFlag.WriteOnly)
        bild.save(puffer, "JPG", 85)
        puffer.close()
        part = datei.with_name(f"{datei.name}.{os.getpid()}.{id(bild)}.part")
        with open(pfade.lang(part), "xb") as f:
            f.write(bytes(ba.data()))
        try:
            pfade.umbenennen_ohne_ueberschreiben(part, datei)
        except OSError:
            pfade.lang(part).unlink()


class _Laden(QRunnable):
    def __init__(self, signale: _Signale, durchgang: int, nr: int, b: sichten.Bild, groesse: int,
                 leser: vorschau.Vorschauleser | None, art: int, zwischen: Path | None = None) -> None:
        super().__init__()
        self.signale, self.durchgang, self.nr, self.b = signale, durchgang, nr, b
        self.groesse, self.leser, self.art, self.zwischen = groesse, leser, art, zwischen

    def run(self) -> None:
        datei = zwischen_datei(self.zwischen, self.b) if self.art == KLEIN else None
        bild = _zwischen_lesen(datei) if datei is not None else None
        if bild is None:
            try:
                bild = bild_laden(self.b, self.groesse, self.leser, self.art != KLEIN)
            except Exception:   # noqa: BLE001 - eine unlesbare Datei ist nur "keine Vorschau"
                bild = None
            if bild is not None and datei is not None:
                _zwischen_schreiben(datei, bild)
        try:
            self.signale.fertig.emit(self.durchgang, self.nr, self.art, bild if bild is not None else QImage())
        except RuntimeError:
            pass   # Fenster inzwischen geschlossen


class _Daten(QRunnable):
    """Kameradaten (Blende, Zeit, ISO ...) im Hintergrund lesen."""

    def __init__(self, signale: _Signale, durchgang: int, nr: int, b: sichten.Bild, leser: vorschau.Vorschauleser) -> None:
        super().__init__()
        self.signale, self.durchgang, self.nr, self.b, self.leser = signale, durchgang, nr, b, leser

    def run(self) -> None:
        try:
            text = meldungen.sichten_kameradaten(self.leser.kameradaten(self.b.anzeige))
        except Exception:   # noqa: BLE001 - ohne Kameradaten geht es auch
            text = ""
        try:
            self.signale.daten.emit(self.durchgang, self.nr, text)
        except RuntimeError:
            pass


def _platzhalter(text: str) -> QIcon:
    pm = QPixmap(KACHEL, KACHEL)
    pal = QApplication.palette()
    pm.fill(pal.color(QPalette.ColorRole.Base))
    maler = QPainter(pm)
    maler.setPen(pal.color(QPalette.ColorRole.Text))
    maler.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
    maler.end()
    return QIcon(pm)


# Gruen und Rot von Windows, lesbar auf hellem und dunklem Grund.
FARBE_MARKIERUNG = {"auswahl": "#2e9e44", "ausschuss": "#d13438"}
#: Farbmarken, wie Windows und Lightroom sie zeigen.
FARBE_MARKE = {"rot": "#e81123", "gelb": "#ffb900", "gruen": "#10893e", "blau": "#0078d4", "lila": "#8764b8"}
#: Tasten fuer Farben wie in Lightroom (Lila nur ueber den Knopf).
FARBE_TASTE = {"6": "rot", "7": "gelb", "8": "gruen", "9": "blau"}


def _abgeblendet(pm: QPixmap) -> QPixmap:
    neu = QPixmap(pm.size())
    neu.fill(Qt.GlobalColor.transparent)
    maler = QPainter(neu)
    maler.setOpacity(0.35)
    maler.drawPixmap(0, 0, pm)
    maler.end()
    return neu


def _mit_farbe(pm: QPixmap, farbe: str) -> QPixmap:
    """Die Farbmarke als Punkt oben rechts auf dem Vorschaubild."""
    if farbe not in FARBE_MARKE:
        return pm
    neu = QPixmap(pm)
    maler = QPainter(neu)
    maler.setRenderHint(QPainter.RenderHint.Antialiasing)
    maler.setPen(QPen(QColor("#ffffff"), 2))
    maler.setBrush(QColor(FARBE_MARKE[farbe]))
    r = max(6, pm.width() // 14)
    maler.drawEllipse(QPointF(pm.width() - r - 4, r + 4), r, r)
    maler.end()
    return neu


def _farbpunkt(farbe: str, groesse: int = 14) -> QIcon:
    pm = QPixmap(groesse, groesse)
    pm.fill(Qt.GlobalColor.transparent)
    maler = QPainter(pm)
    maler.setRenderHint(QPainter.RenderHint.Antialiasing)
    maler.setBrush(QColor(FARBE_MARKE[farbe]))
    maler.setPen(Qt.PenStyle.NoPen)
    maler.drawEllipse(QRectF(1, 1, groesse - 2, groesse - 2))
    maler.end()
    return QIcon(pm)


def _sterne(n: int) -> str:
    return "★" * n + "☆" * (5 - n)


def _beschriftung(b: sichten.Bild, bew: sichten.Bewertung) -> str:
    zusatz = [x for x in (meldungen.SICHTEN_MARKIERUNG[bew.markierung], meldungen.SICHTEN_FARBE.get(bew.farbe, "")) if x]
    return _sterne(bew.sterne) + (", " + ", ".join(zusatz) if zusatz else "")
class _Raster(QListWidget):
    """Die Vorschaubilder. Bewertungstasten gehen an die Seite."""

    def __init__(self, seite: "SichtenSeite") -> None:
        super().__init__()
        self.seite = seite
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(KACHEL, KACHEL))
        self.setGridSize(QSize(KACHEL + 24, KACHEL + 52))
        self.setWordWrap(True)
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.itemActivated.connect(lambda _i: self.seite.gross_zeigen())

    def keyPressEvent(self, ev) -> None:
        if self.seite.taste(ev.key(), ev.text()):
            ev.accept()
            return
        super().keyPressEvent(ev)


class _Gross(QWidget):
    """Ein Bild gross: eingepasst, oder mit der Lupe in voller Groesse (Z oder
    ein Klick; mit gedrueckter Maustaste verschieben). Die Lupe braucht das
    Bild in voller Aufloesung - es wird nachgeladen (seite.voll_laden)."""

    def __init__(self, seite: "SichtenSeite", aktiv_bei_klick=None) -> None:
        super().__init__()
        self.seite = seite
        self.bild: QImage | None = None
        self.voll: QImage | None = None     # volle Aufloesung, sobald da
        self.text = ""
        self.lupe = False
        self.mitte = QPointF(0.5, 0.5)       # Bildstelle (Anteil) in der Fenstermitte
        self.aktiv = False
        self._ziehen: QPointF | None = None
        self._gezogen = False
        self._aktiv_bei_klick = aktiv_bei_klick
        self.setProperty("klasse", "sicht-gross")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(160, 160)

    def zeigen(self, bild: QImage | None, text: str = "") -> None:
        self.bild, self.voll, self.text = bild, None, text
        self.lupe = False
        self.mitte = QPointF(0.5, 0.5)
        self.update()

    def voll_setzen(self, bild: QImage | None) -> None:
        self.voll = bild
        self.update()

    def lupe_umschalten(self, stelle: QPointF | None = None) -> None:
        if self.bild is None:
            return
        self.lupe = not self.lupe
        if self.lupe:
            if stelle is not None:
                r = self._eingepasst()
                if r.width() > 0 and r.height() > 0:
                    self.mitte = QPointF(min(1.0, max(0.0, (stelle.x() - r.x()) / r.width())),
                                         min(1.0, max(0.0, (stelle.y() - r.y()) / r.height())))
            if self.voll is None:
                self.seite.voll_laden(self)
        self.update()

    def _eingepasst(self) -> QRectF:
        if self.bild is None:
            return QRectF()
        g = self.bild.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - g.width()) / 2, (self.height() - g.height()) / 2, g.width(), g.height())

    def _lupe_rechteck(self) -> tuple[QImage, QRectF]:
        """Das Bild in 1:1 und wo es liegt, die gewaehlte Stelle in der Mitte -
        nie weiter verschoben, als das Bild reicht."""
        bild = self.voll or self.bild
        b, h = bild.width(), bild.height()
        x = self.width() / 2 - self.mitte.x() * b
        y = self.height() / 2 - self.mitte.y() * h
        x = min(0.0, max(self.width() - b, x)) if b > self.width() else (self.width() - b) / 2
        y = min(0.0, max(self.height() - h, y)) if h > self.height() else (self.height() - h) / 2
        return bild, QRectF(x, y, b, h)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(QPalette.ColorRole.Base))
        if self.bild is None:
            p.setPen(pal.color(QPalette.ColorRole.Text))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text)
        elif self.lupe:
            bild, r = self._lupe_rechteck()
            p.drawImage(r, bild)
        else:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(self._eingepasst(), self.bild)
        if self.aktiv:
            p.setPen(QPen(pal.color(QPalette.ColorRole.Highlight), 3))
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()

    def mousePressEvent(self, ev) -> None:
        if self._aktiv_bei_klick is not None:
            self._aktiv_bei_klick(self)
        if ev.button() == Qt.MouseButton.LeftButton:
            self._ziehen = ev.position()
            self._gezogen = False
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self._ziehen is not None and self.lupe:
            bild = self.voll or self.bild
            d = ev.position() - self._ziehen
            if abs(d.x()) + abs(d.y()) > 3:
                self._gezogen = True
                self.mitte = QPointF(min(1.0, max(0.0, self.mitte.x() - d.x() / bild.width())),
                                     min(1.0, max(0.0, self.mitte.y() - d.y() / bild.height())))
                self._ziehen = ev.position()
                self.update()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton and self._ziehen is not None and not self._gezogen:
            self.lupe_umschalten(ev.position())
        self._ziehen = None
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev) -> None:
        taste = ev.key()
        if taste in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.seite.raster_zeigen()
        elif taste in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space):
            self.seite.blaettern(1)
        elif taste in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backspace):
            self.seite.blaettern(-1)
        elif taste == Qt.Key.Key_Z:
            self.lupe_umschalten()
        elif not self.seite.taste(taste, ev.text()):
            super().keyPressEvent(ev)
            return
        ev.accept()


class _Vergleich(QWidget):
    """Zwei bis vier Bilder nebeneinander. Bewertet wird das umrandete;
    Pfeiltasten oder ein Klick waehlen ein anderes, Z zeigt die Lupe."""

    def __init__(self, seite: "SichtenSeite") -> None:
        super().__init__()
        self.seite = seite
        self.nummern: list[int] = []
        self.aktiv = 0
        self.felder: list[_Gross] = []
        self.unter: list[QLabel] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for _ in range(VERGLEICH_HOECHSTENS):
            spalte = QVBoxLayout()
            feld = _Gross(seite, aktiv_bei_klick=self._geklickt)
            feld.keyPressEvent = self._taste      # Tasten gehen an den Vergleich
            unter = QLabel("")
            unter.setAlignment(Qt.AlignmentFlag.AlignCenter)
            unter.setWordWrap(True)
            spalte.addWidget(feld, 1)
            spalte.addWidget(unter)
            lay.addLayout(spalte, 1)
            self.felder.append(feld)
            self.unter.append(unter)

    def zeigen(self, nummern: list[int]) -> None:
        self.nummern = nummern[:VERGLEICH_HOECHSTENS]
        self.aktiv = 0
        for i, (feld, unter) in enumerate(zip(self.felder, self.unter)):
            sichtbar = i < len(self.nummern)
            feld.setVisible(sichtbar)
            unter.setVisible(sichtbar)
            if sichtbar:
                feld.zeigen(None, "…")
        self.beschriften()
        if self.nummern:
            self.felder[0].setFocus()

    def beschriften(self) -> None:
        for i, nr in enumerate(self.nummern):
            b = self.seite.alle[nr]
            self.unter[i].setText(f"{b.name}\n{_beschriftung(b, self.seite.bewertung(b))}")
            self.felder[i].aktiv = i == self.aktiv
            self.felder[i].update()

    def _geklickt(self, feld: _Gross) -> None:
        if feld in self.felder:
            self.aktiv = self.felder.index(feld)
            self.beschriften()

    def aktive_nummer(self) -> int | None:
        return self.nummern[self.aktiv] if self.nummern else None

    def _taste(self, ev) -> None:
        taste = ev.key()
        if taste == Qt.Key.Key_Escape:
            self.seite.raster_zeigen()
        elif taste in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Tab):
            self.aktiv = (self.aktiv + 1) % max(1, len(self.nummern))
            self.beschriften()
        elif taste in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.aktiv = (self.aktiv - 1) % max(1, len(self.nummern))
            self.beschriften()
        elif taste == Qt.Key.Key_Z and self.nummern:
            self.felder[self.aktiv].lupe_umschalten()
        elif not self.seite.taste(taste, ev.text()):
            return
        ev.accept()


class SichtenSeite(QWidget):
    """Der Reiter „Sichten“. oeffnen() mit ablauf.sichten_info()."""

    def __init__(self, eltern=None) -> None:
        super().__init__(eltern)
        self.info: dict = {}
        self.ziel: Path | None = None
        self.bew: sichten.Bewertungen | None = None
        self.leser: vorschau.Vorschauleser | None = None
        self.zwischen: Path | None = None             # Zwischenspeicher der Vorschaubilder
        self.alle: list[sichten.Bild] = []          # alle Bilder des Ordners
        self.gezeigt: list[int] = []                 # Nummern (in alle) der gezeigten, in Reihenfolge
        self.stand: dict[str, sichten.Bewertung] = {}  # Bewertungen des Ordners
        self.aus_xmp: set[str] = set()               # Bewertung nur aus einer XMP-Datei, noch nicht gespeichert
        self.vorschau: dict[int, QPixmap] = {}       # geladene Vorschaubilder des Ordners
        self.eintraege: dict[int, QListWidgetItem] = {}  # Nummer -> Kachel (grosse Ordner: kein Suchen)
        self.ordner_jetzt: Path | None = None
        self.durchgang = 0                           # Raster: Ordner oder Filter
        self.ordner_nr = 0                           # Ordner: gilt fuer grosse Bilder und Kameradaten
        self.gross_nr: int | None = None
        self.gross_bilder: OrderedDict[int, QImage | None] = OrderedDict()   # vorab geladene grosse Bilder
        self.angefragt: set[int] = set()
        self.voll_warten: dict[int, list[_Gross]] = {}
        self.daten_text: dict[int, str] = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(LESER)
        self.signale = _Signale()
        self.signale.fertig.connect(self._geladen)
        self.signale.daten.connect(self._daten_da)
        self._icon_leer = _platzhalter("…")
        self._icon_video = _platzhalter("Video")
        self._icon_keins = _platzhalter(meldungen.SICHTEN_KEINE_VORSCHAU)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)
        links = QVBoxLayout()
        self.baum = QTreeWidget()
        self.baum.setHeaderHidden(True)
        self.baum.setMinimumWidth(240)
        self.baum.setMaximumWidth(340)
        self.baum.itemExpanded.connect(self._aufklappen)
        self.baum.currentItemChanged.connect(lambda neu, _alt: self._ordner_gewaehlt(neu))
        links.addWidget(self.baum, 1)
        self.aktualisieren_knopf = QPushButton("Neu einlesen")
        self.aktualisieren_knopf.setProperty("klasse", "ghost")
        self.aktualisieren_knopf.setFlat(True)
        self.aktualisieren_knopf.clicked.connect(self.neu_einlesen)
        links.addWidget(self.aktualisieren_knopf)
        self.xmp_knopf = QPushButton(meldungen.SICHTEN_XMP_KNOPF)
        self.xmp_knopf.setProperty("klasse", "ghost")
        self.xmp_knopf.setFlat(True)
        self.xmp_knopf.setToolTip(meldungen.SICHTEN_XMP_FRAGE)
        self.xmp_knopf.clicked.connect(self.xmp_anlegen)
        links.addWidget(self.xmp_knopf)
        lay.addLayout(links)

        rechts = QVBoxLayout()
        rechts.setSpacing(8)
        kopf = QHBoxLayout()
        self.titel = QLabel("")
        self.titel.setProperty("klasse", "titel")
        kopf.addWidget(self.titel, 1)
        self.filter = QComboBox()
        for wert, text in meldungen.SICHTEN_FILTER:
            self.filter.addItem(text, wert)
        self.filter.currentIndexChanged.connect(lambda _i: self._zeigen())
        kopf.addWidget(self.filter)
        rechts.addLayout(kopf)
        self.zahlen = QLabel("")
        self.zahlen.setProperty("klasse", "hinweis")
        self.zahlen.setWordWrap(True)
        rechts.addWidget(self.zahlen)
        self.kameradaten = QLabel("")
        self.kameradaten.setProperty("klasse", "hinweis")
        self.kameradaten.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.kameradaten.hide()
        rechts.addWidget(self.kameradaten)
        self.stapel = QStackedWidget()
        self.raster = _Raster(self)
        self.gross = _Gross(self)
        self.vergleich = _Vergleich(self)
        self.hinweis = QLabel("")
        self.hinweis.setWordWrap(True)
        self.hinweis.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (self.raster, self.gross, self.vergleich, self.hinweis):
            self.stapel.addWidget(w)
        rechts.addWidget(self.stapel, 1)
        rechts.addWidget(self._leiste_bauen())
        tasten = QLabel(meldungen.SICHTEN_TASTEN)
        tasten.setProperty("klasse", "hinweis")
        tasten.setWordWrap(True)
        rechts.addWidget(tasten)
        lay.addLayout(rechts, 1)

    def _leiste_bauen(self) -> QWidget:
        """Bewerten mit der Maus: Sterne, Markierung, Farbe - fuer alle gewaehlten Bilder."""
        leiste = QFrame()
        spalte = QVBoxLayout(leiste)
        spalte.setContentsMargins(0, 0, 0, 0)
        spalte.setSpacing(4)
        zeile = QHBoxLayout()
        zeile.setSpacing(4)
        spalte.addLayout(zeile)

        def k(text: str, tipp: str, klick, breite: int = 0) -> QPushButton:
            knopf = QPushButton(text)
            knopf.setToolTip(tipp)
            knopf.setAutoDefault(False)
            knopf.setFocusPolicy(Qt.FocusPolicy.NoFocus)    # die Tasten bleiben bei den Bildern
            if breite:
                knopf.setFixedWidth(breite)
            knopf.clicked.connect(klick)
            zeile.addWidget(knopf)
            return knopf

        self.sterne_knoepfe = [k("☆" if n == 0 else f"{n} ★", "Keine Sterne (Taste 0)" if n == 0 else f"{n} Sterne (Taste {n})",
                                 lambda _c=False, n=n: self.bewerten(sterne=n), 46) for n in range(6)]
        zeile.addSpacing(10)
        k("Auswahl", "Als Auswahl markieren (Taste P)", lambda: self.bewerten(markierung="auswahl"))
        k("Ausschuss", "Als Ausschuss markieren (Taste X) – nur eine Markierung", lambda: self.bewerten(markierung="ausschuss"))
        k("Aufheben", "Markierung aufheben (Taste U)", lambda: self.bewerten(markierung=""))
        zeile.addSpacing(10)
        self.farb_knoepfe: dict[str, QPushButton] = {}
        tasten = {v: t for t, v in FARBE_TASTE.items()}
        for farbe in sichten.FARBEN[1:]:
            name = meldungen.SICHTEN_FARBE[farbe]
            knopf = k("", f"{name}" + (f" (Taste {tasten[farbe]})" if farbe in tasten else ""),
                      lambda _c=False, f=farbe: self.farbe_umschalten(f), 36)
            knopf.setIcon(_farbpunkt(farbe))
            self.farb_knoepfe[farbe] = knopf
        zeile.addStretch(1)
        zeile = QHBoxLayout()
        zeile.setSpacing(4)
        spalte.addLayout(zeile)
        k("Groß ansehen", "Das gewählte Bild groß zeigen (Eingabe)", lambda: self.gross_zeigen())
        k("Vergleichen", "Zwei bis vier gewählte Bilder nebeneinander (Taste C)", self.vergleichen)
        zeile.addStretch(1)
        self.weiter = QCheckBox(meldungen.SICHTEN_WEITER)
        self.weiter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        zeile.addWidget(self.weiter)
        return leiste

    def bewertung(self, b: sichten.Bild) -> sichten.Bewertung:
        return self.stand.get(b.schluessel, sichten.Bewertung())

    # -- Oeffnen und Ordner -----------------------------------------------------

    def oeffnen(self, info: dict) -> None:
        """Mit dem Archiv aus ablauf.sichten_info(). Gleiches Archiv: der Stand
        bleibt, fehlende Vorschaubilder werden weiter geladen ("Neu einlesen"
        liest Ordner und Bilder frisch)."""
        if info.get("text"):
            self.schliessen()
            self.info, self.ziel, self.bew = {}, None, None
            self.baum.clear()
            self.titel.setText("")
            self.zahlen.setText("")
            self.hinweis.setText(info["text"])
            self.stapel.setCurrentWidget(self.hinweis)
            return
        neu = Path(info["ziel"]) != self.ziel or Path(info["archiv_ordner"]) != (self.bew.datei.parent if self.bew else None)
        if neu:
            self.schliessen()
            self.info = info
            self.ziel = Path(info["ziel"])
            self.bew = sichten.Bewertungen(Path(info["archiv_ordner"]))
            self.zwischen = Path(info["archiv_ordner"]) / ZWISCHENORDNER
            self.leser = vorschau.Vorschauleser(info["exiftool"]) if info.get("exiftool") else None
            self.pool.setMaxThreadCount(leser_fuer(str(info.get("laufwerksart") or "")))
            self.neu_einlesen()
        else:
            self._fehlende_laden()

    def pausieren(self) -> None:
        """Reiter verlassen: keine weiteren Vorschaubilder lesen - die Platte
        gehoert dem Ablauf im Reiter „Archiv“. Was gerade gelesen wird, kommt
        noch an; der Rest folgt beim Zurueckkommen (_fehlende_laden)."""
        self.pool.clear()
        self.angefragt.clear()

    def _fehlende_laden(self) -> None:
        for i in self.gezeigt:
            b = self.alle[i]
            if b.art != dateitypen.VIDEO and i not in self.vorschau:
                self.pool.start(_Laden(self.signale, self.durchgang, i, b, KACHEL, self.leser, KLEIN, self.zwischen))

    def neu_einlesen(self) -> None:
        if self.ziel is None:
            return
        gewaehlt = self.ordner_jetzt
        self.baum.blockSignals(True)
        self.baum.clear()
        wurzel = self._eintrag(self.ziel, self.ziel.name or str(self.ziel))
        self.baum.addTopLevelItem(wurzel)
        self.baum.blockSignals(False)
        # Den zuletzt gewaehlten Ordner wieder waehlen, sonst den neuesten Tag.
        ziel_eintrag = self._finden(gewaehlt) if gewaehlt else None
        if ziel_eintrag is None:
            ziel_eintrag = wurzel
            while True:
                ziel_eintrag.setExpanded(True)          # liest die Unterordner (_aufklappen)
                if not (ziel_eintrag.childCount() and ziel_eintrag.child(0).data(0, ROLLE_PFAD)):
                    break
                ziel_eintrag = ziel_eintrag.child(0)
        self.baum.setCurrentItem(ziel_eintrag)
        self._ordner_gewaehlt(ziel_eintrag, erzwingen=True)

    def _eintrag(self, pfad: Path, text: str) -> QTreeWidgetItem:
        e = QTreeWidgetItem([text])
        e.setData(0, ROLLE_PFAD, str(pfad))
        e.addChild(QTreeWidgetItem([""]))   # Platzhalter: gelesen wird erst beim Aufklappen
        return e

    def _aufklappen(self, e: QTreeWidgetItem) -> None:
        if e.childCount() != 1 or e.child(0).data(0, ROLLE_PFAD):
            return
        e.takeChild(0)
        try:
            unter = sichten.ordner(self.ziel, Path(e.data(0, ROLLE_PFAD)))
        except FotosortFehler:
            unter = []
        for p in unter:
            e.addChild(self._eintrag(p, p.name))
        if not unter:
            e.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)

    def _finden(self, pfad: Path) -> QTreeWidgetItem | None:
        """Den Eintrag eines Ordners, die Ebenen darueber aufgeklappt."""
        e = self.baum.topLevelItem(0)
        try:
            teile = Path(pfad).relative_to(self.ziel).parts
        except (ValueError, TypeError):
            return None
        for teil in teile:
            e.setExpanded(True)
            e = next((e.child(i) for i in range(e.childCount()) if Path(e.child(i).data(0, ROLLE_PFAD) or "").name == teil), None)
            if e is None:
                return None
        return e

    def _ordner_gewaehlt(self, e: QTreeWidgetItem | None, erzwingen: bool = False) -> None:
        if e is None or not e.data(0, ROLLE_PFAD) or self.ziel is None:
            return
        pfad = Path(e.data(0, ROLLE_PFAD))
        if pfad == self.ordner_jetzt and not erzwingen:
            return
        self.ordner_jetzt = pfad
        self.ordner_nr += 1
        self.vorschau = {}
        self.gross_bilder.clear()
        self.angefragt.clear()
        self.voll_warten.clear()
        self.daten_text.clear()
        self.titel.setText(pfad.name or str(pfad))
        try:
            self.alle = sichten.bilder(pfad, self.ziel, self.info["konf"])
            self.stand = self.bew.lesen([b.schluessel for b in self.alle]) if self.bew else {}
        except FotosortFehler as fehler:
            self.alle, self.stand = [], {}
            self.zahlen.setText(str(fehler))
        # Bilder ohne eigene Bewertung zeigen, was in ihrer XMP-Datei steht
        # (Lightroom, darktable) - nur gelesen; gespeichert erst, wenn hier
        # etwas geaendert wird.
        self.aus_xmp = set()
        for b in self.alle:
            if b.xmp and b.schluessel not in self.stand:
                aus = sichten.xmp_lesen(b.xmp[0])
                if aus is not None:
                    self.stand[b.schluessel] = aus
                    self.aus_xmp.add(b.schluessel)
        self._zeigen()

    # -- Raster -----------------------------------------------------------------

    def _zeigen(self) -> None:
        """Das Raster fuer den Ordner und den Filter neu fuellen; Vorschau im Hintergrund."""
        self.pool.clear()
        self.angefragt.clear()
        self.durchgang += 1
        self.gross_nr = None
        filter_ = self.filter.currentData() or "alle"
        self.gezeigt = [i for i, b in enumerate(self.alle) if sichten.passt(self.stand.get(b.schluessel), filter_)]
        self.raster.clear()
        self.eintraege = {}
        for i in self.gezeigt:
            eintrag = QListWidgetItem("")
            eintrag.setData(ROLLE_NR, i)
            eintrag.setSizeHint(QSize(KACHEL + 20, KACHEL + 48))
            self.raster.addItem(eintrag)
            self.eintraege[i] = eintrag
            self._beschriften(eintrag)
        self._fehlende_laden()
        self.kameradaten.hide()
        self.stapel.setCurrentWidget(self.raster if self.alle or self.ordner_jetzt else self.hinweis)
        if not self.alle and self.ordner_jetzt is None:
            self.hinweis.setText(meldungen.SICHTEN_ORDNER_WAEHLEN)
        if self.raster.count():
            self.raster.setCurrentRow(0)
        self._zahlen()

    def _beschriften(self, eintrag: QListWidgetItem) -> None:
        """Text, Farbe und Bild einer Kachel: Auswahl gruen, Ausschuss rot und
        abgeblendet, Farbmarke als Punkt - nur in der Anzeige, die Datei bleibt."""
        nr = eintrag.data(ROLLE_NR)
        b = self.alle[nr]
        bew = self.bewertung(b)
        eintrag.setText(f"{b.name}\n{_beschriftung(b, bew)}")
        eintrag.setToolTip("\n".join(str(p) for p in b.dateien + b.xmp))
        eintrag.setForeground(QColor(FARBE_MARKIERUNG[bew.markierung]) if bew.markierung in FARBE_MARKIERUNG
                              else QApplication.palette().color(QPalette.ColorRole.Text))
        pm = self.vorschau.get(nr)
        if pm is None:
            eintrag.setIcon(self._icon_video if b.art == dateitypen.VIDEO else self._icon_leer)
        elif pm.isNull():
            eintrag.setIcon(self._icon_keins)
        else:
            if bew.markierung == "ausschuss":
                pm = _abgeblendet(pm)
            eintrag.setIcon(QIcon(_mit_farbe(pm, bew.farbe)))

    def _zahlen(self) -> None:
        werte = [self.bewertung(b) for b in self.alle]
        self.zahlen.setText(meldungen.sichten_ordner_zahlen(
            len(self.gezeigt), len(self.alle), sum(1 for w in werte if w.sterne),
            sum(1 for w in werte if w.markierung == "auswahl"), sum(1 for w in werte if w.markierung == "ausschuss")))

    def _geladen(self, durchgang: int, nr: int, art: int, bild: QImage) -> None:
        if art == KLEIN:
            if durchgang != self.durchgang:
                return   # anderer Ordner oder Filter inzwischen
            self.vorschau[nr] = QPixmap() if bild.isNull() else QPixmap.fromImage(bild)
            e = self.eintraege.get(nr)
            if e is not None:
                self._beschriften(e)
            return
        if durchgang != self.ordner_nr:
            return       # anderer Ordner inzwischen
        img = None if bild.isNull() else bild
        if art == VOLL:
            for feld in self.voll_warten.pop(nr, []):
                if self._nummer_von(feld) == nr:
                    feld.voll_setzen(img)
            return
        self.angefragt.discard(nr)
        self.gross_bilder[nr] = img
        self.gross_bilder.move_to_end(nr)
        while len(self.gross_bilder) > ZWISCHENSPEICHER:
            self.gross_bilder.popitem(last=False)
        if self.stapel.currentWidget() is self.gross and nr == self.gross_nr and self.gross.bild is None:
            self.gross.zeigen(img, meldungen.SICHTEN_KEINE_VORSCHAU)
        if self.stapel.currentWidget() is self.vergleich and nr in self.vergleich.nummern:
            feld = self.vergleich.felder[self.vergleich.nummern.index(nr)]
            if feld.bild is None:
                feld.zeigen(img, meldungen.SICHTEN_KEINE_VORSCHAU)

    def _daten_da(self, durchgang: int, nr: int, text: str) -> None:
        if durchgang != self.ordner_nr:
            return
        self.daten_text[nr] = text
        if self.stapel.currentWidget() is self.gross and nr == self.gross_nr:
            self.kameradaten.setText(text)

    # -- Bewerten ---------------------------------------------------------------

    def _gewaehlte(self) -> list[int]:
        if self.stapel.currentWidget() is self.gross and self.gross_nr is not None:
            return [self.gross_nr]
        if self.stapel.currentWidget() is self.vergleich:
            nr = self.vergleich.aktive_nummer()
            return [] if nr is None else [nr]
        return [e.data(ROLLE_NR) for e in self.raster.selectedItems()]

    def taste(self, taste: int, text: str) -> bool:
        """0-5 Sterne, P/X/U markieren, 6-9 Farbe, C vergleichen; True, wenn
        die Taste dazu gehoerte."""
        text = (text or "").lower()
        if text in ("0", "1", "2", "3", "4", "5"):
            return self.bewerten(sterne=int(text))
        if text in FARBE_TASTE:
            return self.farbe_umschalten(FARBE_TASTE[text])
        if text in ("p", "x", "u"):
            return self.bewerten(markierung={"p": "auswahl", "x": "ausschuss", "u": ""}[text])
        if text == "c" and self.stapel.currentWidget() is self.raster:
            self.vergleichen()
            return True
        if taste in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.stapel.currentWidget() is self.raster:
            self.gross_zeigen()
            return True
        return False

    def farbe_umschalten(self, farbe: str) -> bool:
        """Wie in Lightroom: dieselbe Farbe noch einmal nimmt sie wieder weg."""
        nummern = self._gewaehlte()
        if nummern and all(self.bewertung(self.alle[i]).farbe == farbe for i in nummern):
            farbe = ""
        return self.bewerten(farbe=farbe)

    def bewerten(self, sterne: int | None = None, markierung: str | None = None, farbe: str | None = None) -> bool:
        nummern = self._gewaehlte()
        if not nummern or self.bew is None:
            return True
        schluessel = [self.alle[i].schluessel for i in nummern]
        try:
            # Was bisher nur in der XMP-Datei stand, wird jetzt erst gespeichert -
            # sonst ginge beim Aendern der Sterne die Farbe aus der XMP verloren.
            for s in schluessel:
                if s in self.aus_xmp:
                    alt = self.stand[s]
                    self.bew.setzen([s], sterne=alt.sterne, markierung=alt.markierung, farbe=alt.farbe)
                    self.aus_xmp.discard(s)
            self.bew.setzen(schluessel, sterne=sterne, markierung=markierung, farbe=farbe)
        except FotosortFehler as fehler:
            self.zahlen.setText(str(fehler))
            return True
        neu = self.bew.lesen(schluessel)
        for s in schluessel:
            if s in neu:
                self.stand[s] = neu[s]
            else:
                self.stand.pop(s, None)       # nichts mehr gesetzt
        for i in nummern:
            if i in self.eintraege:
                self._beschriften(self.eintraege[i])
        if self.stapel.currentWidget() is self.gross:
            self._gross_titel()
        if self.stapel.currentWidget() is self.vergleich:
            self.vergleich.beschriften()
        self._zahlen()
        if self.weiter.isChecked():
            self.naechstes()
        return True

    def naechstes(self) -> None:
        """Nach dem Bewerten weiter (wenn angehakt): grosse Ansicht blaettert,
        im Raster wird das naechste Bild gewaehlt; im Vergleich das naechste Feld."""
        jetzt = self.stapel.currentWidget()
        if jetzt is self.gross:
            self.blaettern(1)
        elif jetzt is self.vergleich and self.vergleich.nummern:
            self.vergleich.aktiv = min(self.vergleich.aktiv + 1, len(self.vergleich.nummern) - 1)
            self.vergleich.beschriften()
        elif jetzt is self.raster and len(self.raster.selectedItems()) == 1:
            zeile = self.raster.currentRow()
            if 0 <= zeile < self.raster.count() - 1:
                self.raster.setCurrentRow(zeile + 1)

    # -- Grosse Ansicht -----------------------------------------------------------

    def _anfragen(self, nr: int, prioritaet: int) -> None:
        b = self.alle[nr]
        if b.art == dateitypen.VIDEO or nr in self.gross_bilder or nr in self.angefragt:
            return
        self.angefragt.add(nr)
        self.pool.start(_Laden(self.signale, self.ordner_nr, nr, b, GROSS, self.leser, GROSS_ART), prioritaet)

    def _vorab(self, nr: int) -> None:
        """Die Nachbarn in der gezeigten Reihenfolge schon laden - Blaettern
        ist dann sofort da (nach dem gezeigten, vor den Vorschaubildern)."""
        if nr not in self.gezeigt:
            return
        stelle = self.gezeigt.index(nr)
        for abstand in range(1, VORAB + 1):
            for nachbar in (stelle + abstand, stelle - abstand):
                if 0 <= nachbar < len(self.gezeigt):
                    self._anfragen(self.gezeigt[nachbar], 5 - abstand)

    def gross_zeigen(self, nr: int | None = None) -> None:
        if nr is None:
            e = self.raster.currentItem()
            if e is None:
                return
            nr = e.data(ROLLE_NR)
        self.gross_nr = nr
        b = self.alle[nr]
        self.stapel.setCurrentWidget(self.gross)
        if nr in self.gross_bilder:
            self.gross.zeigen(self.gross_bilder[nr], meldungen.SICHTEN_KEINE_VORSCHAU)
        else:
            self.gross.zeigen(None, "…" if b.art != dateitypen.VIDEO else "Video")
            self._anfragen(nr, 10)                # vor allem anderen
        self._gross_titel()
        self.kameradaten.setText(self.daten_text.get(nr, ""))
        self.kameradaten.show()
        if nr not in self.daten_text and self.leser is not None and b.art != dateitypen.VIDEO:
            self.pool.start(_Daten(self.signale, self.ordner_nr, nr, b, self.leser), 9)
        self.gross.setFocus()
        self._vorab(nr)

    def _gross_titel(self) -> None:
        if self.gross_nr is None:
            return
        b = self.alle[self.gross_nr]
        self.titel.setText(f"{b.name}   {_beschriftung(b, self.bewertung(b))}")

    def blaettern(self, schritt: int) -> None:
        if self.gross_nr is None or self.gross_nr not in self.gezeigt:
            return
        stelle = self.gezeigt.index(self.gross_nr) + schritt
        if 0 <= stelle < len(self.gezeigt):
            self.raster.setCurrentRow(stelle)
            self.gross_zeigen(self.gezeigt[stelle])

    def _nummer_von(self, feld: _Gross) -> int | None:
        if feld is self.gross:
            return self.gross_nr
        if feld in self.vergleich.felder:
            i = self.vergleich.felder.index(feld)
            return self.vergleich.nummern[i] if i < len(self.vergleich.nummern) else None
        return None

    def voll_laden(self, feld: _Gross) -> None:
        """Die Lupe braucht das Bild in voller Aufloesung."""
        nr = self._nummer_von(feld)
        if nr is None or self.alle[nr].art == dateitypen.VIDEO:
            return
        wartend = self.voll_warten.setdefault(nr, [])
        if feld not in wartend:
            wartend.append(feld)
        if len(wartend) == 1:
            self.pool.start(_Laden(self.signale, self.ordner_nr, nr, self.alle[nr], 0, self.leser, VOLL), 11)

    # -- Vergleich ----------------------------------------------------------------

    def vergleichen(self) -> None:
        nummern = [e.data(ROLLE_NR) for e in self.raster.selectedItems()]
        nummern = sorted(nummern, key=lambda n: self.gezeigt.index(n) if n in self.gezeigt else n)
        if not 2 <= len(nummern) <= VERGLEICH_HOECHSTENS:
            self.zahlen.setText(meldungen.SICHTEN_VERGLEICH_WAEHLEN)
            return
        self.gross_nr = None
        self.stapel.setCurrentWidget(self.vergleich)
        self.vergleich.zeigen(nummern)
        self.kameradaten.hide()
        self.titel.setText(meldungen.SICHTEN_VERGLEICH_TITEL)
        for i, nr in enumerate(nummern):
            if nr in self.gross_bilder:
                self.vergleich.felder[i].zeigen(self.gross_bilder[nr], meldungen.SICHTEN_KEINE_VORSCHAU)
            else:
                self._anfragen(nr, 10)

    def raster_zeigen(self) -> None:
        self.stapel.setCurrentWidget(self.raster)
        self.gross_nr = None
        self.kameradaten.hide()
        self.titel.setText(self.ordner_jetzt.name if self.ordner_jetzt else "")
        self.raster.setFocus()

    # -- XMP ------------------------------------------------------------------------

    def xmp_anlegen(self) -> None:
        """Nach Rueckfrage: fuer jedes bewertete Bild des Archivs eine neue
        XMP-Datei - nur, wo noch keine liegt (sichten.xmp_anlegen)."""
        if self.bew is None or self.ziel is None:
            return
        antwort = QMessageBox.question(self, meldungen.SICHTEN_XMP_TITEL, meldungen.SICHTEN_XMP_FRAGE)
        if antwort != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            e = sichten.xmp_anlegen(self.ziel, self.bew, self.info.get("konf"))
        except FotosortFehler as fehler:
            self.zahlen.setText(str(fehler))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.zahlen.setText(meldungen.sichten_xmp_ergebnis(e))

    # -- Ende ---------------------------------------------------------------------

    def schliessen(self) -> None:
        """Hintergrund anhalten und ExifTool beenden (anderes Archiv, Fenster zu).
        Erst den Leser schliessen - ein haengendes Bild wird dabei abgebrochen,
        und danach startet kein Strang mehr ein ExifTool -, dann warten."""
        self.durchgang += 1
        self.ordner_nr += 1
        self.pool.clear()
        if self.leser is not None:
            self.leser.schliessen()
        self.pool.waitForDone(5000)
        self.leser = None
        self.ordner_jetzt = None
        self.gross_bilder.clear()
        self.angefragt.clear()
        # Beim naechsten Oeffnen alles frisch (auch ExifTool).
        self.ziel = None
        self.bew = None
