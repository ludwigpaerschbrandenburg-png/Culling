"""Die EINZIGE Stelle, an der eine Quelldatei aus dem Bestand entfernt wird.

SPEC Abschnitt 5, der Satz, an dem sich der Code messen lassen muss:
Eine Quelldatei wird genau dann geloescht, wenn ihr Status geprueft oder
duplikat_bestaetigt ist UND Quelldatei und Zieldatei in diesem Lauf beide
vollstaendig frisch gelesen wurden (bestaetigt_in_lauf traegt die Nummer des
laufenden Laufs) UND beide denselben Hash tragen wie der gespeicherte
Quell-Hash; fehlt auch nur eine dieser Bedingungen, wird nicht geloescht.

Beide Aufrufer - "kopieren --verschieben" und "aufraeumen" - gehen durch
quelldatei_entfernen(). Die Funktion prueft jede Bedingung selbst noch
einmal an der frisch aus der Datenbank gelesenen Zeile; sie vertraut keinem
Aufrufer. Verweigert sie, ist nichts passiert.

Zwei Loeschweisen:
  endgueltig   - os.unlink
  papierkorb   - nicht ueberschreibend in <Quellwurzel>/_geloescht_<Datum>/
                 verschoben (gleicher relativer Pfad), damit der Nutzer den
                 Ordner spaeter selbst loeschen kann (Standard).
"""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import db, hashes, meldungen, pfade

# Ereignisarten dieser Phase (SPEC Abschnitt 6, 10).
ART_QUELLE_GELOESCHT = "quelle_geloescht"
ART_QUELLE_IN_PAPIERKORB = "quelle_in_geloescht_ordner"
ART_QUELLE_SEIT_KOPIEREN_GEAENDERT = "quelle_seit_kopieren_geaendert"
ART_LOESCHUNG_VERWEIGERT = "loeschung_verweigert"
ART_LOESCHUNG_NACHGETRAGEN = "loeschung_nachgetragen"
ART_REST_NICHT_ENTFERNT = "rest_nicht_entfernt"
ART_REST_ENTFERNT = "rest_entfernt"
ART_LEERER_ORDNER_ENTFERNT = "leerer_ordner_entfernt"

LOESCHBERECHTIGT: frozenset[str] = frozenset({"geprueft", "duplikat_bestaetigt"})
WEISE_ENDGUELTIG = "endgueltig"
WEISE_PAPIERKORB = "papierkorb"
PAPIERKORB_PRAEFIX = "_geloescht_"


class Verweigert(Exception):
    """Eine Loeschbedingung ist nicht erfuellt. Es wurde nichts entfernt."""


@dataclass
class Lesung:
    """Ergebnis der Frischlesung von Quelle UND Ziel (laeuft im Hash-Worker)."""
    art: str                 # ok | quelle_fehlt | ziel_fehlt | abgebrochen | fehler
    quell_hash: str = ""
    ziel_hash: str = ""
    quell_groesse: int = -1
    ziel_groesse: int = -1
    byte_gleich: bool | None = None
    grund: str = ""


def papierkorb_ordner(quellwurzel: Path, heute: date | None = None) -> Path:
    heute = heute or date.today()
    return Path(quellwurzel) / f"{PAPIERKORB_PRAEFIX}{heute.isoformat()}"


def ist_papierkorb(name: str) -> bool:
    return name.startswith(PAPIERKORB_PRAEFIX)


def frisch_lesen(quelle: Path, zielpfad: Path, byte_vergleich: bool,
                 stop: threading.Event | None = None) -> Lesung:
    """Quelle UND Ziel vollstaendig neu lesen. Nur lesen, nie schreiben."""
    try:
        st_q = os.stat(pfade.lang(quelle))
    except FileNotFoundError:
        return Lesung("quelle_fehlt")
    except OSError as fehler:
        return Lesung("fehler", grund=f"{meldungen.GRUND_QUELLE_NICHT_LESBAR}: {fehler.strerror or fehler}")
    try:
        st_z = os.stat(pfade.lang(zielpfad))
    except FileNotFoundError:
        return Lesung("ziel_fehlt", quell_groesse=st_q.st_size)
    except OSError as fehler:
        return Lesung("fehler", grund=f"{meldungen.GRUND_ZIEL_NICHT_LESBAR}: {fehler.strerror or fehler}")
    try:
        hz = hashes.blake3_datei(pfade.lang(zielpfad), stop)
        hq = hashes.blake3_datei(pfade.lang(quelle), stop)
        gleich = None
        if byte_vergleich:
            gleich = hashes.gleich_byteweise(pfade.lang(quelle), pfade.lang(zielpfad))
    except hashes.Abgebrochen:
        return Lesung("abgebrochen")
    except OSError as fehler:
        return Lesung("fehler", grund=f"{meldungen.GRUND_QUELLE_NICHT_LESBAR}: {fehler.strerror or fehler}")
    return Lesung("ok", quell_hash=hq, ziel_hash=hz, quell_groesse=st_q.st_size,
                  ziel_groesse=st_z.st_size, byte_gleich=gleich)


