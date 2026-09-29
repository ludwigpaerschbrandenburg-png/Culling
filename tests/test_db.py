"""Tests fuer db.py (SPEC Abschnitt 6)."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

import testbaum

from fotosort import FotosortFehler, config, db, pfade


@pytest.fixture
def datenbank(tmp_path):
    d = db.Datenbank.oeffnen(tmp_path / "archiv")
    yield d
    d.schliessen()


def test_status_sind_genau_die_elf_werte():
    assert db.STATUS == frozenset(
        {
            "gefunden",
            "analysiert",
            "kopieren_laeuft",
            "kopiert",
            "geprueft",
            "verschoben",
            "duplikat",
            "duplikat_bestaetigt",
            "quelle_geloescht",
            "uebersprungen",
            "fehler",
        }
    )
    assert len(db.STATUS) == 11
    # Umlautfrei gespeichert - an diesen Zeichenketten haengt die
    # Loeschberechtigung.
    for wert in db.STATUS:
        assert wert.isascii()


def test_schema_hat_vier_tabellen(datenbank):
    namen = {
        z[0]
        for z in datenbank.verbindung.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"dateien", "ziel_index", "laeufe", "lauf_ereignisse"} <= namen


def test_dateien_hat_alle_spalten_aus_der_spec(datenbank):
    spalten = {
        z["name"] for z in datenbank.verbindung.execute("PRAGMA table_info(dateien)")
    }
    assert spalten == {
        "quellpfad",
        "quellwurzel",
        "groesse",
        "mtime",
        "dateityp",
        "hash",
        "kamera",
        "kamera_modell",
        "aufnahme_zeit",
        "datum_quelle",
        "datum_sicher",
        "datum_hinweis",
        "gruppe",
        "zielpfad",
        "status",
        "fehlergrund",
        "bestaetigt_in_lauf",
        "kopiert_in_lauf",
        "umbenannt",
        "schreibpfad",
        "gefunden_in_lauf",
        "zuletzt_gesehen_in_lauf",
    }


def test_ziel_index_und_laeufe_spalten(datenbank):
    ziel = {
        z["name"] for z in datenbank.verbindung.execute("PRAGMA table_info(ziel_index)")
    }
    assert ziel == {"zielpfad", "groesse", "mtime", "hash", "zuletzt_gelesen_in_lauf"}
    laeufe = {
        z["name"] for z in datenbank.verbindung.execute("PRAGMA table_info(laeufe)")
    }
    assert laeufe == {"nummer", "befehl", "start", "ende", "zusammenfassung"}
    ereignisse = {
        z["name"]
        for z in datenbank.verbindung.execute("PRAGMA table_info(lauf_ereignisse)")
    }
    assert ereignisse == {"lauf_nummer", "art", "pfad", "anzahl", "text"}


def test_wal_ist_an(datenbank):
    modus = datenbank.verbindung.execute("PRAGMA journal_mode").fetchone()[0]
    assert modus.lower() == "wal"


def test_lauf_beginnen_und_beenden(datenbank):
    eins = datenbank.lauf_beginnen("fotosort scan")
    zwei = datenbank.lauf_beginnen("fotosort scan")
    assert zwei == eins + 1
    zeile = datenbank.letzter_lauf()
    assert zeile["nummer"] == zwei
    assert zeile["ende"] == ""
    datenbank.lauf_beenden(zwei)
    assert datenbank.letzter_lauf()["ende"] != ""


def test_datei_gesehen_neu_unveraendert_veraendert(datenbank):
    lauf = datenbank.lauf_beginnen("scan")
    assert datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0, "foto", lauf) == "neu"
    assert (
        datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0, "foto", lauf)
        == "unveraendert"
    )
    assert (
        datenbank.datei_gesehen("/q/a.jpg", "/q", 101, 1000.0, "foto", lauf)
        == "veraendert"
    )
    assert (
        datenbank.datei_gesehen("/q/a.jpg", "/q", 101, 2000.0, "foto", lauf)
        == "veraendert"
    )


def test_unveraendert_laesst_die_zeile_in_ruhe(datenbank):
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0, "foto", lauf)
    datenbank.verbindung.execute(
        "UPDATE dateien SET status='kopiert', hash='abc', zielpfad='/z/a.jpg'"
    )
    zweiter = datenbank.lauf_beginnen("scan")
    assert (
        datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0, "foto", zweiter)
        == "unveraendert"
    )
    datenbank.stapel_schreiben()
    zeile = datenbank.zeile("/q/a.jpg")
    assert zeile["status"] == "kopiert"
    assert zeile["hash"] == "abc"
    assert zeile["zielpfad"] == "/z/a.jpg"
    assert zeile["zuletzt_gesehen_in_lauf"] == zweiter


def test_veraendert_faellt_auf_gefunden_zurueck(datenbank):
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0, "foto", lauf)
    datenbank.verbindung.execute(
        "UPDATE dateien SET status='kopiert', hash='abc', zielpfad='/z/a.jpg',"
        " bestaetigt_in_lauf=1"
    )
    datenbank.datei_gesehen("/q/a.jpg", "/q", 200, 1000.0, "foto", lauf)
    datenbank.stapel_schreiben()
    zeile = datenbank.zeile("/q/a.jpg")
    assert zeile["status"] == "gefunden"
    assert zeile["hash"] == ""
    assert zeile["zielpfad"] == ""
    assert zeile["bestaetigt_in_lauf"] is None


def test_nicht_mehr_gesehen_nur_fuer_die_gescannte_wurzel(datenbank):
    erster = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q1/a.jpg", "/q1", 1, 1.0, "foto", erster)
    datenbank.datei_gesehen("/q1/b.jpg", "/q1", 1, 1.0, "foto", erster)
    datenbank.datei_gesehen("/q2/c.jpg", "/q2", 1, 1.0, "foto", erster)

    zweiter = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q1/a.jpg", "/q1", 1, 1.0, "foto", zweiter)
    fehlt = datenbank.nicht_mehr_gesehen("/q1", zweiter)
    assert fehlt == ["/q1/b.jpg"]  # /q2/c.jpg gehoert zu einer anderen Wurzel


def test_nicht_mehr_gesehen_ohne_erwartetes_fehlen(datenbank):
    erster = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", erster)
    datenbank.datei_gesehen("/q/b.jpg", "/q", 1, 1.0, "foto", erster)
    datenbank.status_setzen("/q/a.jpg", "quelle_geloescht")
    datenbank.status_setzen("/q/b.jpg", "verschoben")
    zweiter = datenbank.lauf_beginnen("scan")
    assert datenbank.nicht_mehr_gesehen("/q", zweiter) == []


def test_es_wird_nie_eine_zeile_geloescht(datenbank):
    erster = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", erster)
    zweiter = datenbank.lauf_beginnen("scan")
    datenbank.nicht_mehr_gesehen("/q", zweiter)
    datenbank.stapel_schreiben()
    assert datenbank.zeile("/q/a.jpg") is not None


def test_status_setzen_nur_mit_bekanntem_status(datenbank):
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", lauf)
    datenbank.status_setzen("/q/a.jpg", "uebersprungen", "zeigt ins Ziel")
    datenbank.stapel_schreiben()
    assert datenbank.zeile("/q/a.jpg")["fehlergrund"] == "zeigt ins Ziel"
    with pytest.raises(ValueError):
        datenbank.status_setzen("/q/a.jpg", "übersprungen")


def test_zaehler_je_status_kennt_alle_elf(datenbank):
    zaehler = datenbank.zaehler_je_status()
    assert set(zaehler) == db.STATUS
    assert all(wert == 0 for wert in zaehler.values())


def test_ereignis_und_zaehlen(datenbank):
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.ereignis(lauf, "verknuepfung_nicht_verfolgt", "/q/link", 1, "Text")
    datenbank.ereignis(lauf, "ausgeschlossen", "/q/muell", 1, "")
    datenbank.stapel_schreiben()
    assert datenbank.ereignisse_zaehlen(lauf, "verknuepfung_nicht_verfolgt") == 1
    assert datenbank.ereignisse_zaehlen(lauf, "zeigt_ins_ziel") == 0


def test_stapel_schreiben_erzwingt_das_schreiben(datenbank, tmp_path):
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", lauf)
    datenbank.stapel_schreiben()
    # Eine zweite Verbindung sieht die Zeile nur nach dem Schreiben.
    zweite = sqlite3.connect(str(tmp_path / "archiv" / db.DATEINAME))
    try:
        assert zweite.execute("SELECT COUNT(*) FROM dateien").fetchone()[0] == 1
    finally:
        zweite.close()


def test_sammelschreiben_grenzen():
    assert db.STAPEL_DATEIEN == 500
    assert db.STAPEL_SEKUNDEN == 2.0


# ---------------------------------------------------------- Archiv-ID ----


def test_archiv_id_wird_angelegt(tmp_path):
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    kennung = db.archiv_id_lesen_oder_anlegen(ziel)
    assert len(kennung) == 32
    assert all(z in "0123456789abcdef" for z in kennung)
    assert db.archiv_id_lesen_oder_anlegen(ziel) == kennung


def test_archiv_id_kaputt_bricht_ab_und_erzeugt_keine_neue(tmp_path):
    ziel = tmp_path / "Ziel"
    datei = db.archiv_id_datei(ziel)
    datei.parent.mkdir(parents=True)
    datei.write_text("kaputt\n", encoding="utf-8")
    with pytest.raises(FotosortFehler) as fehler:
        db.archiv_id_lesen_oder_anlegen(ziel)
    assert "kaputt" in str(fehler.value)
    assert str(datei) in str(fehler.value)
    assert datei.read_text(encoding="utf-8") == "kaputt\n"


def test_archiv_id_mit_bindestrichen_gilt_als_kaputt(tmp_path):
    ziel = tmp_path / "Ziel"
    datei = db.archiv_id_datei(ziel)
    datei.parent.mkdir(parents=True)
    datei.write_text("0f8fad5b-d9cb-469f-a165-70867728950e\n", encoding="utf-8")
    with pytest.raises(FotosortFehler):
        db.archiv_id_lesen_oder_anlegen(ziel)


# ------------------------------------------------------- Archiv-Ordner ----


def test_archiv_ordner_vorrang_umgebungsvariable(monkeypatch, tmp_path):
    monkeypatch.setenv("FOTOSORT_DATENBANK", str(tmp_path / "aus_umgebung"))
    k = config.Konfiguration()
    k.alle()["datenbank"]["datenbank_ort"] = str(tmp_path / "aus_konf")
    assert db.archiv_ordner("a" * 32, k) == tmp_path / "aus_umgebung" / ("a" * 32)


def test_archiv_ordner_dann_konfigurationswert(monkeypatch, tmp_path):
    monkeypatch.delenv("FOTOSORT_DATENBANK", raising=False)
    k = config.Konfiguration()
    k.alle()["datenbank"]["datenbank_ort"] = str(tmp_path / "aus_konf")
    assert db.archiv_ordner("b" * 32, k) == tmp_path / "aus_konf" / ("b" * 32)


def test_archiv_ordner_zuletzt_standardpfad(monkeypatch, tmp_path):
    """Linux: XDG_DATA_HOME; Windows: %LOCALAPPDATA% (SPEC Abschnitt 6)."""
    monkeypatch.delenv("FOTOSORT_DATENBANK", raising=False)
    if sys.platform.startswith("win"):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))
        erwartet = tmp_path / "lokal" / "fotosortierer" / ("c" * 32)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        erwartet = tmp_path / "xdg" / "fotosortierer" / ("c" * 32)
    assert db.archiv_ordner("c" * 32, None) == erwartet


def test_datenbank_auf_netzlaufwerk_bricht_ab(tmp_path, monkeypatch):
    monkeypatch.setattr(pfade, "ist_netzpfad", lambda p: True)
    monkeypatch.setattr(pfade, "dateisystem_typ", lambda p: "cifs")
    with pytest.raises(FotosortFehler) as fehler:
        db.Datenbank.oeffnen(tmp_path / "netz")
    assert "Netzlaufwerk" in str(fehler.value)
    assert "cifs" in str(fehler.value)


# ---------------------------------------------------------- Sicherung ----


def test_sichern_nach_erzeugt_genau_zwei_staende(tmp_path, datenbank):
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", lauf)

    datenbank.sichern_nach(ziel)
    ordner = ziel / ".fotosortierer"
    assert (ordner / db.SICHERUNG).is_file()
    assert not (ordner / db.SICHERUNG_VORHER).exists()
    assert not (ordner / db.SICHERUNG_NEU).exists()

    datenbank.sichern_nach(ziel)
    assert (ordner / db.SICHERUNG).is_file()
    assert (ordner / db.SICHERUNG_VORHER).is_file()
    assert not (ordner / db.SICHERUNG_NEU).exists()


def test_sicherung_ist_lesbar_und_vollstaendig(tmp_path, datenbank):
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", lauf)
    datenbank.sichern_nach(ziel)
    kopie = sqlite3.connect(str(ziel / ".fotosortierer" / db.SICHERUNG))
    try:
        assert kopie.execute("SELECT COUNT(*) FROM dateien").fetchone()[0] == 1
    finally:
        kopie.close()


class _Gesperrt(PermissionError):
    """Wie Windows beim Ersetzen einer Datei, die ein anderes Programm gerade
    offen haelt: "Zugriff verweigert" (5); 32 bei einer Freigabeverletzung."""

    def __init__(self, nummer: int):
        super().__init__(13, "Der Prozess kann nicht auf die Datei zugreifen")
        self.winerror = nummer


def test_sicherung_wartet_auf_eine_kurz_offene_alte_sicherung(tmp_path, datenbank, monkeypatch):
    """Liest der Suchindex, ein Sync-Programm oder die naechtliche Sicherung des
    NAS die alte Sicherung gerade, meldet Windows beim Ersetzen Fehler 5. Dann
    warten und erneut versuchen - frueher endete der ganze Schritt als Fehler."""
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    datenbank.sichern_nach(ziel)
    echt = os.replace
    versuche: list = []

    def ersetzen(a, b):
        versuche.append(1)
        if len(versuche) == 1:
            raise _Gesperrt(5)
        echt(a, b)

    monkeypatch.setattr(pfade, "GEDULD_PAUSE", 0.0)
    monkeypatch.setattr(db.os, "replace", ersetzen)
    datenbank.sichern_nach(ziel)
    assert (ziel / ".fotosortierer" / db.SICHERUNG_VORHER).is_file() and len(versuche) >= 3


def test_klemmende_lokale_zwischendatei_macht_die_sicherung_nicht_zunichte(tmp_path, datenbank, monkeypatch):
    """Die lokale Zwischendatei laesst sich gerade nicht entfernen (Virenscanner):
    Die Sicherung im Ziel ist trotzdem fertig und steht an ihrem Platz."""
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    echt = os.unlink

    def unlink(pfad, *a, **k):
        if Path(pfad).name == db.SICHERUNG_LOKAL:
            raise _Gesperrt(32)
        return echt(pfad, *a, **k)

    monkeypatch.setattr(pfade, "GEDULD_PAUSE", 0.0)
    monkeypatch.setattr(db.os, "unlink", unlink)
    datenbank.sichern_nach(ziel)
    assert (ziel / ".fotosortierer" / db.SICHERUNG).is_file()
    assert not (ziel / ".fotosortierer" / db.SICHERUNG_NEU).exists()


def test_sichern_nimmt_die_konfiguration_mit(tmp_path, datenbank):
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    konf_pfad = tmp_path / "config.toml"
    config.erzeugen(konf_pfad)
    datenbank.sichern_nach(ziel, konf_pfad)
    kopie = ziel / ".fotosortierer" / "config.toml"
    assert kopie.is_file()
    assert kopie.read_bytes() == konf_pfad.read_bytes()
    assert not (ziel / ".fotosortierer" / "config.toml.neu").exists()


# ----------------------------------------- Pfade mit kaputten Bytes ----


@testbaum.NUR_POSIX_NAMEN
def test_pfad_mit_ungueltigen_bytes_laesst_sich_speichern(datenbank):
    """Ein einziger solcher Name darf nicht den ganzen Scan abbrechen.

    Namen dieser Art entstehen auf alten Platten, Kameraspeicherkarten und
    falsch eingehaengten SMB-Freigaben.
    """
    roh = b"/q/kaputt_\xff\xfe_bild.jpg"
    pfad = os.fsdecode(roh)
    lauf = datenbank.lauf_beginnen("scan")
    assert datenbank.datei_gesehen(pfad, "/q", 10, 1.0, "foto", lauf) == "neu"
    datenbank.stapel_schreiben()

    zeile = datenbank.zeile(pfad)
    assert zeile is not None
    assert zeile["dateityp"] == "foto"
    # Zweiter Scan findet dieselbe Zeile wieder.
    assert datenbank.datei_gesehen(pfad, "/q", 10, 1.0, "foto", lauf) == "unveraendert"


@testbaum.NUR_POSIX_NAMEN
def test_pfad_mit_ungueltigen_bytes_kommt_verlustfrei_zurueck(datenbank):
    roh = b"/q/kaputt_\xff\xfe_bild.jpg"
    pfad = os.fsdecode(roh)
    erster = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen(pfad, "/q", 10, 1.0, "foto", erster)
    zweiter = datenbank.lauf_beginnen("scan")
    fehlt = datenbank.nicht_mehr_gesehen("/q", zweiter)
    assert fehlt == [pfad]
    assert os.fsencode(fehlt[0]) == roh


def test_pfad_text_laesst_gewoehnliche_pfade_in_ruhe():
    assert db.pfad_text("/q/Ümläute und [Klammern]/a.jpg") == "/q/Ümläute und [Klammern]/a.jpg"
    assert db.text_pfad("/q/a.jpg") == "/q/a.jpg"


@testbaum.NUR_POSIX_NAMEN
def test_ereignis_mit_kaputtem_pfad(datenbank):
    pfad = os.fsdecode(b"/q/ordner_\xff")
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.ereignis(lauf, "ordner_nicht_lesbar", pfad, 1, "Ordner nicht lesbar")
    datenbank.stapel_schreiben()
    assert datenbank.ereignisse_zaehlen(lauf, "ordner_nicht_lesbar") == 1


# --------------------------------------------------------- Zaehlen ----


def test_nicht_mehr_gesehen_zaehlen_gibt_dieselbe_zahl(datenbank):
    erster = datenbank.lauf_beginnen("scan")
    for name in ("a", "b", "c"):
        datenbank.datei_gesehen(f"/q/{name}.jpg", "/q", 1, 1.0, "foto", erster)
    zweiter = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", zweiter)
    assert datenbank.nicht_mehr_gesehen_zaehlen("/q", zweiter) == 2
    assert len(datenbank.nicht_mehr_gesehen("/q", zweiter)) == 2


# ----------------------------------------------------- Archivsperre ----


def test_zweiter_lauf_auf_dasselbe_archiv_bricht_verstaendlich_ab(tmp_path):
    ordner = tmp_path / "archiv"
    erste = db.Datenbank.oeffnen(ordner, sperren=True)
    try:
        with pytest.raises(FotosortFehler) as fehler:
            db.Datenbank.oeffnen(ordner, sperren=True)
        assert "laeuft bereits ein Vorgang" in str(fehler.value)
    finally:
        erste.schliessen()
    # Nach dem Schliessen ist das Archiv wieder frei.
    zweite = db.Datenbank.oeffnen(ordner, sperren=True)
    zweite.schliessen()


def test_ohne_sperre_stoert_ein_zweites_oeffnen_nicht(tmp_path):
    ordner = tmp_path / "archiv"
    eine = db.Datenbank.oeffnen(ordner)
    andere = db.Datenbank.oeffnen(ordner)
    eine.schliessen()
    andere.schliessen()


def test_busy_timeout_ist_gesetzt(datenbank):
    wert = datenbank.verbindung.execute("PRAGMA busy_timeout").fetchone()[0]
    assert int(wert) == db.BUSY_TIMEOUT_MS


# --------------------------------------------------- Sammelschreiben ----


def test_zweites_stapel_schreiben_nach_abbruch_im_commit(datenbank):
    """Strg+C genau waehrend des COMMIT darf keinen Folgefehler ergeben.

    Die Merkvariable wird vor dem COMMIT zurueckgesetzt; scheitert das
    COMMIT mit "no transaction is active", wird das geschluckt.
    """
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", lauf)
    assert datenbank._in_transaktion is True

    echt = datenbank.verbindung

    class MitSignal:
        """Leitet alles weiter, faellt aber beim COMMIT ins Signal."""

        def __getattr__(self, name):
            return getattr(echt, name)

        def execute(self, sql, *rest):
            if sql == "COMMIT":
                # Die Transaktion wird beendet, danach kommt das Signal.
                echt.execute("COMMIT")
                raise KeyboardInterrupt
            return echt.execute(sql, *rest)

    datenbank.verbindung = MitSignal()
    with pytest.raises(KeyboardInterrupt):
        datenbank.stapel_schreiben()
    assert datenbank._in_transaktion is False

    # Der naechste Versuch laeuft durch, statt mit
    # "cannot commit - no transaction is active" zu scheitern.
    datenbank.verbindung = echt
    datenbank.stapel_schreiben()
    datenbank.schliessen()
    datenbank.schliessen()


def test_stapel_schreiben_schluckt_fehlende_transaktion(datenbank):
    datenbank._in_transaktion = True  # Merkvariable und Wirklichkeit uneins
    datenbank.stapel_schreiben()
    assert datenbank._in_transaktion is False


# ------------------------------------------ Toleranz beim mtime ----


def test_zeit_toleranz_ist_klein_und_begruendet():
    assert db.ZEIT_TOLERANZ == 0.001


def test_eine_sekunde_versatz_gilt_als_veraendert(datenbank):
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0, "foto", lauf)
    assert (
        datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1001.0, "foto", lauf)
        == "veraendert"
    )


def test_drei_sekunden_versatz_gilt_als_veraendert(datenbank):
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0, "foto", lauf)
    assert (
        datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1003.0, "foto", lauf)
        == "veraendert"
    )


def test_rundungsrest_gilt_als_unveraendert(datenbank):
    lauf = datenbank.lauf_beginnen("scan")
    datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0, "foto", lauf)
    assert (
        datenbank.datei_gesehen("/q/a.jpg", "/q", 100, 1000.0005, "foto", lauf)
        == "unveraendert"
    )


# ------------------------------------------------ Schema anheben (Migration) --


def _mit_version(ordner, version: int) -> None:
    """Eine vollstaendige Datenbank auf eine andere Schema-Version stellen."""
    d = db.Datenbank.oeffnen(ordner)
    d.stapel_schreiben()
    d.verbindung.execute(f"PRAGMA user_version={version}")
    d.schliessen()


def test_neuere_schema_version_wird_nie_angefasst(tmp_path):
    ordner = tmp_path / "neuer"
    _mit_version(ordner, db.SCHEMA_VERSION + 1)
    vorher = db.datenbank_pfad(ordner).read_bytes()
    with pytest.raises(FotosortFehler) as fehler:
        db.Datenbank.oeffnen(ordner)
    assert "neueren Stand" in str(fehler.value) and f"Schema-Version {db.SCHEMA_VERSION + 1}" in str(fehler.value)
    assert db.datenbank_pfad(ordner).read_bytes() == vorher
    assert not list(ordner.glob(db.VOR_SCHEMA + "*"))


def test_aeltere_version_wird_angehoben_und_vorher_aufgehoben(tmp_path, monkeypatch):
    ordner = tmp_path / "aelter"
    _mit_version(ordner, db.SCHEMA_VERSION - 1)
    schritte = {db.SCHEMA_VERSION - 1: ("ALTER TABLE dateien ADD COLUMN probe TEXT NOT NULL DEFAULT 'x'",)}
    monkeypatch.setattr(db, "MIGRATIONEN", schritte)
    assert db.migrierbar(db.SCHEMA_VERSION - 1) and not db.migrierbar(db.SCHEMA_VERSION + 1)
    d = db.Datenbank.oeffnen(ordner)
    try:
        assert d.angehoben_von == db.SCHEMA_VERSION - 1
        assert d.verbindung.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        spalten = {z["name"] for z in d.verbindung.execute("PRAGMA table_info(dateien)")}
        assert "probe" in spalten
    finally:
        d.schliessen()
    kopie = db.vor_schema_pfad(db.datenbank_pfad(ordner), db.SCHEMA_VERSION - 1)
    assert kopie.is_file()
    alt = sqlite3.connect(str(kopie))
    try:
        assert alt.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION - 1
        assert "probe" not in {z[1] for z in alt.execute("PRAGMA table_info(dateien)")}
    finally:
        alt.close()
    # Ein zweites Oeffnen hebt nichts mehr an.
    d = db.Datenbank.oeffnen(ordner)
    try:
        assert d.angehoben_von is None
    finally:
        d.schliessen()


def test_anhebung_ohne_schritt_lehnt_ab_und_laesst_alles_stehen(tmp_path, monkeypatch):
    ordner = tmp_path / "luecke"
    _mit_version(ordner, db.SCHEMA_VERSION - 2)
    monkeypatch.setattr(db, "MIGRATIONEN", {db.SCHEMA_VERSION - 1: ("SELECT 1",)})   # der erste Schritt fehlt
    vorher = db.datenbank_pfad(ordner).read_bytes()
    with pytest.raises(FotosortFehler) as fehler:
        db.Datenbank.oeffnen(ordner)
    assert f"Schema-Version {db.SCHEMA_VERSION - 2}" in str(fehler.value)
    assert db.datenbank_pfad(ordner).read_bytes() == vorher


def test_fehlgeschlagener_schritt_laesst_die_version_stehen(tmp_path, monkeypatch):
    ordner = tmp_path / "kaputt"
    _mit_version(ordner, db.SCHEMA_VERSION - 1)
    monkeypatch.setattr(db, "MIGRATIONEN", {db.SCHEMA_VERSION - 1: ("ALTER TABLE gibt_es_nicht ADD COLUMN x TEXT",)})
    with pytest.raises(sqlite3.OperationalError):
        db.Datenbank.oeffnen(ordner)
    alt = sqlite3.connect(str(db.datenbank_pfad(ordner)))
    try:
        assert alt.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION - 1
    finally:
        alt.close()
    assert db.vor_schema_pfad(db.datenbank_pfad(ordner), db.SCHEMA_VERSION - 1).is_file()


def test_festschreiben_uebersteht_einen_stromausfall(datenbank):
    """synchronous=FULL: Was vor dem Umbenennen oder Loeschen festgeschrieben
    wird, ist auch nach einem Stromausfall da."""
    assert datenbank.verbindung.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_nicht_sperrbares_archiv_bricht_ab(tmp_path):
    ordner = tmp_path / "archiv"
    ordner.mkdir()
    (ordner / db.SPERRDATEI).mkdir()          # die Sperrdatei laesst sich nicht oeffnen
    with pytest.raises(FotosortFehler) as fehler:
        db.Datenbank.oeffnen(ordner, sperren=True)
    assert "nicht sperren" in str(fehler.value)


def test_dieselbe_datei_ueber_zwei_einhaengungen():
    from types import SimpleNamespace as S

    from fotosort import loeschen

    a = S(st_dev=1, st_ino=4711, st_size=10, st_mtime_ns=5, st_ctime_ns=6)
    b = S(st_dev=2, st_ino=4711, st_size=10, st_mtime_ns=5, st_ctime_ns=6)   # andere Einhaengung
    kopie = S(st_dev=2, st_ino=999, st_size=10, st_mtime_ns=5, st_ctime_ns=7)
    assert loeschen.dieselbe_datei(Path("/mnt/a/x"), Path("/mnt/b/x"), a, b) is True
    assert loeschen.dieselbe_datei(Path("/mnt/a/x"), Path("/mnt/b/x"), a, kopie) is False


# ------------------------------------------ Abfrageplaene (Tempo) --------


def _plan(d: db.Datenbank, sql: str, werte: tuple) -> str:
    return " | ".join(z[3] for z in d.verbindung.execute("EXPLAIN QUERY PLAN " + sql, werte))


def test_seitenabfragen_nutzen_einen_index_ohne_neu_zu_sortieren(tmp_path):
    """Pruefen, Aufraeumen und Analyse holen ihre Zeilen seitenweise. Ohne
    passenden Index las jede Seite die ganze Restmenge und sortierte neu - der
    Aufwand wuchs quadratisch (500.000 Dateien: Pruefen 49 s nur fuer Abfragen)."""
    d = db.Datenbank.oeffnen(tmp_path / "a")
    try:
        abfragen = {
            "zu_pruefen": (f"SELECT * FROM dateien WHERE {d.ZU_PRUEFEN_SQL} AND (zielpfad, quellpfad) > (?, ?)"
                           " ORDER BY zielpfad, quellpfad LIMIT ?", ("", "", 10)),
            "zu_loeschen": (f"SELECT * FROM dateien WHERE quellwurzel = ? AND {d.ZU_LOESCHEN_SQL} AND quellpfad > ?"
                            " ORDER BY quellpfad LIMIT ?", ("/q", "", 10)),
            "zu_analysieren": ("SELECT quellpfad FROM dateien WHERE status = 'gefunden'"
                               f" AND dateityp IN {d.ECHTE_TYPEN_SQL} AND quellpfad > ? ORDER BY quellpfad LIMIT ?", ("", 10)),
            "ereignisse": ("SELECT rowid, * FROM lauf_ereignisse WHERE 1 AND art = ? ORDER BY lauf_nummer, rowid", ("x",)),
        }
        for name, (sql, werte) in abfragen.items():
            plan = _plan(d, sql, werte)
            assert "TEMP B-TREE" not in plan, (name, plan)
            assert "USING INDEX" in plan or "USING COVERING INDEX" in plan, (name, plan)
            assert "MULTI-INDEX OR" not in plan, (name, plan)
    finally:
        d.schliessen()


def test_ordner_inhalt_holt_nur_direkte_kinder_aus_der_datenbank(tmp_path, monkeypatch):
    """Eine lose Datei neben einem grossen Unterbaum: Frueher kam der ganze
    Unterbaum nach Python (300.000 Zeilen, 207 MB), um eine Zeile zu finden."""
    import os
    t = os.sep
    d = db.Datenbank.oeffnen(tmp_path / "a")
    try:
        lauf = d.lauf_beginnen("test")
        w = f"{t}q"
        d.datei_gesehen(f"{w}{t}A{t}lose.jpg", w, 1, 1.0, "foto", lauf)
        for i in range(50):
            d.datei_gesehen(f"{w}{t}A{t}2019{t}{i}.jpg", w, 1, 1.0, "foto", lauf)
        d.stapel_schreiben()
        gelesen = []
        echt = d.verbindung

        class Zaehler:
            def execute(self, sql, werte=()):
                cur = echt.execute(sql, werte)
                zeilen = cur.fetchall()
                gelesen.append(len(zeilen))
                return _Liste(zeilen)

            def __getattr__(self, name):
                return getattr(echt, name)

        class _Liste(list):
            def fetchall(self):
                return list(self)

        d.verbindung = Zaehler()
        try:
            zeilen = d.ordner_inhalt(f"{w}{t}A", t)
        finally:
            d.verbindung = echt
        assert [z["quellpfad"] for z in zeilen] == [f"{w}{t}A{t}lose.jpg"]
        assert gelesen == [1]
    finally:
        d.schliessen()


def test_sicherung_entsteht_lokal_und_wird_am_stueck_ins_ziel_kopiert(tmp_path, monkeypatch):
    """Frueher schrieb SQLite die Sicherung Seite fuer Seite (4 KiB je Aufruf)
    direkt ins Ziel - auf einem Netzlaufwerk Zehntausende Netzwege, und eine
    SQLite-Datei in Arbeit auf dem Netzlaufwerk (SPEC §6: nie). Jetzt entsteht
    sie lokal und wird als fertige Datei kopiert."""
    d = db.Datenbank.oeffnen(tmp_path / "a")
    try:
        lauf = d.lauf_beginnen("test")
        d.datei_gesehen("/q/a.jpg", "/q", 1, 1.0, "foto", lauf)
        ziel = tmp_path / "Ziel"
        ziel.mkdir()
        geoeffnet = []
        echt = sqlite3.connect
        monkeypatch.setattr(db.sqlite3, "connect", lambda pfad, *a, **k: geoeffnet.append(str(pfad)) or echt(pfad, *a, **k))
        d.sichern_nach(ziel)
        d.sichern_nach(ziel)
        assert geoeffnet and not [p for p in geoeffnet if str(ziel) in p]
        monkeypatch.setattr(db.sqlite3, "connect", echt)
        assert db.sicherung_pfad(ziel).is_file() and db.sicherung_vorher_pfad(ziel).is_file()
        con = sqlite3.connect(db.sicherung_pfad(ziel))
        try:
            assert con.execute("SELECT quellpfad FROM dateien").fetchall() == [("/q/a.jpg",)]
            assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            con.close()
        # Nichts Halbes bleibt liegen, weder lokal noch im Ziel.
        assert not list((tmp_path / "a").glob("*sicherung*"))
        assert not list((ziel / db.ARCHIV_UNTERORDNER).glob("*.neu"))
    finally:
        d.schliessen()
