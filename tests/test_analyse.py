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
    original = analyse._seite_abschliessen
    aufrufe = []

    def unterbrechen(*args, **kwargs):
        aufrufe.append(1)
        if len(aufrufe) == 2:
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr(analyse, "_seite_abschliessen", unterbrechen)
    e1 = _analyse(dbank, lauf, ziel, konf)
    assert e1.abgebrochen and 0 < e1.bearbeitet
    teil = dbank.zaehler_je_status()
    assert teil.get("gefunden", 0) > 0 and teil.get("analysiert", 0) > 0

    monkeypatch.setattr(analyse, "_seite_abschliessen", original)
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


# ------------------------------------------ Befunde der Abnahme (Phase 2) --


@testbaum.NUR_POSIX_NAMEN
def test_zeilenumbruch_im_dateinamen_wird_nie_an_exiftool_gegeben(vorbereitet, ziel, konf, quelle, baum):
    """Ein Name mit Zeilenumbruch koennte ExifTool Schreibbefehle unterschieben."""
    dbank, lauf, _ = vorbereitet
    boese = quelle / "2026" / "harmlos\n-Model=GEAENDERT\n-overwrite_original\nrest.jpg"
    boese.write_bytes(testbaum._JPEG)
    nachbarn = {p: p.read_bytes() for p in (quelle / "2026").iterdir() if p.is_file()}
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    e = _analyse(dbank, lauf, ziel, konf)
    assert {p: p.read_bytes() for p in nachbarn} == nachbarn  # nichts angefasst
    assert not list((quelle / "2026").glob("*_original"))
    z = _zeile(dbank, boese)
    assert z["status"] == "fehler" and "Zeilenumbruch" in z["fehlergrund"]
    assert dbank.zaehler_je_status().get("gefunden", 0) == 0
    assert e.fehler == 1


def test_emoji_im_dateinamen_wird_analysiert(vorbereitet, ziel, konf, quelle):
    dbank, lauf, _ = vorbereitet
    for name in ("😀.jpg", "𝕏.jpg", "b😀.jpg"):
        (quelle / "2026" / name).write_bytes(testbaum._JPEG)
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    _analyse(dbank, lauf, ziel, konf)
    assert dbank.zaehler_je_status().get("gefunden", 0) == 0
    for name in ("😀.jpg", "𝕏.jpg", "b😀.jpg"):
        assert _zeile(dbank, quelle / "2026" / name)["status"] == "analysiert"


@testbaum.NUR_POSIX_NAMEN
def test_nicht_utf8_dateiname_bekommt_sichtbaren_fehler(vorbereitet, ziel, konf, quelle):
    import os

    dbank, lauf, _ = vorbereitet
    roh = os.path.join(os.fsencode(quelle / "2026"), b"latin1_\xe9.jpg")
    with open(roh, "wb") as f:
        f.write(testbaum._JPEG)
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    e = _analyse(dbank, lauf, ziel, konf)
    assert dbank.zaehler_je_status().get("gefunden", 0) == 0
    fehler = dbank.verbindung.execute(
        "SELECT fehlergrund FROM dateien WHERE status = 'fehler'"
    ).fetchall()
    assert any("UTF-8" in z[0] for z in fehler) and e.fehler == 1


@pytest.mark.parametrize("seite", [5000, 2, 1])
def test_ordner_mit_unterordnern_liest_jede_datei_genau_einmal(ziel, archiv_basis, konf, tmp_path, monkeypatch, seite):
    """Auch mit kleinen Seiten: Ein Ordner, der ueber die Seitengrenze reicht,
    wird nur einmal gelesen (die naechste Seite laeuft schon, waehrend die
    vorige geschrieben wird)."""
    from fotosort import metadaten
    monkeypatch.setattr(analyse, "SEITE", seite)

    quelle = tmp_path / "q"
    (quelle / "o" / "b").mkdir(parents=True)
    (quelle / "o" / "m").mkdir()
    for rel in ("o/a.jpg", "o/b/x.jpg", "o/k.jpg", "o/m/y.jpg", "o/z.jpg"):
        (quelle / rel).write_bytes(testbaum._JPEG)
    gesehen: list[str] = []
    original = metadaten.ExifToolPool.einreichen

    def zaehlen(self, pfade_typ):
        gesehen.extend(p for p, _ in pfade_typ)
        return original(self, pfade_typ)

    monkeypatch.setattr(metadaten.ExifToolPool, "einreichen", zaehlen)
    dbank = db.Datenbank.oeffnen(archiv_basis / "u")
    try:
        lauf = dbank.lauf_beginnen("test")
        scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
        e = _analyse(dbank, lauf, ziel, konf)
    finally:
        dbank.schliessen()
    assert sorted(gesehen) == sorted(str(quelle / r) for r in ("o/a.jpg", "o/b/x.jpg", "o/k.jpg", "o/m/y.jpg", "o/z.jpg"))
    assert e.bearbeitet == 5 and e.gruppen == 5


