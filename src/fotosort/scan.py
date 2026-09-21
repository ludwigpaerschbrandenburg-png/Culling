"""Phase 1: Quelle durchlaufen, zaehlen, in die Datenbank schreiben.

SPEC Abschnitt 4 Phase 1 und Abschnitt 6 ("Zweiter Scan").
Es wird nichts gelesen ausser Name, Groesse und Aenderungsdatum - keine
Metadaten, keine Inhalte, keine Hashes.
"""

from __future__ import annotations

import fnmatch
import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import FotosortFehler, dateitypen, meldungen, pfade

# Ereignisarten in lauf_ereignisse (SPEC Abschnitt 6; die Aufzaehlung dort
# ist mit "z. B." eingeleitet und damit offen).
ART_AUSGESCHLOSSEN = "ausgeschlossen"
ART_VERKNUEPFUNG = "verknuepfung_nicht_verfolgt"
ART_INS_ZIEL = "zeigt_ins_ziel"
# Eigene Kennung statt des unspezifischen "fehler": Der Bericht einer
# spaeteren Phase findet die Zeilen sonst nicht wieder.
ART_ORDNER_NICHT_LESBAR = "ordner_nicht_lesbar"
# "Quelle veraendert, wird neu eingeordnet" (SPEC Abschnitt 10). Die Liste
# muss in der Datenbank stehen, nicht nur als Zaehler im Speicher.
ART_QUELLE_VERAENDERT = "quelle_veraendert"
# Ein geordneter Abbruch - im Unterschied zum Absturz.
ART_ABGEBROCHEN = "abgebrochen"

TEXT_QUELLE_VERAENDERT = "Quelle veraendert, wird neu eingeordnet"

GRUND_INS_ZIEL = "zeigt ins Ziel"
GRUND_NACH_TYP = "übersprungen nach Typ"

_ANZEIGE_ALLE = 50

# Hoechstens so viele nicht lesbare Ordner werden namentlich genannt.
_BEISPIELE = 5

# Ohne Terminal hoechstens alle so viele Sekunden eine Zeile ausgeben.
_STILLE_SEKUNDEN = 5.0


@dataclass
class Ergebnis:
    dateien: int = 0
    bytes_gesamt: int = 0
    je_typ: dict[str, int] = field(default_factory=dict)
    neu: int = 0
    unveraendert: int = 0
    veraendert: int = 0
    verschwunden: int = 0
    ausgeschlossen: int = 0
    verknuepfungen: int = 0
    ins_ziel: int = 0
    fehler: int = 0
    ordner_nicht_lesbar: int = 0
    nicht_lesbare_ordner: list = field(default_factory=list)
    sekunden: float = 0.0
    abgebrochen: bool = False
    ziel_ausgeschlossen: bool = False
    verschwunden_ausgewertet: bool = False
    alles_ausgeschlossen: bool = False


@lru_cache(maxsize=256)
def _muster(glob: str) -> re.Pattern[str]:
    return re.compile(fnmatch.translate(glob), re.IGNORECASE)


@lru_cache(maxsize=256)
def _regeln(glob: str) -> tuple[re.Pattern[str], ...]:
    """Ein Muster und, wenn es mit "*/" beginnt, dasselbe ohne diesen Anfang.

    Das Beispiel aus SPEC Abschnitt 9 lautet "*/Papierkorb/*". Verglichen
    wird gegen den Pfad relativ zur Quellwurzel; ein Papierkorb-Ordner ganz
    oben in der Quelle heisst dort schlicht "Papierkorb/...", und "*/"
    verlangt mindestens ein Zeichen davor. Wer das Beispiel abschreibt, will
    aber ersichtlich jeden Papierkorb treffen - deshalb wird zusaetzlich
    ohne den fuehrenden Anker geprueft.
    """
    regeln = [_muster(glob)]
    if glob.startswith("*/"):
        regeln.append(_muster(glob[2:]))
    return tuple(regeln)


def _relativ(pfad: Path, wurzel: Path) -> str:
    """Pfad relativ zur Quellwurzel, mit Schraegstrich als Trenner."""
    try:
        return pfad.relative_to(wurzel).as_posix()
    except ValueError:
        return pfad.as_posix()