def bedingungen_pruefen(zeile, lesung: Lesung, lauf: int, byte_vergleich: bool) -> None:
    """Alle Loeschbedingungen an der frischen Zeile. Wirft Verweigert."""
    if zeile is None:
        raise Verweigert(meldungen.GRUND_ZEILE_FEHLT)
    if zeile["status"] not in LOESCHBERECHTIGT:
        raise Verweigert(meldungen.grund_status_nicht_berechtigt(zeile["status"]))
    if zeile["dateityp"] not in ("foto", "raw", "video", "sidecar"):
        raise Verweigert(meldungen.GRUND_KEIN_ECHTER_TYP)
    gespeichert = zeile["hash"]
    if not gespeichert:
        raise Verweigert(meldungen.GRUND_KEIN_HASH)
    if lesung.art != "ok":
        raise Verweigert(lesung.grund or meldungen.grund_lesung(lesung.art))
    groesse = int(zeile["groesse"])
    # Zuerst die Quelle: Weicht sie ab (Groesse oder Hash), ist das der Fall
    # "Quelle seit dem Kopieren geaendert" - neu kopieren, nicht loeschen.
    if lesung.quell_groesse != groesse or lesung.quell_hash != gespeichert:
        raise Verweigert(meldungen.GRUND_QUELLE_ABWEICHUNG)
    if lesung.ziel_groesse != groesse:
        raise Verweigert(meldungen.grund_groesse_abweichung(groesse, lesung.quell_groesse, lesung.ziel_groesse))
    if lesung.ziel_hash != gespeichert:
        raise Verweigert(meldungen.GRUND_ZIEL_ABWEICHUNG)
    if byte_vergleich and lesung.byte_gleich is not True:
        raise Verweigert(meldungen.GRUND_BYTEVERGLEICH)
    if zeile["bestaetigt_in_lauf"] != lauf:
        raise Verweigert(meldungen.GRUND_KEINE_FRISCHLESUNG)


def quelldatei_entfernen(dbank: db.Datenbank, lauf: int, quellpfad, lesung: Lesung,
                         weise: str, byte_vergleich: bool, papierkorb: Path | None = None) -> Path | None:
    """Quelldatei entfernen - nach Pruefung ALLER Bedingungen an der frisch
    gelesenen Datenbankzeile. Liefert den neuen Pfad (Papierkorb) oder None.

    Ablauf: Zeile frisch lesen -> Bedingungen ohne Lauf-Kennung pruefen ->
    bestaetigt_in_lauf = laufender Lauf festschreiben -> Zeile erneut lesen
    und ALLE Bedingungen pruefen (jetzt mit Lauf-Kennung) -> entfernen ->
    Status quelle_geloescht festschreiben.
    """
    if weise not in (WEISE_ENDGUELTIG, WEISE_PAPIERKORB):
        raise Verweigert(meldungen.grund_weise_unbekannt(weise))
    zeile = dbank.zeile(quellpfad)
    # Erste Pruefung: alles ausser der Lauf-Kennung (die setzen wir gleich).
    try:
        bedingungen_pruefen(zeile, lesung, lauf, byte_vergleich)
    except Verweigert as v:
        if str(v) != meldungen.GRUND_KEINE_FRISCHLESUNG:
            raise
    neuer_pfad: Path | None = None
    if weise == WEISE_PAPIERKORB:
        if papierkorb is None:
            raise Verweigert(meldungen.GRUND_PAPIERKORB_FEHLT)
        neuer_pfad = _papierkorb_pfad(Path(db.text_pfad(zeile["quellwurzel"])), Path(db.text_pfad(quellpfad)), papierkorb)
    dbank.bestaetigt_setzen(quellpfad, lauf, neuer_pfad)
    dbank.stapel_schreiben()   # vor dem Entfernen festgeschrieben
    zeile = dbank.zeile(quellpfad)
    bedingungen_pruefen(zeile, lesung, lauf, byte_vergleich)   # jetzt vollstaendig
    quelle = Path(db.text_pfad(quellpfad))
    if weise == WEISE_ENDGUELTIG:
        os.unlink(pfade.lang(quelle))
        dbank.quelle_geloescht_setzen(quellpfad, lauf, None)
        dbank.ereignis(lauf, ART_QUELLE_GELOESCHT, quelle, 1, meldungen.EREIGNIS_GELOESCHT)
        return None
    neuer_pfad = _in_papierkorb(quelle, neuer_pfad, zeile["hash"])
    dbank.quelle_geloescht_setzen(quellpfad, lauf, neuer_pfad)
    dbank.ereignis(lauf, ART_QUELLE_IN_PAPIERKORB, quelle, 1, db.pfad_text(neuer_pfad))
    return neuer_pfad


def _papierkorb_pfad(wurzel: Path, quelle: Path, papierkorb: Path) -> Path:
    try:
        relativ = quelle.relative_to(wurzel)
    except ValueError:
        relativ = Path(quelle.name)
    return papierkorb / relativ


def _in_papierkorb(quelle: Path, ziel: Path, erwarteter_hash: str) -> Path:
    """Quelle nicht ueberschreibend in den Papierkorb bringen; bei belegtem
    Namen Anhang _1, _2 ...; kann das Dateisystem kein nicht
    ueberschreibendes Umbenennen, wird kopiert, geprueft und dann entfernt."""
    pfade.lang(ziel.parent).mkdir(parents=True, exist_ok=True)
    k = 0
    while True:
        kandidat = ziel if k == 0 else ziel.with_name(f"{ziel.stem}_{k}{ziel.suffix}")
        try:
            pfade.umbenennen_ohne_ueberschreiben(quelle, kandidat)
            return kandidat
        except FileExistsError:
            k += 1
            continue
        except pfade.KeinNoReplace:
            try:
                h, _n = hashes.kopieren_mit_hash(pfade.lang(quelle), pfade.lang(kandidat))
            except FileExistsError:
                k += 1
                continue
            if h != erwarteter_hash:
                # Die eben geschriebene Kopie ist unsere eigene; die Quelle bleibt.
                os.unlink(pfade.lang(kandidat))
                raise Verweigert(meldungen.GRUND_PAPIERKORB_KOPIE)
            try:
                shutil.copystat(pfade.lang(quelle), pfade.lang(kandidat))
            except OSError:
                pass
            os.unlink(pfade.lang(quelle))
            return kandidat