def test_geaenderte_hauptdatei_zieht_die_gruppe_mit(vorbereitet, ziel, konf, quelle, baum):
    """SPEC §3: Mitglieder wandern gemeinsam - auch nach einer Korrektur des
    Datums. Seit v0.8 wird dabei jedes Mitglied selbst gelesen: Korrigiert der
    Nutzer RAW und JPG, gehen beide mit; korrigiert er nur eines, sind es nach
    der Aufnahmezeit zwei Aufnahmen (test_neu_begonnener_zaehler_wird_getrennt)."""
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    testbaum._exiftool([["-overwrite_original", "-EXIF:DateTimeOriginal=2025:07:07 07:07:07", str(baum[k])]
                        for k in ("raw", "jpg")])
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)  # beide fallen auf gefunden zurueck
    assert _zeile(dbank, baum["raw"])["status"] == "gefunden"
    _analyse(dbank, lauf, ziel, konf)
    for schluessel in ("raw", "jpg", "sidecar_form1", "sidecar_form2"):
        z = _zeile(dbank, baum[schluessel])
        assert z["aufnahme_zeit"] == "2025-07-07T07:07:07", schluessel
        assert "/2025-07-07/" in z["zielpfad"].replace("\\", "/"), schluessel


def test_sidecar_zu_hauptdatei_mit_fehler_wird_nicht_analysiert_ohne_ziel(vorbereitet, ziel, konf, quelle):
    dbank, lauf, _ = vorbereitet
    weg = quelle / "2026" / "weg.jpg"
    weg.write_bytes(b"x")
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    weg.unlink()
    _analyse(dbank, lauf, ziel, konf)
    assert _zeile(dbank, weg)["status"] == "fehler"
    sidecar = quelle / "2026" / "weg.xmp"
    sidecar.write_text("<x/>", encoding="utf-8")
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, sidecar)
    assert z["status"] == "fehler" and z["fehlergrund"].startswith("Hauptdatei")
    assert z["zielpfad"] == ""


def test_leere_datei_bekommt_fehler_mit_exiftool_grund(vorbereitet, ziel, konf, quelle):
    dbank, lauf, _ = vorbereitet
    leer = quelle / "2026" / "leer.jpg"
    leer.write_bytes(b"")
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    e = _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, leer)
    assert z["status"] == "fehler" and "Metadaten nicht lesbar" in z["fehlergrund"]
    assert "empty" in z["fehlergrund"].lower() or "leer" in z["fehlergrund"].lower()
    assert e.fehler == 1


def test_ungueltige_zeitzone_bricht_verstaendlich_ab(vorbereitet, ziel, konf):
    from fotosort import FotosortFehler

    dbank, lauf, _ = vorbereitet
    konf.alle()["datum"]["heimat_zeitzone"] = "Europa/Berlin"
    with pytest.raises(FotosortFehler) as fehler:
        _analyse(dbank, lauf, ziel, konf)
    assert "Europa/Berlin" in str(fehler.value)
    assert dbank.zaehler_je_status().get("analysiert", 0) == 0


def test_zusammenfassung_zaehlt_namenskonflikte(vorbereitet, ziel, konf):
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    z = dbank.analyse_zusammenfassung()
    assert z["namenskonflikte"] >= 1  # 2026/DSC01234.JPG und Namenskonflikt/DSC01234.JPG


def test_cli_analyse_mit_exiftool_pfad_nur_in_config(capsys, quelle, ziel, monkeypatch, archiv_basis):
    """SPEC §2: der Konfigurationswert exiftool_pfad muss fuer analyse wirken."""
    import shutil

    programm = shutil.which("exiftool")
    _laufen(capsys, "scan", "--quelle", quelle, "--ziel", ziel)
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    konf_pfad = archiv_basis / kennung / "config.toml"
    text = konf_pfad.read_text(encoding="utf-8")
    # TOML: Backslaeche (Windows-Pfade) muessen verdoppelt werden.
    text = text.replace('exiftool_pfad = ""', 'exiftool_pfad = "' + str(programm).replace("\\", "\\\\") + '"')
    konf_pfad.write_text(text, encoding="utf-8")
    monkeypatch.setenv("PATH", str(ziel))  # kein exiftool mehr ueber PATH
    monkeypatch.delenv("FOTOSORT_EXIFTOOL", raising=False)
    rueckgabe, ausgabe = _laufen(capsys, "analyse", "--ziel", ziel)
    assert rueckgabe == cli.OK, ausgabe


