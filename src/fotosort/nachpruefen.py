"""Archiv nachpruefen: "fotosort pruefen --alles" (seit v0.7).

Das normale "pruefen" liest nur Dateien, die neu ins Archiv kamen. Ein
Archiv lebt aber Jahre: Auf der Platte koennen Bits kippen ("Bitfaeule"),
eine Datei kann versehentlich bearbeitet, ueberschrieben oder geloescht
werden. Die Nachpruefung liest JEDE schon gepruefte Datei im Archiv erneut
vollstaendig und vergleicht ihren BLAKE3 mit dem gespeicherten.

Was sie bei einer Abweichung tut, haengt davon ab, ob es die Quelle noch gibt:
  - Quelle noch da (Status geprueft oder duplikat_bestaetigt): Die Zeile
    bekommt Status fehler (Grund beginnt mit "Zielpruefung fehlgeschlagen")
    und verliert damit ihre Loeschberechtigung. Das naechste "kopieren" legt
    aus der Quelle eine frische Kopie an (kopieren.py, "nach fehlgeschlagener
    Pruefung"); die veraenderte Archivdatei bleibt liegen - nie ueberschreiben.
  - Quelle schon geloescht (quelle_geloescht, verschoben): Es gibt keinen
    Ersatz im Programm. Dann nur melden - unuebersehbar in Ausgabe und Bericht
    und mit Rueckgabewert 1 -, damit der Nutzer aus seiner Sicherung holt.
Im Archiv wird nichts veraendert, geloescht oder verschoben.

Dazu schreibt jedes Pruefen die Pruefsummen-Liste .fotosortierer/
pruefsummen.b3 im Format von b3sum ("<hash>  <relativer Pfad>"): Damit laesst
sich das Archiv auch ohne dieses Programm pruefen (b3sum --check).
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from . import db, fortschritt, hashes, meldungen, pfade
from .kopieren import worker_zahlen

ART_FEHLT = "archiv_datei_fehlt"
ART_VERAENDERT = "archiv_datei_veraendert"
ART_NICHT_LESBAR = "archiv_datei_nicht_lesbar"
ART_NACHGEPRUEFT = "archiv_nachgeprueft"      # Abschluss mit Zahlen (Bericht, Oberflaeche)

#: Status, deren Zieldatei schon einmal gepruefte Archivdatei ist.
NACHPRUEFBAR = ("geprueft", "duplikat_bestaetigt", "quelle_geloescht", "verschoben")
#: Hierzu gibt es die Quelle noch: Die Zeile kann neu kopiert werden.
MIT_QUELLE = ("geprueft", "duplikat_bestaetigt")

PRUEFSUMMEN = "pruefsummen.b3"
SEITE = 2000


@dataclass
class Ergebnis:
    geplant: int = 0
    geplant_bytes: int = 0
    bearbeitet: int = 0
    unveraendert: int = 0
    schon_gelesen: int = 0            # in diesem Lauf schon vom normalen Pruefen gelesen
    fehlt: list[str] = field(default_factory=list)
    veraendert: list[str] = field(default_factory=list)
    nicht_lesbar: list[str] = field(default_factory=list)
    neu_zu_kopieren: int = 0          # Zeilen mit Quelle, die jetzt neu kopiert werden
    ohne_quelle: list[str] = field(default_factory=list)   # Archivdatei betroffen, Quelle schon weg
    bytes_gelesen: int = 0
    sekunden: float = 0.0
    abgebrochen: bool = False
    hash_worker: int = 0

    @property
    def befunde(self) -> int:
        return len(self.fehlt) + len(self.veraendert) + len(self.nicht_lesbar)


@dataclass
class _Lesung:
    art: str           # ok | fehlt | abgebrochen | fehler
    hash: str = ""
    groesse: int = 0
    mtime: float = 0.0
    grund: str = ""


def _lesen(pfad: Path, stop: threading.Event) -> _Lesung:
    """Laeuft im Hash-Worker. Nur lesen, nie schreiben."""
    try:
        st = os.stat(pfade.lang(pfad))
    except FileNotFoundError:
        return _Lesung("fehlt")
    except OSError as fehler:
        return _Lesung("fehler", grund=str(fehler.strerror or fehler))
    try:
        h = hashes.blake3_datei(pfade.lang(pfad), stop)
    except hashes.Abgebrochen:
        return _Lesung("abgebrochen")
    except FileNotFoundError:
        return _Lesung("fehlt")
    except OSError as fehler:
        return _Lesung("fehler", grund=str(fehler.strerror or fehler))
    return _Lesung("ok", hash=h, groesse=st.st_size, mtime=st.st_mtime)


def ausfuehren(ziel: Path, konf, dbank: db.Datenbank, lauf: int, konsole=None,
               hash_worker: int | None = None, profil: str | None = None) -> Ergebnis:
    begonnen = time.monotonic()
    _kw, hw, _prof = worker_zahlen(konf, profil, None, hash_worker)
    e = Ergebnis(hash_worker=hw)
    e.geplant, e.geplant_bytes = dbank.nachpruefbar_summe(NACHPRUEFBAR)
    if e.geplant == 0:
        return e
    if konsole is not None:
        konsole.print(meldungen.nachpruefen_beginnt(e.geplant, e.geplant_bytes, hw))
    anzeige = fortschritt.Fortschritt(konsole, e.geplant, e.geplant_bytes, meldungen.nachpruefen_laeuft)
    stop = threading.Event()
    pool = ThreadPoolExecutor(max_workers=hw, thread_name_prefix="nachpruefen")
    offen: deque[tuple[object, Future | None]] = deque()
    max_offen = max(4, hw * 4)
    ab = ""
    erschoepft = False
    try:
        while True:
            while len(offen) < max_offen and not erschoepft:
                seite = dbank.nachpruefbar(NACHPRUEFBAR, ab, SEITE)
                if not seite:
                    erschoepft = True
                    break
                ab = seite[-1]["zielpfad"]
                for z in seite:
                    if _schon_gelesen(dbank, z, lauf):
                        offen.append((z, None))
                        continue
                    offen.append((z, pool.submit(_lesen, Path(db.text_pfad(z["zielpfad"])), stop)))
            if not offen:
                break
            if offen[0][1] is not None:
                wait([offen[0][1]], timeout=1.0)
            while offen and (offen[0][1] is None or offen[0][1].done()):
                z, zukunft = offen.popleft()
                if zukunft is None:
                    e.bearbeitet += 1
                    e.schon_gelesen += 1
                    e.unveraendert += 1
                    anzeige.weiter(1, int(z["groesse"]))
                    continue
                _verbuchen(z, zukunft.result(), dbank, lauf, e, anzeige)
    except KeyboardInterrupt:
        e.abgebrochen = True
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
    finally:
        anzeige.stop()
        pool.shutdown(wait=True)
        dbank.stapel_schreiben()
    e.sekunden = time.monotonic() - begonnen
    if not e.abgebrochen:
        dbank.ereignis(lauf, ART_NACHGEPRUEFT, db.pfad_text(Path(ziel)), e.bearbeitet, meldungen.ereignis_nachgeprueft(e))
        dbank.stapel_schreiben()
    return e


def _schon_gelesen(dbank: db.Datenbank, z, lauf: int) -> bool:
    """Hat das normale Pruefen desselben Laufs die Datei eben erst gelesen
    (Ziel-Index: gelesen in diesem Lauf, gleicher Hash)? Dann nicht noch einmal."""
    eintrag = dbank.ziel_index_nach_pfad(z["zielpfad"])
    return (eintrag is not None and eintrag["zuletzt_gelesen_in_lauf"] == lauf
            and eintrag["hash"] == z["hash"] and int(eintrag["groesse"]) == int(z["groesse"]))


def _verbuchen(z, L: _Lesung, dbank: db.Datenbank, lauf: int, e: Ergebnis, anzeige) -> None:
    if L.art == "abgebrochen":
        return
    zielpfad = z["zielpfad"]
    e.bearbeitet += 1
    anzeige.weiter(1, L.groesse if L.art == "ok" else 0)
    if L.art == "ok":
        e.bytes_gelesen += L.groesse
        dbank.ziel_index_setzen(zielpfad, L.groesse, L.mtime, L.hash, lauf)
        if L.hash == z["hash"] and L.groesse == int(z["groesse"]):
            e.unveraendert += 1
            return
        e.veraendert.append(zielpfad)
        _abweichung(dbank, lauf, e, zielpfad, ART_VERAENDERT, meldungen.GRUND_NACHPRUEFUNG_VERAENDERT)
        return
    if L.art == "fehlt":
        e.fehlt.append(zielpfad)
        dbank.ziel_index_entfernen(zielpfad)
        _abweichung(dbank, lauf, e, zielpfad, ART_FEHLT, meldungen.GRUND_NACHPRUEFUNG_FEHLT)
        return
    # Nicht lesbar: vielleicht nur voruebergehend (Netz, gesperrt). Melden,
    # nichts umstellen - geloescht wird ohnehin nur nach frischem Lesen.
    e.nicht_lesbar.append(zielpfad)
    dbank.ereignis(lauf, ART_NICHT_LESBAR, zielpfad, 1, L.grund or meldungen.GRUND_PRUEFUNG_LESEN)


def _abweichung(dbank: db.Datenbank, lauf: int, e: Ergebnis, zielpfad: str, art: str, grund: str) -> None:
    """Alle Zeilen zu dieser Archivdatei: mit Quelle -> fehler (neu kopieren),
    ohne Quelle -> nur melden."""
    mit_quelle = 0
    for z in dbank.zeilen_mit_zielpfad(zielpfad):
        if z["status"] in MIT_QUELLE:
            dbank.status_setzen(z["quellpfad"], "fehler", grund)
            mit_quelle += 1
    e.neu_zu_kopieren += mit_quelle
    if not mit_quelle:
        e.ohne_quelle.append(zielpfad)
    dbank.ereignis(lauf, art, zielpfad, 1, meldungen.ereignis_nachpruefung(grund, bool(mit_quelle)))


# ------------------------------------------------------ Pruefsummen-Liste --


def pruefsummen_pfad(ziel: Path) -> Path:
    return Path(ziel) / db.ARCHIV_UNTERORDNER / PRUEFSUMMEN


def _b3sum_zeile(h: str, rel: str) -> str:
    """Eine Zeile wie b3sum sie schreibt: Hash, zwei Leerzeichen, Pfad. Ein
    Zeilenumbruch oder Rueckstrich im Namen wird maskiert, die Zeile beginnt
    dann mit einem Rueckstrich (wie bei b3sum/sha256sum)."""
    if "\\" in rel or "\n" in rel or "\r" in rel:
        rel = rel.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
        return f"\\{h}  {rel}\n"
    return f"{h}  {rel}\n"


def pruefsummen_schreiben(ziel: Path, dbank: db.Datenbank) -> tuple[Path, int]:
    """Die Liste aller gepruefte Archivdateien mit ihrem BLAKE3 neu schreiben
    (erst .neu, dann an ihren Platz - es ist eine eigene Datei des Programms).
    Pfade relativ zum Ziel mit "/"."""
    ziel = Path(ziel)
    pfad = pruefsummen_pfad(ziel)
    neu = pfad.with_name(pfad.name + ".neu")
    pfade.lang(pfad.parent).mkdir(parents=True, exist_ok=True)
    wurzel = db.pfad_text(ziel).rstrip("/\\")
    n = 0
    with open(pfade.lang(neu), "w", encoding="utf-8", newline="\n") as f:
        for z in dbank.nachpruefbar_alle(NACHPRUEFBAR):
            zp = z["zielpfad"]
            if not zp.startswith(wurzel) or zp[len(wurzel):len(wurzel) + 1] not in ("/", "\\"):
                continue
            rel = zp[len(wurzel) + 1:].replace("\\", "/") if os.sep == "\\" else zp[len(wurzel) + 1:]
            f.write(_b3sum_zeile(z["hash"], rel))
            n += 1
        f.flush()
        os.fsync(f.fileno())
    pfade.geduldig(os.replace, pfade.lang(neu), pfade.lang(pfad))
    return pfad, n
