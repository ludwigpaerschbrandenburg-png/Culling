"""Tests fuer scan.py (SPEC Abschnitt 4 Phase 1, Abschnitt 6 "Zweiter Scan")."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import testbaum
from fotosort import FotosortFehler, config, db, scan


@pytest.fixture
def datenbank(tmp_path):
    d = db.Datenbank.oeffnen(tmp_path / "archiv")
    yield d
    d.schliessen()


def _scannen(quelle, ziel, datenbank, konf, lauf=None):
    nummer = lauf if lauf is not None else datenbank.lauf_beginnen("scan")
    ergebnis = scan.ausfuehren(quelle, ziel, konf, datenbank, nummer)
    datenbank.lauf_beenden(nummer)
    return ergebnis, nummer


def _mit_muster(muster: list[str]) -> config.Konfiguration:
    k = config.Konfiguration()
    k.alle()["quelle"]["ausschlussmuster"] = muster
    return k


# ------------------------------------------------- Anzahl und Aufteilung ----


def test_scan_findet_erwartete_anzahl_und_aufteilung(quelle, ziel, datenbank, konf):
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT
    assert ergebnis.je_typ == testbaum.ERWARTET_JE_TYP
    assert ergebnis.neu == testbaum.ERWARTET_GESAMT
    assert ergebnis.bytes_gesamt > 0


def test_jede_datei_bekommt_eine_zeile(quelle, ziel, datenbank, konf):
    _scannen(quelle, ziel, datenbank, konf)
    anzahl = datenbank.verbindung.execute("SELECT COUNT(*) FROM dateien").fetchone()[0]
    assert anzahl == testbaum.ERWARTET_GESAMT


def test_dateien_ausserhalb_der_typenlisten(quelle, ziel, datenbank, konf, baum):
    # sonstiges plus Status uebersprungen mit Grund "uebersprungen nach Typ".
    _scannen(quelle, ziel, datenbank, konf)
    zeile = datenbank.zeile(baum["sonstiges_text"].resolve())
    assert zeile["dateityp"] == "sonstiges"
    assert zeile["status"] == "uebersprungen"
    assert zeile["fehlergrund"] == scan.GRUND_NACH_TYP


def test_sidecar_ist_nie_uebersprungen_nach_typ(quelle, ziel, datenbank, konf, baum):
    _scannen(quelle, ziel, datenbank, konf)
    for schluessel in ("sidecar_form1", "sidecar_form2", "sidecar_form3"):
        zeile = datenbank.zeile(baum[schluessel].resolve())
        assert zeile["dateityp"] == "sidecar"
        assert zeile["status"] == "gefunden"


def test_lauf_nummern_werden_eingetragen(quelle, ziel, datenbank, konf, baum):
    _, lauf = _scannen(quelle, ziel, datenbank, konf)
    zeile = datenbank.zeile(baum["jpg"].resolve())
    assert zeile["gefunden_in_lauf"] == lauf
    assert zeile["zuletzt_gesehen_in_lauf"] == lauf


# ------------------------------------------------------------ Fortsetzen ----


def test_zweiter_scan_zaehlt_nichts_doppelt(quelle, ziel, datenbank, konf):
    _scannen(quelle, ziel, datenbank, konf)
    zweites, _ = _scannen(quelle, ziel, datenbank, konf)
    assert zweites.dateien == testbaum.ERWARTET_GESAMT
    assert zweites.neu == 0
    assert zweites.unveraendert == testbaum.ERWARTET_GESAMT
    assert zweites.veraendert == 0
    anzahl = datenbank.verbindung.execute("SELECT COUNT(*) FROM dateien").fetchone()[0]
    assert anzahl == testbaum.ERWARTET_GESAMT


def test_zweiter_scan_laesst_den_status_in_ruhe(quelle, ziel, datenbank, konf, baum):
    _scannen(quelle, ziel, datenbank, konf)
    pfad = str(baum["jpg"].resolve())
    datenbank.verbindung.execute(
        "UPDATE dateien SET status='kopiert', hash='abc', zielpfad='/z/x.jpg'"
        " WHERE quellpfad=?",
        (pfad,),
    )
    _scannen(quelle, ziel, datenbank, konf)
    zeile = datenbank.zeile(pfad)
    assert zeile["status"] == "kopiert"
    assert zeile["hash"] == "abc"
    assert zeile["zielpfad"] == "/z/x.jpg"


def test_veraenderte_datei_faellt_auf_gefunden_zurueck(
    quelle, ziel, datenbank, konf, baum
):
    _scannen(quelle, ziel, datenbank, konf)
    pfad = str(baum["aendert_sich"].resolve())
    datenbank.verbindung.execute(
        "UPDATE dateien SET status='geprueft', hash='abc', zielpfad='/z/x.jpg',"
        " bestaetigt_in_lauf=1 WHERE quellpfad=?",
        (pfad,),
    )

    baum["aendert_sich"].write_bytes(b"ein ganz anderer Inhalt")
    werte = os.stat(pfad)
    os.utime(pfad, (werte.st_atime, werte.st_mtime + 10))

    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.veraendert == 1
    zeile = datenbank.zeile(pfad)
    assert zeile["status"] == "gefunden"
    assert zeile["hash"] == ""
    assert zeile["zielpfad"] == ""
    assert zeile["bestaetigt_in_lauf"] is None


def test_verschwundene_datei_behaelt_ihre_zeile(quelle, ziel, datenbank, konf, baum):
    _scannen(quelle, ziel, datenbank, konf)
    pfad = str(baum["ohne_datum"].resolve())
    baum["ohne_datum"].unlink()

    ergebnis, lauf = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.verschwunden == 1
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT - 1
    zeile = datenbank.zeile(pfad)
    assert zeile is not None
    assert zeile["zuletzt_gesehen_in_lauf"] != lauf


def test_abgebrochener_scan_wertet_verschwundene_nicht_aus(
    quelle, ziel, datenbank, konf, monkeypatch
):
    _scannen(quelle, ziel, datenbank, konf)

    echt = datenbank.datei_gesehen
    stand = {"n": 0}

    def abbrechen(*args, **kwargs):
        stand["n"] += 1
        if stand["n"] > 3:
            raise KeyboardInterrupt
        return echt(*args, **kwargs)

    monkeypatch.setattr(datenbank, "datei_gesehen", abbrechen)
    lauf = datenbank.lauf_beginnen("scan")
    ergebnis = scan.ausfuehren(quelle, ziel, konf, datenbank, lauf)

    assert ergebnis.abgebrochen is True
    assert ergebnis.verschwunden == 0
    # Das Bisherige ist geschrieben, der Lauf bleibt offen und fortsetzbar.
    assert datenbank.letzter_lauf()["ende"] == ""
    assert (
        datenbank.verbindung.execute("SELECT COUNT(*) FROM dateien").fetchone()[0]
        == testbaum.ERWARTET_GESAMT
    )


def test_nach_abbruch_laeuft_der_naechste_scan_durch(quelle, ziel, datenbank, konf):
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.abgebrochen is False
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT


# ---------------------------------------------------- Lage Quelle/Ziel ----


def test_quelle_gleich_ziel_bricht_ab(quelle, datenbank, konf):
    with pytest.raises(FotosortFehler) as fehler:
        _scannen(quelle, quelle, datenbank, konf)
    assert "derselbe Ordner" in str(fehler.value)


def test_quelle_in_ziel_bricht_ab(quelle, datenbank, konf, baum):
    grosses_ziel = baum["wurzel"]
    with pytest.raises(FotosortFehler) as fehler:
        _scannen(quelle, grosses_ziel, datenbank, konf)
    assert "innerhalb des Ziels" in str(fehler.value)


def test_ziel_in_quelle_wird_uebersprungen_und_der_lauf_laeuft_weiter(
    quelle, datenbank, konf
):
    inneres_ziel = quelle / "_Ziel"
    inneres_ziel.mkdir()
    (inneres_ziel / "schon_einsortiert.jpg").write_bytes(b"Archivbild")

    ergebnis, _ = _scannen(quelle, inneres_ziel, datenbank, konf)
    assert ergebnis.ziel_ausgeschlossen is True
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT
    zeile = datenbank.zeile((inneres_ziel / "schon_einsortiert.jpg").resolve())
    assert zeile is None


def test_datei_verknuepfung_ins_ziel_wird_uebersprungen(quelle, ziel, datenbank, konf):
    archivbild = ziel / "2026" / "DSC01234.ARW"
    archivbild.parent.mkdir(parents=True)
    archivbild.write_bytes(b"fertiges Archivbild")
    link = quelle / "Lieblingsbilder_DSC01234.ARW"
    link.symlink_to(archivbild)

    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.ins_ziel == 1
    zeile = datenbank.zeile(link)
    assert zeile is not None
    assert zeile["status"] == "uebersprungen"
    assert zeile["fehlergrund"] == scan.GRUND_INS_ZIEL
    # Der Pfad der Archivdatei steht nirgends als quellpfad.
    assert datenbank.zeile(archivbild.resolve()) is None


def test_ordner_verknuepfung_ins_ziel_wird_uebersprungen(quelle, ziel, datenbank, konf):
    (ziel / "2026").mkdir(parents=True)
    (ziel / "2026" / "bild.jpg").write_bytes(b"Archivbild")
    konf.alle()["quelle"]["verknuepfungen_folgen"] = True
    link = quelle / "abkuerzung_ins_ziel"
    link.symlink_to(ziel, target_is_directory=True)

    ergebnis, lauf = _scannen(quelle, ziel, datenbank, konf)
    # Verfolgt werden beide Verknuepfungen; die ins Ziel wird trotzdem
    # ausgeschlossen. Dazu kommt nur die Datei hinter "verlinkt".
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT + 1
    assert datenbank.ereignisse_zaehlen(lauf, scan.ART_INS_ZIEL) >= 1
    assert datenbank.zeile((ziel / "2026" / "bild.jpg").resolve()) is None


# ------------------------------------------------------ Verknuepfungen ----


def test_ordner_verknuepfung_wird_nicht_verfolgt_und_erzeugt_ereignis(
    quelle, ziel, datenbank, konf, baum
):
    ergebnis, lauf = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.verknuepfungen == 1
    assert datenbank.ereignisse_zaehlen(lauf, scan.ART_VERKNUEPFUNG) == 1
    # Die Datei dahinter steht nicht in der Datenbank.
    assert datenbank.zeile(baum["nur_ueber_verknuepfung"].resolve()) is None


def test_mit_verknuepfungen_folgen_kommt_die_datei_dazu(quelle, ziel, datenbank, konf):
    konf.alle()["quelle"]["verknuepfungen_folgen"] = True
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.verknuepfungen == 0
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT + 1


# ---------------------------------------------------- Ausschlussmuster ----


def test_ausschlussmuster_ueberspringt_ordner_samt_inhalt(quelle, ziel, datenbank, baum):
    konf = _mit_muster([testbaum.AUSSCHLUSSMUSTER_BEISPIEL])
    ergebnis, lauf = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT_OHNE_PAPIERKORB
    assert ergebnis.je_typ == testbaum.ERWARTET_JE_TYP_OHNE_PAPIERKORB
    assert ergebnis.ausgeschlossen == 1
    assert datenbank.ereignisse_zaehlen(lauf, scan.ART_AUSGESCHLOSSEN) == 1
    assert datenbank.zeile(baum["im_papierkorb"].resolve()) is None


def test_ausschlussmuster_ohne_gross_kleinschreibung(quelle, ziel, datenbank, baum):
    konf = _mit_muster(["*/PAPIERKORB/*"])
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert datenbank.zeile(baum["im_papierkorb"].resolve()) is None
    assert ergebnis.ausgeschlossen == 1


def test_ausschlussmuster_trifft_einzelne_datei(quelle, ziel, datenbank, baum):
    konf = _mit_muster(["*.txt"])
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert datenbank.zeile(baum["sonstiges_text"].resolve()) is None
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT - 1


@pytest.mark.parametrize(
    "relativ,muster,ordner,erwartet",
    [
        ("a/Papierkorb/x.jpg", ["*/Papierkorb/*"], False, True),
        ("a/Papierkorb", ["*/Papierkorb/*"], True, True),
        # Ein Papierkorb ganz oben in der Quelle heisst relativ zur Wurzel
        # schlicht "Papierkorb/...". Wer das Beispiel aus SPEC Abschnitt 9
        # abschreibt, will auch ihn treffen.
        ("Papierkorb/x.jpg", ["*/Papierkorb/*"], False, True),
        ("Papierkorb", ["*/Papierkorb/*"], True, True),
        ("a/b.JPG", ["*.jpg"], False, True),
        ("a/b.jpg", [], False, False),
        # Ohne fuehrendes "*/" bleibt das Muster so streng wie geschrieben.
        ("a/Papierkorb/x.jpg", ["Papierkorb/*"], False, False),
    ],
)
def test_ist_ausgeschlossen(relativ, muster, ordner, erwartet):
    assert scan.ist_ausgeschlossen(relativ, muster, ordner=ordner) is erwartet


# ------------------------------------------------------------- Sonstiges ----


def test_versteckter_ordner_wird_normal_erfasst(quelle, ziel, datenbank, konf, baum):
    _scannen(quelle, ziel, datenbank, konf)
    assert datenbank.zeile(baum["versteckt"].resolve()) is not None


def test_fehlende_quelle_bricht_ab(tmp_path, ziel, datenbank, konf):
    with pytest.raises(FotosortFehler) as fehler:
        _scannen(tmp_path / "gibt-es-nicht", ziel, datenbank, konf)
    assert "Quellordner" in str(fehler.value)


def test_kaputte_verknuepfung_bekommt_status_fehler(quelle, ziel, datenbank, konf):
    kaputt = quelle / "kaputte_verknuepfung.jpg"
    kaputt.symlink_to(quelle / "gibt-es-nicht.jpg")
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.fehler == 1
    # Gespeichert wird der Pfad der Verknuepfung selbst, nicht ihr Ziel.
    zeile = datenbank.zeile(kaputt)
    assert zeile["status"] == "fehler"
    assert datenbank.zeile(quelle / "gibt-es-nicht.jpg") is None


def test_quellwurzel_wird_gespeichert(quelle, ziel, datenbank, konf, baum):
    _scannen(quelle, ziel, datenbank, konf)
    zeile = datenbank.zeile(baum["jpg"].resolve())
    assert zeile["quellwurzel"] == str(quelle.resolve())


def test_scan_liest_keine_inhalte(quelle, ziel, datenbank, konf, baum):
    # In Phase 1 wird nichts gehasht und kein Ziel berechnet.
    _scannen(quelle, ziel, datenbank, konf)
    zeile = datenbank.zeile(baum["jpg"].resolve())
    assert zeile["hash"] == ""
    assert zeile["zielpfad"] == ""
    assert zeile["kamera"] == ""
    assert zeile["aufnahme_zeit"] == ""


# -------------------------------------------- Nicht lesbarer Ordner ----


def _ordner_sperren(monkeypatch, gesperrt: Path):
    """os.scandir fuer genau einen Ordner scheitern lassen.

    Im Container laeuft alles als Systemverwalter; Rechte greifen dort
    nicht. Nachgestellt wird deshalb der Fehler selbst - es ist derselbe,
    den ein Netzlaufwerk mit Aussetzer und ein zu langer Pfad unter Windows
    ausloesen.
    """
    echt = os.scandir

    def gestoert(pfad="."):
        if Path(pfad) == gesperrt:
            raise PermissionError(13, "Permission denied")
        return echt(pfad)

    monkeypatch.setattr(scan.os, "scandir", gestoert)


def test_nicht_lesbarer_ordner_wird_gezaehlt_und_genannt(
    quelle, ziel, datenbank, konf, monkeypatch
):
    gesperrt = quelle / "Duplikate"
    _ordner_sperren(monkeypatch, gesperrt.resolve())

    ergebnis, lauf = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.ordner_nicht_lesbar == 1
    assert str(gesperrt.resolve()) in ergebnis.nicht_lesbare_ordner
    # Eigene Ereignisart, nicht das unspezifische "fehler".
    assert datenbank.ereignisse_zaehlen(lauf, scan.ART_ORDNER_NICHT_LESBAR) == 1
    assert datenbank.ereignisse_zaehlen(lauf, "fehler") == 0
    # Die zwei Dateien darin fehlen im Ergebnis - genau das muss auffallen.
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT - 2


def test_nicht_lesbarer_ordner_sperrt_die_auswertung_der_verschwundenen(
    quelle, ziel, datenbank, konf, monkeypatch
):
    """Sonst meldet ein erfolgreicher Lauf dem Nutzer den Verlust von Bildern."""
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.verschwunden_ausgewertet is True

    gesperrt = quelle / "Duplikate"
    _ordner_sperren(monkeypatch, gesperrt.resolve())
    zweites, _ = _scannen(quelle, ziel, datenbank, konf)

    assert zweites.ordner_nicht_lesbar == 1
    assert zweites.verschwunden_ausgewertet is False
    assert zweites.verschwunden == 0
    # Die Zeilen der beiden Dateien stehen unveraendert in der Datenbank.
    for schluessel in ("duplikat_a", "duplikat_b"):
        assert datenbank.zeile(baum_pfad(quelle, schluessel)) is not None


def baum_pfad(quelle: Path, schluessel: str) -> Path:
    namen = {"duplikat_a": "kopie_a.jpg", "duplikat_b": "kopie_b.jpg"}
    return quelle.resolve() / "Duplikate" / namen[schluessel]


# ------------------------------------------------------ Verknuepfungen ----


def test_verknuepfung_wird_unter_ihrem_eigenen_pfad_gespeichert(
    quelle, ziel, datenbank, konf, baum
):
    """Nie der aufgeloeste Pfad: Der zeigt aus der Quelle heraus.

    Ein spaeteres Aufraeumen wuerde sonst die Originaldatei ausserhalb der
    Quelle loeschen.
    """
    aussen = baum["ausserhalb"] / "original.jpg"
    aussen.write_bytes(b"Originalbild")
    link = quelle / "verweis_auf_original.jpg"
    link.symlink_to(aussen)

    _scannen(quelle, ziel, datenbank, konf)
    assert datenbank.zeile(link) is not None
    assert datenbank.zeile(aussen.resolve()) is None


def test_zwei_verknuepfungen_auf_dieselbe_datei_ergeben_zwei_zeilen(
    quelle, ziel, datenbank, konf, baum
):
    aussen = baum["ausserhalb"] / "original.jpg"
    aussen.write_bytes(b"Originalbild")
    eins = quelle / "verweis_eins.jpg"
    zwei = quelle / "verweis_zwei.jpg"
    eins.symlink_to(aussen)
    zwei.symlink_to(aussen)

    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT + 2
    # Gezaehlt wird, was auch in der Datenbank steht.
    anzahl = datenbank.verbindung.execute("SELECT COUNT(*) FROM dateien").fetchone()[0]
    assert anzahl == ergebnis.dateien
    assert ergebnis.neu == ergebnis.dateien
    assert ergebnis.unveraendert == 0
    assert datenbank.zeile(eins) is not None
    assert datenbank.zeile(zwei) is not None


def test_verknuepfung_auf_eine_datei_in_der_quelle_faellt_nicht_zusammen(
    quelle, ziel, datenbank, konf, baum
):
    link = quelle / "verweis_auf_jpg.jpg"
    link.symlink_to(baum["jpg"])
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT + 1
    assert datenbank.zeile(link) is not None
    assert datenbank.zeile(baum["jpg"].resolve()) is not None


# ---------------------------------------------- Kaputte Dateinamen ----


@testbaum.NUR_POSIX_NAMEN
def test_dateiname_mit_ungueltigen_bytes_bricht_den_scan_nicht_ab(
    quelle, ziel, datenbank, konf
):
    """Ein einziger solcher Name hat frueher den ganzen Scan abgebrochen."""
    roh = os.fsencode(str(quelle.resolve())) + b"/kaputt_\xff\xfe_bild.jpg"
    with open(roh, "wb") as fh:
        fh.write(b"Bild")

    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.abgebrochen is False
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT + 1
    anzahl = datenbank.verbindung.execute("SELECT COUNT(*) FROM dateien").fetchone()[0]
    assert anzahl == testbaum.ERWARTET_GESAMT + 1
    zeile = datenbank.zeile(os.fsdecode(roh))
    assert zeile is not None
    assert zeile["dateityp"] == "foto"

    # Und ein zweiter Scan erkennt sie wieder.
    zweites, _ = _scannen(quelle, ziel, datenbank, konf)
    assert zweites.neu == 0
    assert zweites.veraendert == 0


# ------------------------------------ Quelle veraendert: Berichtsliste ----


def test_veraenderte_quelle_steht_in_lauf_ereignissen(quelle, ziel, datenbank, konf, baum):
    """SPEC Abschnitt 10: Die Liste muss die Datenbank ueberleben."""
    _scannen(quelle, ziel, datenbank, konf)
    pfad = baum["aendert_sich"]
    pfad.write_bytes(b"ein ganz anderer Inhalt")
    werte = os.stat(pfad)
    os.utime(pfad, (werte.st_atime, werte.st_mtime + 10))

    ergebnis, lauf = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.veraendert == 1
    assert datenbank.ereignisse_zaehlen(lauf, scan.ART_QUELLE_VERAENDERT) == 1
    zeile = datenbank.verbindung.execute(
        "SELECT pfad, text FROM lauf_ereignisse WHERE lauf_nummer = ? AND art = ?",
        (lauf, scan.ART_QUELLE_VERAENDERT),
    ).fetchone()
    assert zeile["pfad"] == str(pfad.resolve())
    assert zeile["text"] == scan.TEXT_QUELLE_VERAENDERT


def test_unveraenderte_datei_erzeugt_kein_ereignis(quelle, ziel, datenbank, konf):
    _scannen(quelle, ziel, datenbank, konf)
    _, lauf = _scannen(quelle, ziel, datenbank, konf)
    assert datenbank.ereignisse_zaehlen(lauf, scan.ART_QUELLE_VERAENDERT) == 0


# ---------------------------------------------- Ausschluss ganz oben ----


def test_ausschlussmuster_trifft_auch_den_obersten_ordner(quelle, ziel, datenbank):
    """Das Beispiel aus SPEC Abschnitt 9 soll jeden Papierkorb treffen."""
    oben = quelle / "Papierkorb"
    oben.mkdir()
    (oben / "muell.jpg").write_bytes(b"Muell")

    konf = _mit_muster([testbaum.AUSSCHLUSSMUSTER_BEISPIEL])
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert datenbank.zeile((oben / "muell.jpg").resolve()) is None
    # Der Papierkorb ganz oben und der tiefer liegende, beide getroffen.
    assert ergebnis.ausgeschlossen == 2
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT_OHNE_PAPIERKORB


# ------------------------------------------- Fortschritt ohne Terminal ----


class _Sammelkonsole:
    """Konsole ohne Terminal - wie im Container und bei umgeleiteter Ausgabe."""

    is_terminal = False

    def __init__(self) -> None:
        self.zeilen: list[str] = []

    def print(self, text="") -> None:
        self.zeilen.append(str(text))


def test_ohne_terminal_gibt_es_trotzdem_fortschritt():
    """Sonst bleibt das Programm bei 500.000 Dateien minutenlang stumm."""
    konsole = _Sammelkonsole()
    anzeige, aufgabe = scan._fortschritt_starten(konsole)
    assert isinstance(anzeige, scan._StilleAnzeige)
    assert aufgabe is None

    # Gleich nach dem Start wird nichts gesagt.
    anzeige.zeigen(1000)
    assert konsole.zeilen == []

    # Nach der Wartezeit kommt eine Zeile.
    anzeige._zuletzt -= scan._STILLE_SEKUNDEN + 1
    anzeige.zeigen(60000)
    assert len(konsole.zeilen) == 1
    assert "60.000" in konsole.zeilen[0]

    # Und danach wieder Ruhe, bis die naechsten Sekunden um sind.
    anzeige.zeigen(60500)
    assert len(konsole.zeilen) == 1


def test_scan_ohne_terminal_laeuft_durch(quelle, ziel, datenbank, konf):
    konsole = _Sammelkonsole()
    lauf = datenbank.lauf_beginnen("scan")
    ergebnis = scan.ausfuehren(quelle, ziel, konf, datenbank, lauf, konsole)
    assert ergebnis.dateien == testbaum.ERWARTET_GESAMT


# ----------------------------------- Ausschlussmuster trifft alles ----


def test_muster_das_die_ganze_quelle_trifft_wird_gemeldet(quelle, ziel, datenbank):
    konf = _mit_muster(["*"])
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.dateien == 0
    assert ergebnis.alles_ausgeschlossen is True


def test_ohne_muster_wird_nichts_gemeldet(quelle, ziel, datenbank, konf):
    ergebnis, _ = _scannen(quelle, ziel, datenbank, konf)
    assert ergebnis.alles_ausgeschlossen is False
