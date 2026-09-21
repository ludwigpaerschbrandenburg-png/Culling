"""Tests fuer db.py (SPEC Abschnitt 6)."""

from __future__ import annotations

import os
import sqlite3
import sys

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
