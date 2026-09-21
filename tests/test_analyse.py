"""Phase 2 Ende-zu-Ende am Testbaum (SPEC Abschnitt 4 Phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

import testbaum
from fotosort import analyse, cli, db, scan


def _laufen(capsys, *args):
    rueckgabe = cli.main([str(a) for a in args])
    return rueckgabe, capsys.readouterr().out


@pytest.fixture
def vorbereitet(quelle, ziel, archiv_basis, konf):
    """Gescannter Testbaum mit vorbelegtem Ziel, Datenbank offen."""
    vor = testbaum.ziel_vorbelegen(ziel, konf)
    dbank = db.Datenbank.oeffnen(archiv_basis / "a")
    lauf = dbank.lauf_beginnen("test")
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    yield dbank, lauf, vor
    dbank.schliessen()


def _analyse(dbank, lauf, ziel, konf, prozesse=2):
    return analyse.ausfuehren(ziel, konf, dbank, lauf, testbaum.exiftool_pfad(), None, prozesse)


def _zeile(dbank, pfad: Path):
    return dbank.zeile(pfad)


# ------------------------------------------------------------ Ablauf ----


def test_alle_echten_typen_werden_analysiert(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    e = _analyse(dbank, lauf, ziel, konf)
    echte = testbaum.ERWARTET_GESAMT - testbaum.ERWARTET_JE_TYP["sonstiges"]
    assert e.bearbeitet == echte
    assert e.fehler == 0 and not e.abgebrochen
    zaehler = dbank.zaehler_je_status()
    assert zaehler.get("analysiert", 0) == echte
    assert zaehler.get("gefunden", 0) == 0
    assert zaehler.get("uebersprungen", 0) == testbaum.ERWARTET_JE_TYP["sonstiges"]


def test_zweiter_lauf_tut_nichts(vorbereitet, ziel, konf):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    vorher = {z["quellpfad"]: tuple(z) for z in dbank.verbindung.execute("SELECT * FROM dateien")}
    e = _analyse(dbank, lauf, ziel, konf)
    assert e.bearbeitet == 0
    nachher = {z["quellpfad"]: tuple(z) for z in dbank.verbindung.execute("SELECT * FROM dateien")}
    assert vorher == nachher


def test_es_wird_keine_datei_angefasst(vorbereitet, ziel, konf, quelle):
    dbank, lauf, _ = vorbereitet
    vorher = sorted((p, p.stat().st_mtime_ns, p.stat().st_size) for p in quelle.rglob("*") if p.is_file())
    ziel_vorher = sorted(p for p in ziel.rglob("*"))
    _analyse(dbank, lauf, ziel, konf)
    nachher = sorted((p, p.stat().st_mtime_ns, p.stat().st_size) for p in quelle.rglob("*") if p.is_file())
    assert vorher == nachher
    assert sorted(p for p in ziel.rglob("*")) == ziel_vorher


# --------------------------------------------------- Datum und Kamera ----


def test_pflichtfall_mp4_2330_utc_landet_im_ordner_0102(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, baum["video_nur_utc"])
    assert z["aufnahme_zeit"] == "2026-01-02T00:30:00"
    assert z["datum_quelle"] == 3 and z["datum_sicher"] == 1
    assert z["datum_hinweis"] == "zeitzone_angenommen"
    assert "/2026-01-02/" in z["zielpfad"].replace("\\", "/")
    assert "_Ohne_Datum" not in z["zielpfad"]


def test_sony_eingebettetes_xml_gewinnt_vor_utc(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, baum["video_sony_eingebettet"])
    assert z["aufnahme_zeit"] == "2026-01-01T23:30:00"  # nicht 22:30 UTC, nicht 02.01.
    assert z["datum_quelle"] == 2 and z["datum_hinweis"] == ""
    assert z["kamera"] == "A7C2" and z["kamera_modell"] == "ILCE-7CM2"


def test_sony_sidecar_gewinnt_vor_utc(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, baum["video_ohne_offset"])  # C0001.MP4 mit C0001M01.XML
    assert z["aufnahme_zeit"] == "2026-03-16T00:30:00" and z["datum_quelle"] == 2


def test_video_mit_offset(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, baum["video_mit_offset"])
    assert z["aufnahme_zeit"] == "2026-02-10T10:00:00" and z["datum_quelle"] == 2


def test_kamera_und_alias(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    assert _zeile(dbank, baum["raw"])["kamera"] == "A7C2"
    assert _zeile(dbank, baum["analog"])["kamera"] == "Analog"
    assert _zeile(dbank, baum["analog"])["kamera_modell"] == "Noritsu Koki QSS-32_33"
    assert _zeile(dbank, baum["ohne_datum"])["kamera"] == "Unbekannte_Kamera"


def test_kaputtes_datum_und_ohne_datum_landen_in_ohne_datum(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    for schluessel in ("kaputtes_datum", "ohne_datum"):
        z = _zeile(dbank, baum[schluessel])
        assert z["datum_quelle"] == 6 and z["datum_sicher"] == 0
        assert "_Ohne_Datum" in z["zielpfad"]


def test_datum_aus_dateiname(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    mit = _zeile(dbank, baum["name_mit_uhrzeit"])
    ohne = _zeile(dbank, baum["name_ohne_uhrzeit"])
    assert mit["datum_quelle"] == 5 and mit["aufnahme_zeit"] == "2026-01-01T01:30:00" and mit["datum_hinweis"] == ""
    assert ohne["datum_quelle"] == 5 and ohne["datum_hinweis"] == "dateiname_ohne_uhrzeit"


# ------------------------------------------------------------ Gruppen ----


def test_gruppe_erbt_datum_und_kamera_der_hauptdatei(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    haupt = _zeile(dbank, baum["raw"])
    for schluessel in ("jpg", "sidecar_form1", "sidecar_form2"):
        z = _zeile(dbank, baum[schluessel])
        assert z["status"] == "analysiert"
        assert z["aufnahme_zeit"] == haupt["aufnahme_zeit"]
        assert z["kamera"] == haupt["kamera"]
        assert z["gruppe"] == haupt["quellpfad"]
        assert Path(z["zielpfad"]).parent == Path(haupt["zielpfad"]).parent
    assert haupt["gruppe"] == haupt["quellpfad"]


def test_sony_sidecar_gehoert_zum_video(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    video = _zeile(dbank, baum["video_ohne_offset"])
    xml = _zeile(dbank, baum["sidecar_form3"])
    assert xml["status"] == "analysiert" and xml["gruppe"] == video["quellpfad"]
    assert xml["aufnahme_zeit"] == video["aufnahme_zeit"]


def test_sidecar_ohne_hauptdatei_wird_uebersprungen(vorbereitet, ziel, konf, quelle):
    dbank, lauf, _ = vorbereitet
    verwaist = quelle / "2026" / "verwaist.xmp"
    verwaist.write_text("<x/>", encoding="utf-8")
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    e = _analyse(dbank, lauf, ziel, konf)
    assert e.sidecar_ohne_haupt == 1
    z = _zeile(dbank, verwaist)
    assert z["status"] == "uebersprungen" and z["fehlergrund"] == "Sidecar ohne Hauptdatei"


# ----------------------------------------------------- Zielstruktur -----


def test_bestehender_ordner_mit_zusatz_wird_benutzt(vorbereitet, ziel, konf, baum):
    """Pflichttest SPEC Abschnitt 11: '2026-01-01 Geburtstag Oma' wird wiederverwendet."""
    dbank, lauf, vor = vorbereitet
    e = _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, baum["raw"])
    assert Path(z["zielpfad"]) == vor["zusatz_ordner"] / "DSC01234.ARW"
    assert e.wiederverwendet >= 1 and e.mehrdeutig == 0


def test_namenskonflikt_bekommt_denselben_zielpfad_anhang_ist_phase_3(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    a = _zeile(dbank, baum["jpg"])
    b = _zeile(dbank, baum["namenskonflikt"])
    assert a["zielpfad"] == b["zielpfad"]


def test_originalname_bleibt_erhalten(vorbereitet, ziel, konf, baum):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    for schluessel in ("raw", "jpg", "name_ohne_uhrzeit", "tiefer_pfad"):
        z = _zeile(dbank, baum[schluessel])
        assert Path(z["zielpfad"]).name == baum[schluessel].name


# ------------------------------------------------------- Fortsetzen -----


def test_abbruch_und_fortsetzen_ergeben_dasselbe(vorbereitet, ziel, konf, monkeypatch, archiv_basis, quelle):
    dbank, lauf, _ = vorbereitet
    # Kleine Seiten, Abbruch nach der ersten
    monkeypatch.setattr(analyse, "SEITE", 4)
    original = analyse._seite_bearbeiten
    aufrufe = []

    def unterbrechen(*args, **kwargs):
        aufrufe.append(1)
        if len(aufrufe) == 2:
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr(analyse, "_seite_bearbeiten", unterbrechen)
    e1 = _analyse(dbank, lauf, ziel, konf)
    assert e1.abgebrochen and 0 < e1.bearbeitet
    teil = dbank.zaehler_je_status()
    assert teil.get("gefunden", 0) > 0 and teil.get("analysiert", 0) > 0

    monkeypatch.setattr(analyse, "_seite_bearbeiten", original)
    e2 = _analyse(dbank, lauf, ziel, konf)
    assert not e2.abgebrochen and dbank.zaehler_je_status().get("gefunden", 0) == 0
    fortgesetzt = {z["quellpfad"]: (z["status"], z["aufnahme_zeit"], z["kamera"], z["zielpfad"], z["gruppe"])
                   for z in dbank.verbindung.execute("SELECT * FROM dateien")}

    # Vergleich mit einem ungestoerten Lauf in einem zweiten Archiv
    d2 = db.Datenbank.oeffnen(archiv_basis / "b")
    try:
        l2 = d2.lauf_beginnen("test")
        scan.ausfuehren(quelle, ziel, konf, d2, l2)
        _analyse(d2, l2, ziel, konf)
        glatt = {z["quellpfad"]: (z["status"], z["aufnahme_zeit"], z["kamera"], z["zielpfad"], z["gruppe"])
                 for z in d2.verbindung.execute("SELECT * FROM dateien")}
    finally:
        d2.schliessen()
    assert fortgesetzt == glatt


def test_nicht_lesbare_hauptdatei_bekommt_fehler_und_der_lauf_geht_weiter(vorbereitet, ziel, konf, quelle):
    """Eine Datei, die ExifTool nicht liefern kann, bekommt Status fehler.

    Im Container laufen die Tests als root, Rechte greifen dort nicht.
    Deshalb verschwindet die Datei zwischen Scan und Analyse - ein
    Alltagsfall (Karte gezogen), der denselben Weg im Code nimmt.
    """
    dbank, lauf, _ = vorbereitet
    weg = quelle / "2026" / "weg.jpg"
    weg.write_bytes(b"kein bild")
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    weg.unlink()
    e = _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, weg)
    assert z["status"] == "fehler" and z["fehlergrund"] == "Metadaten nicht lesbar"
    assert e.fehler == 1
    assert dbank.zaehler_je_status().get("gefunden", 0) == 0
    assert dbank.zaehler_je_status().get("analysiert", 0) > 0  # der Rest lief weiter


# ---------------------------------------------------------- CLI --------


def test_cli_analyse_zeigt_zusammenfassung(capsys, quelle, ziel):
    _laufen(capsys, "scan", "--quelle", quelle, "--ziel", ziel)
    rueckgabe, ausgabe = _laufen(capsys, "analyse", "--ziel", ziel)
    assert rueckgabe == cli.OK, ausgabe
    assert "Ergebnis der Analyse" in ausgabe
    assert "Zusammenfassung des Plans" in ausgabe
    assert "Dateien pro Jahr" in ausgabe and "2026" in ausgabe
    assert "ILCE-7CM2" in ausgabe and "A7C2" in ausgabe
    assert "Zeitzone angenommen" in ausgabe
    assert "ExifTool-Prozesse" in ausgabe
    assert "Sicherungskopie" in ausgabe
    _, status = _laufen(capsys, "status", "--ziel", ziel)
    assert "Kopieren offen" in status or "3" in status


def test_cli_analyse_zweimal_ist_harmlos(capsys, quelle, ziel):
    _laufen(capsys, "scan", "--quelle", quelle, "--ziel", ziel)
    _laufen(capsys, "analyse", "--ziel", ziel)
    rueckgabe, ausgabe = _laufen(capsys, "analyse", "--ziel", ziel)
    assert rueckgabe == cli.OK
    assert "Nichts zu analysieren" in ausgabe


def test_cli_analyse_je_quelle(capsys, tmp_path, ziel):
    a = testbaum.erzeugen(tmp_path / "a")["quelle"]
    b = testbaum.erzeugen(tmp_path / "b")["quelle"]
    _laufen(capsys, "scan", "--quelle", a, "--quelle", b, "--ziel", ziel)
    _, ausgabe = _laufen(capsys, "analyse", "--ziel", ziel)
    assert "Dateien pro Jahr je Quelle" in ausgabe


def test_cli_analyse_ohne_exiftool_bricht_hart_ab(capsys, quelle, ziel, monkeypatch):
    _laufen(capsys, "scan", "--quelle", quelle, "--ziel", ziel)
    monkeypatch.setenv("FOTOSORT_EXIFTOOL", "/gibt/es/nicht")
    rueckgabe, ausgabe = _laufen(capsys, "analyse", "--ziel", ziel)
    assert rueckgabe == cli.FEHLER
    assert "ExifTool" in ausgabe
