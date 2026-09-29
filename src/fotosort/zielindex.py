"""Ziel-Index neu aufbauen (SPEC Abschnitt 6 "Ziel-Index", Abschnitt 8).

"fotosort ziel-index --neu-aufbauen" liest jede Datei im Zielordner, berechnet
ihren BLAKE3 und baut die Tabelle ziel_index vollstaendig neu auf. Gebraucht,
wenn lokale Datenbank und Sicherungskopie beide fehlen, oder wenn im Ziel von
Hand etwas veraendert wurde. Im Ziel wird nichts geloescht und nichts
verschoben; entfernt werden nur Zeilen des Index, zu denen keine Datei mehr
liegt.

Uebergangen werden der Programmordner .fotosortierer in der Zielwurzel,
vorruebergehende Messordner (.fotosort_messung_*), Verknuepfungen (nie
verfolgt, wie beim Scan) und liegengebliebene .part-Dateien - die gehoeren
keinem fertigen Bild und werden vom naechsten "kopieren" aufgeraeumt.

Gelesen wird parallel mit den Hash-Workern des Profils; geschrieben nur im
Hauptstrang, in der Reihenfolge des Durchlaufs (Ordner fuer Ordner, damit
eine Festplatte moeglichst hintereinander liest). Strg+C bricht sauber ab.
Fortsetzbar: Zeilen, die ein nicht beendeter Neuaufbau schon gelesen hat
(zuletzt_gelesen_in_lauf = dessen Lauf-Nummer) und deren Groesse und
Aenderungsdatum unveraendert sind, werden uebernommen statt erneut gehasht.

Der Index darf nur entscheiden, ob kopiert wird. Er berechtigt nie allein
zu einer Loeschung (SPEC Abschnitt 6) - auch nicht nach einem Neuaufbau.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from . import db, fortschritt, hashes, meldungen, messen, pfade, steuerung
from .kopieren import worker_zahlen

ART_NICHT_LESBAR = "ziel_index_nicht_lesbar"
ART_NEU_AUFGEBAUT = "ziel_index_neu_aufgebaut"

#: Woran ein Neuaufbau-Lauf in der Tabelle laeufe erkannt wird (Fortsetzen).
BEFEHLSTEILE = ("ziel-index", "--neu-aufbauen")


@dataclass
class Ergebnis:
    geplant: int = 0                 # Dateien im Ziel (ohne Uebergangenes)
    geplant_bytes: int = 0
    gehasht: int = 0                 # in diesem Lauf vollstaendig gelesen
    uebernommen: int = 0             # aus einem nicht beendeten Neuaufbau
    fehler: int = 0                  # nicht lesbar oder zwischendurch verschwunden
    entfernt: int = 0                # Indexzeilen, zu denen keine Datei liegt
    verknuepfungen: int = 0
    part_dateien: int = 0
    ordner_nicht_lesbar: int = 0
    bytes_gelesen: int = 0
    sekunden: float = 0.0
    abgebrochen: bool = False
    hash_worker: int = 0
    profil: str = ""
    fortgesetzt_von_lauf: int | None = None


@dataclass(slots=True)
class _Datei:
    pfad: str          # Schreibweise der Datenbank (db.pfad_text)
    groesse: int
    mtime: float


@dataclass
class _Lesung:
    art: str           # ok | fehlt | abgebrochen | fehler
    hash: str = ""
    groesse: int = 0
    mtime: float = 0.0
    grund: str = ""


def _ist_verknuepfung(eintrag: os.DirEntry) -> bool:
    if eintrag.is_symlink():
        return True
    pruefen = getattr(eintrag, "is_junction", None)   # Python 3.12: Windows-Junctions
    return bool(pruefen and pruefen())


def dateien_im_ziel(ziel: Path, e: Ergebnis) -> list[_Datei]:
    """Alle Dateien unter dem Ziel, Ordner fuer Ordner, Namen sortiert.

    Ein Durchlauf mit os.scandir; die Groesse kommt aus dem Verzeichniseintrag
    mit. Uebergangenes wird nur gezaehlt.
    """
    ziel = Path(ziel)
    gefunden: list[_Datei] = []
    stapel: list[Path] = [ziel]
    while stapel:
        # Schon beim Durchsuchen melden: Fortschritt fuer das Fenster, und ein
        # Abbruchwunsch greift hier (KeyboardInterrupt), nicht erst danach.
        steuerung.melden(len(gefunden), 0, 0, 0)
        ordner = stapel.pop()
        try:
            with os.scandir(pfade.lang(ordner)) as eintraege:
                sortiert = sorted(eintraege, key=lambda x: x.name)
        except OSError:
            e.ordner_nicht_lesbar += 1
            continue
        unterordner: list[Path] = []
        for eintrag in sortiert:
            if _ist_verknuepfung(eintrag):
                e.verknuepfungen += 1
                continue
            pfad = ordner / eintrag.name
            try:
                if eintrag.is_dir(follow_symlinks=False):
                    if ordner == ziel and eintrag.name == db.ARCHIV_UNTERORDNER:
                        continue
                    if eintrag.name.startswith(messen.MESSORDNER_PRAEFIX):
                        continue
                    unterordner.append(pfad)
                    continue
                if not eintrag.is_file(follow_symlinks=False):
                    continue
                if eintrag.name.lower().endswith(".part"):
                    e.part_dateien += 1
                    continue
                st = eintrag.stat(follow_symlinks=False)
            except OSError:
                e.fehler += 1
                continue
            gefunden.append(_Datei(db.pfad_text(pfad), st.st_size, st.st_mtime))
        # Der Stapel gibt das zuletzt Abgelegte zuerst her: Unterordner
        # umgekehrt ablegen, damit sie alphabetisch durchlaufen werden.
        stapel.extend(reversed(unterordner))
    return gefunden


def _lesen(pfad: Path, stop: threading.Event) -> _Lesung:
    """Laeuft im Hash-Worker. Nur lesen, nie schreiben."""
    try:
        st = os.stat(pfade.lang(pfad))
    except FileNotFoundError:
        return _Lesung("fehlt")
    except OSError as fehler:
        return _Lesung("fehler", grund=f"{meldungen.GRUND_ZIEL_INDEX_LESEN}: {fehler.strerror or fehler}")
    try:
        h = hashes.blake3_datei(pfade.lang(pfad), stop)
    except hashes.Abgebrochen:
        return _Lesung("abgebrochen")
    except FileNotFoundError:
        return _Lesung("fehlt")
    except OSError as fehler:
        return _Lesung("fehler", grund=f"{meldungen.GRUND_ZIEL_INDEX_LESEN}: {fehler.strerror or fehler}")
    return _Lesung("ok", hash=h, groesse=st.st_size, mtime=st.st_mtime)


def _uebernehmbar(zeile, datei: _Datei, von_lauf: int | None) -> bool:
    """Hat ein nicht beendeter Neuaufbau diese Datei schon gelesen, und ist
    sie seitdem unveraendert (Groesse und Aenderungsdatum)?"""
    if zeile is None or von_lauf is None:
        return False
    if zeile["zuletzt_gelesen_in_lauf"] != von_lauf or not zeile["hash"]:
        return False
    return int(zeile["groesse"]) == datei.groesse and db._gleiche_zeit(zeile["mtime"], datei.mtime)


def neu_aufbauen(ziel: Path, konf, dbank: db.Datenbank, lauf: int, konsole=None,
                 hash_worker: int | None = None, profil: str | None = None) -> Ergebnis:
    begonnen = time.monotonic()
    _kw, hw, prof = worker_zahlen(konf, profil, None, hash_worker)
    e = Ergebnis(hash_worker=hw, profil=prof)
    e.fortgesetzt_von_lauf = dbank.unvollendeter_lauf(BEFEHLSTEILE, vor=lauf)

    if konsole is not None:
        konsole.print(meldungen.ziel_index_durchsucht(ziel))
    try:
        dateien = dateien_im_ziel(ziel, e)
    except KeyboardInterrupt:
        e.abgebrochen = True
        e.sekunden = time.monotonic() - begonnen
        return e
    e.geplant = len(dateien)
    e.geplant_bytes = sum(d.groesse for d in dateien)
    if konsole is not None:
        if e.geplant == 0:
            konsole.print(meldungen.ziel_index_nichts_gefunden(ziel))
        else:
            konsole.print(meldungen.ziel_index_beginnt(e.geplant, e.geplant_bytes, hw, prof, e.fortgesetzt_von_lauf))
    anzeige = fortschritt.Fortschritt(konsole, e.geplant, e.geplant_bytes, meldungen.ziel_index_laeuft)
    stop = threading.Event()
    pool = ThreadPoolExecutor(max_workers=hw, thread_name_prefix="zielindex")
    offen: deque[tuple[_Datei, Future]] = deque()
    max_offen = max(4, hw * 4)
    naechste = 0
    try:
        while True:
            while len(offen) < max_offen and naechste < len(dateien):
                datei = dateien[naechste]
                naechste += 1
                bekannt = dbank.ziel_index_nach_pfad(datei.pfad)
                if _uebernehmbar(bekannt, datei, e.fortgesetzt_von_lauf):
                    dbank.ziel_index_setzen(datei.pfad, datei.groesse, datei.mtime, bekannt["hash"], lauf)
                    e.uebernommen += 1
                    anzeige.weiter(1, datei.groesse)
                    continue
                offen.append((datei, pool.submit(_lesen, Path(db.text_pfad(datei.pfad)), stop)))
            if not offen:
                break
            # Verbucht wird der Reihe nach; die Zeitgrenze laesst Strg+C durch.
            wait([offen[0][1]], timeout=1.0)
            while offen and offen[0][1].done():
                datei, zukunft = offen.popleft()
                _verbuchen(datei, zukunft.result(), dbank, lauf, e, anzeige)
    except KeyboardInterrupt:
        e.abgebrochen = True
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
    finally:
        anzeige.stop()
        pool.shutdown(wait=True)
        dbank.stapel_schreiben()
    if not e.abgebrochen:
        e.entfernt = dbank.ziel_index_veraltete_entfernen(lauf)
        dbank.ereignis(lauf, ART_NEU_AUFGEBAUT, db.pfad_text(ziel), e.gehasht + e.uebernommen,
                       meldungen.ereignis_ziel_index_neu_aufgebaut(e))
        dbank.stapel_schreiben()
    e.sekunden = time.monotonic() - begonnen
    return e


def _verbuchen(datei: _Datei, L: _Lesung, dbank: db.Datenbank, lauf: int, e: Ergebnis, anzeige) -> None:
    if L.art == "abgebrochen":
        return   # bleibt, wie es war; der naechste Neuaufbau liest die Datei
    if L.art == "ok":
        # Groesse und Zeit der Datei, die da liegt - nicht die aus dem
        # Durchlauf: Zwischen beidem kann sie geschrieben worden sein.
        dbank.ziel_index_setzen(datei.pfad, L.groesse, L.mtime, L.hash, lauf)
        e.gehasht += 1
        e.bytes_gelesen += L.groesse
        anzeige.weiter(1, L.groesse)
        return
    anzeige.weiter(1, 0)
    e.fehler += 1
    dbank.ziel_index_entfernen(datei.pfad)   # ein Eintrag ohne lesbare Datei taeuscht nur
    grund = meldungen.GRUND_ZIEL_INDEX_FEHLT if L.art == "fehlt" else (L.grund or meldungen.GRUND_ZIEL_INDEX_LESEN)
    dbank.ereignis(lauf, ART_NICHT_LESBAR, datei.pfad, 1, grund)
