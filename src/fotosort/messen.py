"""fotosort messen: Lese- und Schreibtempo einer Quelle und eines Ziels
(SPEC Abschnitt 7 und 8, Phase 6).

Gelesen wird eine Stichprobe echter Dateien aus der Quelle (nur lesen und
hashen, nichts wird veraendert); geschrieben wird in einen voruebergehenden
Messordner im Ziel, der am Ende - auch nach Strg+C oder einem Fehler -
wieder entfernt wird. Es entsteht kein Archiv und kein Lauf. Jede Stufe
liest andere Dateien, damit der Zwischenspeicher des Betriebssystems die
Stufen nicht gegeneinander verfaelscht.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import hashes, loeschen, meldungen, pfade

STUFEN: tuple[int, ...] = (1, 2, 4, 8)
MINDEST_LESE_BYTES = 16 * 1024 * 1024
SCHREIB_DATEIEN = 8
MESSORDNER_PRAEFIX = ".fotosort_messung_"
# Bei diesem Abstand vom besten Wert gilt eine Stufe als "gleich gut".
TOLERANZ = 0.9


@dataclass
class Stufe:
    worker: int
    lesen_mb_s: float | None = None
    schreiben_mb_s: float | None = None
    lese_bytes: int = 0
    lese_dateien: int = 0
    schreib_bytes: int = 0


@dataclass
class Ergebnis:
    stufen: list[Stufe] = field(default_factory=list)
    kopier_worker: int = 0
    hash_worker: int = 0
    profil: str = ""
    hinweis: str = ""
    sekunden: float = 0.0
    lesen_gemessen: bool = False
    schreiben_gemessen: bool = False


def dateien_sammeln(quelle: Path, je_stufe_bytes: int, stufen: int) -> list[list[Path]]:
    """Stichprobe: Dateien in Ordnerreihenfolge, reihum auf die Stufen verteilt,
    bis jede Stufe ihre Datenmenge hat. Verknuepfungen, der Ordner _geloescht_
    und .fotosortierer bleiben aussen vor."""
    koerbe: list[list[Path]] = [[] for _ in range(stufen)]
    summen = [0] * stufen
    naechster = 0
    for wurzel, ordner, dateien in os.walk(pfade.lang(quelle)):
        ordner[:] = sorted(
            o for o in ordner
            if not loeschen.ist_papierkorb(o) and o != ".fotosortierer"
            and not os.path.islink(os.path.join(wurzel, o))
        )
        for name in sorted(dateien):
            p = Path(wurzel) / name
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not os.path.isfile(p) or os.path.islink(p) or st.st_size == 0:
                continue
            # Den Korb mit der kleinsten Summe fuellen, bis alle voll sind.
            naechster = min(range(stufen), key=lambda i: summen[i])
            if summen[naechster] >= je_stufe_bytes:
                return koerbe
            koerbe[naechster].append(p)
            summen[naechster] += st.st_size
    return koerbe


def _lesen(dateien: list[Path], worker: int, stop: threading.Event) -> tuple[int, int, float]:
    """(Bytes, Dateien, Sekunden) - alle Dateien vollstaendig lesen und hashen."""
    begonnen = time.monotonic()
    gelesen = 0
    anzahl = 0

    def eine(p: Path) -> int:
        try:
            hashes.blake3_datei(pfade.lang(p), stop)
            return os.stat(pfade.lang(p)).st_size
        except (OSError, hashes.Abgebrochen):
            return 0

    with ThreadPoolExecutor(max_workers=worker) as pool:
        for n in pool.map(eine, dateien):
            if n:
                gelesen += n
                anzahl += 1
            if stop.is_set():
                break
    return gelesen, anzahl, time.monotonic() - begonnen


def _schreiben(ordner: Path, worker: int, gesamt_bytes: int, stop: threading.Event,
               angelegt: list[Path]) -> tuple[int, float]:
    """(Bytes, Sekunden) - SCHREIB_DATEIEN Dateien mit 'worker' gleichzeitigen
    Schreibvorgaengen anlegen (exklusiv, nie ueberschreibend) und mit fsync
    auf die Platte bringen."""
    block = os.urandom(hashes.BLOCK)
    je_datei = max(hashes.BLOCK, gesamt_bytes // SCHREIB_DATEIEN)
    bloecke = max(1, je_datei // hashes.BLOCK)
    sperre = threading.Lock()
    begonnen = time.monotonic()

    def eine(nummer: int) -> int:
        pfad = ordner / f"messung_{worker}_{nummer}.part"
        with sperre:
            angelegt.append(pfad)
        fd = hashes.exklusiv_anlegen(pfade.lang(pfad))
        geschrieben = 0
        try:
            with os.fdopen(fd, "wb", buffering=0) as f:
                for _ in range(bloecke):
                    if stop.is_set():
                        break
                    f.write(block)
                    geschrieben += len(block)
                f.flush()
                os.fsync(f.fileno())
        finally:
            pass
        return geschrieben

    with ThreadPoolExecutor(max_workers=worker) as pool:
        summe = sum(pool.map(eine, range(SCHREIB_DATEIEN)))
    return summe, time.monotonic() - begonnen


def _aufraeumen(ordner: Path | None, angelegt: list[Path]) -> None:
    """Nur entfernen, was diese Messung selbst angelegt hat."""
    for p in angelegt:
        try:
            os.unlink(pfade.lang(p))
        except FileNotFoundError:
            pass
        except OSError:
            pass
    angelegt.clear()
    if ordner is not None:
        try:
            os.rmdir(pfade.lang(ordner))
        except OSError:
            pass


def _messordner_anlegen(ziel: Path) -> Path:
    for _ in range(20):
        kandidat = ziel / f"{MESSORDNER_PRAEFIX}{os.getpid()}_{secrets.token_hex(4)}"
        try:
            pfade.lang(kandidat).mkdir()
            return kandidat
        except FileExistsError:
            continue
    raise OSError(meldungen.messen_nichts_gemessen())


def empfehlung(e: Ergebnis, quelle: Path, ziel: Path) -> None:
    """Kleinste Worker-Zahl, die nahe am besten Wert liegt; Profil danach."""
    mit_lesen = [s for s in e.stufen if s.lesen_mb_s]
    mit_schreiben = [s for s in e.stufen if s.schreiben_mb_s]
    if mit_lesen:
        best = max(s.lesen_mb_s for s in mit_lesen)
        e.hash_worker = min(s.worker for s in mit_lesen if s.lesen_mb_s >= TOLERANZ * best)
    else:
        e.hash_worker = max(1, min(8, os.cpu_count() or 1))
    if mit_schreiben:
        best = max(s.schreiben_mb_s for s in mit_schreiben)
        e.kopier_worker = min(s.worker for s in mit_schreiben if s.schreiben_mb_s >= TOLERANZ * best)
    else:
        e.kopier_worker = 2
    netz = None
    if pfade.ist_netzpfad(ziel):
        netz = "das Ziel"
    elif pfade.ist_netzpfad(quelle):
        netz = "die Quelle"
    if netz:
        e.profil = "netzwerk"
        e.hinweis = meldungen.messen_netz_hinweis(netz)
        return
    profile = {"hdd": 2, "netzwerk": 4, "ssd": 8}
    e.profil = min(profile, key=lambda name: (abs(profile[name] - e.kopier_worker), profile[name]))


def ausfuehren(quelle: Path, ziel: Path, konsole=None, *, mb: int = 256,
               stufen: tuple[int, ...] = STUFEN) -> Ergebnis:
    begonnen = time.monotonic()
    e = Ergebnis()
    stop = threading.Event()
    je_stufe = max(1, mb) * 1024 * 1024
    if konsole is not None:
        konsole.print(meldungen.messen_beginnt(quelle, ziel, mb, stufen))

    koerbe = dateien_sammeln(quelle, je_stufe, len(stufen))
    lese_bytes = [sum(os.stat(pfade.lang(p)).st_size for p in korb) for korb in koerbe]
    lesen_moeglich = min(lese_bytes) >= min(MINDEST_LESE_BYTES, je_stufe)
    if not lesen_moeglich and konsole is not None:
        konsole.print(meldungen.messen_quelle_zu_klein(sum(lese_bytes), MINDEST_LESE_BYTES * len(stufen)))

    frei = pfade.freier_platz(ziel)
    schreiben_moeglich = frei >= 2 * je_stufe
    if not schreiben_moeglich and konsole is not None:
        konsole.print(meldungen.messen_zu_wenig_platz(ziel, 2 * je_stufe, frei))

    ordner: Path | None = None
    angelegt: list[Path] = []
    try:
        if schreiben_moeglich:
            ordner = _messordner_anlegen(ziel)
        if konsole is not None:
            konsole.print("")
            konsole.print(meldungen.messen_tabelle_kopf())
        for i, w in enumerate(stufen):
            s = Stufe(worker=w)
            if lesen_moeglich:
                b, n, sek = _lesen(koerbe[i], w, stop)
                s.lese_bytes, s.lese_dateien = b, n
                s.lesen_mb_s = b / 1e6 / sek if sek > 0 and b else None
                e.lesen_gemessen = e.lesen_gemessen or s.lesen_mb_s is not None
            if schreiben_moeglich and ordner is not None:
                b, sek = _schreiben(ordner, w, je_stufe, stop, angelegt)
                s.schreib_bytes = b
                s.schreiben_mb_s = b / 1e6 / sek if sek > 0 and b else None
                e.schreiben_gemessen = e.schreiben_gemessen or s.schreiben_mb_s is not None
                _aufraeumen(None, angelegt)   # Platz freigeben, Ordner bleibt bis zum Ende
            e.stufen.append(s)
            if konsole is not None:
                konsole.print(meldungen.messen_stufe(w, s.lesen_mb_s, s.schreiben_mb_s))
    except KeyboardInterrupt:
        stop.set()
        raise
    finally:
        _aufraeumen(ordner, angelegt)
    empfehlung(e, quelle, ziel)
    e.sekunden = time.monotonic() - begonnen
    return e
