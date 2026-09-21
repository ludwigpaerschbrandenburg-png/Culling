"""Phase 4: Pruefen (SPEC Abschnitt 4 Phase 4, Abschnitt 5).

Jede Zieldatei wird vollstaendig neu gelesen und ihr BLAKE3 mit dem beim
Kopieren gespeicherten Quell-Hash verglichen:

  kopiert     -> geprueft            (Zieldatei stimmt)
  duplikat    -> duplikat_bestaetigt (Partnerdatei im Ziel stimmt, SPEC §5)
  verschoben  -> Hash aus der Zieldatei nachgetragen (es gibt keine Quelle
                 mehr zum Vergleichen; Groesse wurde in Phase 3 geprueft)

Stimmt etwas nicht, bekommt die Zeile Status fehler mit Grund. Die
fehlerhafte Zieldatei wird weder geloescht noch ueberschrieben, nur
gemeldet; ein erneutes "kopieren" legt nach den bestehenden Regeln eine
frische Kopie an (kopieren.py, "nach fehlgeschlagener Pruefung").

Gelesen wird parallel mit den Hash-Workern des Profils; entschieden und
in die Datenbank geschrieben wird nur im Hauptstrang. Fortsetzbar: Bearbeitet
werden nur Zeilen, die noch nicht geprueft sind. Der Ziel-Index bekommt die
frisch gelesenen Hashes.

Diese Phase setzt NICHT bestaetigt_in_lauf: Das bedeutet "Quelle UND Ziel
im Lauf frisch gelesen" und ist allein Sache des Aufraeumens (SPEC §5).
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from . import db, fortschritt, hashes, meldungen, pfade
from .kopieren import worker_zahlen

ART_PRUEFUNG_FEHLGESCHLAGEN = "pruefung_fehlgeschlagen"

SEITE = 2000


@dataclass
class Ergebnis:
    geplant: int = 0
    geplant_bytes: int = 0
    bearbeitet: int = 0
    geprueft: int = 0                # kopiert -> geprueft
    duplikate_bestaetigt: int = 0    # duplikat -> duplikat_bestaetigt
    verschoben_gehasht: int = 0      # verschoben: Hash nachgetragen
    fehler: int = 0
    fehler_fehlt: int = 0
    fehler_groesse: int = 0
    fehler_inhalt: int = 0
    fehler_lesen: int = 0
    bytes_gelesen: int = 0
    sekunden: float = 0.0
    abgebrochen: bool = False
    hash_worker: int = 0
    profil: str = ""


@dataclass
class _Lesung:
    art: str          # ok | fehlt | groesse | abgebrochen | fehler
    hash: str = ""
    groesse: int = 0
    mtime: float = 0.0
    grund: str = ""


def _lesen(pfad: Path, stop: threading.Event) -> _Lesung:
    """Laeuft im Hash-Worker. Nur lesen, nie schreiben.

    Liefert immer Groesse UND Hash der Datei, die da liegt. Ob das zur Zeile
    passt, entscheidet der Hauptstrang je Zeile - eine Lesung kann mehreren
    Zeilen dienen (Duplikate zeigen auf dieselbe Partnerdatei).
    """
    try:
        st = os.stat(pfade.lang(pfad))
    except FileNotFoundError:
        return _Lesung("fehlt")
    except OSError as fehler:
        return _Lesung("fehler", grund=f"{meldungen.GRUND_PRUEFUNG_LESEN}: {fehler.strerror or fehler}")
    try:
        h = hashes.blake3_datei(pfade.lang(pfad), stop)
    except hashes.Abgebrochen:
        return _Lesung("abgebrochen")
    except OSError as fehler:
        return _Lesung("fehler", grund=f"{meldungen.GRUND_PRUEFUNG_LESEN}: {fehler.strerror or fehler}")
    return _Lesung("ok", hash=h, groesse=st.st_size, mtime=st.st_mtime)


def ausfuehren(ziel: Path, konf, dbank: db.Datenbank, lauf: int, konsole=None,
               hash_worker: int | None = None, profil: str | None = None) -> Ergebnis:
    begonnen = time.monotonic()
    _kw, hw, prof = worker_zahlen(konf, profil, None, hash_worker)
    e = Ergebnis(hash_worker=hw, profil=prof)
    e.geplant, e.geplant_bytes = dbank.zu_pruefen_summe()
    if e.geplant == 0:
        return e
    if konsole is not None:
        konsole.print(meldungen.pruefen_beginnt(e.geplant, e.geplant_bytes, hw, prof))
    anzeige = fortschritt.Fortschritt(konsole, e.geplant, e.geplant_bytes, meldungen.pruefen_laeuft)
    stop = threading.Event()
    pool = ThreadPoolExecutor(max_workers=hw, thread_name_prefix="pruefen")
    # Mehrere Duplikate zeigen auf dieselbe Partnerdatei: je Lauf nur einmal
    # lesen. Die Zeilen kommen nach Zielpfad sortiert, gleiche Zielpfade
    # liegen also nebeneinander - der Merkspeicher braucht nur den letzten.
    lesungen: dict[str, Future] = {}
    offen: deque[tuple[object, Future]] = deque()
    max_offen = max(4, hw * 4)
    ab_ziel = ab_pfad = ""
    erschoepft = False
    try:
        while True:
            while len(offen) < max_offen and not erschoepft:
                seite = dbank.zu_pruefen(ab_ziel, ab_pfad, SEITE)
                if not seite:
                    erschoepft = True
                    break
                ab_ziel, ab_pfad = seite[-1]["zielpfad"], seite[-1]["quellpfad"]
                for z in seite:
                    zp = z["zielpfad"]
                    zukunft = lesungen.get(zp)
                    neu = zukunft is None
                    if neu:
                        lesungen.clear()
                        zukunft = pool.submit(_lesen, Path(db.text_pfad(zp)), stop)
                        lesungen[zp] = zukunft
                    offen.append((z, zukunft, neu))
            if not offen:
                break
            # Verbucht wird streng der Reihe nach: Es genuegt, auf die vorderste
            # Lesung zu warten (mit Zeitgrenze, damit Strg+C jederzeit ankommt).
            wait([offen[0][1]], timeout=1.0)
            while offen and offen[0][1].done():
                z, zukunft, gelesen = offen.popleft()
                _verbuchen(z, zukunft.result(), dbank, lauf, e, anzeige, gelesen)
    except KeyboardInterrupt:
        e.abgebrochen = True
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
    finally:
        anzeige.stop()
        pool.shutdown(wait=True)
        dbank.stapel_schreiben()
    e.sekunden = time.monotonic() - begonnen
    return e


def _verbuchen(z, L: _Lesung, dbank: db.Datenbank, lauf: int, e: Ergebnis, anzeige, gelesen: bool) -> None:
    """gelesen: diese Zeile hat die Datei selbst lesen lassen (zaehlt Bytes);
    Duplikate teilen sich die Lesung ihrer Partnerdatei."""
    quellpfad = z["quellpfad"]
    zielpfad = Path(db.text_pfad(z["zielpfad"]))
    if L.art == "abgebrochen":
        return  # bleibt im alten Status, naechster Lauf macht weiter
    e.bearbeitet += 1
    anzeige.weiter(1, L.groesse if (L.art == "ok" and gelesen) else 0)
    if L.art == "ok" and L.groesse != int(z["groesse"]):
        # Die Groesse muss fuer JEDE Zeile stimmen - auch fuer ein Duplikat
        # (gleicher Inhalt heisst gleiche Groesse) und fuer eine verschobene
        # Datei (die hat sonst keinen Vergleichswert).
        L = _Lesung("groesse", groesse=L.groesse, mtime=L.mtime)
    if L.art == "ok":
        if gelesen:
            e.bytes_gelesen += L.groesse
        if z["status"] == "verschoben":
            dbank.verschoben_hash_setzen(quellpfad, L.hash)
            dbank.ziel_index_setzen(zielpfad, L.groesse, L.mtime, L.hash, lauf)
            e.verschoben_gehasht += 1
            return
        if L.hash == z["hash"]:
            dbank.ziel_index_setzen(zielpfad, L.groesse, L.mtime, L.hash, lauf)
            if z["status"] == "duplikat":
                dbank.duplikat_bestaetigt_setzen(quellpfad)
                e.duplikate_bestaetigt += 1
            else:
                dbank.geprueft_setzen(quellpfad)
                e.geprueft += 1
            return
        grund = meldungen.GRUND_PRUEFUNG_INHALT
        e.fehler_inhalt += 1
        # Der Ziel-Index bekommt den wahren Hash der Datei, die da liegt -
        # als Kandidat fuer die Duplikatsuche, nie als Loeschgrund.
        dbank.ziel_index_setzen(zielpfad, L.groesse, L.mtime, L.hash, lauf)
    elif L.art == "fehlt":
        grund = meldungen.GRUND_PRUEFUNG_FEHLT
        e.fehler_fehlt += 1
        dbank.ziel_index_entfernen(zielpfad)
    elif L.art == "groesse":
        grund = meldungen.grund_pruefung_groesse(int(z["groesse"]), L.groesse)
        e.fehler_groesse += 1
        # Der alte Eintrag im Ziel-Index beschreibt die Datei nicht mehr.
        dbank.ziel_index_entfernen(zielpfad)
    else:
        grund = L.grund or meldungen.GRUND_PRUEFUNG_LESEN
        e.fehler_lesen += 1
    e.fehler += 1
    dbank.status_setzen(quellpfad, "fehler", grund)
    dbank.ereignis(lauf, ART_PRUEFUNG_FEHLGESCHLAGEN, quellpfad, 1, f"{db.pfad_text(zielpfad)} | {grund}")
