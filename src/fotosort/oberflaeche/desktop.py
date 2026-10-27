"""Das Desktop-Fenster (PySide6/Qt) - die Oberflaeche unter Windows (Phase 7).

Ein normales Fenster mit Taskleisten-Symbol, Ordnerwahl ueber den Dialog des
Systems, nie ein getippter Pfad. Aufbau und Seiten wie die Browser-Fassung
(static/): Startseite, Uebersicht mit Phasenleiste, Fortschritt, Zaehlern und
Karten, geblaetterte Listen. Das Aussehen kommt aus stil.py: Grundstil und
Palette des Systems (wie ein Windows-11-Programm, seit v0.10).

Die Arbeit tut weiterhin der Ablauf (ablauf.py) mit einem eigenen Prozess je
Schritt; das Fenster fragt hoechstens zweimal je Sekunde die Statusdatei ab
und liest die Datenbank nur, wenn kein Prozess laeuft (SPEC Abschnitt 8).

--selbsttest: Fenster oeffnen, Zustand lesen, wieder schliessen (Rueckgabe 0/1).
--durchlauf ZIEL QUELLE [--fotos ORDNER]: der ganze Ablauf ueber die Bedien-
elemente des Fensters am kuenstlichen Testbaum, wahlweise mit Bildschirmfoto
jeder Ansicht - fuer die CI (offscreen) und fuer docs/oberflaeche/.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from .. import FotosortFehler, __version__, meldungen
from . import ablauf as ablauf_modul
from . import meldungsfenster, sichtfenster, stil

SCHRITTE = ["scan", "analyse", "kopieren", "pruefen", "aufraeumen"]
#: Marke des kuenstlichen Testbaums (tests/testbaum.py legt sie neben "Quelle" ab):
#: nur dort darf --durchlauf laufen, denn er raeumt am Ende die Quelle auf.
TESTBAUM_MARKE = ".fotosort_testbaum"
ENDE = {"fertig", "abgebrochen", "fehler", "abgestuerzt"}
POLL_MS = 500          # hoechstens zweimal je Sekunde (SPEC Abschnitt 8)
MARKER = "fenster.json"
SCHLIESSEN = "schliessen"


# ------------------------------------------------------------ Bausteine --


def label(text: str = "", klasse: str = "", wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if klasse:
        l.setProperty("klasse", klasse)
    l.setWordWrap(wrap)
    l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return l


def knopf(text: str, klasse: str = "secondary", klick=None) -> QPushButton:
    """Ein normaler Windows-Knopf. "primary": der hervorgehobene Knopf in der
    Akzentfarbe von Windows; "ghost": flach, wie ein Textknopf."""
    k = QPushButton(text)
    k.setProperty("klasse", klasse)
    k.setAutoDefault(False)
    if klasse == "primary":
        k.setDefault(True)
    elif klasse == "ghost":
        k.setFlat(True)
    if klick is not None:
        k.clicked.connect(klick)
    return k


def klasse_setzen(w: QWidget, klasse: str) -> None:
    w.setProperty("klasse", klasse)
    w.style().unpolish(w)
    w.style().polish(w)


def tag(text: str, klasse: str = "tag", breite: int = 0) -> QLabel:
    l = label(text, klasse)
    l.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    if breite:
        kuerzen(l, text, breite)
    return l


def kuerzen(l: QLabel, text: str, breite: int) -> None:
    """Langen Pfad in der Mitte kuerzen (…), voller Pfad als Tooltip."""
    from PySide6.QtGui import QFontMetrics
    l.setToolTip(text)
    l.setText(QFontMetrics(l.font()).elidedText(text, Qt.TextElideMode.ElideMiddle, breite))


class TagZeile(QFrame):
    """Ein Pfad als Textzeile, wahlweise mit Knopf „Entfernen“."""

    def __init__(self, text: str, entfernen=None) -> None:
        super().__init__()
        self.setProperty("klasse", "tagzeile")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        t = QLabel(text)
        kuerzen(t, text, 560)
        lay.addWidget(t)
        if entfernen is not None:
            x = knopf("Entfernen", "ghost", entfernen)
            x.setToolTip("Diese Quelle wieder entfernen")
            lay.addWidget(x)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class Seg(QFrame):
    """Auswahl aus wenigen Werten: Optionsfelder wie in Windows; als
    "reiter" eine Leiste mit Unterstrich unter dem gewaehlten Eintrag."""

    geaendert = Signal(str)

    def __init__(self, werte: list[tuple[str, str]], reiter: bool = False, untereinander: bool = False) -> None:
        super().__init__()
        self.setProperty("klasse", "seg")
        lay = QVBoxLayout(self) if untereinander else QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4 if reiter else (6 if untereinander else 18))
        self.gruppe = QButtonGroup(self)
        self.gruppe.setExclusive(True)
        self.knoepfe: dict[str, QAbstractButton] = {}
        for wert, text in werte:
            if reiter:
                k = QPushButton(text)
                k.setProperty("klasse", "reiter")
                k.setAutoDefault(False)
            else:
                k = QRadioButton(text)
            k.setCheckable(True)
            self.gruppe.addButton(k)
            lay.addWidget(k)
            self.knoepfe[wert] = k
            k.clicked.connect(lambda _c=False, w=wert: self.geaendert.emit(w))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def wert(self) -> str:
        for w, k in self.knoepfe.items():
            if k.isChecked():
                return w
        return ""

    def setzen(self, wert: str) -> None:
        if wert in self.knoepfe:
            self.knoepfe[wert].setChecked(True)

    def sperren(self, gesperrt: bool) -> None:
        for k in self.knoepfe.values():
            k.setEnabled(not gesperrt)


class Karte(QFrame):
    """Ein Kasten mit Ueberschrift, wie die Karten in den Windows-Einstellungen."""

    def __init__(self, kicker: str, gedaempft: bool = False) -> None:
        super().__init__()
        self.setProperty("klasse", "card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 14)
        self.lay.setSpacing(8)
        self.kicker = label(kicker, "kicker-gedaempft" if gedaempft else "kicker")
        self.lay.addWidget(self.kicker)

    def inaktiv(self, ja: bool) -> None:
        klasse_setzen(self, "card-inaktiv" if ja else "card")
        for l in self.findChildren(QLabel):
            l.style().unpolish(l)
            l.style().polish(l)


class Linie(QProgressBar):
    """Fortschrittsbalken von Windows (ohne Prozentzahl daneben)."""

    def __init__(self) -> None:
        super().__init__()
        self.setRange(0, 1000)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self.anteil = 0.0

    def setzen(self, anteil: float) -> None:
        self.anteil = max(0.0, min(1.0, float(anteil)))
        self.setValue(round(self.anteil * 1000))


class Phasenleiste(QWidget):
    """Die fuenf Schritte nebeneinander: erledigte mit Haken, der aktuelle fett."""

    NAMEN = ("Scan", "Analyse", "Kopieren", "Prüfen", "Aufräumen")

    def __init__(self) -> None:
        super().__init__()
        zeile = QHBoxLayout(self)
        zeile.setContentsMargins(0, 0, 0, 0)
        zeile.setSpacing(28)
        self.namen: list[QLabel] = []
        for name in self.NAMEN:
            l = label(name, "phase")
            zeile.addWidget(l)
            self.namen.append(l)
        zeile.addStretch(1)

    def setzen(self, aktiv: str, anteil: float = 0.0, alles_fertig: bool = False) -> None:
        idx = SCHRITTE.index(aktiv) if aktiv in SCHRITTE else -1
        for i, (l, name) in enumerate(zip(self.namen, self.NAMEN)):
            if alles_fertig or (idx >= 0 and i < idx):
                l.setText("✓ " + name)
                klasse_setzen(l, "phase-fertig")
            elif i == idx:
                l.setText("● " + name)
                klasse_setzen(l, "phase-aktiv")
            else:
                l.setText(name)
                klasse_setzen(l, "phase")


class Zaehler(QWidget):
    """Zeilen Bezeichnung / Wert, wie eine schlichte Tabelle."""

    def __init__(self) -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self.setMaximumWidth(560)

    def setzen(self, zeilen: list) -> None:
        _leeren(self.lay)
        for name, wert in zeilen or []:
            z = QHBoxLayout()
            z.setContentsMargins(0, 0, 0, 0)
            z.addWidget(label(str(name), "zaehler-name"))
            z.addStretch(1)
            wert = str(wert)
            z.addWidget(label(wert, "zaehler-null" if wert == "0" else "zaehler-wert"))
            self.lay.addLayout(z)


class Dialog(QDialog):
    """Frage mit Ja/Abbrechen, wahlweise mit Eingabefeld (Bestaetigungswort)."""

    def __init__(self, eltern, titel: str, text: str, eingabe: bool = False, ja: str = "Ja", nein: str = "Abbrechen") -> None:
        super().__init__(eltern)
        self.setWindowTitle(titel)
        self.setModal(True)
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(label(titel, "dialog-titel", wrap=True))
        lay.addWidget(label(text, "dialog-text", wrap=True))
        self.feld = QLineEdit()
        self.feld.setVisible(eingabe)
        lay.addWidget(self.feld)
        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        self.nein = knopf(nein, "secondary", self.reject)
        self.ja = knopf(ja, "primary", self.accept)
        knoepfe.addWidget(self.nein)
        knoepfe.addWidget(self.ja)
        lay.addLayout(knoepfe)
        self.feld.returnPressed.connect(self.accept)
        (self.feld if eingabe else self.ja).setFocus()


def frage(eltern, titel: str, text: str, eingabe: bool = False, ja: str = "Ja", nein: str = "Abbrechen") -> tuple[bool, str]:
    d = Dialog(eltern, titel, text, eingabe, ja, nein)
    ergebnis = d.exec() == QDialog.DialogCode.Accepted
    return ergebnis, d.feld.text()


# ---------------------------------------------------------------- Seiten --


class StartSeite(QWidget):
    def __init__(self, fenster: "Hauptfenster") -> None:
        super().__init__()
        self.f = fenster
        aussen = QHBoxLayout(self)
        aussen.setContentsMargins(0, 0, 0, 0)
        aussen.setSpacing(32)
        form = QVBoxLayout()
        form.setSpacing(22)

        # Ziel
        form.addWidget(label("Zielordner – hier entsteht das sortierte Archiv", "feldname"))
        zeile = QHBoxLayout()
        self.ziel = QLineEdit()
        self.ziel.setReadOnly(True)
        self.ziel.setPlaceholderText("noch kein Ordner gewählt")
        zeile.addWidget(self.ziel, 1)
        zeile.addWidget(knopf("Auswählen…", "secondary", self.ziel_waehlen))
        form.addLayout(zeile)
        self.ziel_hinweis = label("Leer oder ein früher angefangenes Archiv.", "hinweis")
        form.addWidget(self.ziel_hinweis)

        # Quellen
        form.addWidget(label("Quellordner – hier liegen die unsortierten Fotos", "feldname"))
        self.quellen_box = QVBoxLayout()
        self.quellen_box.setSpacing(4)
        form.addLayout(self.quellen_box)
        zeile = QHBoxLayout()
        zeile.addWidget(knopf("Quelle hinzufügen…", "secondary", self.quelle_waehlen))
        zeile.addStretch(1)
        form.addLayout(zeile)
        form.addWidget(label("Mehrere Quellen sind möglich. Beim Kopieren bleibt die Quelle unverändert.", "hinweis"))

        # Modus und Profil
        zeile = QHBoxLayout()
        zeile.setSpacing(40)
        block = QVBoxLayout()
        block.setSpacing(6)
        block.addWidget(label("Modus", "feldname"))
        self.modus = Seg([("kopieren", "Kopieren"), ("verschieben", "Verschieben")])
        self.modus.geaendert.connect(lambda _w: self.f.einstellungen_senden())
        block.addWidget(self.modus)
        self.modus_text = label("", "hinweis", wrap=True)
        block.addWidget(self.modus_text)
        block.addStretch(1)
        zeile.addLayout(block)
        block = QVBoxLayout()
        block.setSpacing(6)
        block.addWidget(label("Quelle und Ziel liegen auf", "feldname"))
        self.profil = Seg([("hdd", "Festplatte"), ("ssd", "SSD"), ("netzwerk", "Netzwerk")])
        self.profil.geaendert.connect(lambda _w: self.f.profil_gewaehlt())
        block.addWidget(self.profil)
        self.profil_text = label("", "hinweis", wrap=True)
        block.addWidget(self.profil_text)
        block.addStretch(1)
        zeile.addLayout(block)
        zeile.addStretch(1)
        form.addLayout(zeile)
        form.addStretch(1)
        aussen.addLayout(form, 1)

        # Karten rechts
        seite = QVBoxLayout()
        seite.setSpacing(12)
        self.karte = Karte("Zielordner")
        self.archiv_text = label("Noch kein Zielordner gewählt.", "hinweis", wrap=True)
        self.karte.lay.addWidget(self.archiv_text)
        self.archiv_tags = QVBoxLayout()
        self.archiv_tags.setSpacing(4)
        self.karte.lay.addLayout(self.archiv_tags)
        self.weitermachen = knopf("Weitermachen", "primary", self.f.weitermachen)
        self.weitermachen.setEnabled(False)
        self.karte.lay.addWidget(self.weitermachen)
        self.rettung = knopf("", "primary", self.f.rettung)
        self.rettung.hide()
        self.karte.lay.addWidget(self.rettung)
        self.verwerfen = knopf("Archiv verwerfen…", "ghost", self.f.archiv_verwerfen)
        self.verwerfen.setToolTip("Merkliste und Berichte zu diesem Ziel entfernen – kopierte Fotos bleiben.")
        self.verwerfen.hide()
        self.karte.lay.addWidget(self.verwerfen)
        seite.addWidget(self.karte)
        k2 = Karte("Bevor es losgeht", gedaempft=True)
        for t in ("Zuerst mit Kopien üben.", "Gelöscht wird nur nach Bestätigungswort.",
                  "Fenster zu hält den Schritt sauber an; beim nächsten Öffnen geht es weiter."):
            k2.lay.addWidget(label(t, "hinweis", wrap=True))
        seite.addWidget(k2)
        seite.addStretch(1)
        rechts = QWidget()
        rechts.setLayout(seite)
        rechts.setFixedWidth(320)
        aussen.addWidget(rechts)

    # -- Bedienung ---------------------------------------------------------

    def ziel_waehlen(self) -> None:
        pfad = QFileDialog.getExistingDirectory(self, "Zielordner wählen", self.ziel.text() or str(Path.home()))
        if pfad:
            self.ziel_setzen(pfad)

    def ziel_setzen(self, pfad: str) -> None:
        self.ziel.setText(str(Path(pfad)))
        self.ziel.setCursorPosition(0)
        self.f.ziel_uebernehmen(self.ziel.text())

    def quelle_waehlen(self) -> None:
        pfad = QFileDialog.getExistingDirectory(self, "Quellordner wählen", str(Path.home()))
        if pfad:
            self.f.quelle_hinzufuegen(str(Path(pfad)))

    def fuellen(self, z: dict) -> None:
        self.ziel.setText(z.get("ziel") or "")
        self.ziel.setCursorPosition(0)
        self.modus.setzen("verschieben" if z.get("verschieben") else "kopieren")
        self.profil.setzen(z.get("profil") or "hdd")
        self.texte(z)
        self.quellen_zeigen(z.get("quellen_neu") or [])
        self.archiv_zeigen(z.get("archiv") or {})

    def texte(self, z: dict) -> None:
        self.modus_text.setText(
            "Jede Datei wird erst nach geprüfter Kopie in der Quelle gelöscht." if self.modus.wert() == "verschieben"
            else "Die Quelle bleibt unverändert; aufgeräumt wird später.")
        p = next((p for p in z.get("profile", []) if p["name"] == self.profil.wert()), None)
        text = p["text"] if p else ""
        # Entscheidung 1 (v0.8): was die Laufwerkserkennung vorschlaegt
        if z.get("profil_erkannt") and not z.get("profil_von_hand"):
            text += "\n" + z["profil_erkannt"]
        self.profil_text.setText(text)

    def quellen_zeigen(self, neu: list) -> None:
        _leeren(self.quellen_box)
        for q in neu:
            self.quellen_box.addWidget(TagZeile(q, lambda _c=False, q=q: self.f.quelle_entfernen(q)))
        if not neu and not (self.f.zustand.get("archiv") or {}).get("quellen"):
            self.quellen_box.addWidget(label("noch keine Quelle", "hinweis"))

    def archiv_zeigen(self, archiv: dict) -> None:
        _leeren(self.archiv_tags)
        self.weitermachen.setEnabled(False)
        self.weitermachen.setText("Weitermachen")
        self.rettung.hide()
        self.verwerfen.setVisible(bool(self.ziel.text()) and bool(archiv.get("da")) and not archiv.get("laeuft"))
        if not self.ziel.text():
            self.karte.kicker.setText("Zielordner")
            self.archiv_text.setText("Noch kein Zielordner gewählt.")
            return
        if not archiv.get("da"):
            if archiv.get("ziel_existiert") is False:
                # Meist eine nicht angeschlossene Platte oder ein umbenannter
                # Ordner - kein neues Archiv (SPEC §8, --ziel-anlegen).
                self.karte.kicker.setText("Zielordner nicht gefunden")
                self.archiv_text.setText(meldungen.ob_ziel_nicht_gefunden())
                return
            self.karte.kicker.setText("Neues Archiv")
            self.archiv_text.setText("Noch kein Archiv in diesem Ordner.")
            return
        self.karte.kicker.setText("Angefangenes Archiv")
        if archiv.get("laeuft"):
            self.archiv_text.setText("Gerade läuft ein Schritt.")
            return
        if archiv.get("rettung"):
            self.karte.kicker.setText("Archiv ohne Merkliste")
            self.archiv_text.setText(archiv.get("rettung_text") or archiv.get("fehler") or "")
            self.rettung.setText("Datenbank zurückholen…" if archiv["rettung"] == "wiederherstellen" else "Archiv neu einlesen…")
            self.rettung.show()
            self.weitermachen.hide()
            return
        self.weitermachen.show()
        if archiv.get("fehler"):
            self.archiv_text.setText(archiv["fehler"])
            return
        self.archiv_text.setText(archiv.get("phase") or "")
        for q in archiv.get("quellen") or []:
            self.archiv_tags.addWidget(TagZeile(q))
        n = archiv.get("naechster")
        if n and n != "fertig":
            self.weitermachen.setEnabled(True)
            self.weitermachen.setText("Weitermachen: " + self.f.kurzname(n))
        else:
            self.weitermachen.setText("Alles erledigt")


class HauptSeite(QWidget):
    def __init__(self, fenster: "Hauptfenster") -> None:
        super().__init__()
        self.f = fenster
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(28)
        self.pfade = QHBoxLayout()
        self.pfade.setSpacing(10)
        lay.addLayout(self.pfade)
        self.phasen = Phasenleiste()
        lay.addWidget(self.phasen)

        tafel = QHBoxLayout()
        tafel.setSpacing(32)
        links = QVBoxLayout()
        links.setSpacing(12)
        self.balken = Linie()
        links.addWidget(self.balken)
        self.kennzahlen = QHBoxLayout()
        self.kennzahlen.setSpacing(24)
        links.addLayout(self.kennzahlen)
        self.aktuell = label("", "hinweis")
        links.addWidget(self.aktuell)
        self.zaehler = Zaehler()
        links.addWidget(self.zaehler)
        self.kameras = QWidget()
        self.kameras_lay = QVBoxLayout(self.kameras)
        self.kameras_lay.setContentsMargins(0, 8, 0, 0)
        self.kameras_lay.setSpacing(8)
        self.kameras.setMaximumWidth(640)
        self.kameras.hide()
        links.addWidget(self.kameras)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(180)
        self.log.hide()
        links.addWidget(self.log)
        links.addStretch(1)
        tafel.addLayout(links, 1)

        rechts = QVBoxLayout()
        rechts.setSpacing(12)
        self.k_auf = Karte("Aufräumen (Schritt 5)")
        self.auf_quellen = QVBoxLayout()
        self.auf_quellen.setSpacing(2)
        self.k_auf.lay.addLayout(self.auf_quellen)
        self.auf_weise = Seg([("papierkorb", "In Ordner _geloescht_ legen"), ("endgueltig", "Endgültig löschen")], untereinander=True)
        self.auf_weise.setzen("papierkorb")
        self.auf_weise.geaendert.connect(lambda _w: self.auf_wort_pruefen())
        self.k_auf.lay.addWidget(self.auf_weise)
        self.auf_soll = label("Zum Bestätigen tippen: verschieben", "hinweis")
        self.k_auf.lay.addWidget(self.auf_soll)
        self.auf_wort = QLineEdit()
        self.auf_wort.textChanged.connect(lambda _t: self.auf_wort_pruefen())
        self.auf_wort.returnPressed.connect(lambda: self.auf_los.isEnabled() and self.auf_los.click())
        self.k_auf.lay.addWidget(self.auf_wort)
        self.auf_los = knopf("Nach _geloescht_ verschieben", "primary", self.f.aufraeumen_starten)
        self.k_auf.lay.addWidget(self.auf_los)
        # Nur sichtbar, wenn das Programm etwas in einen Ordner _geloescht_ gelegt hat.
        self.zurueck_los = knopf("Zurücklegen…", "ghost", self.f.zuruecklegen)
        self.zurueck_los.hide()
        self.k_auf.lay.addWidget(self.zurueck_los)
        rechts.addWidget(self.k_auf)

        self.k_ordner = Karte("Leere Ordner")
        self.k_ordner.lay.addWidget(label("Reste wie Thumbs.db zählen als leer. Der Quellordner selbst bleibt.", "hinweis", wrap=True))
        self.k_ordner.lay.addWidget(label("Zum Bestätigen tippen: entfernen", "hinweis"))
        self.ordner_wort = QLineEdit()
        self.ordner_wort.textChanged.connect(lambda _t: self.ordner_wort_pruefen())
        self.k_ordner.lay.addWidget(self.ordner_wort)
        self.ordner_los = knopf("Leere Ordner entfernen", "primary", self.f.ordner_starten)
        self.k_ordner.lay.addWidget(self.ordner_los)
        rechts.addWidget(self.k_ordner)

        self.k_bericht = Karte("Letzter Bericht", gedaempft=True)
        self.bericht_name = label("noch keiner")
        self.k_bericht.lay.addWidget(self.bericht_name)
        zeile = QHBoxLayout()
        zeile.setSpacing(6)
        self.bericht_oeffnen = knopf("Öffnen", "ghost", lambda: self.f.bericht_oeffnen("txt"))
        self.bericht_csv = knopf("Tabelle", "ghost", lambda: self.f.bericht_oeffnen("csv"))
        self.bericht_csv.setToolTip("Den Bericht als Tabelle (CSV) öffnen")
        zeile.addWidget(self.bericht_oeffnen)
        zeile.addWidget(self.bericht_csv)
        zeile.addWidget(knopf("Neu schreiben", "ghost", lambda: self.f.bericht_oeffnen("neu")))
        zeile.addStretch(1)
        self.k_bericht.lay.addLayout(zeile)
        rechts.addWidget(self.k_bericht)
        rechts.addStretch(1)
        rechts_w = QWidget()
        rechts_w.setLayout(rechts)
        rechts_w.setFixedWidth(320)
        tafel.addWidget(rechts_w)
        lay.addLayout(tafel, 1)
        self.woerter = dict(meldungen.BESTAETIGUNGSWORT)
        self.karten_sperren(True)

    def auf_wort_soll(self) -> str:
        return self.woerter.get(self.auf_weise.wert(), "verschieben")

    def auf_wort_pruefen(self) -> None:
        soll = self.auf_wort_soll()
        self.auf_soll.setText("Zum Bestätigen tippen: " + soll)
        self.auf_los.setText("Endgültig löschen" if self.auf_weise.wert() == "endgueltig" else "Nach _geloescht_ verschieben")
        self.auf_los.setEnabled(self.auf_wort.isEnabled() and self.auf_wort.text().strip().lower() == soll)

    def ordner_wort_pruefen(self) -> None:
        self.ordner_los.setEnabled(self.ordner_wort.isEnabled() and self.ordner_wort.text().strip().lower() == self.woerter.get("ordner", "entfernen"))

    def karten_sperren(self, gesperrt: bool) -> None:
        for w in (self.auf_wort, self.auf_los, self.ordner_wort, self.ordner_los):
            w.setEnabled(False)
        self.auf_weise.sperren(gesperrt)
        self.k_auf.inaktiv(gesperrt)
        self.k_ordner.inaktiv(gesperrt)

    def kennzahlen_setzen(self, l: dict | None) -> None:
        _leeren(self.kennzahlen)
        if not l or not l.get("text"):
            self.kennzahlen.addStretch(1)
            return
        t = l["text"]

        def paar(text: str, einheit: str) -> QLabel:
            teile = str(text).split(" von ")
            rest = (" / " + teile[1] + " " + einheit) if len(teile) > 1 else (" " + einheit)
            w = label("", "kennzahl")
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setText(f'<b>{teile[0]}</b>{rest}')
            return w

        self.kennzahlen.addWidget(paar(t.get("dateien") or "0", "Dateien"))
        if l.get("bytes") or l.get("gesamt_bytes"):
            self.kennzahlen.addWidget(paar(t.get("bytes") or "", ""))
        if t.get("rate"):
            w = label("", "kennzahl")
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setText(f'<b>{t["rate"].replace(" MB/s", "")}</b> MB/s')
            self.kennzahlen.addWidget(w)
        if t.get("restzeit") and l.get("zustand") not in ENDE:
            w = label("", "kennzahl")
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setText(f'noch <b>{t["restzeit"]}</b>')
            self.kennzahlen.addWidget(w)
        if t.get("dauer") and l.get("zustand") not in ENDE:
            w = label("", "kennzahl")
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setText(f'bisher <b>{t["dauer"]}</b>')
            self.kennzahlen.addWidget(w)
        self.kennzahlen.addStretch(1)


class ListenSeite(QWidget):
    def __init__(self, fenster: "Hauptfenster") -> None:
        super().__init__()
        self.f = fenster
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        kopf = QHBoxLayout()
        kopf.setSpacing(12)
        self.titel = label("", "titel")
        self.gesamt = label("", "kennzahl")
        kopf.addWidget(self.titel)
        kopf.addWidget(self.gesamt)
        kopf.addStretch(1)
        self.zurueck = knopf("‹", "ghost", lambda: self.f.liste_zeigen(self.art, self.seite - 1))
        self.stand = label("", "hell")
        self.stand.setMinimumWidth(70)
        self.stand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vor = knopf("›", "ghost", lambda: self.f.liste_zeigen(self.art, self.seite + 1))
        kopf.addWidget(self.zurueck)
        kopf.addWidget(self.stand)
        kopf.addWidget(self.vor)
        lay.addLayout(kopf)
        self.tabelle = QTableWidget(0, 3)
        self.tabelle.verticalHeader().setVisible(False)
        self.tabelle.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabelle.setWordWrap(True)
        self.tabelle.horizontalHeader().setStretchLastSection(False)
        self.tabelle.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.tabelle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.tabelle, 1)
        self.art = ""
        self.seite = 1

    def fuellen(self, art: str, l: dict) -> None:
        self.art, self.seite = art, int(l["seite"])
        info = LISTEN[art]
        self.titel.setText(info[0])
        self.gesamt.setText(f'{l["gesamt_text"]} {"Eintrag" if l["gesamt"] == 1 else "Einträge"}, 100 je Seite')
        self.stand.setText(f'{meldungen.anzahl(l["seite"])} / {meldungen.anzahl(l["seiten"])}')
        self.zurueck.setEnabled(l["seite"] > 1)
        self.vor.setEnabled(l["seite"] < l["seiten"])
        t = self.tabelle
        t.setRowCount(0)
        t.setHorizontalHeaderLabels(list(info[1]))
        for z in l["zeilen"]:
            r = t.rowCount()
            t.insertRow(r)
            for i, w in enumerate(info[2](z)):
                item = QTableWidgetItem(str(w))
                if i == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(r, i, item)
        h = t.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        t.resizeRowsToContents()


LISTEN = {
    "fehler": ("Fehler", ["Datei", "Grund", "Größe"], lambda z: [z["quellpfad"], z["grund"], z["groesse"]]),
    "duplikate": ("Duplikate", ["Datei in der Quelle", "gleiche Datei im Archiv", "Größe"], lambda z: [z["quellpfad"], z["partner"], z["groesse"]]),
    "ohne_datum": ("Ohne Aufnahmedatum", ["Datei", "Zielordner", "Größe"], lambda z: [z["quellpfad"], z["zielpfad"], z["groesse"]]),
}


def _leeren(lay) -> None:
    """Alle Eintraege eines Layouts entfernen - Widgets sofort aus der Anzeige
    (setParent(None)), sonst blieben sie bis zum naechsten Ereignisdurchlauf sichtbar."""
    while lay.count():
        eintrag = lay.takeAt(0)
        w = eintrag.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif eintrag.layout() is not None:
            _leeren(eintrag.layout())
            eintrag.layout().deleteLater()


# ------------------------------------------------------------ Hauptfenster --


def fenstermasse(breite: int, hoehe: int) -> tuple[int, int, int, int]:
    """(Breite, Hoehe, Mindestbreite, Mindesthoehe) fuer die verfuegbare
    Bildschirmflaeche. Vorgabe 1180x800, Mindestens 1040x700 (SPEC §8) - auf
    einem kleineren Bildschirm (Laptop mit 150 % Skalierung: etwa 1280x672)
    passt sich beides an, sonst laegen die Knoepfe unter der Bildschirmkante.
    Der Inhalt laesst sich scrollen."""
    b = min(1180, int(breite * 0.95))
    h = min(800, int(hoehe * 0.92))
    return b, h, min(1040, b), min(700, h)


class Hauptfenster(QMainWindow):
    def __init__(self, ab: ablauf_modul.Ablauf, konsole=None) -> None:
        super().__init__()
        self.ab = ab
        # Schritte, die dieses Fenster startet, gehoeren zu ihm: Ist es weg,
        # halten sie an (seit v0.9: Fenster zu = Programm aus).
        self.ab.fenster_pid = os.getpid()
        self.konsole = konsole
        self._schliessen_ohne_frage = False
        self._beendet_gerade = False
        self.instanz: Instanz | None = None
        self.zustand: dict = {}
        self.lauf: dict = {}
        self.naechster: dict | None = None
        self.zf: dict | None = None
        self.letzter_schritt = ""
        self.abbruch_zeit = 0.0
        self.profil_gewaehlt_ = False
        self.ansicht = "start"
        self.vorher = "start"
        self.gezeigt = False

        self.setWindowTitle("fotosort")
        bildschirm = QApplication.primaryScreen()
        flaeche = bildschirm.availableGeometry() if bildschirm is not None else None
        b, h, mb, mh = fenstermasse(flaeche.width(), flaeche.height()) if flaeche is not None else (1180, 800, 1040, 700)
        self.setMinimumSize(mb, mh)
        self.resize(b, h)
        if flaeche is not None:
            self.move(flaeche.x() + max(0, (flaeche.width() - b) // 2), flaeche.y() + max(0, (flaeche.height() - h) // 2))
        self._gesperrt = False
        self.setWindowIcon(stil.programm_symbol())

        inhalt = QWidget()
        inhalt.setObjectName("inhalt")
        self.setCentralWidget(inhalt)
        aussen = QVBoxLayout(inhalt)
        aussen.setContentsMargins(0, 0, 0, 0)
        aussen.setSpacing(0)

        # Kopfzeile: Reiter links, Ziel und Hilfe rechts
        self.titel = QFrame()
        self.titel.setObjectName("titelzeile")
        tl = QHBoxLayout(self.titel)
        tl.setContentsMargins(32, 10, 24, 0)
        tl.setSpacing(12)
        # Zwei Reiter (SPEC §8 seit v0.8): „Archiv“ ist der bisherige Ablauf,
        # „Sichten“ zeigt und bewertet die Bilder im Archiv - er ersetzt nichts.
        self.reiter = Seg([("archiv", "Archiv"), ("sichten", "Sichten")], reiter=True)
        self.reiter.setzen("archiv")
        self.reiter.geaendert.connect(self.reiter_wechseln)
        tl.addWidget(self.reiter)
        tl.addStretch(1)
        self.titel_ziel = label("kein Zielordner", "hinweis")
        tl.addWidget(self.titel_ziel)
        self.titel_lauf = label("", "hinweis")
        tl.addWidget(self.titel_lauf)
        tl.addWidget(knopf("Hilfe", "ghost", lambda: self.hilfe_zeigen()))
        QShortcut(QKeySequence("F1"), self, activated=lambda: self.hilfe_zeigen())
        aussen.addWidget(self.titel)

        # Inhalt (scrollbar) + Aktionen
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        rolle = QWidget()
        rl = QVBoxLayout(rolle)
        rl.setContentsMargins(40, 24, 40, 12)
        rl.setSpacing(20)
        self.meldung_label = label("", "hinweis", wrap=True)
        self.meldung_label.setProperty("klasse", "hell")
        self.meldung_label.hide()
        rl.addWidget(self.meldung_label)
        self.stapel = QStackedWidget()
        self.start = StartSeite(self)
        self.haupt = HauptSeite(self)
        self.listen = ListenSeite(self)
        for s in (self.start, self.haupt, self.listen):
            self.stapel.addWidget(s)
        rl.addWidget(self.stapel, 1)
        self.scroll.setWidget(rolle)
        archiv_w = QWidget()
        al = QVBoxLayout(archiv_w)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)
        al.addWidget(self.scroll, 1)
        aktionen_w = QWidget()
        self.aktionen = QHBoxLayout(aktionen_w)
        self.aktionen.setContentsMargins(40, 8, 40, 16)
        self.aktionen.setSpacing(8)
        al.addWidget(aktionen_w)
        self.reiter_stapel = QStackedWidget()
        self.archiv_reiter = archiv_w
        self.sichten = sichtfenster.SichtenSeite(self)
        self.reiter_stapel.addWidget(archiv_w)
        self.reiter_stapel.addWidget(self.sichten)
        aussen.addWidget(self.reiter_stapel, 1)

        # Statusleiste von Windows
        self.status = self.statusBar()
        self.status.setSizeGripEnabled(True)
        self.leiste_db = QLabel("")
        self.leiste_sicherung = QLabel("")
        self.leiste_sperre = QLabel("")
        for l in (self.leiste_db, self.leiste_sicherung, self.leiste_sperre):
            l.setContentsMargins(10, 2, 10, 2)
        self.status.addWidget(self.leiste_db)
        self.status.addWidget(self.leiste_sicherung)
        self.status.addPermanentWidget(self.leiste_sperre)

        self.poll = QTimer(self)
        self.poll.setInterval(POLL_MS)
        self.poll.timeout.connect(self.lauf_abfragen)
        self.waechter = QTimer(self)
        self.waechter.setInterval(1000)
        self.waechter.timeout.connect(self._schliessen_pruefen)
        self.waechter.start()

    # -- Rahmen ---------------------------------------------------------------

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if not self.gezeigt:
            self.gezeigt = True
            self._marker_schreiben(True)
            QTimer.singleShot(0, lambda: self.laden("start"))

    def closeEvent(self, ev) -> None:
        """Fenster zu = Programm aus (Entscheidung vom 26.10.2026). Laeuft ein
        Schritt, fragt das Fenster kurz; bei "Beenden" haelt es ihn sauber an
        (aktuelle Datei fertig, alles gespeichert) und wartet, bis er aus ist.
        Der naechste Start macht dort weiter."""
        if self._beendet_gerade:
            ev.ignore()
            return
        eigener = self.ab.lauf is not None and self.ab.lauf.auftrag.get("fenster_pid") == os.getpid()
        if eigener and self.ab.lauf_lebt():
            # Windows meldet sich ab oder faehrt herunter: nicht fragen, kurz warten.
            sitzung_endet = QApplication.instance() is not None and QApplication.instance().isSavingSession()
            if not self._schliessen_ohne_frage and not sitzung_endet:
                schritt = self.kurzname((self.ab.lauf.schritt if self.ab.lauf else "") or self.lauf.get("schritt", ""))
                ja, _ = frage(self, meldungen.OB_BEENDEN_TITEL, meldungen.ob_beenden_frage(schritt),
                              ja="Beenden", nein="Weiterarbeiten")
                if not ja:
                    ev.ignore()
                    return
            self._beendet_gerade = True
            self.meldung(meldungen.OB_WIRD_BEENDET)
            try:
                with self.beschaeftigt():
                    self.ab.beenden(warten=10.0 if sitzung_endet else 60.0, takt=QApplication.processEvents)
            finally:
                self._beendet_gerade = False
        self.poll.stop()
        self.sichten.schliessen()
        self._marker_schreiben(False)
        if self.instanz is not None:
            self.instanz.freigeben()
        super().closeEvent(ev)

    def reiter_wechseln(self, name: str) -> None:
        """„Archiv“ oder „Sichten“. Der Ablauf im Reiter „Archiv“ laeuft dabei weiter."""
        self.reiter.setzen(name)
        if name == "sichten":
            self.sichten.oeffnen(self.ab.sichten_info())
            self.reiter_stapel.setCurrentWidget(self.sichten)
            self.sichten.raster.setFocus()
        else:
            self.sichten.pausieren()
            self.reiter_stapel.setCurrentWidget(self.archiv_reiter)

    def _marker_schreiben(self, sichtbar: bool) -> None:
        try:
            from .. import steuerung
            steuerung.json_schreiben(self.ab.ordner / MARKER, {"pid": os.getpid(), "zeit": time.time(), "sichtbar": sichtbar, "version": __version__})
        except OSError:
            pass

    def _schliessen_pruefen(self) -> None:
        """Eine Datei "schliessen" im Ordner der Oberflaeche beendet das Fenster (CI);
        ein zweiter Start (Datei "wecken") holt es nach vorn."""
        if self.instanz is not None and self.instanz.geweckt():
            nach_vorn(self)
        datei = self.ab.ordner / SCHLIESSEN
        if datei.exists():
            try:
                datei.unlink()
            except OSError:
                pass
            self._schliessen_ohne_frage = True     # niemand da, der antworten koennte
            self.close()

    def meldung(self, text: str, gut: bool = False) -> None:
        if not text:
            self.meldung_label.hide()
            return
        self.meldung_label.setText(text)
        klasse_setzen(self.meldung_label, "hell" if gut else "titel")
        self.meldung_label.show()
        self.scroll.verticalScrollBar().setValue(0)

    @contextlib.contextmanager
    def beschaeftigt(self):
        """Fuer Arbeiten, die im Fenster selbst laufen und dauern koennen
        (ExifTool-Probestart bis 20 s, Bericht schreiben, Datenbank lesen):
        Wartezeiger und gesperrte Knoepfe, damit Klicks nicht auflaufen."""
        knoepfe = [self.aktionen.itemAt(i).widget() for i in range(self.aktionen.count())]
        knoepfe = [(k, k.isEnabled()) for k in knoepfe if isinstance(k, QPushButton)]
        for k, _ in knoepfe:
            k.setEnabled(False)
        self._gesperrt = True
        # Kein processEvents hier: Sonst liefe ein Zeitgeber (Statusabfrage,
        # Durchlauf) mitten in diesen Klick hinein. Der Zeiger wechselt auch so.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()
            self._gesperrt = False
            for k, an in knoepfe:
                try:
                    k.setEnabled(an)
                except RuntimeError:
                    pass   # inzwischen ersetzt

    def hilfe_zeigen(self, modal: bool = True) -> QDialog | None:
        """Die Anleitung (LIESMICH) lesbar in einem eigenen Fenster."""
        pfad = ablauf_modul.anleitung_pfad()
        if pfad is None:
            self.meldung(meldungen.ob_anleitung_fehlt())
            return None
        fenster = QDialog(self)
        fenster.setWindowTitle("fotosort – Anleitung")
        lay = QVBoxLayout(fenster)
        lay.setContentsMargins(0, 0, 0, 0)
        text = QTextBrowser(fenster)
        text.setOpenExternalLinks(True)
        text.setMarkdown(pfad.read_text(encoding="utf-8"))
        lay.addWidget(text)
        b, h = self.width(), self.height()
        fenster.resize(max(600, int(b * 0.9)), max(400, int(h * 0.9)))
        if modal:
            fenster.exec()
            return None
        fenster.show()
        return fenster

    def aktionen_gesperrt(self) -> bool:
        return self._gesperrt

    def _versuchen(self, fn, *args):
        """Fehler des Kerns (FotosortFehler) als Meldung, nie als Absturz."""
        try:
            return fn(*args)
        except FotosortFehler as f:
            self.meldung(str(f))
            return None

    def zeige(self, name: str) -> None:
        if self.ansicht != name:
            self.vorher = self.ansicht
        self.ansicht = name
        self.stapel.setCurrentWidget({"start": self.start, "haupt": self.haupt, "liste": self.listen}[name])
        _leeren(self.aktionen)
        self.meldung("")
        self.scroll.verticalScrollBar().setValue(0)

    def aktionen_setzen(self, eintraege: list) -> None:
        _leeren(self.aktionen)
        for text, klasse, klick, aktiv in eintraege:
            k = knopf(text, klasse, klick)
            k.setEnabled(aktiv)
            self.aktionen.addWidget(k)
        self.aktionen.addStretch(1)

    def primaer(self) -> QPushButton | None:
        for i in range(self.aktionen.count()):
            w = self.aktionen.itemAt(i).widget()
            if isinstance(w, QPushButton) and w.property("klasse") == "primary":
                return w
        return None

    def kurzname(self, schritt: str) -> str:
        return {"scan": "Scan", "analyse": "Analyse", "kopieren": "Verschieben" if self.zustand.get("verschieben") else "Kopieren",
                "pruefen": "Prüfen", "aufraeumen": "Aufräumen", "ziel-index": "Neu einlesen",
                "zuruecklegen": "Zurücklegen"}.get(schritt, schritt)

    def rahmen(self) -> None:
        z = self.zustand
        ziel = z.get("ziel") or ""
        self.setWindowTitle(f"fotosort – {ziel}" if ziel else "fotosort")
        kuerzen(self.titel_ziel, ("Archiv: " + ziel) if ziel else "kein Zielordner", max(200, self.width() - 520))
        laeuft = bool(self.lauf.get("zustand")) and self.lauf.get("zustand") not in ENDE
        archiv = z.get("archiv") or {}
        nr = (laeuft and self.lauf.get("lauf")) or archiv.get("lauf_nr") or 0
        self.titel_lauf.setText(f"Lauf {nr}" if nr else "")
        self.leiste_db.setText("Merkliste auf diesem PC" if archiv.get("da") else "")
        self.leiste_sicherung.setText(("Letzte Sicherung: " + archiv["sicherung"]) if archiv.get("sicherung") else "")
        self.leiste_sperre.setText("Archiv in Arbeit" if laeuft else ("Bereit" if archiv.get("da") else ""))
        b = archiv.get("bericht") or {}
        self.haupt.bericht_name.setText(b.get("name") or "noch keiner")
        self.haupt.bericht_oeffnen.setEnabled(bool(b.get("txt")))
        self.haupt.bericht_csv.setEnabled(bool(b.get("csv")))

    # -- Laden ------------------------------------------------------------------

    def laden(self, ansicht: str = "start") -> None:
        z = self._versuchen(self.ab.zustand)
        if z is None:
            return
        self.zustand = z
        self.profil_gewaehlt_ = bool(z.get("profil_von_hand"))
        self.lauf = z.get("lauf") or {}
        self.rahmen()
        self.start.fuellen(z)
        l = self.lauf
        if l.get("zustand") and l["zustand"] not in ENDE:
            self.haupt_zeigen()
            self.lauf_starten(l.get("schritt", ""))
            return
        if ansicht == "haupt":
            self.haupt_zeigen()
            self.ruhe_zeigen()
            return
        self.zeige("start")
        self.start_aktionen()

    def start_aktionen(self) -> None:
        eintraege = [("Los geht's", "primary", lambda: self.los(False), True)]
        if (self.zustand.get("archiv") or {}).get("da"):
            eintraege.append(("Übersicht", "secondary", lambda: (self.haupt_zeigen(), self.ruhe_zeigen()), True))
            eintraege.append(("Einstellungen", "secondary", self.einstellungen_oeffnen, True))
        self.aktionen_setzen(eintraege)

    # -- Startseite ----------------------------------------------------------------

    def ziel_uebernehmen(self, ziel: str) -> None:
        a = self._versuchen(self.ab.ziel_setzen, ziel)
        if a is None:
            return
        self.zustand["ziel"] = a["ziel"]
        self.zustand["archiv"] = a["archiv"]
        self.start.archiv_zeigen(a["archiv"])
        self.start.quellen_zeigen(self.zustand.get("quellen_neu") or [])
        self.rahmen()
        self.start_aktionen()
        self._profil_uebernehmen(a)

    def _profil_uebernehmen(self, a: dict) -> None:
        """Vorschlag der Laufwerkserkennung zeigen (SPEC §8 seit v0.8); hat der
        Nutzer selbst gewaehlt, aendert der Hintergrund das Profil nicht mehr."""
        for k in ("profil", "profil_erkannt", "profil_von_hand"):
            if k in a:
                self.zustand[k] = a[k]
        self.start.profil.setzen(self.zustand.get("profil") or "hdd")
        self.start.texte(self.zustand)

    def quelle_hinzufuegen(self, pfad: str, trotzdem: bool = False) -> None:
        a = self._versuchen(self.ab.quelle_hinzufuegen, pfad, trotzdem)
        if a is None:
            return
        if a.get("frage") == "quelle_gross":
            ja, _ = frage(self, "Wirklich diesen Ordner?", a["text"], ja="Trotzdem nehmen", nein="Anderen wählen")
            if ja:
                self.quelle_hinzufuegen(pfad, True)
            return
        self.zustand["quellen_neu"] = a["quellen_neu"]
        self.start.quellen_zeigen(a["quellen_neu"])
        self._profil_uebernehmen(a)
        self.meldung("")

    def quelle_entfernen(self, pfad: str) -> None:
        a = self._versuchen(self.ab.quelle_entfernen, pfad)
        if a is None:
            return
        self.zustand["quellen_neu"] = a["quellen_neu"]
        self.start.quellen_zeigen(a["quellen_neu"])
        self._profil_uebernehmen(a)

    def profil_gewaehlt(self) -> None:
        self.profil_gewaehlt_ = True
        self.einstellungen_senden()

    def einstellungen_senden(self) -> None:
        # Das Profil geht nur mit, wenn der Nutzer es selbst gewaehlt hat - sonst
        # bliebe der Vorschlag der Laufwerkserkennung nach einem Moduswechsel stehen.
        profil = self.start.profil.wert() if self.profil_gewaehlt_ else None
        a = self._versuchen(self.ab.einstellungen_setzen, self.start.modus.wert() == "verschieben", profil)
        if a is not None:
            self.zustand["verschieben"] = a["verschieben"]
            self._profil_uebernehmen(a)

    def los(self, ziel_anlegen: bool, ziel_trotzdem: bool = False) -> None:
        with self.beschaeftigt():
            a = self._versuchen(self.ab.los, ziel_anlegen, ziel_trotzdem)
        if a is None:
            return
        if a.get("frage") == "ziel_anlegen":
            ja, _ = frage(self, "Ordner anlegen?", a["text"], ja="Anlegen")
            if ja:
                self.los(True, ziel_trotzdem)
            return
        if a.get("frage") == "ziel_nicht_leer":
            ja, _ = frage(self, "Zielordner ist nicht leer", a["text"], ja="Weiter", nein="Anderen Ordner wählen")
            if ja:
                self.los(ziel_anlegen, True)
            return
        if a.get("gestartet"):
            self.haupt_zeigen()
            self.lauf_starten(a["gestartet"])

    def rettung(self) -> None:
        """Startseite: Datenbank aus der Sicherung holen oder das Ziel neu einlesen."""
        art = (self.zustand.get("archiv") or {}).get("rettung")
        if art == "wiederherstellen":
            a = self._versuchen(self.ab.archiv_wiederherstellen, False)
            if a is None or a.get("frage") != "wiederherstellen":
                return
            ja, _ = frage(self, "Datenbank zurückholen?", a["text"], ja="Zurückholen", nein="Nicht jetzt")
            if not ja:
                return
            with self.beschaeftigt():
                a = self._versuchen(self.ab.archiv_wiederherstellen, True)
            if a is None:
                return
            self.laden("start")
            self.meldung(a.get("text", ""), gut=True)
        elif art == "neuaufbau":
            self.neuaufbau()

    def nachpruefen(self) -> None:
        """Das ganze Archiv erneut lesen (Bitfaeule, veraenderte oder
        verschwundene Dateien) - nach Rueckfrage, als eigener Schritt."""
        with self.beschaeftigt():
            a = self._versuchen(self.ab.nachpruefen_starten, False)
        if a is None or a.get("frage") != "nachpruefen":
            return
        ja, _ = frage(self, "Archiv nachprüfen?", a["text"], ja="Nachprüfen", nein="Nicht jetzt")
        if not ja:
            return
        a = self._versuchen(self.ab.nachpruefen_starten, True)
        if a is None or not a.get("gestartet"):
            return
        self.haupt_zeigen()
        self.lauf_starten(a["gestartet"])

    def zuruecklegen(self) -> None:
        """Den Ordner _geloescht_ an die alten Orte zuruecklegen - nach
        Rueckfrage, als eigener Schritt. Nichts wird ueberschrieben."""
        with self.beschaeftigt():
            a = self._versuchen(self.ab.zuruecklegen_starten, False)
        if a is None or a.get("frage") != "zuruecklegen":
            return
        ja, _ = frage(self, "Zurücklegen?", a["text"], ja="Zurücklegen", nein="Nicht jetzt")
        if not ja:
            return
        a = self._versuchen(self.ab.zuruecklegen_starten, True)
        if a is None or not a.get("gestartet"):
            return
        self.haupt_zeigen()
        self.lauf_starten(a["gestartet"])

    def neuaufbau(self) -> None:
        """Das Ziel vollstaendig neu einlesen (Rettung ohne Sicherung, oder nach
        Umsortieren von Hand im Archiv) - nach Rueckfrage, als eigener Schritt."""
        a = self._versuchen(self.ab.neuaufbau_starten, False)
        if a is None or a.get("frage") != "neuaufbau":
            return
        ja, _ = frage(self, "Archiv neu einlesen?", a["text"], ja="Neu einlesen", nein="Nicht jetzt")
        if not ja:
            return
        a = self._versuchen(self.ab.neuaufbau_starten, True)
        if a is None or not a.get("gestartet"):
            return
        self.haupt_zeigen()
        self.lauf_starten(a["gestartet"])

    def archiv_verwerfen(self) -> None:
        a = self._versuchen(self.ab.archiv_verwerfen, "")
        if a is None or a.get("frage") != "verwerfen":
            return
        ja, wort = frage(self, "Archiv verwerfen?", a["text"], eingabe=True, ja="Verwerfen", nein="Behalten")
        if not ja:
            return
        a = self._versuchen(self.ab.archiv_verwerfen, wort)
        if a is None:
            return
        if a.get("frage"):
            # Leeres Wort: wie ein falsches, nie als Erfolg melden.
            self.meldung(meldungen.ob_wort_falsch(a.get("wort") or meldungen.BESTAETIGUNGSWORT["verwerfen"]))
            return
        self.laden("start")
        self.meldung(a.get("text", ""), gut=True)

    def weitermachen(self) -> None:
        self.letzter_schritt = ""
        self.haupt_zeigen()
        self.ruhe_zeigen()

    # -- Uebersicht --------------------------------------------------------------------

    def haupt_zeigen(self) -> None:
        self.zeige("haupt")
        self.pfade_zeigen()

    def pfade_zeigen(self) -> None:
        z = self.zustand
        _leeren(self.haupt.pfade)
        quellen = list((z.get("archiv") or {}).get("quellen") or []) + list(z.get("quellen_neu") or [])
        for q in quellen:
            self.haupt.pfade.addWidget(tag(q, "tag", breite=300))
        self.haupt.pfade.addWidget(label("→", "pfeil"))
        self.haupt.pfade.addWidget(tag(z.get("ziel") or "–", "tag", breite=300))
        self.haupt.pfade.addStretch(1)
        art = {"hdd": "Festplatte", "ssd": "SSD", "netzwerk": "Netzwerk"}.get(z.get("profil") or "hdd", z.get("profil") or "")
        self.haupt.pfade.addWidget(tag(f'{"Verschieben" if z.get("verschieben") else "Kopieren"}, {art}', "hinweis"))

    def lauf_starten(self, schritt: str) -> None:
        self.letzter_schritt = schritt or self.letzter_schritt
        self.abbruch_zeit = 0.0
        self.haupt.kameras.hide()
        self.haupt.log.hide()
        self.haupt.zaehler.setzen([])
        self.haupt.aktuell.setText("Wird gestartet …")
        self.haupt.phasen.setzen(self.letzter_schritt, 0)
        self.haupt.karten_sperren(True)
        self.lauf_aktionen({"zustand": "startet"})
        self.poll.start()
        self.lauf_abfragen()

    def lauf_abfragen(self) -> None:
        l = self.ab.lauf_status()
        self.lauf = l
        if l.get("schritt"):
            self.letzter_schritt = l["schritt"]
        self.lauf_fuellen(l)
        self.rahmen()
        if l.get("zustand") in ENDE:
            if self.poll.isActive():
                # Der verfolgte Schritt ist eben zu Ende: in der Taskleiste
                # blinken, falls der Nutzer gerade woanders ist.
                QApplication.alert(self, 0)
            self.poll.stop()
            self.ruhe_zeigen(l)

    def lauf_fuellen(self, l: dict) -> None:
        anteil = l.get("anteil")
        self.haupt.balken.setzen(1.0 if l.get("zustand") in ENDE else (anteil or 0.0))
        self.haupt.kennzahlen_setzen(l)
        self.haupt.aktuell.setText(f'{l.get("schritt_name") or ""}: {l.get("zustand_text") or ""}')
        self.haupt.phasen.setzen(l.get("schritt") or "", anteil or 0.0)
        if l.get("zustand") not in ENDE:
            self.lauf_aktionen(l)
        if l.get("log"):
            self.haupt.log.setPlainText(l["log"])
            self.haupt.log.show()
        if l.get("zustand") == "fehler" and l.get("hinweis"):
            # Der Grund (zu wenig Platz, Archiv belegt ...) gross, nicht nur im Protokoll.
            self.meldung(l["hinweis"])

    def lauf_aktionen(self, l: dict) -> None:
        eintraege = [((self.kurzname(self.letzter_schritt) + " läuft …") if self.letzter_schritt else "läuft …", "primary", None, False)]
        if l.get("zustand") == "pause":
            eintraege.append(("Fortsetzen", "secondary", lambda: self.steuern("weiter"), True))
        else:
            eintraege.append(("Pause", "secondary", lambda: self.steuern("pause"), True))
        eintraege.append(("Abbrechen", "secondary", self.abbrechen_fragen, True))
        if self.abbruch_zeit and time.time() - self.abbruch_zeit > 20:
            eintraege.append(("Sofort beenden", "secondary", self.sofort_fragen, True))
        self.aktionen_setzen(eintraege)

    def abbrechen_fragen(self) -> None:
        ja, _ = frage(self, "Schritt abbrechen?", "Das Bisherige bleibt gespeichert; der nächste Lauf macht dort weiter.", ja="Abbrechen", nein="Weiterlaufen lassen")
        if ja:
            self.steuern("abbrechen")

    def sofort_fragen(self) -> None:
        ja, _ = frage(self, "Sofort beenden?", "Der Schritt reagiert nicht. Angefangene Kopien räumt der nächste Lauf auf.", ja="Sofort beenden")
        if ja:
            self.steuern("sofort")

    def steuern(self, wunsch: str) -> None:
        a = self._versuchen(self.ab.steuern, wunsch)
        if a is None:
            return
        if wunsch == "abbrechen":
            self.abbruch_zeit = time.time()
        if a.get("text"):
            self.meldung(a["text"], True)
        self.lauf_abfragen()

    def ruhe_zeigen(self, l: dict | None = None) -> None:
        with self.beschaeftigt():
            self._ruhe_zeigen(l)

    def _ruhe_zeigen(self, l: dict | None = None) -> None:
        self.haupt.karten_sperren(True)
        z = self._versuchen(self.ab.zustand)
        if z is None:
            return
        self.zustand = z
        self.rahmen()
        self.pfade_zeigen()
        lauf = l or z.get("lauf") or {}
        self.lauf = lauf
        if lauf.get("zustand") and lauf["zustand"] not in ENDE:
            self.lauf_starten(lauf.get("schritt", ""))
            return
        n = self._versuchen(self.ab.naechster)
        if n is None:
            self.aktionen_setzen([("Startseite", "secondary", lambda: self.laden("start"), True)])
            return
        self.naechster = n
        letzter = self.letzter_schritt or (lauf.get("schritt") if lauf.get("zustand") in ENDE else "") or self._vorheriger(n["schritt"], (z.get("archiv") or {}).get("zaehler") or {})
        self.letzter_schritt = letzter
        zf = self._versuchen(self.ab.zusammenfassung, letzter)
        if zf is None:
            self.aktionen_setzen([("Startseite", "secondary", lambda: self.laden("start"), True)])
            return
        self.zf = zf
        h = self.haupt
        h.balken.setzen(1.0)
        h.kennzahlen_setzen(lauf if lauf.get("zustand") in ENDE else None)
        h.aktuell.setText(f'{zf.get("name") or ""}: {lauf.get("zustand_text") if lauf.get("zustand") in ENDE and lauf.get("schritt") == letzter else "erledigt"}')
        h.zaehler.setzen(zf.get("zeilen") or [])
        if lauf.get("log") and lauf.get("schritt") == letzter:
            h.log.setPlainText(lauf["log"])
            h.log.show()
        else:
            h.log.hide()
        self.kameras_zeigen(zf.get("modelle") if letzter == "analyse" else None, zf.get("ohne_modell") or 0,
                            zf.get("ohne_modell_ordner") or "")
        if n["schritt"] == "fertig":
            h.phasen.setzen("", 0, alles_fertig=True)
        else:
            h.phasen.setzen(n["schritt"], 0)
        self.karten_fuellen(n, z)
        self.ruhe_aktionen(n, zf)

    @staticmethod
    def _vorheriger(naechster: str, zaehler: dict) -> str:
        if naechster == "fertig":
            return "aufraeumen" if zaehler.get("quelle_geloescht") else "pruefen"
        i = SCHRITTE.index(naechster) if naechster in SCHRITTE else 0
        return SCHRITTE[i - 1] if i > 0 else "scan"

    def ruhe_aktionen(self, n: dict, zf: dict) -> None:
        v = bool(self.zustand.get("verschieben"))
        s = n["schritt"]
        eintraege = []
        if s == "scan":
            eintraege.append(("Startseite: Quellordner angeben", "primary", lambda: self.laden("start"), True))
        elif s == "analyse":
            eintraege.append(("Analyse starten", "primary", lambda: self.schritt_starten("analyse"), True))
        elif s == "pruefen":
            eintraege.append(("Prüfen starten", "primary", lambda: self.schritt_starten("pruefen"), True))
        elif s == "kopieren":
            eintraege.append((f'{"Verschieben" if v else "Kopieren"} starten ({meldungen.anzahl(n.get("n", 0))} Dateien)', "primary", lambda: self.kopieren_starten(n), True))
        elif s == "aufraeumen":
            eintraege.append(("Aufräumen: Wort rechts eintippen", "primary", lambda: self.haupt.auf_wort.setFocus(), True))
        else:
            eintraege.append(("Bericht öffnen", "primary", lambda: self.bericht_oeffnen("neu"), True))
        if zf.get("fehler"):
            eintraege.append((f'Fehler {meldungen.anzahl(zf["fehler"])}', "ghost", lambda: self.liste_zeigen("fehler", 1), True))
        if zf.get("duplikate"):
            eintraege.append((f'Duplikate {meldungen.anzahl(zf["duplikate"])}', "ghost", lambda: self.liste_zeigen("duplikate", 1), True))
        eintraege.append(("Ohne Datum", "ghost", lambda: self.liste_zeigen("ohne_datum", 1), True))
        z = (self.zustand.get("archiv") or {}).get("zaehler") or {}
        if any(z.get(s, 0) for s in ("geprueft", "duplikat_bestaetigt", "quelle_geloescht", "verschoben")):
            eintraege.append(("Archiv nachprüfen…", "ghost", self.nachpruefen, True))
        eintraege.append(("Archiv neu einlesen…", "ghost", self.neuaufbau, True))
        eintraege.append(("Einstellungen", "secondary", self.einstellungen_oeffnen, True))
        eintraege.append(("Startseite", "secondary", lambda: self.laden("start"), True))
        self.aktionen_setzen(eintraege)

    def schritt_starten(self, schritt: str, **extra) -> None:
        a = self._versuchen(lambda: self.ab.schritt(schritt, **extra))
        if a is not None:
            self.lauf_starten(a["gestartet"])

    def kopieren_starten(self, n: dict) -> None:
        if not n.get("wort"):
            self.schritt_starten("kopieren")
            return
        text = n["text"] if f'„{n["wort"]}“' in n["text"] else f'{n["text"]} Zum Bestätigen „{n["wort"]}“ tippen:'
        ja, wort = frage(self, "Verschieben bestätigen", text, eingabe=True, ja="Verschieben")
        if ja:
            self.schritt_starten("kopieren", wort=wort)

    def aufraeumen_starten(self) -> None:
        self.schritt_starten("aufraeumen", weise=self.haupt.auf_weise.wert(), wort=self.haupt.auf_wort.text())

    def ordner_starten(self) -> None:
        self.schritt_starten("aufraeumen", leere_ordner=True, wort_ordner=self.haupt.ordner_wort.text(), wort="")

    # -- Kamera-Tabelle -------------------------------------------------------------------

    def kameras_zeigen(self, modelle, ohne: int, ohne_ordner: str = "") -> None:
        h = self.haupt
        _leeren(h.kameras_lay)
        if not modelle:
            h.kameras.hide()
            return
        t = QTableWidget(len(modelle), 3)
        t.setHorizontalHeaderLabels(["Kameramodell", "Dateien", "Ordnername im Archiv"])
        t.verticalHeader().setVisible(False)
        t.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.alias_felder: list[tuple[str, str, QLineEdit]] = []
        for r, m in enumerate(modelle):
            t.setItem(r, 0, QTableWidgetItem(m["modell"]))
            z = QTableWidgetItem(m["n_text"])
            z.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(r, 1, z)
            feld = QLineEdit(m["ordner"])
            t.setCellWidget(r, 2, feld)
            self.alias_felder.append((m["modell"], m["ordner"], feld))
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        t.setFixedHeight(t.horizontalHeader().height() + 44 * len(modelle) + 4)
        h.kameras_lay.addWidget(t)
        zeile = QHBoxLayout()
        zeile.addWidget(knopf("Ordnernamen übernehmen", "ghost", self.aliase_senden))
        if ohne:
            zeile.addWidget(label(meldungen.ob_ohne_modell(ohne, ohne_ordner), "hinweis"))
        zeile.addStretch(1)
        h.kameras_lay.addLayout(zeile)
        h.kameras.show()

    def aliase_senden(self) -> None:
        neue = {m: f.text().strip() for m, alt, f in getattr(self, "alias_felder", []) if f.text().strip() and f.text().strip() != alt}
        if not neue:
            self.meldung("Kein Ordnername geändert.", True)
            return
        a = self._versuchen(self.ab.aliase_setzen, neue)
        if a is None:
            return
        self.meldung(a.get("text", ""), True)
        if a.get("gestartet"):
            self.lauf_starten(a["gestartet"])

    # -- Karten ---------------------------------------------------------------------------

    def karten_fuellen(self, n: dict, z: dict) -> None:
        h = self.haupt
        plan = n.get("plan")
        _leeren(h.auf_quellen)
        if plan:
            for q in plan["je_quelle"]:
                zeile = QHBoxLayout()
                p = label("")
                kuerzen(p, q["wurzel"], 165)
                zeile.addWidget(p)
                zeile.addStretch(1)
                zeile.addWidget(label(f'{q["n_text"]}, {q["groesse"]}', "hell"))
                h.auf_quellen.addLayout(zeile)
            h.woerter = dict(plan.get("woerter") or h.woerter)
        else:
            h.auf_quellen.addWidget(label("nichts mehr zu entfernen" if n["schritt"] == "fertig" else "erst nach dem Prüfen", "hinweis"))
        darf = bool(plan and plan.get("n", 0) > 0)
        h.k_auf.inaktiv(not darf)
        h.auf_weise.sperren(not darf)
        h.auf_wort.setEnabled(darf)
        h.auf_wort.setText("")
        h.auf_wort_pruefen()
        zurueck = int(n.get("zuruecklegbar", 0) or 0)
        h.zurueck_los.setVisible(zurueck > 0)
        h.zurueck_los.setEnabled(zurueck > 0)
        h.zurueck_los.setText(f"Aus _geloescht_ zurücklegen… ({meldungen.anzahl(zurueck)})")
        archiv_da = bool((z.get("archiv") or {}).get("da"))
        h.k_ordner.inaktiv(not archiv_da)
        h.ordner_wort.setEnabled(archiv_da)
        h.ordner_wort.setText("")
        h.ordner_wort_pruefen()

    # -- Bericht, Einstellungen, Listen -----------------------------------------------------

    def bericht_oeffnen(self, art: str) -> None:
        with self.beschaeftigt():
            a = self._versuchen(self.ab.bericht_oeffnen, art)
        if a is None:
            return
        self.meldung(a.get("text", ""), True)
        if self.zustand.get("archiv") is not None:
            self.zustand["archiv"]["bericht"] = a.get("bericht") or {}
            self.rahmen()

    def einstellungen_oeffnen(self) -> None:
        a = self._versuchen(self.ab.einstellungen_oeffnen)
        if a is not None:
            self.meldung(a.get("text", ""), True)

    def liste_zeigen(self, art: str, seite: int) -> None:
        l = self._versuchen(self.ab.liste, art, seite)
        if l is None:
            return
        if self.ansicht != "liste":
            self.zeige("liste")
        self.listen.fuellen(art, l)
        eintraege = [("Zurück", "primary", self.liste_zurueck, True)]
        for k, info in LISTEN.items():
            if k != art:
                eintraege.append((info[0], "ghost", lambda _c=False, k=k: self.liste_zeigen(k, 1), True))
        self.aktionen_setzen(eintraege)

    def liste_zurueck(self) -> None:
        if self.vorher == "haupt":
            self.haupt_zeigen()
            self.ruhe_zeigen()
        else:
            self.laden("start")

    # -- fuer Selbsttest und Durchlauf -------------------------------------------------------

    def in_ruhe(self) -> bool:
        p = self.primaer()
        return self.ansicht == "haupt" and not self.poll.isActive() and p is not None and p.isEnabled()


# --------------------------------------------------------------- Durchlauf --


class Durchlauf(QObject):
    """Der ganze Ablauf ueber die Bedienelemente - Schritt fuer Schritt, mit Wartezeiten,
    wahlweise mit Bildschirmfoto jeder Ansicht. Beendet die Anwendung mit 0 oder 1."""

    def __init__(self, fenster: Hauptfenster, ziel: str, quelle: str, fotos: Path | None, konsole) -> None:
        super().__init__()
        self.f = fenster
        self.ziel, self.quelle, self.fotos, self.konsole = ziel, quelle, fotos, konsole
        self.stufe = 0
        self.warte_seit = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._weiter)
        self.beginn = time.monotonic()
        self.fehler = ""
        self._in_arbeit = False
        if fotos is not None:
            # Bildschirmfotos immer in der Vorgabegroesse - der virtuelle
            # Bildschirm ohne Anzeige (offscreen) ist nur 800x800 gross.
            self.f.setMinimumSize(1040, 700)
            self.f.resize(1180, 800)

    def starten(self) -> None:
        # Der Durchlauf faehrt bis zum Aufraeumen, ohne eine einzige Rueckfrage.
        # Deshalb laeuft er nur am kuenstlichen Testbaum (SPEC §11), den
        # tests/testbaum.py mit einer Marke versieht - nie an echten Fotos.
        if not (Path(self.quelle).parent / TESTBAUM_MARKE).is_file():
            QTimer.singleShot(0, lambda: self._abbruch(meldungen.ob_durchlauf_nur_testbaum(self.quelle)))
            return
        QTimer.singleShot(300, self.timer.start)

    def _sagen(self, text: str) -> None:
        if self.konsole is not None:
            self.konsole.print(text)

    def _foto(self, name: str) -> None:
        if self.fotos is None:
            return
        self.fotos.mkdir(parents=True, exist_ok=True)
        QApplication.processEvents()
        self.f.grab().save(str(self.fotos / f"{name}.png"))
        self._sagen(f"Foto {name}")

    def _sichten_zeigen(self) -> None:
        """Reiter „Sichten“ (v0.8): oeffnen, das erste Bild mit 4 Sternen als
        Auswahl markieren, fotografieren, zurueck zum Reiter „Archiv“."""
        f = self.f
        f.reiter.knoepfe["sichten"].click()
        f.sichten.pool.waitForDone(20000)
        QApplication.processEvents()
        if f.sichten.raster.count():
            f.sichten.raster.setCurrentRow(0)
            f.sichten.bewerten(sterne=4, markierung="auswahl")
        self._foto("13-sichten")
        f.reiter.knoepfe["archiv"].click()

    def _abbruch(self, text: str) -> None:
        self.timer.stop()
        self.fehler = text
        self._sagen(meldungen.ob_durchlauf(False, text))
        QApplication.exit(1)

    def _weiter(self) -> None:
        # Nie doppelt: Oeffnet ein Schritt einen Dialog oder laesst die
        # Ereignisschleife laufen, darf der Zeitgeber nicht erneut hinein.
        if self._in_arbeit:
            return
        self._in_arbeit = True
        try:
            self._schritt()
        finally:
            self._in_arbeit = False

    def _schritt(self) -> None:
        f = self.f
        if time.monotonic() - self.warte_seit > 300:
            self._abbruch(f"Stufe {self.stufe}: nichts passiert seit 5 Minuten")
            return
        if self.fehler:
            return
        st = self.stufe
        try:
            if st == 0:
                if not f.gezeigt or f.ansicht != "start":
                    return
                self._foto("01-startseite-leer")
                f.start.ziel_setzen(self.ziel)
                f.quelle_hinzufuegen(self.quelle, True)    # Rueckfragen kann niemand beantworten
                self._foto("02-startseite-ausgefuellt")
                f.los(False, True)
                self._naechste()
            elif st == 1:          # Scan laeuft -> Uebersicht
                if f.in_ruhe():
                    self._foto("03-uebersicht-nach-scan")
                    self._klick("Analyse starten")
            elif st == 2:
                if f.in_ruhe():
                    self._foto("04-uebersicht-nach-analyse-kameras")
                    self._beispielstand()
                    self._naechste()
            elif st == 3:          # Beispiel eines laufenden Schritts (Kopieren, mit Pause)
                if f.poll.isActive() and "1.284" in "".join(l.text() for l in f.haupt.findChildren(QLabel)):
                    self._foto("05-laufender-schritt-kopieren")
                    self._beispielstand("pause")
                    self._naechste()
            elif st == 4:
                if f.lauf.get("zustand") == "pause":
                    self._foto("06-laufender-schritt-pause")
                    self._beispielstand("fertig")
                    self._naechste()
            elif st == 5:
                if f.in_ruhe():
                    self._klick("Kopieren starten")
            elif st == 6:
                if f.in_ruhe():
                    self._foto("07-uebersicht-nach-kopieren")
                    self._sichten_zeigen()
                    self._klick("Prüfen starten")
            elif st == 7:
                if f.in_ruhe():
                    self._foto("08-uebersicht-nach-pruefen-aufraeumen-karte")
                    f.haupt.auf_wort.setText(f.haupt.auf_wort_soll())
                    if not f.haupt.auf_los.isEnabled():
                        self._abbruch("Aufräumen-Knopf bleibt gesperrt, obwohl das Wort stimmt")
                        return
                    self._foto("09-aufraeumen-bestaetigt")
                    f.liste_zeigen("duplikate", 1)
                    self._foto("10-liste-duplikate")
                    f.liste_zurueck()
                    self._naechste()
            elif st == 8:
                if f.in_ruhe():
                    f.haupt.auf_wort.setText(f.haupt.auf_wort_soll())
                    f.haupt.auf_los.click()
                    self._naechste()
            elif st == 9:
                if f.in_ruhe():
                    self._foto("11-uebersicht-nach-aufraeumen-fertig")
                    d = Dialog(f, "Ordner anlegen?", meldungen.ob_frage_ziel_anlegen(str(Path(self.ziel).with_name(Path(self.ziel).name + "_neu"))), ja="Anlegen")
                    d.show()
                    QApplication.processEvents()
                    if self.fotos is not None:
                        d.grab().save(str(self.fotos / "12-dialog-ordner-anlegen.png"))
                        self._sagen("Foto 12-dialog-ordner-anlegen")
                    d.reject()
                    self._pruefen()
        except Exception as fehler:  # noqa: BLE001 - der Durchlauf meldet, statt abzustuerzen
            self._abbruch(f"{type(fehler).__name__}: {fehler}")

    def _naechste(self) -> None:
        self.stufe += 1
        self.warte_seit = time.monotonic()

    def _klick(self, anfang: str) -> None:
        p = self.f.primaer()
        if p is None or not p.text().startswith(anfang):
            self._abbruch(f'erwartet Knopf „{anfang}“, gefunden „{p.text() if p else "-"}“')
            return
        p.click()
        self._naechste()

    def _beispielstand(self, zustand: str = "laeuft") -> None:
        """Ein Stand wie mitten im Kopieren, fuer die Bilder des laufenden Schritts.
        Der Testbaum ist zu klein, um ihn dort zu erwischen."""
        from .. import steuerung
        jetzt = time.time()
        ab = self.f.ab
        alt = steuerung.json_lesen(ab.status_datei) or {}
        if zustand == "laeuft":
            daten = {"schritt": "kopieren", "zustand": "laeuft", "pid": os.getpid(), "beginn": jetzt - 312, "aktualisiert": jetzt,
                     "dateien": 1284, "gesamt": 3912, "bytes": int(18.6 * 1024 ** 3), "gesamt_bytes": int(48.2 * 1024 ** 3),
                     "bytes_pro_s": 186 * 1024 ** 2, "restzeit_s": 720, "restzeit_zustand": "geschaetzt", "sekunden": 312, "lauf": 3, "rc": None, "hinweis": ""}
            steuerung.json_schreiben(ab.auftrag_datei, {"schritt": "kopieren", "ziel": self.ziel})
            steuerung.json_schreiben(ab.status_datei, daten)
            self.f.lauf_starten("kopieren")
        elif zustand == "pause":
            alt.update(zustand="pause", aktualisiert=jetzt)
            steuerung.json_schreiben(ab.status_datei, alt)
        else:
            alt.update(zustand="fertig", rc=0, aktualisiert=jetzt)
            steuerung.json_schreiben(ab.status_datei, alt)
            self.f.letzter_schritt = "analyse"   # die echte Zusammenfassung ist die der Analyse

    def _pruefen(self) -> None:
        self.timer.stop()
        try:
            stand = self.f.ab.archiv_lesen()
        except FotosortFehler as fehler:
            self._abbruch(str(fehler))
            return
        z = stand["zaehler"]
        ok = z.get("quelle_geloescht", 0) > 0 and z.get("fehler", 0) == 0 and z.get("geprueft", 0) == 0 and z.get("gefunden", 0) == 0
        self._sagen(meldungen.ob_durchlauf(ok, f'quelle_geloescht {z.get("quelle_geloescht", 0)}, fehler {z.get("fehler", 0)}, Dauer {meldungen.dauer(time.monotonic() - self.beginn)}'))
        QApplication.exit(0 if ok else 1)


# ------------------------------------------------------------------ Start --


APP_ID = "fotosort.fotosortierer"


def eigene_taskleiste() -> None:
    """Unter Windows: eigene Kennung fuer die Taskleiste. Das Fenster laeuft im
    Paket unter pythonw.exe; ohne eigene Kennung zeigte die Taskleiste das
    Python-Symbol und legte das Fenster mit anderen Python-Programmen zusammen.
    So erscheint es als "fotosort" mit dem eigenen Symbol."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):  # pragma: no cover - nur Windows
        pass


