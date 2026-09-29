"""Archiv nachpruefen: "fotosort pruefen --alles" (seit v0.7).

Das normale "pruefen" liest nur Dateien, die neu ins Archiv kamen. Ein
Archiv lebt aber Jahre: Auf der Platte koennen Bits kippen ("Bitfaeule"),
eine Datei kann versehentlich bearbeitet, ueberschrieben oder geloescht
werden. Die Nachpruefung liest JEDE schon gepruefte Datei im Archiv erneut
vollstaendig und vergleicht ihren BLAKE3 mit dem gespeicherten.

Verglichen wird je Zeile: Zeigen mehrere Zeilen auf dieselbe Archivdatei
(Duplikate, oder ein spaeter unter demselben Namen abgelegtes Bild), wird die
Datei einmal gelesen und das Ergebnis mit jeder Zeile fuer sich verglichen.

Was bei einer Abweichung geschieht, haengt davon ab, ob es die Quelle noch gibt
- nachgesehen, nicht am Status abgelesen (die Karte kann auch ohne "aufraeumen"
formatiert worden sein):
  - Status geprueft oder duplikat_bestaetigt: Die Zeile bekommt Status fehler
    (Grund beginnt mit "Zielpruefung fehlgeschlagen") und verliert damit ihre
    Loeschberechtigung. Liegt die Quelle noch da, legt das naechste "kopieren"
    daraus eine frische Kopie an (kopieren.py, "nach fehlgeschlagener
    Pruefung"); die veraenderte Archivdatei bleibt liegen - nie ueberschreiben.
    Liegt sie nicht mehr da, wird es laut gemeldet (Karte anschliessen oder
    aus der eigenen Sicherung holen).
  - Quelle schon geloescht (quelle_geloescht, verschoben): Es gibt keinen
    Ersatz im Programm. Liegt das Original noch im Papierkorb der Quelle, wird
    er genannt; sonst unuebersehbar melden (Ausgabe, Bericht, Rueckgabewert 1),
    damit der Nutzer aus seiner Sicherung holt.
Ist das ganze Ziel weg (Platte abgezogen, Netz gerissen), fehlt ploetzlich
jede Datei: Dann bricht die Nachpruefung ab und stellt nichts um.
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
from .pruefen import ZielWeg

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
    ohne_quelle: list[str] = field(default_factory=list)   # Archivdatei betroffen, Quelle schon geloescht
    quelle_fehlt: list[str] = field(default_factory=list)  # Status sagt "Quelle da", sie liegt aber nicht mehr da
    im_papierkorb: list[str] = field(default_factory=list)  # Original noch im Papierkorb der Quelle
    ziel_weg: bool = False            # das ganze Ziel war mitten im Lauf nicht mehr erreichbar
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
                _verbuchen(z, zukunft.result(), dbank, lauf, e, anzeige, ziel)
    except (KeyboardInterrupt, ZielWeg) as grund:
        e.abgebrochen = True
        e.ziel_weg = isinstance(grund, ZielWeg)
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
    if int(z["varianten"]) != 1:
        return False
    eintrag = dbank.ziel_index_nach_pfad(z["zielpfad"])
    return (eintrag is not None and eintrag["zuletzt_gelesen_in_lauf"] == lauf
            and eintrag["hash"] == z["hash"] and int(eintrag["groesse"]) == int(z["groesse"]))


def _verbuchen(z, L: _Lesung, dbank: db.Datenbank, lauf: int, e: Ergebnis, anzeige, ziel: Path) -> None:
    if L.art == "abgebrochen":
        return
    if L.art != "ok" and not db.ziel_erreichbar(ziel):
        # Nicht die Datei ist weg, sondern das ganze Ziel: nichts umstellen,
        # auch diese Lesung nicht verbuchen.
        raise ZielWeg
    zielpfad = z["zielpfad"]
    e.bearbeitet += 1
    anzeige.weiter(1, L.groesse if L.art == "ok" else 0)
    if L.art == "ok":
        e.bytes_gelesen += L.groesse
        dbank.ziel_index_setzen(zielpfad, L.groesse, L.mtime, L.hash, lauf)
        if int(z["varianten"]) == 1 and L.hash == z["hash"] and L.groesse == int(z["groesse"]):
            e.unveraendert += 1
            return
        # Jede Zeile fuer sich: Passt eine, ist ihre Datei heil - auch wenn eine
        # andere Zeile mit anderem Inhalt auf denselben Namen zeigt.
        betroffen = [r for r in _zeilen(dbank, zielpfad)
                     if r["hash"] != L.hash or int(r["groesse"]) != L.groesse]
        if not betroffen:
            e.unveraendert += 1
            return
        e.veraendert.append(zielpfad)
        _abweichung(dbank, lauf, e, zielpfad, betroffen, ART_VERAENDERT, meldungen.GRUND_NACHPRUEFUNG_VERAENDERT)
        return
    if L.art == "fehlt":
        e.fehlt.append(zielpfad)
        dbank.ziel_index_entfernen(zielpfad)
        _abweichung(dbank, lauf, e, zielpfad, _zeilen(dbank, zielpfad), ART_FEHLT, meldungen.GRUND_NACHPRUEFUNG_FEHLT)
        return
    # Nicht lesbar: vielleicht nur voruebergehend (Netz, gesperrt). Melden,
    # nichts umstellen - geloescht wird ohnehin nur nach frischem Lesen.
    e.nicht_lesbar.append(zielpfad)
    dbank.ereignis(lauf, ART_NICHT_LESBAR, zielpfad, 1, L.grund or meldungen.GRUND_PRUEFUNG_LESEN)


def _zeilen(dbank: db.Datenbank, zielpfad: str) -> list:
    return [r for r in dbank.zeilen_mit_zielpfad(zielpfad) if r["status"] in NACHPRUEFBAR and r["hash"]]


def _da(text: str) -> bool:
    """Liegt unter diesem Pfad (aus der Datenbank) noch eine Datei?"""
    try:
        return os.path.isfile(pfade.lang(Path(db.text_pfad(text))))
    except (OSError, ValueError):
        return False


def _abweichung(dbank: db.Datenbank, lauf: int, e: Ergebnis, zielpfad: str, betroffen: list,
                art: str, grund: str) -> None:
    """Die betroffenen Zeilen zu dieser Archivdatei. Ob es die Quelle noch
    gibt, wird nachgesehen - der Status allein sagt es nicht."""
    neu_kopieren = fehlt = geloescht = 0
    papierkorb: list[str] = []
    for r in betroffen:
        if r["status"] in MIT_QUELLE:
            # Die Loeschberechtigung ist weg, ob die Quelle nun da ist oder nicht:
            # Kommt sie wieder (Karte eingesteckt), kopiert "kopieren" neu.
            dbank.status_setzen(r["quellpfad"], "fehler", grund)
            if _da(r["quellpfad"]):
                neu_kopieren += 1
            else:
                fehlt += 1
        elif r["status"] == "quelle_geloescht" and r["schreibpfad"] and _da(r["schreibpfad"]):
            papierkorb.append(db.text_pfad(r["schreibpfad"]))
        else:
            geloescht += 1
    e.neu_zu_kopieren += neu_kopieren
    if fehlt:
        e.quelle_fehlt.append(zielpfad)
    if geloescht:
        e.ohne_quelle.append(zielpfad)
    e.im_papierkorb.extend(papierkorb)
    dbank.ereignis(lauf, art, zielpfad, 1, meldungen.ereignis_nachpruefung(grund, neu_kopieren, fehlt, geloescht, papierkorb))


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


def _unter(zp: str, wurzel: str) -> str | None:
    """Relativer Teil von zp unter wurzel, sonst None. Unter Windows ohne
    Ruecksicht auf Gross-/Kleinschreibung (d:\\fotos ist D:\\Fotos)."""
    kopf = zp[:len(wurzel)]
    if os.path.normcase(kopf) != os.path.normcase(wurzel) or zp[len(wurzel):len(wurzel) + 1] not in ("/", "\\"):
        return None
    rel = zp[len(wurzel) + 1:]
    return rel.replace("\\", "/") if os.sep == "\\" else rel


def pruefsummen_schreiben(ziel: Path, dbank: db.Datenbank) -> tuple[Path, int, int]:
    """Die Liste aller geprueften Archivdateien mit ihrem BLAKE3 neu schreiben
    (erst .neu, dann an ihren Platz - es ist eine eigene Datei des Programms).
    Pfade relativ zum Ziel mit "/". Liefert (Pfad, Zeilen, ausserhalb).

    Die Zielpfade in der Datenbank sind aufgeloest (ziel.Zielstruktur); das
    Ziel wird es hier auch - sonst passte bei "--ziel ." oder ueber eine
    Verknuepfung keine Zeile. Liegen trotzdem Archivdateien laut Datenbank
    nicht unter dem Ziel (ausserhalb > 0), bleibt die bisherige Liste stehen:
    Eine lueckenhafte Liste liesse "b3sum --check" still weniger pruefen."""
    ziel = Path(ziel)
    pfad = pruefsummen_pfad(ziel)
    neu = pfad.with_name(pfad.name + ".neu")
    pfade.lang(pfad.parent).mkdir(parents=True, exist_ok=True)
    wurzel = str(pfade.aufloesen(ziel)).rstrip("/\\")
    n = ausserhalb = 0
    # surrogateescape: Ein Name, der kein gueltiges UTF-8 ist, wird mit seinen
    # rohen Bytes geschrieben - so liest ihn auch b3sum.
    with open(pfade.lang(neu), "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        for z in dbank.nachpruefbar_alle(NACHPRUEFBAR):
            rel = _unter(db.text_pfad(z["zielpfad"]), wurzel)
            if rel is None:
                ausserhalb += 1
                continue
            f.write(_b3sum_zeile(z["hash"], rel))
            n += 1
        f.flush()
        os.fsync(f.fileno())
    if ausserhalb:
        pfade.lang(neu).unlink(missing_ok=True)
        return pfad, n, ausserhalb
    pfade.geduldig(os.replace, pfade.lang(neu), pfade.lang(pfad), fehlernummern=pfade.GESPERRT_ERSETZEN)
    return pfad, n, 0