def ist_ausgeschlossen(relativ: str, muster: list[str], ordner: bool = False) -> bool:
    """Trifft eines der Ausschlussmuster? (SPEC Abschnitt 9)

    Verglichen wird gegen den Pfad relativ zur Quellwurzel, mit Schraegstrich
    als Trenner, Gross- und Kleinschreibung wird ignoriert. Ein Ordner wird
    zusaetzlich mit abschliessendem Schraegstrich geprueft, damit ein Muster
    wie "*/Papierkorb/*" den ganzen Ordner samt Inhalt trifft.
    """
    kandidaten = [relativ]
    if ordner:
        kandidaten.append(relativ + "/")
    for glob in muster:
        for regel in _regeln(str(glob)):
            for kandidat in kandidaten:
                if regel.match(kandidat):
                    return True
    return False


def _ist_verknuepfung(eintrag: os.DirEntry) -> bool:
    if eintrag.is_symlink():
        return True
    # Windows-Junctions; unter Linux immer False.
    pruefung = getattr(eintrag, "is_junction", None)
    if pruefung is not None:
        try:
            return bool(pruefung())
        except OSError:  # pragma: no cover
            return False
    return False


def ausfuehren(quelle: Path, ziel: Path, konf, dbank, lauf: int, konsole=None) -> Ergebnis:
    """Den Scan durchfuehren.

    Bricht mit FotosortFehler ab, wenn Quelle und Ziel gleich sind oder die
    Quelle im Ziel liegt (SPEC Abschnitt 4 Phase 1).
    """
    quelle = Path(quelle)
    if not quelle.is_dir():
        raise FotosortFehler(meldungen.quelle_existiert_nicht(quelle))

    quelle_auf = pfade.aufloesen(quelle)
    ziel_auf = pfade.aufloesen(ziel)

    lage = pfade.lage_pruefen(quelle, ziel)
    ergebnis = Ergebnis()
    if lage == "gleich":
        raise FotosortFehler(meldungen.quelle_gleich_ziel(quelle_auf))
    if lage == "quelle_in_ziel":
        raise FotosortFehler(meldungen.quelle_in_ziel(quelle_auf))
    if lage == "ziel_in_quelle":
        ergebnis.ziel_ausgeschlossen = True
        _sagen(konsole, meldungen.ziel_in_quelle(ziel_auf))

    muster = [str(m) for m in konf.wert("quelle.ausschlussmuster")]
    folgen = bool(konf.wert("quelle.verknuepfungen_folgen"))

    begonnen = time.monotonic()
    balken, aufgabe = _fortschritt_starten(konsole)
    try:
        try:
            _durchlaufen(
                quelle_auf,
                ziel_auf,
                muster,
                folgen,
                konf,
                dbank,
                lauf,
                ergebnis,
                balken,
                aufgabe,
            )
        except KeyboardInterrupt:
            ergebnis.abgebrochen = True
    finally:
        if balken is not None:
            balken.stop()
        dbank.stapel_schreiben()

    # "Quelle nicht mehr vorhanden" wird nur nach einem wirklich
    # vollstaendigen Durchlauf ausgewertet. Ein Abbruch hat nicht alles
    # gesehen - und ein Ordner, der sich nicht oeffnen liess, ebenfalls
    # nicht: Die Dateien darunter gaelten sonst als verschwunden, obwohl
    # sie unveraendert da liegen. Genau das passiert bei einem kurzen
    # Aussetzer eines Netzlaufwerks.
    ergebnis.verschwunden_ausgewertet = (
        not ergebnis.abgebrochen and ergebnis.ordner_nicht_lesbar == 0
    )
    if ergebnis.verschwunden_ausgewertet:
        ergebnis.verschwunden = dbank.nicht_mehr_gesehen_zaehlen(quelle_auf, lauf)

    ergebnis.alles_ausgeschlossen = bool(
        muster and ergebnis.dateien == 0 and ergebnis.ausgeschlossen > 0
    )

    ergebnis.sekunden = time.monotonic() - begonnen
    return ergebnis


