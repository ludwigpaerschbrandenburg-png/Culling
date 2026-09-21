"""Phase 5: Quelle aufraeumen und leere Ordner entfernen (SPEC Abschnitt 4
Phase 5 und 6, Abschnitt 5).

Geloescht werden ausschliesslich Quelldateien mit Status geprueft oder
duplikat_bestaetigt - und jede einzelne nur ueber loeschen.quelldatei_entfernen,
nach Frischlesung von Quelle UND Ziel im laufenden Lauf. Vorher wird je Quelle
Anzahl und Groesse gezeigt und ein Bestaetigungswort verlangt; --dry-run
zeigt nur die Liste.

Loeschweise: Standard ist der Ordner _geloescht_<Datum> innerhalb der Quelle
(der Nutzer loescht ihn spaeter selbst); endgueltig nur mit --endgueltig.

Leere Ordner: nur wirklich leere. Reste-Dateien laut Konfiguration zaehlen
als leer, aber nur, wenn sie nicht mit echtem Dateityp in der Datenbank
stehen (geprueft, nicht geglaubt). Der Wurzelordner bleibt; der Ordner
_geloescht_ und ein im Quellbaum liegendes Ziel werden nie angefasst.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from . import db, fortschritt, hashes, loeschen, meldungen, pfade
from .kopieren import worker_zahlen
from .scan import ART_QUELLE_NICHT_ERREICHBAR

SEITE = 2000
DRY_RUN_ZEIGEN = 50


@dataclass
class Plan:
    je_quelle: dict[str, tuple[int, int]] = field(default_factory=dict)   # wurzel -> (n, bytes)
    nicht_erreichbar: list[str] = field(default_factory=list)
    unbekannt: list[str] = field(default_factory=list)                    # --quelle, die es nicht gibt
    quellen: list[tuple[str, Path]] = field(default_factory=list)         # (wurzel-Text, Pfad), erreichbar


@dataclass
class Ergebnis:
    geplant: int = 0
    bearbeitet: int = 0
    geloescht: int = 0
    in_papierkorb: int = 0
    nachgetragen: int = 0
    quelle_veraendert: int = 0
    verweigert: int = 0
    bytes_frei: int = 0
    bytes_gelesen: int = 0
    leere_ordner_entfernt: int = 0
    reste_entfernt: int = 0
    reste_verweigert: int = 0
    sekunden: float = 0.0
    abgebrochen: bool = False
    dry_run: bool = False
    weise: str = loeschen.WEISE_PAPIERKORB
    quellen_uebersprungen: list[str] = field(default_factory=list)
    nicht_erreichbar: list[str] = field(default_factory=list)
    dry_run_ordner: dict[str, list[Path]] = field(default_factory=dict)


# ----------------------------------------------------------- Planen -----


def planen(dbank: db.Datenbank, quellen_filter: list | None, lauf: int = 0, ergebnis=None) -> Plan:
    plan = Plan()
    bekannte = {z["wurzel"]: z for z in dbank.quellen_liste()}
    gewuenscht: list[str] | None = None
    if quellen_filter:
        gewuenscht = []
        for q in quellen_filter:
            text = db.pfad_text(pfade.aufloesen(Path(q)))
            if text in bekannte:
                gewuenscht.append(text)
            else:
                plan.unbekannt.append(str(q))
    for wurzel, z in bekannte.items():
        if gewuenscht is not None and wurzel not in gewuenscht:
            continue
        pfad = Path(db.text_pfad(wurzel))
        if not pfad.is_dir():
            plan.nicht_erreichbar.append(wurzel)
            if lauf and ergebnis is not None:
                dbank.ereignis(lauf, ART_QUELLE_NICHT_ERREICHBAR, pfad, 1, meldungen.EREIGNIS_QUELLE_UEBERSPRUNGEN)
            continue
        plan.quellen.append((wurzel, pfad))
    summen = dbank.zu_loeschen_summe([w for w, _ in plan.quellen])
    for wurzel, _ in plan.quellen:
        plan.je_quelle[wurzel] = summen.get(wurzel, (0, 0))
    return plan


# --------------------------------------------------------- Ausfuehren ---


def ausfuehren(
    ziel: Path, konf, dbank: db.Datenbank, lauf: int, konsole=None, *,
    quellen: list | None = None, weise: str = loeschen.WEISE_PAPIERKORB, dry_run: bool = False,
    leere_ordner: bool = False, bestaetigen: Callable[[str, int, int, str], bool] | None = None,
    bestaetigen_ordner: Callable[[str, int], bool] | None = None,
    hash_worker: int | None = None, profil: str | None = None,
) -> Ergebnis:
    begonnen = time.monotonic()
    e = Ergebnis(dry_run=dry_run, weise=weise)
    byte_vergleich = bool(konf.wert("sicherheit.byte_vergleich_vor_loeschen"))
    _kw, hw, _prof = worker_zahlen(konf, profil, None, hash_worker)
    plan = planen(dbank, quellen, lauf, e)
    e.nicht_erreichbar = list(plan.nicht_erreichbar)
    e.geplant = sum(n for n, _ in plan.je_quelle.values())
    reste = [str(r).lower() for r in (konf.wert("aufraeumen.reste_dateien") or [])]

    if dry_run:
        for wurzel, pfad in plan.quellen:
            n, _b = plan.je_quelle[wurzel]
            if n and konsole is not None:
                zeilen = dbank.zu_loeschen(wurzel, "", DRY_RUN_ZEIGEN)
                konsole.print(meldungen.aufraeumen_dry_run_liste(
                    wurzel, [z["quellpfad"] for z in zeilen], max(0, n - len(zeilen))))
            if leere_ordner:
                liste: list[Path] = []
                _ordner_leeren(pfad, pfad, ziel, reste, dbank, lauf, e, True, liste, melden=False)
                e.dry_run_ordner[wurzel] = liste
                if konsole is not None:
                    konsole.print(meldungen.aufraeumen_ordner_dry_run(wurzel, [str(o) for o in liste]))
        e.sekunden = time.monotonic() - begonnen
        return e

    heute = date.today()
    stop = threading.Event()
    pool = ThreadPoolExecutor(max_workers=hw, thread_name_prefix="aufraeumen")
    anzeige = None
    try:
        for wurzel, pfad in plan.quellen:
            n, b = plan.je_quelle[wurzel]
            if n:
                if bestaetigen is None or not bestaetigen(wurzel, n, b, weise):
                    e.quellen_uebersprungen.append(wurzel)
                    if konsole is not None:
                        konsole.print(meldungen.aufraeumen_uebersprungen(wurzel))
                else:
                    if anzeige is None:
                        anzeige = fortschritt.Fortschritt(konsole, e.geplant, 2 * sum(b for _, b in plan.je_quelle.values()),
                                                          meldungen.aufraeumen_laeuft)
                    papierkorb = loeschen.papierkorb_ordner(pfad, heute)
                    _quelle_aufraeumen(wurzel, dbank, lauf, e, pool, stop, anzeige, weise, byte_vergleich, papierkorb)
            if leere_ordner:
                # Vorlauf: zaehlen und melden, nichts anfassen. Ernstfall erst
                # nach Bestaetigung; dort wird nur noch entfernt, nicht gezaehlt.
                liste: list[Path] = []
                _ordner_leeren(pfad, pfad, ziel, reste, dbank, lauf, e, True, liste, melden=True)
                if liste and (bestaetigen_ordner is None or not bestaetigen_ordner(wurzel, len(liste))):
                    if konsole is not None:
                        konsole.print(meldungen.aufraeumen_uebersprungen(wurzel))
                elif liste:
                    _ordner_leeren(pfad, pfad, ziel, reste, dbank, lauf, e, False, [], melden=False)
    except KeyboardInterrupt:
        e.abgebrochen = True
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
    finally:
        if anzeige is not None:
            anzeige.stop()
        pool.shutdown(wait=True)
        dbank.stapel_schreiben()
    e.sekunden = time.monotonic() - begonnen
    return e


def _quelle_aufraeumen(wurzel, dbank, lauf, e, pool, stop, anzeige, weise, byte_vergleich, papierkorb) -> None:
    offen: deque[tuple[object, Future]] = deque()
    max_offen = max(4, pool._max_workers * 4)
    ab = ""
    erschoepft = False
    while True:
        while len(offen) < max_offen and not erschoepft:
            seite = dbank.zu_loeschen(wurzel, ab, SEITE)
            if not seite:
                erschoepft = True
                break
            ab = seite[-1]["quellpfad"]
            for z in seite:
                zukunft = pool.submit(
                    loeschen.frisch_lesen, Path(db.text_pfad(z["quellpfad"])),
                    Path(db.text_pfad(z["zielpfad"])), byte_vergleich, stop,
                )
                offen.append((z, zukunft))
        if not offen:
            break
        wait([offen[0][1]], timeout=1.0)
        while offen and offen[0][1].done():
            z, zukunft = offen.popleft()
            _verbuchen(z, zukunft.result(), dbank, lauf, e, anzeige, weise, byte_vergleich, papierkorb)


def _verbuchen(z, L: loeschen.Lesung, dbank, lauf, e, anzeige, weise, byte_vergleich, papierkorb) -> None:
    quellpfad = z["quellpfad"]
    if L.art == "abgebrochen":
        return
    e.bearbeitet += 1
    gelesen = (L.quell_groesse if L.quell_groesse > 0 else 0) + (L.ziel_groesse if L.ziel_groesse > 0 else 0)
    e.bytes_gelesen += gelesen
    anzeige.weiter(1, gelesen)
    if L.art == "quelle_fehlt":
        _quelle_fehlt(z, dbank, lauf, e)
        return
    try:
        neu = loeschen.quelldatei_entfernen(dbank, lauf, quellpfad, L, weise, byte_vergleich, papierkorb)
    except loeschen.Verweigert as v:
        grund = str(v)
        if grund == meldungen.GRUND_QUELLE_ABWEICHUNG:
            # Der wichtigste Fall: Die Quelle hat sich seit dem Kopieren
            # veraendert. Nicht loeschen, neu kopieren (SPEC Abschnitt 5).
            dbank.zurueck_auf_analysiert_ohne_hash(quellpfad)
            dbank.ereignis(lauf, loeschen.ART_QUELLE_SEIT_KOPIEREN_GEAENDERT, quellpfad, 1, grund)
            e.quelle_veraendert += 1
            return
        dbank.status_setzen(quellpfad, "fehler", grund)
        dbank.ereignis(lauf, loeschen.ART_LOESCHUNG_VERWEIGERT, quellpfad, 1, grund)
        e.verweigert += 1
        return
    e.bytes_frei += int(z["groesse"])
    if neu is None:
        e.geloescht += 1
    else:
        e.in_papierkorb += 1


def _quelle_fehlt(z, dbank, lauf, e) -> None:
    """Quelle nicht mehr da. Nur wenn die Frischlesung eines frueheren Laufs
    festgeschrieben ist UND die Datei nachweislich im Ziel (oder im
    Papierkorb) mit dem gespeicherten Hash liegt, war es unsere Loeschung
    kurz vor einem Absturz: Status nachtragen. Sonst Fehler. Geloescht wird
    hier nichts."""
    quellpfad = z["quellpfad"]
    if z["bestaetigt_in_lauf"] is not None and z["hash"]:
        kandidaten = []
        if z["schreibpfad"]:
            kandidaten.append(Path(db.text_pfad(z["schreibpfad"])))
        kandidaten.append(Path(db.text_pfad(z["zielpfad"])))
        for p in kandidaten:
            try:
                if os.stat(pfade.lang(p)).st_size == int(z["groesse"]) and hashes.blake3_datei(pfade.lang(p)) == z["hash"]:
                    im_papierkorb = z["schreibpfad"] and p == Path(db.text_pfad(z["schreibpfad"]))
                    dbank.quelle_geloescht_setzen(quellpfad, lauf, p if im_papierkorb else None)
                    dbank.ereignis(lauf, loeschen.ART_LOESCHUNG_NACHGETRAGEN, quellpfad, 1, meldungen.EREIGNIS_NACHGETRAGEN)
                    e.nachgetragen += 1
                    return
            except OSError:
                continue
    grund = meldungen.GRUND_QUELLE_FEHLT_LOESCHEN
    dbank.status_setzen(quellpfad, "fehler", grund)
    dbank.ereignis(lauf, loeschen.ART_LOESCHUNG_VERWEIGERT, quellpfad, 1, grund)
    e.verweigert += 1


# ------------------------------------------------------- Leere Ordner ---


def _ordner_leeren(pfad: Path, wurzel: Path, ziel: Path, reste: list[str], dbank, lauf, e,
                   dry_run: bool, liste: list[Path], melden: bool) -> bool:
    """Liefert True, wenn der Ordner leer ist (oder es nach dem Entfernen der
    Reste waere). Entfernt im Ernstfall Reste und dann den Ordner selbst -
    nie den Wurzelordner, nie den Papierkorb, nie das Ziel."""
    ziel_auf = pfade.aufloesen(ziel)
    if pfad != wurzel and (loeschen.ist_papierkorb(pfad.name) or pfade.liegt_in(pfad, ziel_auf) or pfad == ziel_auf):
        return False
    if pfade.liegt_in(ziel_auf, pfad):
        # Das Ziel liegt unterhalb: Dieser Ordner ist nie leer.
        leer_unten = False
    else:
        leer_unten = True
    reste_hier: list[Path] = []
    try:
        with os.scandir(pfade.lang(pfad)) as eintraege:
            kinder = list(eintraege)
    except OSError:
        return False
    leer = leer_unten
    for k in kinder:
        kind = pfad / k.name
        if k.is_symlink():
            leer = False
            continue
        if k.is_dir(follow_symlinks=False):
            if not _ordner_leeren(kind, wurzel, ziel, reste, dbank, lauf, e, dry_run, liste, melden):
                leer = False
            continue
        if k.name.lower() in reste:
            if dbank.echter_typ_bekannt(kind):
                # Name aus reste_dateien, aber ein echtes Foto/Video: bleibt.
                if melden:
                    e.reste_verweigert += 1
                    if lauf:
                        dbank.ereignis(lauf, loeschen.ART_REST_NICHT_ENTFERNT, kind, 1, meldungen.EREIGNIS_REST_NICHT_ENTFERNT)
                leer = False
            else:
                reste_hier.append(kind)
            continue
        leer = False
    if not leer or pfad == wurzel:
        return False
    if dry_run:
        liste.append(pfad)
        return True
    for r in reste_hier:
        os.unlink(pfade.lang(r))
        dbank.ereignis(lauf, loeschen.ART_REST_ENTFERNT, r, 1, meldungen.EREIGNIS_REST_ENTFERNT)
        e.reste_entfernt += 1
    try:
        os.rmdir(pfade.lang(pfad))
    except OSError:
        return False
    dbank.ereignis(lauf, loeschen.ART_LEERER_ORDNER_ENTFERNT, pfad, 1, meldungen.EREIGNIS_LEERER_ORDNER)
    e.leere_ordner_entfernt += 1
    return True