# ------------------------------------------ voruebergehende Fehler ----


def test_voruebergehender_exiftool_fehler_wird_beim_naechsten_lauf_erneut_versucht(vorbereitet, ziel, konf, baum):
    """Ein Absturz oder Zeitlimit von ExifTool liegt selten an der Datei. Frueher
    blieb die Gruppe fuer immer auf fehler; jetzt versucht die naechste Analyse
    sie erneut. Ein Fehler, der an der Datei selbst liegt, bleibt."""
    from fotosort import meldungen
    dbank, lauf, _ = vorbereitet
    _analyse(dbank, lauf, ziel, konf)
    richtig = {k: dict(_zeile(dbank, baum[k])) for k in ("raw", "jpg", "sidecar_form1")}
    grund = f"{analyse.GRUND_METADATEN}: {meldungen.EXIFTOOL_ABGESTUERZT}"
    analyse._fehler_setzen(dbank, baum["raw"], grund, "")
    for k in ("jpg", "sidecar_form1"):
        analyse._fehler_setzen(dbank, baum[k], f"{analyse.GRUND_HAUPTDATEI}: {grund}", baum["raw"])
    analyse._fehler_setzen(dbank, baum["analog"], f"{analyse.GRUND_METADATEN}: File format error", "")
    dbank.stapel_schreiben()

    e = _analyse(dbank, lauf, ziel, konf)
    assert e.erneut_versucht == 3
    for k, vorher in richtig.items():
        z = dict(_zeile(dbank, baum[k]))
        assert z["status"] == "analysiert" and z["fehlergrund"] == ""
        assert (z["zielpfad"], z["aufnahme_zeit"], z["kamera"]) == (vorher["zielpfad"], vorher["aufnahme_zeit"], vorher["kamera"])
    assert _zeile(dbank, baum["analog"])["status"] == "fehler"
    ereignisse = dbank.ereignisse_liste(analyse.ART_ERNEUT_VERSUCHT)
    assert len(ereignisse) == 3


def test_stapelfehler_nennt_den_grund(vorbereitet, ziel, konf, monkeypatch):
    """Scheitert ein ganzer Stapel (ExifTool stuerzt wiederholt ab), steht der
    Grund bei jeder Datei - nicht nur "Metadaten nicht lesbar"."""
    from fotosort import meldungen, metadaten
    dbank, lauf, _ = vorbereitet

    def scheitert(self, pfade_typ):
        raise metadaten.MetadatenFehler(meldungen.EXIFTOOL_STUERZT_WIEDERHOLT)

    echt = metadaten.ExifToolPool._lesen
    monkeypatch.setattr(metadaten.ExifToolPool, "_lesen", scheitert)
    _analyse(dbank, lauf, ziel, konf)
    zeilen = dbank.verbindung.execute("SELECT fehlergrund FROM dateien WHERE status = 'fehler'").fetchall()
    assert zeilen and all("stuerzt wiederholt ab" in z["fehlergrund"] for z in zeilen)
    # Sobald ExifTool wieder geht, holt die naechste Analyse alles nach.
    monkeypatch.setattr(metadaten.ExifToolPool, "_lesen", echt)
    e = _analyse(dbank, lauf, ziel, konf)
    assert e.erneut_versucht == len(zeilen)
    assert dbank.zaehler_je_status().get("fehler", 0) == 0


# ------------------------------------ Runde 2 (v0.8): Gruppen und Datum -----


def _anlegen(ordner: Path, dateien: dict) -> dict:
    """name -> (Inhalt, ExifTool-Argumente) im Ordner anlegen; liefert name -> Pfad."""
    wo, befehle = {}, []
    for name, (inhalt, argumente) in dateien.items():
        pfad = testbaum._schreiben(ordner / name, inhalt)
        wo[name] = pfad
        if argumente:
            befehle.append(["-overwrite_original", *argumente, str(pfad)])
    if befehle:
        testbaum._exiftool(befehle)
    return wo


def _ereignisse(dbank, art):
    return [dict(e) for e in dbank.ereignisse_liste(art)]


