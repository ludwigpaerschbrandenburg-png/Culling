"""Phase 1: Quellen durchlaufen, zaehlen, in die Datenbank schreiben.

SPEC Abschnitt 4 Phase 1 und Abschnitt 6 ("Zweiter Scan", Tabelle quellen).
Es wird nichts gelesen ausser Name, Groesse und Aenderungsdatum - keine
Metadaten, keine Inhalte, keine Hashes.

Aufbau: Der Durchlauf ueber das Dateisystem (_ablaufen) ist von der
Verbuchung in der Datenbank (_verbuchen) getrennt. Bei mehreren Quellen
laeuft je physischem Laufwerk ein eigener Strang durch das Dateisystem und
legt seine Funde in eine Warteschlange; verbucht wird ausschliesslich im
Hauptstrang. SQLite-Verbindungen sind nicht fuer mehrere Straenge gebaut.
"""

from __future__ import annotations

import fnmatch
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from . import FotosortFehler, dateitypen, loeschen, meldungen, pfade, steuerung

# Ereignisarten in lauf_ereignisse (SPEC Abschnitt 6).
ART_AUSGESCHLOSSEN = "ausgeschlossen"
ART_VERKNUEPFUNG = "verknuepfung_nicht_verfolgt"
ART_INS_ZIEL = "zeigt_ins_ziel"
ART_ORDNER_NICHT_LESBAR = "ordner_nicht_lesbar"
ART_QUELLE_VERAENDERT = "quelle_veraendert"
ART_ABGEBROCHEN = "abgebrochen"
ART_QUELLE_NICHT_ERREICHBAR = "quelle_nicht_erreichbar"
ART_QUELLE_ABGELEHNT = "quelle_abgelehnt"
ART_NICHT_MEHR_VORHANDEN = "quelle_nicht_mehr_vorhanden"

TEXT_QUELLE_VERAENDERT = "Quelle veraendert, wird neu eingeordnet"

GRUND_INS_ZIEL = "zeigt ins Ziel"
GRUND_NACH_TYP = "übersprungen nach Typ"

_ANZEIGE_ALLE = 50

# Hoechstens so viele nicht lesbare Ordner werden namentlich genannt.
_BEISPIELE = 5

# Ohne Terminal hoechstens alle so viele Sekunden eine Zeile ausgeben.
_STILLE_SEKUNDEN = 5.0

# Wie viele Funde die Straenge vorlegen duerfen, bevor sie warten muessen.
# Begrenzt den Speicher: Bei einer halben Million Dateien darf nicht alles
# auf einmal in der Warteschlange liegen.
_WARTESCHLANGE = 2000


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

    def hinzufuegen(self, anderes: "Ergebnis") -> None:
        """Ein Quell-Ergebnis in ein Gesamt-Ergebnis einrechnen."""
        for name in (
            "dateien", "bytes_gesamt", "neu", "unveraendert", "veraendert",
            "verschwunden", "ausgeschlossen", "verknuepfungen", "ins_ziel",
            "fehler", "ordner_nicht_lesbar",
        ):
            setattr(self, name, getattr(self, name) + getattr(anderes, name))
        for typ, n in anderes.je_typ.items():
            self.je_typ[typ] = self.je_typ.get(typ, 0) + n
        for ordner in anderes.nicht_lesbare_ordner:
            if len(self.nicht_lesbare_ordner) < _BEISPIELE:
                self.nicht_lesbare_ordner.append(ordner)
        self.abgebrochen = self.abgebrochen or anderes.abgebrochen
        self.ziel_ausgeschlossen = self.ziel_ausgeschlossen or anderes.ziel_ausgeschlossen


@dataclass
class Gesamt:
    """Ergebnis eines Scans ueber mehrere Quellen (SPEC Abschnitt 4 Phase 1)."""

    je_quelle: dict[str, Ergebnis] = field(default_factory=dict)
    gesamt: Ergebnis = field(default_factory=Ergebnis)
    neue_quellen: list[str] = field(default_factory=list)
    nicht_erreichbar: list[str] = field(default_factory=list)
    abgelehnt: list[tuple[str, str]] = field(default_factory=list)  # (pfad, grund)
    laufwerke: int = 0
    sekunden: float = 0.0

    @property
    def abgebrochen(self) -> bool:
        return self.gesamt.abgebrochen