def _durchlaufen(
    quelle_auf: Path,
    ziel_auf: Path,
    muster: list[str],
    folgen: bool,
    konf,
    dbank,
    lauf: int,
    ergebnis: Ergebnis,
    balken,
    aufgabe,
) -> None:
    stapel: list[Path] = [quelle_auf]
    seit_anzeige = 0

    while stapel:
        ordner = stapel.pop()
        try:
            with os.scandir(pfade.lang(ordner)) as eintraege:
                gesammelt = sorted(eintraege, key=lambda e: e.name)
        except OSError as fehler:
            # Ein Ordner, der sich nicht oeffnen laesst, wird wie eine nicht
            # lesbare Datei behandelt: gezaehlt, gemeldet und am Ende mit
            # einem von Null verschiedenen Rueckgabewert quittiert. Still
            # zu ueberspringen waere der schlimmste Fall - der Nutzer
            # bekaeme "alles in Ordnung" zu sehen, und die Bilder darunter
            # fehlten vollstaendig.
            grund = fehler.strerror or str(fehler)
            ergebnis.ordner_nicht_lesbar += 1
            if len(ergebnis.nicht_lesbare_ordner) < _BEISPIELE:
                ergebnis.nicht_lesbare_ordner.append(str(ordner))
            dbank.ereignis(
                lauf,
                ART_ORDNER_NICHT_LESBAR,
                ordner,
                1,
                f"Ordner nicht lesbar: {grund}",
            )
            continue

        for eintrag in gesammelt:
            # os.scandir gibt den uebergebenen Pfad unveraendert weiter.
            # Unter Windows traegt er das lange Praefix; das muss hier
            # wieder weg, sonst passt kein Vergleich mehr zur Quellwurzel.
            pfad = pfade.kurz(eintrag.path)
            relativ = _relativ(pfad, quelle_auf)

            try:
                ist_ordner = eintrag.is_dir(follow_symlinks=True)
            except OSError:
                ist_ordner = False

            if ist_ordner:
                if _ist_verknuepfung(eintrag) and not folgen:
                    ergebnis.verknuepfungen += 1
                    dbank.ereignis(
                        lauf,
                        ART_VERKNUEPFUNG,
                        pfad,
                        1,
                        "Ordner-Verknuepfung nicht verfolgt",
                    )
                    continue
                if ist_ausgeschlossen(relativ, muster, ordner=True):
                    ergebnis.ausgeschlossen += 1
                    dbank.ereignis(lauf, ART_AUSGESCHLOSSEN, pfad, 1, "Ordner")
                    continue
                if pfade.liegt_in(pfad, ziel_auf):
                    dbank.ereignis(
                        lauf, ART_INS_ZIEL, pfad, 1, "Zielordner vom Scan ausgeschlossen"
                    )
                    continue
                stapel.append(pfad)
                continue

            # ------------------------------------------------ Datei ----
            if ist_ausgeschlossen(relativ, muster):
                ergebnis.ausgeschlossen += 1
                dbank.ereignis(lauf, ART_AUSGESCHLOSSEN, pfad, 1, "Datei")
                continue

            aufgeloest = pfade.aufloesen(pfad)
            zeigt_ins_ziel = pfade.liegt_in(aufgeloest, ziel_auf)
            # Gespeichert wird immer der Pfad, unter dem die Datei in der
            # Quelle steht - nicht das aufgeloeste Ziel einer Verknuepfung.
            # Die Ordner darueber sind bereits aufgeloest (der Durchlauf
            # beginnt an der aufgeloesten Wurzel), die Datei selbst wird es
            # bewusst nicht: Sonst stuende bei einer Verknuepfung ein Pfad
            # ausserhalb der Quelle in der Spalte quellpfad - im
            # schlimmsten Fall eine Archivdatei -, zwei Verknuepfungen auf
            # dieselbe Datei fielen auf eine einzige Zeile zusammen, und
            # ein spaeteres Aufraeumen loeschte das Original ausserhalb der
            # Quelle.
            gespeichert = pfad

            typ = dateitypen.typ_von(eintrag.name, konf)
            grund = ""
            try:
                werte = eintrag.stat(follow_symlinks=True)
                groesse, mtime = werte.st_size, werte.st_mtime
                lesbar = True
            except OSError as fehler:
                groesse, mtime, lesbar = 0, 0.0, False
                grund = f"nicht lesbar: {fehler.strerror}"

            art = dbank.datei_gesehen(
                gespeichert, quelle_auf, groesse, mtime, typ, lauf
            )
            if art == "neu":
                ergebnis.neu += 1
            elif art == "unveraendert":
                ergebnis.unveraendert += 1
            else:
                ergebnis.veraendert += 1
                # Die Berichtsliste "Quelle veraendert, wird neu
                # eingeordnet" (SPEC Abschnitt 10) gehoert in die
                # Datenbank: Aus der Tabelle dateien allein laesst sich
                # der Fall hinterher nicht mehr erkennen, weil eine
                # veraenderte Zeile genauso aussieht wie eine, die seit
                # dem ersten Scan auf "gefunden" steht.
                dbank.ereignis(
                    lauf, ART_QUELLE_VERAENDERT, gespeichert, 1, TEXT_QUELLE_VERAENDERT
                )

            if art in ("neu", "veraendert"):
                if not lesbar:
                    dbank.status_setzen(gespeichert, "fehler", grund)
                elif zeigt_ins_ziel:
                    dbank.status_setzen(gespeichert, "uebersprungen", GRUND_INS_ZIEL)
                elif typ == dateitypen.SONSTIGES:
                    dbank.status_setzen(gespeichert, "uebersprungen", GRUND_NACH_TYP)

            if not lesbar:
                ergebnis.fehler += 1
            if zeigt_ins_ziel:
                ergebnis.ins_ziel += 1

            ergebnis.dateien += 1
            ergebnis.bytes_gesamt += groesse
            ergebnis.je_typ[typ] = ergebnis.je_typ.get(typ, 0) + 1

            seit_anzeige += 1
            if seit_anzeige >= _ANZEIGE_ALLE:
                _fortschritt_zeigen(balken, aufgabe, ergebnis, seit_anzeige)
                seit_anzeige = 0

    if seit_anzeige:
        _fortschritt_zeigen(balken, aufgabe, ergebnis, seit_anzeige)