def test_neu_begonnener_zaehler_wird_getrennt(vorbereitet, ziel, konf, quelle):
    """Entscheidung 2: IMG_0001.JPG von 2016 und IMG_0001.MOV von 2021 haben nur
    den Namen gemeinsam - jede in ihr eigenes Jahr, das Sidecar zum Foto."""
    dbank, lauf, _ = vorbereitet
    wo = _anlegen(quelle / "Handy", {
        "IMG_0001.JPG": (testbaum._JPEG, ["-EXIF:DateTimeOriginal=2016:05:05 10:00:00"]),
        "IMG_0001.MOV": (testbaum._mp4(b"qt  "), ["-QuickTime:CreationDate=2021:06:06 10:00:00+02:00"]),
        "IMG_0001.AAE": (b"<plist/>", None),
    })
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    e = _analyse(dbank, lauf, ziel, konf)
    jpg, mov, aae = (_zeile(dbank, wo[n]) for n in ("IMG_0001.JPG", "IMG_0001.MOV", "IMG_0001.AAE"))
    assert "/2016-05-05/" in jpg["zielpfad"].replace("\\", "/")
    assert "/2021-06-06/" in mov["zielpfad"].replace("\\", "/")
    assert jpg["gruppe"] == jpg["quellpfad"] and mov["gruppe"] == mov["quellpfad"]
    assert aae["gruppe"] == jpg["quellpfad"] and Path(aae["zielpfad"]).parent == Path(jpg["zielpfad"]).parent
    getrennt = _ereignisse(dbank, analyse.ART_GRUPPE_GETRENNT)
    assert len(getrennt) == 1 and getrennt[0]["pfad"] == mov["quellpfad"] and "2016" in getrennt[0]["text"]
    assert e.getrennt == 1


def test_raw_ohne_datum_folgt_dem_jpg_mit_datum(vorbereitet, ziel, konf, quelle):
    """Entscheidung 3 (zweiter Fall): Die RAW hat kein Datum, das JPG schon -
    beide gehen in den Tagesordner, nicht nach _Ohne_Datum."""
    dbank, lauf, _ = vorbereitet
    wo = _anlegen(quelle / "Paar", {
        "DSC0100.ARW": (testbaum._tiff(), ["-EXIF:Model=ILCE-7C"]),
        "DSC0100.JPG": (testbaum._JPEG, ["-EXIF:DateTimeOriginal=2019:04:04 04:04:04", "-EXIF:Model=ILCE-7C"]),
    })
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    _analyse(dbank, lauf, ziel, konf)
    raw, jpg = _zeile(dbank, wo["DSC0100.ARW"]), _zeile(dbank, wo["DSC0100.JPG"])
    assert raw["gruppe"] == raw["quellpfad"] == jpg["gruppe"]            # RAW bleibt Hauptdatei
    assert raw["aufnahme_zeit"] == jpg["aufnahme_zeit"] == "2019-04-04T04:04:04"
    assert "/2019-04-04/" in raw["zielpfad"].replace("\\", "/") and raw["datum_sicher"] == 1


def test_kaputte_hauptdatei_reisst_das_jpg_nicht_mit(vorbereitet, ziel, konf, quelle):
    """Entscheidung 3: Eine leere ARW bekommt fehler - das JPG wird Hauptdatei,
    das Sidecar geht mit ihm."""
    dbank, lauf, _ = vorbereitet
    wo = _anlegen(quelle / "Kaputt", {
        "DSC0200.ARW": (b"", None),
        "DSC0200.JPG": (testbaum._JPEG, ["-EXIF:DateTimeOriginal=2020:02:02 02:02:02"]),
        "DSC0200.xmp": (b'<?xpacket?><x:xmpmeta xmlns:x="adobe:ns:meta/"/>\n', None),
    })
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    _analyse(dbank, lauf, ziel, konf)
    raw, jpg, xmp = (_zeile(dbank, wo[n]) for n in ("DSC0200.ARW", "DSC0200.JPG", "DSC0200.xmp"))
    assert raw["status"] == "fehler" and "Metadaten nicht lesbar" in raw["fehlergrund"]
    assert jpg["status"] == "analysiert" and jpg["gruppe"] == jpg["quellpfad"]
    assert "/2020-02-02/" in jpg["zielpfad"].replace("\\", "/")
    assert xmp["status"] == "analysiert" and xmp["gruppe"] == jpg["quellpfad"]


_XMP_DATUM = (
    b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description rdf:about="" xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
    b' photoshop:DateCreated="2018-08-08T08:08:08"/></rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>\n'
)