# ------------------------------------------------------------- Muster ----


@lru_cache(maxsize=256)
def _muster(glob: str) -> re.Pattern[str]:
    return re.compile(fnmatch.translate(glob), re.IGNORECASE)


@lru_cache(maxsize=256)
def _regeln(glob: str) -> tuple[re.Pattern[str], ...]:
    """Ein Muster und, wenn es mit "*/" beginnt, dasselbe ohne diesen Anfang.

    Das Beispiel aus SPEC Abschnitt 9 lautet "*/Papierkorb/*". Ein
    Papierkorb-Ordner ganz oben in der Quelle heisst relativ schlicht
    "Papierkorb/...", und "*/" verlangt mindestens ein Zeichen davor.
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
    """Trifft eines der Ausschlussmuster auf den relativen Pfad zu?

    Ein Ordner wird auch dann getroffen, wenn das Muster auf seinen Inhalt
    zielt ("Papierkorb/*" trifft "Papierkorb").
    """
    if not muster:
        return False
    kandidaten = [relativ]
    if ordner:
        kandidaten.append(relativ + "/")
        kandidaten.append(relativ + "/x")
    for glob in muster:
        for regel in _regeln(glob):
            for kandidat in kandidaten:
                if regel.match(kandidat):
                    return True
    return False


def _ist_verknuepfung(eintrag: os.DirEntry) -> bool:
    try:
        if eintrag.is_symlink():
            return True
    except OSError:
        return False
    if os.name == "nt":  # pragma: no cover - Junctions gibt es nur unter Windows
        try:
            return bool(eintrag.stat(follow_symlinks=False).st_reparse_tag)
        except (OSError, AttributeError):
            return False
    return False


# ------------------------------------------------------------- Funde -----


@dataclass
class Fund:
    """Ein Fund des Dateisystem-Durchlaufs, noch nicht verbucht."""

    art: str  # "datei" | "ordner_fehler" | "verknuepfung" | "ausgeschlossen" | "ins_ziel"
    pfad: Path
    text: str = ""
    typ: str = ""
    groesse: int = 0
    mtime: float = 0.0
    lesbar: bool = True
    zeigt_ins_ziel: bool = False


def _liegt_in_aufgeloest(kind_auf: Path, eltern_auf: Path) -> bool:
    """liegt_in fuer zwei schon aufgeloeste Pfade - ohne erneutes resolve()."""
    k = os.path.normcase(str(kind_auf))
    e = os.path.normcase(str(eltern_auf))
    if k == e:
        return True
    if not e.endswith(os.sep):
        e += os.sep
    return k.startswith(e)


def _ablaufen(
    quelle_auf: Path,
    ziel_auf: Path,
    muster: list[str],
    folgen: bool,
    konf,
    stop: threading.Event | None = None,
) -> Iterator[Fund]:
    """Reiner Dateisystem-Durchlauf einer Quelle. Kein Datenbankzugriff.

    Laeuft bei mehreren Quellen in einem eigenen Strang.

    Tempo (Phase 6): Der aufgeloeste Pfad wird je ORDNER mitgefuehrt, nicht
    je Datei neu berechnet. Eine gewoehnliche Datei in einem gewoehnlichen
    Ordner loest sich immer zu <aufgeloester Ordner>/<Name> auf; nur
    Verknuepfungen brauchen resolve(). Vorher kostete resolve() je Datei
    drei Viertel der Scan-Zeit (50.000 Dateien: 150.000 Aufrufe).
    """
    # (Pfad wie in der Quelle, aufgeloester Pfad, Pfad relativ zur Wurzel)
    stapel: list[tuple[Path, Path, str]] = [(quelle_auf, quelle_auf, "")]
    ziel_kennung = pfade.ordner_kennung(ziel_auf)

    while stapel:
        if stop is not None and stop.is_set():
            return
        ordner, ordner_auf, ordner_rel = stapel.pop()
        try:
            with os.scandir(pfade.lang(ordner)) as eintraege:
                gesammelt = sorted(eintraege, key=lambda e: e.name)
        except OSError as fehler:
            # Ein Ordner, der sich nicht oeffnen laesst, wird gezaehlt und
            # gemeldet. Still zu ueberspringen waere der schlimmste Fall.
            yield Fund("ordner_fehler", ordner, fehler.strerror or str(fehler))
            continue

        for eintrag in gesammelt:
            name = eintrag.name
            pfad = pfade.kurz(eintrag.path)
            relativ = f"{ordner_rel}/{name}" if ordner_rel else name

            try:
                ist_ordner = eintrag.is_dir(follow_symlinks=True)
            except OSError:
                ist_ordner = False

            if ist_ordner:
                verknuepft = _ist_verknuepfung(eintrag)
                if verknuepft and not folgen:
                    yield Fund("verknuepfung", pfad)
                    continue
                if loeschen.ist_papierkorb(name):
                    # Der Ordner _geloescht_ wird vom Scan nie angefasst
                    # (SPEC §4 Phase 5): Sonst wuerden die dorthin geraeumten
                    # Dateien als neue Quelldateien erfasst und beim naechsten
                    # Aufraeumen ein zweites Mal entfernt.
                    yield Fund("ausgeschlossen", pfad, "Ordner _geloescht_")
                    continue
                if ist_ausgeschlossen(relativ, muster, ordner=True):
                    yield Fund("ausgeschlossen", pfad, "Ordner")
                    continue
                kind_auf = pfade.aufloesen(pfad) if verknuepft else ordner_auf / name
                if _liegt_in_aufgeloest(kind_auf, ziel_auf) or (
                    ziel_kennung is not None and pfade.ordner_kennung(pfad) == ziel_kennung
                ):
                    # Auch ueber einen zweiten Pfad (Bind-Mount, zweite
                    # Freigabe) erkannt: gleiche Geraete- und Inode-Nummer.
                    yield Fund("ins_ziel", pfad)
                    continue
                stapel.append((pfad, kind_auf, relativ))
                continue

            if ist_ausgeschlossen(relativ, muster):
                yield Fund("ausgeschlossen", pfad, "Datei")
                continue

            # Nur eine Verknuepfung kann woandershin zeigen (SPEC §4 Phase 1).
            zeigt_ins_ziel = False
            if _ist_verknuepfung(eintrag):
                zeigt_ins_ziel = _liegt_in_aufgeloest(pfade.aufloesen(pfad), ziel_auf)
            fund = Fund(
                "datei",
                pfad,
                typ=dateitypen.typ_von(name, konf),
                zeigt_ins_ziel=zeigt_ins_ziel,
            )
            try:
                werte = eintrag.stat(follow_symlinks=True)
                fund.groesse, fund.mtime = werte.st_size, werte.st_mtime
            except OSError as fehler:
                fund.lesbar = False
                fund.text = f"nicht lesbar: {fehler.strerror}"
            yield fund


def _verbuchen(fund: Fund, quelle_auf: Path, dbank, lauf: int, ergebnis: Ergebnis) -> None:
    """Einen Fund in der Datenbank und in den Zaehlern verbuchen. Hauptstrang."""
    if fund.art == "ordner_fehler":
        ergebnis.ordner_nicht_lesbar += 1
        if len(ergebnis.nicht_lesbare_ordner) < _BEISPIELE:
            ergebnis.nicht_lesbare_ordner.append(str(fund.pfad))
        dbank.ereignis(
            lauf, ART_ORDNER_NICHT_LESBAR, fund.pfad, 1, f"Ordner nicht lesbar: {fund.text}"
        )
        return
    if fund.art == "verknuepfung":
        ergebnis.verknuepfungen += 1
        dbank.ereignis(lauf, ART_VERKNUEPFUNG, fund.pfad, 1, "Ordner-Verknuepfung nicht verfolgt")
        return
    if fund.art == "ausgeschlossen":
        ergebnis.ausgeschlossen += 1
        dbank.ereignis(lauf, ART_AUSGESCHLOSSEN, fund.pfad, 1, fund.text)
        return
    if fund.art == "ins_ziel":
        dbank.ereignis(lauf, ART_INS_ZIEL, fund.pfad, 1, "Zielordner vom Scan ausgeschlossen")
        return

    # ---------------------------------------------------------- Datei ----
    # Gespeichert wird der Pfad, unter dem die Datei in der Quelle steht -
    # nicht das aufgeloeste Ziel einer Verknuepfung. Sonst stuende bei einer
    # Verknuepfung ein Pfad ausserhalb der Quelle in quellpfad, im
    # schlimmsten Fall eine Archivdatei.
    gespeichert = fund.pfad
    art = dbank.datei_gesehen(gespeichert, quelle_auf, fund.groesse, fund.mtime, fund.typ, lauf)
    if art == "neu":
        ergebnis.neu += 1
    elif art == "unveraendert":
        ergebnis.unveraendert += 1
    else:
        ergebnis.veraendert += 1
        dbank.ereignis(lauf, ART_QUELLE_VERAENDERT, gespeichert, 1, TEXT_QUELLE_VERAENDERT)

    if art in ("neu", "veraendert"):
        if not fund.lesbar:
            dbank.status_setzen(gespeichert, "fehler", fund.text)
        elif fund.zeigt_ins_ziel:
            dbank.status_setzen(gespeichert, "uebersprungen", GRUND_INS_ZIEL)
        elif fund.typ == dateitypen.SONSTIGES:
            dbank.status_setzen(gespeichert, "uebersprungen", GRUND_NACH_TYP)

    if not fund.lesbar:
        ergebnis.fehler += 1
    if fund.zeigt_ins_ziel:
        ergebnis.ins_ziel += 1

    ergebnis.dateien += 1
    ergebnis.bytes_gesamt += fund.groesse
    ergebnis.je_typ[fund.typ] = ergebnis.je_typ.get(fund.typ, 0) + 1


def _abschliessen(quelle_auf: Path, muster, dbank, lauf: int, ergebnis: Ergebnis) -> None:
    """Nach dem Durchlauf einer Quelle: Verschwundene auswerten.

    Nur nach einem vollstaendigen Durchlauf. Ein Abbruch hat nicht alles
    gesehen, ein nicht lesbarer Ordner ebenfalls nicht - die Dateien
    darunter gaelten sonst als verschwunden (SPEC Abschnitt 6).
    """
    ergebnis.verschwunden_ausgewertet = (
        not ergebnis.abgebrochen and ergebnis.ordner_nicht_lesbar == 0
    )
    if ergebnis.verschwunden_ausgewertet:
        ergebnis.verschwunden = dbank.nicht_mehr_gesehen_zaehlen(quelle_auf, lauf)
        if ergebnis.verschwunden:
            # Fuer den Bericht (SPEC Abschnitt 10): jeden Pfad einzeln.
            for pfad in dbank.nicht_mehr_gesehen(quelle_auf, lauf):
                dbank.ereignis(lauf, ART_NICHT_MEHR_VORHANDEN, pfad, 1, "beim Scan nicht mehr gefunden")
    ergebnis.alles_ausgeschlossen = bool(
        muster and ergebnis.dateien == 0 and ergebnis.ausgeschlossen > 0
    )


# ------------------------------------------------------- eine Quelle ----


def ausfuehren(quelle: Path, ziel: Path, konf, dbank, lauf: int, konsole=None) -> Ergebnis:
    """Den Scan einer einzelnen Quelle durchfuehren.

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

    dbank.quelle_aufnehmen(quelle_auf, pfade.laufwerk_kennung(quelle_auf), lauf)

    muster = [str(m) for m in konf.wert("quelle.ausschlussmuster")]
    folgen = bool(konf.wert("quelle.verknuepfungen_folgen"))

    begonnen = time.monotonic()
    balken, aufgabe = _fortschritt_starten(konsole)
    seit_anzeige = 0
    try:
        try:
            for fund in _ablaufen(quelle_auf, ziel_auf, muster, folgen, konf):
                _verbuchen(fund, quelle_auf, dbank, lauf, ergebnis)
                if fund.art == "datei":
                    seit_anzeige += 1
                    if seit_anzeige >= _ANZEIGE_ALLE:
                        _fortschritt_zeigen(balken, aufgabe, ergebnis, seit_anzeige)
                        steuerung.melden(ergebnis.dateien, 0, ergebnis.bytes_gesamt, 0)
                        seit_anzeige = 0
            steuerung.melden(ergebnis.dateien, 0, ergebnis.bytes_gesamt, 0)   # Endstand
        except KeyboardInterrupt:
            ergebnis.abgebrochen = True
    finally:
        if balken is not None:
            balken.stop()
        dbank.stapel_schreiben()

    _abschliessen(quelle_auf, muster, dbank, lauf, ergebnis)
    dbank.quelle_gescannt(quelle_auf, lauf, True)
    ergebnis.sekunden = time.monotonic() - begonnen
    return ergebnis