INSTANZ_SPERRE = "fenster.sperre"
WECKEN = "wecken"


class Instanz:
    """Nur eine Instanz des Fensters je Benutzer (seit v0.9). Die erste haelt
    eine Sperrdatei im Ordner der Oberflaeche (dieselbe Technik wie die
    Archivsperre). Ein zweiter Start bekommt sie nicht, legt die Datei
    "wecken" ab und endet; die erste sieht sie (Waechter, jede Sekunde) und
    holt ihr Fenster nach vorn. Ohne Netzwerk-Modul, ohne Port."""

    def __init__(self, ordner: Path) -> None:
        from .. import db
        self.ordner = Path(ordner)
        self.sperre = db.Archivsperre(self.ordner / INSTANZ_SPERRE)
        try:
            self.erste = self.sperre.nehmen()
        except FotosortFehler:
            self.erste = True       # nicht sperrbar: lieber ein Fenster zu viel als keins
        if not self.erste:
            if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
                # Sonst darf das erste Fenster nicht nach vorn (Windows blinkt
                # nur in der Taskleiste): Dieser Start erlaubt es ausdruecklich.
                try:
                    import ctypes
                    ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
                except (OSError, AttributeError):
                    pass
            try:
                (self.ordner / WECKEN).write_text(str(time.time()), encoding="utf-8")
            except OSError:
                pass

    def geweckt(self) -> bool:
        """Hat ein zweiter Start angeklopft? (Die Datei wird dabei entfernt.)"""
        datei = self.ordner / WECKEN
        if not datei.exists():
            return False
        try:
            datei.unlink()
        except OSError:
            pass
        return True

    def freigeben(self) -> None:
        self.sperre.freigeben()