def test_datum_aus_dem_xmp_sidecar(vorbereitet, ziel, konf, quelle):
    """Entscheidung 5: Ein Scan ohne Datum, dessen Datum nur Lightroom kennt."""
    dbank, lauf, _ = vorbereitet
    wo = _anlegen(quelle / "Scans", {"scan_0001.tif": (testbaum._tiff(), None), "scan_0001.xmp": (_XMP_DATUM, None)})
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, wo["scan_0001.tif"])
    assert z["aufnahme_zeit"] == "2018-08-08T08:08:08" and z["datum_quelle"] == 4 and z["datum_sicher"] == 1


def test_datecreated_in_der_datei(vorbereitet, ziel, konf, quelle):
    dbank, lauf, _ = vorbereitet
    wo = _anlegen(quelle / "Scans", {"scan_0002.tif": (testbaum._tiff(), ["-XMP-photoshop:DateCreated=2017:07:07 07:07:07"])})
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, wo["scan_0002.tif"])
    assert z["aufnahme_zeit"] == "2017-07-07T07:07:07" and z["datum_quelle"] == 4


def test_datum_auffaellig_und_nur_hersteller_werden_vermerkt(vorbereitet, ziel, konf, quelle):
    """Entscheidungen 9 und 7: nur Hinweise - einsortiert wird wie immer."""
    dbank, lauf, _ = vorbereitet
    wo = _anlegen(quelle / "Uhr", {
        "IMG_20230405_101010.jpg": (testbaum._JPEG, ["-EXIF:DateTimeOriginal=2000:01:01 00:01:00", "-EXIF:Make=Canon"]),
    })
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    e = _analyse(dbank, lauf, ziel, konf)
    z = _zeile(dbank, wo["IMG_20230405_101010.jpg"])
    assert "/2000-01-01/" in z["zielpfad"].replace("\\", "/") and z["kamera"] == konf.wert("kamera.unbekannt")
    auff = _ereignisse(dbank, analyse.ART_DATUM_AUFFAELLIG)
    assert [a["pfad"] for a in auff] == [z["quellpfad"]] and "Dateinamen" in auff[0]["text"]
    hersteller = _ereignisse(dbank, analyse.ART_NUR_HERSTELLER)
    assert [(h["pfad"], h["text"]) for h in hersteller] == [(z["quellpfad"], "Canon")]
    assert e.auffaellig == 1 and e.nur_hersteller == 1


def test_spaeter_hinzugekommenes_mitglied(vorbereitet, ziel, konf, quelle):
    """Das JPG ist schon kopiert; spaeter taucht ein MOV mit demselben Namen
    auf. Passt die Zeit, gehoert es dazu (Ordner und Gruppe des JPG), sonst
    ist es eine eigene Aufnahme."""
    dbank, lauf, _ = vorbereitet
    wo = _anlegen(quelle / "Spaeter", {
        "IMG_0500.JPG": (testbaum._JPEG, ["-EXIF:DateTimeOriginal=2016:05:05 10:00:00"]),
        "IMG_0600.JPG": (testbaum._JPEG, ["-EXIF:DateTimeOriginal=2016:06:06 10:00:00"]),
    })
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    _analyse(dbank, lauf, ziel, konf)
    for n in ("IMG_0500.JPG", "IMG_0600.JPG"):
        dbank.verbindung.execute("UPDATE dateien SET status = 'kopiert' WHERE quellpfad = ?", (db.pfad_text(wo[n]),))
    dbank.verbindung.commit()
    wo.update(_anlegen(quelle / "Spaeter", {
        "IMG_0500.MOV": (testbaum._mp4(b"qt  "), ["-QuickTime:CreationDate=2016:05:05 10:00:02+02:00"]),
        "IMG_0600.MOV": (testbaum._mp4(b"qt  "), ["-QuickTime:CreationDate=2022:02:02 10:00:00+01:00"]),
    }))
    scan.ausfuehren(quelle, ziel, konf, dbank, lauf)
    _analyse(dbank, lauf, ziel, konf)
    jpg5, mov5 = _zeile(dbank, wo["IMG_0500.JPG"]), _zeile(dbank, wo["IMG_0500.MOV"])
    assert mov5["gruppe"] == jpg5["quellpfad"] and Path(mov5["zielpfad"]).parent == Path(jpg5["zielpfad"]).parent
    assert jpg5["status"] == "kopiert"                                  # bleibt, wo es ist
    jpg6, mov6 = _zeile(dbank, wo["IMG_0600.JPG"]), _zeile(dbank, wo["IMG_0600.MOV"])
    assert mov6["gruppe"] == mov6["quellpfad"] and "/2022-02-02/" in mov6["zielpfad"].replace("\\", "/")
