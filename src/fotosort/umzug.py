"""Archiv an einem neuen Ort: gespeicherte Pfade nachziehen (v0.14).

Die Datenbank speichert Pfade ins Archiv absolut: dateien.zielpfad und
schreibpfad, abgelegt, ziel_index. Unter Windows bekommt eine USB-Platte beim
naechsten Einstecken oft einen anderen Laufwerksbuchstaben (E: -> F:); auch
ein im Explorer verschobener Archivordner oder ein anderer Einhaengepunkt
unter Linux aendern den Pfad. Die Archiv-Kennung (.fotosortierer/archiv-id.txt)
zieht mit und fuehrt zur selben Datenbank - deren Pfade zeigen dann auf den
alten Ort. Ohne Nachziehen hielten "Pruefen" und "Aufraeumen" alle Kopien
fuer fehlend, ein neuer Lauf die eigenen Kopien fuer "schon im Archiv", und
ein schon geplantes Kopieren schrieb an den alten Pfad.

Beim Oeffnen fuer einen veraendernden Befehl (cli.archiv_oeffnen mit
sperren) gilt:

- Der zuletzt benutzte Ort steht in archiv_angaben (ziel_wurzel). Ist er der
  jetzige, ist nichts zu tun.
- Liegt am alten Ort noch ein Archiv mit derselben Kennung (und ist es nicht
  derselbe Ordner unter anderem Namen), gibt es das Archiv zweimal: Abbruch,
  nichts wird geaendert - im Zweifel fragen statt raten.
- Sonst: die Datenbank sichern (fotosort.db.vor_umzug_<Zeit>, neben der
  Datenbank, nie ueberschrieben), alle Pfade unter dem alten Ort auf den
  neuen umschreiben, den neuen Ort merken, melden.
- Datenbanken von vor v0.14 kennen ihren Ort nicht. Liegen ihre Pfade nicht
  unter dem jetzigen, ergibt sich der alte aus abgelegten Dateien, die am
  neuen Ort unter demselben Unterpfad mit derselben Groesse liegen.
- Was danach noch ausserhalb liegt und erst geplant ist (analysiert,
  kopieren_laeuft), wird neu eingeplant (Status gefunden): Kopiert wird nie
  ausserhalb des gewaehlten Archivs.

Fuer die oberste Regel aendert das nichts: Jede Loeschung liest Quelle und Ziel
weiterhin frisch (loeschen.py). Ein falsch umgeschriebener Pfad fuehrte nur zu
"Archivdatei fehlt", nie zu einer Loeschung.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import FotosortFehler, db, meldungen, pfade

ANGABE_WURZEL = "ziel_wurzel"
SICHERUNG_PRAEFIX = "fotosort.db.vor_umzug_"
SICHERUNG_MUSTER = SICHERUNG_PRAEFIX + "*"

#: So viele abgelegte Dateien werden angesehen, um bei einer Datenbank von vor
#: v0.14 den alten Ort zu bestimmen; mindestens die Haelfte muss passen.
STICHPROBE = 50
#: Hoechstens so viele verschiedene alte Orte nacheinander (E: -> G: -> F:).
HOECHSTENS_ORTE = 5

_ABGELEGT = ("kopiert", "geprueft", "verschoben", "quelle_geloescht", "duplikat", "duplikat_bestaetigt")
_GEPLANT = ("analysiert", "kopieren_laeuft")

# Kodiert gespeicherte Namen (kein gueltiges UTF-8, db.pfad_text) beginnen mit
# diesem Kennzeichen; ihr Pfad steckt kodiert dahinter und wird in Python
# verglichen. Bereich [von, bis) fuer den Index.
_ROH = db._ROH_KENNZEICHEN
_ROH_BEREICH = (_ROH, _ROH[:-1] + chr(ord(_ROH[-1]) + 1))


@dataclass
class Ergebnis:
    umzuege: list[tuple[str, str, int]] = field(default_factory=list)   # (alt, neu, Dateien)
    sicherung: Path | None = None
    neu_geplant: int = 0


def _basis(wurzel: str, trenner: str) -> str:
    """Wurzel mit genau einem Trenner am Ende ("E:\\" bleibt "E:\\")."""
    return wurzel if wurzel.endswith(trenner) else wurzel + trenner


def _bereich(wurzel: str, trenner: str) -> tuple[str, str]:
    """Textbereich [von, bis) aller gespeicherten Pfade unter wurzel. SQLite
    vergleicht Text Zeichen fuer Zeichen; so nutzt die Abfrage den Index und
    braucht kein LIKE (in Pfaden sind "%" und "_" erlaubt)."""
    b = _basis(wurzel, trenner)
    return b, b[:-1] + chr(ord(trenner) + 1)


def _unter(text: str, wurzel: str, trenner: str) -> bool:
    return db.text_pfad(text).startswith(_basis(wurzel, trenner))


def _ausserhalb(dbank: db.Datenbank, neu: str, trenner: str, status: tuple[str, ...] | None = None,
                grenze: int | None = None) -> list[sqlite3.Row]:
    """Zeilen, deren zielpfad gesetzt ist, aber nicht unter neu liegt."""
    von, bis = _bereich(neu, trenner)
    filter_ = ""
    werte: list = [von, bis, *_ROH_BEREICH]
    if status:
        filter_ = f" AND status IN ({','.join('?' * len(status))})"
        werte += list(status)
    sql = ("SELECT quellpfad, zielpfad, groesse, status FROM dateien WHERE"
           " ((zielpfad > '' AND zielpfad < ?) OR (zielpfad >= ? AND NOT (zielpfad >= ? AND zielpfad < ?)))"
           + filter_)
    if grenze is not None:
        sql += f" LIMIT {int(grenze)}"
    zeilen = list(dbank.verbindung.execute(sql, werte))
    # Kodierte Namen: entschluesselt vergleichen (wenige, wenn ueberhaupt).
    roh_sql = "SELECT quellpfad, zielpfad, groesse, status FROM dateien WHERE zielpfad >= ? AND zielpfad < ?" + filter_
    for z in dbank.verbindung.execute(roh_sql, [*_ROH_BEREICH, *(status or ())]):
        if not _unter(z["zielpfad"], neu, trenner):
            zeilen.append(z)
    return zeilen if grenze is None else zeilen[:grenze]


def _ableiten(dbank: db.Datenbank, ziel: Path, neu: str, trenner: str) -> str | None:
    """Alter Ort aus abgelegten Dateien, die am neuen Ort unter demselben
    Unterpfad mit derselben Groesse liegen. None, wenn das nicht sicher geht."""
    stichprobe = _ausserhalb(dbank, neu, trenner, _ABGELEGT, STICHPROBE)
    if not stichprobe:
        return None
    stimmen: Counter = Counter()
    for z in stichprobe:
        teile = Path(db.text_pfad(z["zielpfad"])).parts
        # Vom laengsten Unterpfad zum kuerzesten: der genaueste Treffer zaehlt.
        for k in range(1, len(teile)):
            try:
                st = os.stat(pfade.lang(ziel.joinpath(*teile[k:])))
            except (OSError, ValueError):
                continue
            if stat.S_ISREG(st.st_mode) and st.st_size == int(z["groesse"]):
                stimmen[db.pfad_text(Path(*teile[:k]))] += 1
                break
    if not stimmen:
        return None
    alt, treffer = stimmen.most_common(1)[0]
    return alt if 2 * treffer >= len(stichprobe) else None


def _zeilen_unter(dbank: db.Datenbank, wurzel: str, trenner: str) -> bool:
    von, bis = _bereich(wurzel, trenner)
    v = dbank.verbindung
    if v.execute("SELECT 1 FROM dateien WHERE zielpfad >= ? AND zielpfad < ? LIMIT 1", (von, bis)).fetchone():
        return True
    return any(_unter(z[0], wurzel, trenner) for z in
               v.execute("SELECT zielpfad FROM dateien WHERE zielpfad >= ? AND zielpfad < ?", _ROH_BEREICH))


def _zweimal_pruefen(alt: str, ziel: Path, archiv_id: str) -> None:
    """Liegt am alten Ort noch dasselbe Archiv, ist der neue Ordner eine Kopie
    (oder umgekehrt) - dann nichts aendern."""
    alter_ort = Path(db.text_pfad(alt))
    try:
        if not pfade.lang(alter_ort).exists():
            return
        if os.path.samefile(pfade.lang(alter_ort), pfade.lang(ziel)):
            return   # derselbe Ordner, nur anders geschrieben
        kennung = db.archiv_id_lesen(alter_ort)
    except (OSError, ValueError, FotosortFehler):
        return       # nicht lesbar: ein anderes oder kaputtes Archiv, nicht dieses
    if kennung == archiv_id:
        raise FotosortFehler(meldungen.archiv_zweimal(alter_ort, ziel))


def _sichern(dbank: db.Datenbank) -> Path:
    """Die Datenbank vor dem Umschreiben aufheben (SQLite-Backup, nimmt auch
    mit, was noch im WAL steht). Nie eine vorhandene Datei ueberschreiben."""
    dbank.stapel_schreiben()
    zeit = time.strftime("%Y-%m-%d_%H%M%S")
    kopie = dbank.pfad.with_name(f"{SICHERUNG_PRAEFIX}{zeit}")
    nummer = 1
    while pfade.lang(kopie).exists():
        nummer += 1
        kopie = dbank.pfad.with_name(f"{SICHERUNG_PRAEFIX}{zeit}_{nummer}")
    sicherung = sqlite3.connect(str(pfade.lang(kopie)))
    try:
        dbank.verbindung.backup(sicherung)
        sicherung.execute("PRAGMA journal_mode=DELETE")   # eine Datei, ohne -wal/-shm
    finally:
        sicherung.close()
    return kopie


def umschreiben(dbank: db.Datenbank, alt: str, neu: str, trenner: str = os.sep) -> int:
    """Alle gespeicherten Archivpfade unter alt auf neu umstellen - in einem
    Zug, ganz oder gar nicht. Liefert die Zahl der Dateien (dateien.zielpfad)."""
    a, n = _basis(alt, trenner), _basis(neu, trenner)
    # Liegt der neue Ort im alten (Archiv von "E:\" nach "E:\Fotos"), gehoert,
    # was schon unter dem neuen liegt, nicht mehr zum alten.
    ausnehmen = n != a and n.startswith(a)

    def neuer(text: str) -> str | None:
        p = db.text_pfad(text)
        if not p.startswith(a) or (ausnehmen and p.startswith(n)):
            return None
        return db.pfad_text(n + p[len(a):])

    von, bis = _bereich(alt, trenner)
    v = dbank.verbindung
    dbank.stapel_schreiben()
    v.execute("BEGIN IMMEDIATE")
    try:
        anzahl = 0
        for spalte in ("zielpfad", "schreibpfad"):
            bereich = f"SELECT quellpfad, {spalte} FROM dateien WHERE {spalte} >= ? AND {spalte} < ?"
            zeilen = list(v.execute(bereich, (von, bis))) + list(v.execute(bereich, _ROH_BEREICH))
            neu_werte = [(t, z[0]) for z in zeilen if (t := neuer(z[1])) is not None]
            v.executemany(f"UPDATE dateien SET {spalte} = ? WHERE quellpfad = ?", neu_werte)
            if spalte == "zielpfad":
                anzahl = len(neu_werte)
        for tabelle in ("abgelegt", "ziel_index"):
            bereich = f"SELECT zielpfad FROM {tabelle} WHERE zielpfad >= ? AND zielpfad < ?"
            zeilen = list(v.execute(bereich, (von, bis))) + list(v.execute(bereich, _ROH_BEREICH))
            paare = [(t, z[0]) for z in zeilen if (t := neuer(z[0])) is not None]
            # Steht der neue Pfad schon da, bleibt dieser; der alte faellt weg.
            v.executemany(f"UPDATE OR IGNORE {tabelle} SET zielpfad = ? WHERE zielpfad = ?", paare)
            v.executemany(f"DELETE FROM {tabelle} WHERE zielpfad = ?", [(p[1],) for p in paare])
        v.execute("COMMIT")
    except BaseException:
        v.execute("ROLLBACK")
        raise
    return anzahl


def _geplante_neu(dbank: db.Datenbank, neu: str, trenner: str) -> int:
    """Erst geplante Zeilen, deren Zielname noch ausserhalb liegt: neu einplanen
    (gefunden) - die Analyse berechnet den Zielnamen am jetzigen Ort neu."""
    zeilen = [(z["quellpfad"],) for z in _ausserhalb(dbank, neu, trenner, _GEPLANT)]
    if zeilen:
        v = dbank.verbindung
        dbank.stapel_schreiben()
        v.execute("BEGIN IMMEDIATE")
        try:
            v.executemany("UPDATE dateien SET status = 'gefunden', zielpfad = '', schreibpfad = '',"
                          " kopiert_in_lauf = NULL WHERE quellpfad = ?", zeilen)
            v.execute("COMMIT")
        except BaseException:
            v.execute("ROLLBACK")
            raise
    return len(zeilen)


def nachziehen(dbank: db.Datenbank, ziel: Path, archiv_id: str, trenner: str = os.sep) -> Ergebnis:
    """Beim Oeffnen fuer einen veraendernden Befehl: Liegt das Archiv an einem
    neuen Ort, die gespeicherten Pfade dorthin umschreiben (siehe oben).
    Wirft FotosortFehler, wenn es das Archiv zweimal gibt - dann ist nichts
    geaendert."""
    ergebnis = Ergebnis()
    neu = db.pfad_text(ziel)
    gespeichert = dbank.angabe_lesen(ANGABE_WURZEL)
    vorschlag = gespeichert if gespeichert and gespeichert != neu else None
    gesehen: set[str] = set()
    for _ in range(HOECHSTENS_ORTE):
        if not _ausserhalb(dbank, neu, trenner, grenze=1):
            break
        alt = vorschlag or _ableiten(dbank, ziel, neu, trenner)
        vorschlag = None
        if alt is None or alt in gesehen or alt == neu:
            break
        gesehen.add(alt)
        if not _zeilen_unter(dbank, alt, trenner):
            continue
        _zweimal_pruefen(alt, ziel, archiv_id)
        if ergebnis.sicherung is None:
            ergebnis.sicherung = _sichern(dbank)
        ergebnis.umzuege.append((db.text_pfad(alt), db.text_pfad(neu), umschreiben(dbank, alt, neu, trenner)))
    if _ausserhalb(dbank, neu, trenner, _GEPLANT, grenze=1):
        if ergebnis.sicherung is None:
            ergebnis.sicherung = _sichern(dbank)
        ergebnis.neu_geplant = _geplante_neu(dbank, neu, trenner)
    if gespeichert != neu:
        dbank.angabe_schreiben(ANGABE_WURZEL, neu)
    return ergebnis