# ----------------------------------------------------------- Fortschritt ----


def _sagen(konsole, text: str) -> None:
    if konsole is not None:
        konsole.print(text)


class _StilleAnzeige:
    """Fortschritt ohne Terminal: hoechstens alle fuenf Sekunden eine Zeile.

    Im Container, mit umgeleiteter Ausgabe und im spaeteren Betrieb auf dem
    Server gibt es kein Terminal. Ohne diese Anzeige bliebe das Programm bei
    einer halben Million Dateien minutenlang voellig still, und niemand
    koennte unterscheiden, ob es arbeitet oder haengt.
    """

    def __init__(self, konsole) -> None:
        self.konsole = konsole
        self._zuletzt = time.monotonic()

    def zeigen(self, gefunden: int, immer: bool = False) -> None:
        jetzt = time.monotonic()
        if not immer and (jetzt - self._zuletzt) < _STILLE_SEKUNDEN:
            return
        self._zuletzt = jetzt
        self.konsole.print(meldungen.scan_laeuft(gefunden))

    def stop(self) -> None:
        return None


def _fortschritt_zeigen(balken, aufgabe, ergebnis, seit_anzeige: int) -> None:
    """Fortschritt anzeigen - mit Balken im Terminal, sonst als Zeile."""
    if balken is None:
        return
    if isinstance(balken, _StilleAnzeige):
        balken.zeigen(ergebnis.dateien)
        return
    balken.update(
        aufgabe,
        advance=seit_anzeige,
        description=meldungen.scan_laeuft(ergebnis.dateien),
    )


def _fortschritt_starten(konsole):
    """Fortschritt mit rich - hoechstens viermal je Sekunde neu gezeichnet."""
    if konsole is None:
        return None, None
    if not getattr(konsole, "is_terminal", False):
        return _StilleAnzeige(konsole), None
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    balken = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(bar_width=None),
        TimeElapsedColumn(),
        console=konsole,
        refresh_per_second=4,
        transient=True,
    )
    aufgabe = balken.add_task(meldungen.scan_laeuft(0), total=None)
    balken.start()
    return balken, aufgabe
