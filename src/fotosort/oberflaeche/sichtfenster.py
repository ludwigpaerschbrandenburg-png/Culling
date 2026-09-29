"""Reiter „Sichten“ im Desktop-Fenster, erster Ausbau (SPEC §8 seit v0.8).

Links die Ordner des Archivs (neueste zuerst, erst beim Aufklappen gelesen),
rechts die Bilder des gewaehlten Ordners als Vorschau; Eingabe oeffnet die
grosse Ansicht. Tasten 0-5 vergeben Sterne, P/X/U markieren - fuer alle
gewaehlten Bilder. Die Bewertungen stehen in bewertungen.db (sichten.py).

Das Fenster liest die Bilder nur. Es veraendert, verschiebt und loescht
nichts - Ausschuss ist eine Markierung, keine Anweisung. Vorschaubilder
entstehen im Speicher, nie als Datei im Archiv. Gelesen wird im
Hintergrund (hoechstens LESER Dateien gleichzeitig - eine Festplatte liest
mit vielen Lesern nur langsamer), die Oberflaeche bleibt bedienbar.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QImageReader, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import FotosortFehler, dateitypen, meldungen, pfade, sichten, vorschau
from . import stil

KACHEL = 180          # Kantenlaenge der Vorschaubilder in Pixeln
GROSS = 2560          # groesste Kante in der grossen Ansicht
LESER = 3             # gleichzeitig gelesene Dateien
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
    fertig = Signal(int, int, bool, QImage)   # Durchgang, Nummer des Bilds, gross?, Bild (leer: keine Vorschau)


class _Laden(QRunnable):
    def __init__(self, signale: _Signale, durchgang: int, nr: int, b: sichten.Bild, groesse: int,
                 leser: vorschau.Vorschauleser | None, gross: bool) -> None:
        super().__init__()
        self.signale, self.durchgang, self.nr, self.b = signale, durchgang, nr, b
        self.groesse, self.leser, self.gross = groesse, leser, gross

    def run(self) -> None:
        try:
            bild = bild_laden(self.b, self.groesse, self.leser, self.gross)
        except Exception:   # noqa: BLE001 - eine unlesbare Datei ist nur "keine Vorschau"
            bild = None
        try:
            self.signale.fertig.emit(self.durchgang, self.nr, self.gross, bild if bild is not None else QImage())
        except RuntimeError:
            pass   # Fenster inzwischen geschlossen


def _platzhalter(text: str) -> QIcon:
    pm = QPixmap(KACHEL, KACHEL)
    pm.fill(QColor(stil.SURFACE))
    maler = QPainter(pm)
    maler.setPen(QColor(stil.TEXT))
    maler.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
    maler.end()
    return QIcon(pm)


FARBE_MARKIERUNG = {"auswahl": "#6fcf97", "ausschuss": "#eb7a7a"}


def _abgeblendet(pm: QPixmap) -> QPixmap:
    neu = QPixmap(pm.size())
    neu.fill(Qt.GlobalColor.transparent)
    maler = QPainter(neu)
    maler.setOpacity(0.35)
    maler.drawPixmap(0, 0, pm)
    maler.end()
    return neu


def _sterne(n: int) -> str:
    return "★" * n + "☆" * (5 - n)


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


class _Gross(QLabel):
    """Die grosse Ansicht eines Bilds."""

    def __init__(self, seite: "SichtenSeite") -> None:
        super().__init__()
        self.seite = seite
        self.bild: QImage | None = None
        self.setProperty("klasse", "sicht-gross")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(200, 200)

    def zeigen(self, bild: QImage | None, text: str = "") -> None:
        self.bild = bild
        if bild is None:
            self.setPixmap(QPixmap())
            self.setText(text)
            return
        self.setText("")
        self._skalieren()

    def _skalieren(self) -> None:
        if self.bild is None or self.width() < 10 or self.height() < 10:
            return
        self.setPixmap(QPixmap.fromImage(self.bild).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._skalieren()

    def keyPressEvent(self, ev) -> None:
        taste = ev.key()
        if taste in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.seite.raster_zeigen()
        elif taste in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space):
            self.seite.blaettern(1)
        elif taste in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backspace):
            self.seite.blaettern(-1)
        elif not self.seite.taste(taste, ev.text()):
            super().keyPressEvent(ev)
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
        self.alle: list[sichten.Bild] = []          # alle Bilder des Ordners
        self.gezeigt: list[int] = []                 # Nummern (in alle) der gezeigten, in Reihenfolge
        self.stand: dict[str, tuple[int, str]] = {}  # Bewertungen des Ordners
        self.vorschau: dict[int, QPixmap] = {}       # geladene Vorschaubilder des Ordners
        self.eintraege: dict[int, QListWidgetItem] = {}  # Nummer -> Kachel (grosse Ordner: kein Suchen)
        self.ordner_jetzt: Path | None = None
        self.durchgang = 0
        self.gross_nr: int | None = None
        self.gross_durchgang = 0
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(LESER)
        self.signale = _Signale()
        self.signale.fertig.connect(self._geladen)
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
        self.aktualisieren_knopf.clicked.connect(self.neu_einlesen)
        links.addWidget(self.aktualisieren_knopf)
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
        self.stapel = QStackedWidget()
        self.raster = _Raster(self)
        self.gross = _Gross(self)
        self.hinweis = QLabel("")
        self.hinweis.setWordWrap(True)
        self.hinweis.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (self.raster, self.gross, self.hinweis):
            self.stapel.addWidget(w)
        rechts.addWidget(self.stapel, 1)
        tasten = QLabel(meldungen.SICHTEN_TASTEN)
        tasten.setProperty("klasse", "hinweis")
        tasten.setWordWrap(True)
        rechts.addWidget(tasten)
        lay.addLayout(rechts, 1)

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
            self.leser = vorschau.Vorschauleser(info["exiftool"]) if info.get("exiftool") else None
            self.neu_einlesen()
        else:
            self._fehlende_laden()

    def pausieren(self) -> None:
        """Reiter verlassen: keine weiteren Vorschaubilder lesen - die Platte
        gehoert dem Ablauf im Reiter „Archiv“. Was gerade gelesen wird, kommt
        noch an; der Rest folgt beim Zurueckkommen (_fehlende_laden)."""
        self.pool.clear()

    def _fehlende_laden(self) -> None:
        for i in self.gezeigt:
            b = self.alle[i]
            if b.art != dateitypen.VIDEO and i not in self.vorschau:
                self.pool.start(_Laden(self.signale, self.durchgang, i, b, KACHEL, self.leser, False))

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
        self.vorschau = {}
        self.titel.setText(pfad.name or str(pfad))
        try:
            self.alle = sichten.bilder(pfad, self.ziel, self.info["konf"])
            self.stand = self.bew.lesen([b.schluessel for b in self.alle]) if self.bew else {}
        except FotosortFehler as fehler:
            self.alle, self.stand = [], {}
            self.zahlen.setText(str(fehler))
        self._zeigen()

    # -- Raster -----------------------------------------------------------------

    def _zeigen(self) -> None:
        """Das Raster fuer den Ordner und den Filter neu fuellen; Vorschau im Hintergrund."""
        self.pool.clear()
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
        self.stapel.setCurrentWidget(self.raster if self.alle or self.ordner_jetzt else self.hinweis)
        if not self.alle and self.ordner_jetzt is None:
            self.hinweis.setText(meldungen.SICHTEN_ORDNER_WAEHLEN)
        if self.raster.count():
            self.raster.setCurrentRow(0)
        self._zahlen()

    def _beschriften(self, eintrag: QListWidgetItem) -> None:
        """Text, Farbe und Bild einer Kachel: Auswahl gruen, Ausschuss rot und
        abgeblendet - nur in der Anzeige, die Datei bleibt, wie sie ist."""
        nr = eintrag.data(ROLLE_NR)
        b = self.alle[nr]
        sterne, markierung = self.stand.get(b.schluessel, (0, ""))
        zusatz = meldungen.SICHTEN_MARKIERUNG[markierung]
        eintrag.setText(f"{b.name}\n{_sterne(sterne)}" + (f" · {zusatz}" if zusatz else ""))
        eintrag.setToolTip("\n".join(str(p) for p in b.dateien))
        eintrag.setForeground(QColor(FARBE_MARKIERUNG.get(markierung, stil.N300)))
        pm = self.vorschau.get(nr)
        if pm is None:
            eintrag.setIcon(self._icon_video if b.art == dateitypen.VIDEO else self._icon_leer)
        elif pm.isNull():
            eintrag.setIcon(self._icon_keins)
        elif markierung == "ausschuss":
            eintrag.setIcon(QIcon(_abgeblendet(pm)))
        else:
            eintrag.setIcon(QIcon(pm))

    def _zahlen(self) -> None:
        werte = [self.stand.get(b.schluessel, (0, "")) for b in self.alle]
        self.zahlen.setText(meldungen.sichten_ordner_zahlen(
            len(self.gezeigt), len(self.alle), sum(1 for s, _m in werte if s),
            sum(1 for _s, m in werte if m == "auswahl"), sum(1 for _s, m in werte if m == "ausschuss")))

    def _geladen(self, durchgang: int, nr: int, gross: bool, bild: QImage) -> None:
        if gross:
            # Nur das zuletzt verlangte grosse Bild zaehlt (schnelles Blaettern).
            if durchgang == self.gross_durchgang and nr == self.gross_nr and self.stapel.currentWidget() is self.gross:
                self.gross.zeigen(None if bild.isNull() else bild, meldungen.SICHTEN_KEINE_VORSCHAU)
            return
        if durchgang != self.durchgang:
            return   # anderer Ordner oder Filter inzwischen
        self.vorschau[nr] = QPixmap() if bild.isNull() else QPixmap.fromImage(bild)
        e = self.eintraege.get(nr)
        if e is not None:
            self._beschriften(e)

    # -- Bewerten ---------------------------------------------------------------

    def _gewaehlte(self) -> list[int]:
        if self.stapel.currentWidget() is self.gross and self.gross_nr is not None:
            return [self.gross_nr]
        return [e.data(ROLLE_NR) for e in self.raster.selectedItems()]

    def taste(self, taste: int, text: str) -> bool:
        """0-5 Sterne, P/X/U markieren; True, wenn die Taste dazu gehoerte."""
        text = (text or "").lower()
        if text in ("0", "1", "2", "3", "4", "5"):
            return self.bewerten(sterne=int(text))
        if text in ("p", "x", "u"):
            return self.bewerten(markierung={"p": "auswahl", "x": "ausschuss", "u": ""}[text])
        if taste in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.stapel.currentWidget() is self.raster:
            self.gross_zeigen()
            return True
        return False

    def bewerten(self, sterne: int | None = None, markierung: str | None = None) -> bool:
        nummern = self._gewaehlte()
        if not nummern or self.bew is None:
            return True
        schluessel = [self.alle[i].schluessel for i in nummern]
        try:
            self.bew.setzen(schluessel, sterne=sterne, markierung=markierung)
        except FotosortFehler as fehler:
            self.zahlen.setText(str(fehler))
            return True
        neu = self.bew.lesen(schluessel)
        for s in schluessel:
            if s in neu:
                self.stand[s] = neu[s]
            else:
                self.stand.pop(s, None)       # keine Sterne, keine Markierung mehr
        for i in nummern:
            if i in self.eintraege:
                self._beschriften(self.eintraege[i])
        if self.stapel.currentWidget() is self.gross:
            self._gross_titel()
        self._zahlen()
        return True

    # -- Grosse Ansicht -----------------------------------------------------------

    def gross_zeigen(self, nr: int | None = None) -> None:
        if nr is None:
            e = self.raster.currentItem()
            if e is None:
                return
            nr = e.data(ROLLE_NR)
        self.gross_nr = nr
        self.gross_durchgang += 1            # eigener Zaehler: die Vorschaubilder laden weiter
        b = self.alle[nr]
        self.stapel.setCurrentWidget(self.gross)
        self.gross.zeigen(None, "…" if b.art != dateitypen.VIDEO else "Video")
        self._gross_titel()
        self.gross.setFocus()
        if b.art != dateitypen.VIDEO:
            # Vor den noch wartenden Vorschaubildern an die Reihe.
            self.pool.start(_Laden(self.signale, self.gross_durchgang, nr, b, GROSS, self.leser, True), 10)

    def _gross_titel(self) -> None:
        if self.gross_nr is None:
            return
        b = self.alle[self.gross_nr]
        sterne, markierung = self.stand.get(b.schluessel, (0, ""))
        zusatz = meldungen.SICHTEN_MARKIERUNG[markierung]
        self.titel.setText(f"{b.name}   {_sterne(sterne)}" + (f" · {zusatz}" if zusatz else ""))

    def blaettern(self, schritt: int) -> None:
        if self.gross_nr is None or self.gross_nr not in self.gezeigt:
            return
        stelle = self.gezeigt.index(self.gross_nr) + schritt
        if 0 <= stelle < len(self.gezeigt):
            self.raster.setCurrentRow(stelle)
            self.gross_zeigen(self.gezeigt[stelle])

    def raster_zeigen(self) -> None:
        self.stapel.setCurrentWidget(self.raster)
        self.gross_nr = None
        self.titel.setText(self.ordner_jetzt.name if self.ordner_jetzt else "")
        self.raster.setFocus()

    # -- Ende ---------------------------------------------------------------------

    def schliessen(self) -> None:
        """Hintergrund anhalten und ExifTool beenden (anderes Archiv, Fenster zu).
        Erst den Leser schliessen - ein haengendes Bild wird dabei abgebrochen,
        und danach startet kein Strang mehr ein ExifTool -, dann warten."""
        self.durchgang += 1
        self.pool.clear()
        if self.leser is not None:
            self.leser.schliessen()
        self.pool.waitForDone(5000)
        self.leser = None
        self.ordner_jetzt = None
        # Beim naechsten Oeffnen alles frisch (auch ExifTool).
        self.ziel = None
        self.bew = None