# --------------------------------------------------- mehrere Quellen ----


def quellen_bestimmen(gewuenscht: list[Path], dbank) -> tuple[list[Path], list[Path]]:
    """Welche Quellen dieser Scan durchlaeuft (SPEC Abschnitt 8).

    Mit Angaben: nur die genannten. Ohne Angaben: alle bekannten.
    Gibt (zu scannen, bekannte Wurzeln) zurueck.
    """
    bekannt = [Path(z["wurzel"]) for z in dbank.quellen_liste()]
    if gewuenscht:
        return [Path(q) for q in gewuenscht], bekannt
    return list(bekannt), bekannt


def ausfuehren_mehrere(
    quellen: list[Path], ziel: Path, konf, dbank, lauf: int, konsole=None
) -> Gesamt:
    """Den Scan ueber mehrere Quellen durchfuehren (SPEC Abschnitt 4 Phase 1).

    Ueberschneidungen werden abgelehnt, nicht erreichbare Quellen gemeldet,
    der Rest laeuft weiter. Je physischem Laufwerk ein Strang.
    """
    begonnen = time.monotonic()
    gesamt = Gesamt()
    ziel_auf = pfade.aufloesen(ziel)
    bekannt = {pfade.aufloesen(Path(z["wurzel"])) for z in dbank.quellen_liste()}

    # 1. Pruefen und aufnehmen - noch ohne Dateisystem-Durchlauf.
    angenommen: list[Path] = []
    for roh in quellen:
        quelle = Path(roh)
        quelle_auf = pfade.aufloesen(quelle)
        if quelle_auf in angenommen:
            continue  # zweimal genannt
        if not quelle.is_dir():
            if quelle_auf in bekannt:
                gesamt.nicht_erreichbar.append(str(quelle_auf))
                dbank.quelle_gescannt(quelle_auf, lauf, False)
                dbank.ereignis(lauf, ART_QUELLE_NICHT_ERREICHBAR, quelle_auf, 1, "nicht erreichbar")
                _sagen(konsole, meldungen.quelle_nicht_erreichbar(quelle_auf))
            else:
                grund = meldungen.quelle_existiert_nicht(quelle)
                gesamt.abgelehnt.append((str(quelle_auf), grund))
                _sagen(konsole, grund)
            continue

        # Ueberschneidung mit anderen Quellen (bekannt oder gerade angenommen)
        andere = (bekannt | set(angenommen)) - {quelle_auf}
        ueberschneidung = next(
            (a for a in andere if pfade.liegt_in(quelle_auf, a) or pfade.liegt_in(a, quelle_auf)),
            None,
        )
        if ueberschneidung is not None:
            grund = meldungen.quelle_abgelehnt_ueberschneidung(quelle_auf, ueberschneidung)
            gesamt.abgelehnt.append((str(quelle_auf), grund))
            dbank.ereignis(lauf, ART_QUELLE_ABGELEHNT, quelle_auf, 1, f"ueberschneidet {ueberschneidung}")
            _sagen(konsole, grund)
            continue

        lage = pfade.lage_pruefen(quelle_auf, ziel_auf)
        if lage in ("gleich", "quelle_in_ziel"):
            grund = (
                meldungen.quelle_gleich_ziel(quelle_auf)
                if lage == "gleich"
                else meldungen.quelle_in_ziel(quelle_auf)
            )
            gesamt.abgelehnt.append((str(quelle_auf), grund))
            dbank.ereignis(lauf, ART_QUELLE_ABGELEHNT, quelle_auf, 1, lage)
            _sagen(konsole, grund)
            continue

        neu = dbank.quelle_aufnehmen(quelle_auf, pfade.laufwerk_kennung(quelle_auf), lauf)
        if neu:
            gesamt.neue_quellen.append(str(quelle_auf))
        angenommen.append(quelle_auf)
        ergebnis = Ergebnis()
        if lage == "ziel_in_quelle":
            ergebnis.ziel_ausgeschlossen = True
            _sagen(konsole, meldungen.ziel_in_quelle(ziel_auf))
        gesamt.je_quelle[str(quelle_auf)] = ergebnis

    if not angenommen:
        gesamt.sekunden = time.monotonic() - begonnen
        return gesamt

    muster = [str(m) for m in konf.wert("quelle.ausschlussmuster")]
    folgen = bool(konf.wert("quelle.verknuepfungen_folgen"))

    # 2. Nach Laufwerk gruppieren - innerhalb einer Gruppe nacheinander.
    gruppen: dict[str, list[Path]] = {}
    for q in angenommen:
        gruppen.setdefault(pfade.laufwerk_kennung(q), []).append(q)
    gesamt.laufwerke = len(gruppen)

    balken, aufgabe = _fortschritt_starten(konsole)
    seit_anzeige = 0
    stop = threading.Event()
    warteschlange: "queue.Queue[tuple[Path, Fund | None]]" = queue.Queue(maxsize=_WARTESCHLANGE)

    def strang(liste: list[Path]) -> None:
        try:
            for q in liste:
                for fund in _ablaufen(q, ziel_auf, muster, folgen, konf, stop):
                    warteschlange.put((q, fund))
                    if stop.is_set():
                        return
        finally:
            warteschlange.put((liste[0], None))  # Ende dieses Strangs

    straenge = [threading.Thread(target=strang, args=(liste,), daemon=True) for liste in gruppen.values()]
    try:
        try:
            for s in straenge:
                s.start()
            offen = len(straenge)
            while offen:
                q, fund = warteschlange.get()
                if fund is None:
                    offen -= 1
                    continue
                ergebnis = gesamt.je_quelle[str(q)]
                _verbuchen(fund, q, dbank, lauf, ergebnis)
                if fund.art == "datei":
                    seit_anzeige += 1
                    if seit_anzeige >= _ANZEIGE_ALLE:
                        summe = _summe(gesamt)
                        _fortschritt_zeigen(balken, aufgabe, summe, seit_anzeige)
                        steuerung.melden(summe.dateien, 0, summe.bytes_gesamt, 0)
                        seit_anzeige = 0
            summe = _summe(gesamt)
            steuerung.melden(summe.dateien, 0, summe.bytes_gesamt, 0)   # Endstand
        except KeyboardInterrupt:
            stop.set()
            for e in gesamt.je_quelle.values():
                e.abgebrochen = True
            # Die Straenge leeren lassen, damit sie nicht an put() haengen.
            while any(s.is_alive() for s in straenge):
                try:
                    warteschlange.get(timeout=0.1)
                except queue.Empty:
                    pass
    finally:
        stop.set()
        if balken is not None:
            balken.stop()
        dbank.stapel_schreiben()

    # 3. Je Quelle abschliessen.
    for q in angenommen:
        ergebnis = gesamt.je_quelle[str(q)]
        _abschliessen(q, muster, dbank, lauf, ergebnis)
        dbank.quelle_gescannt(q, lauf, True)
        gesamt.gesamt.hinzufuegen(ergebnis)
    gesamt.gesamt.verschwunden_ausgewertet = all(
        e.verschwunden_ausgewertet for e in gesamt.je_quelle.values()
    )
    gesamt.gesamt.alles_ausgeschlossen = all(
        e.alles_ausgeschlossen for e in gesamt.je_quelle.values()
    )
    gesamt.sekunden = time.monotonic() - begonnen
    gesamt.gesamt.sekunden = gesamt.sekunden
    return gesamt


def _summe(gesamt: Gesamt) -> Ergebnis:
    summe = Ergebnis()
    for e in gesamt.je_quelle.values():
        summe.hinzufuegen(e)
    return summe


# ----------------------------------------------------------- Fortschritt ----


def _sagen(konsole, text: str) -> None:
    if konsole is not None:
        konsole.print(text)


class _StilleAnzeige:
    """Fortschritt ohne Terminal: hoechstens alle fuenf Sekunden eine Zeile.

    Im Container, mit umgeleiteter Ausgabe und im spaeteren Betrieb auf dem
    Server gibt es kein Terminal. Ohne diese Anzeige bliebe das Programm bei
    einer halben Million Dateien minutenlang voellig still.
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