def nach_vorn(fenster: QMainWindow) -> None:
    if fenster.isMinimized():
        fenster.showNormal()
    fenster.show()
    fenster.raise_()
    fenster.activateWindow()


def starten(ziel: str | None, selbsttest: bool = False, durchlauf: tuple[str, str] | None = None,
            fotos: str | None = None, konsole=None, config: str | None = None) -> int:
    """Das Desktop-Fenster oeffnen. Rueckgabe wie ein Befehl (0 gut)."""
    from .. import cli
    protokoll = None
    try:
        protokoll = cli.fenster_protokoll()
    except OSError:
        pass
    if (selbsttest or durchlauf) and not os.environ.get("QT_QPA_PLATFORM") and not sys.platform.startswith("win") and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    eigene_taskleiste()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("fotosort")
    app.setApplicationDisplayName("fotosort")
    stil.einrichten(app)
    app.setWindowIcon(stil.programm_symbol())
    meldungsfenster.excepthook_einrichten(protokoll)

    from . import fenster as fenster_modul
    ab = fenster_modul.ablauf_bauen(ziel, config)
    # Nur eine Instanz (seit v0.9): Ein zweiter Start holt das offene Fenster
    # nach vorn und endet. Selbsttest und Durchlauf (CI) laufen unabhaengig.
    if not (selbsttest or durchlauf):
        instanz = Instanz(ab.ordner)
        if not instanz.erste:
            return 0
    ab.fenster = True
    fenster = Hauptfenster(ab, konsole)
    if not (selbsttest or durchlauf):
        fenster.instanz = instanz
    fenster.show()

    if durchlauf:
        d = Durchlauf(fenster, durchlauf[0], durchlauf[1], Path(fotos) if fotos else None, konsole)
        fenster._durchlauf = d
        d.starten()
        return app.exec()
    if selbsttest:
        def pruefen() -> None:
            ok = fenster.gezeigt and (ab.ordner / MARKER).is_file() and fenster.ansicht in ("start", "haupt")
            if konsole is not None:
                konsole.print(meldungen.ob_selbsttest(ok, f"Version {__version__}, Fenster {fenster.width()}×{fenster.height()}"))
            fenster.close()
            app.exit(0 if ok else 1)
        QTimer.singleShot(1500, pruefen)
        return app.exec()
    return app.exec()
