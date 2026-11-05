"""v0.14: Befunde aus der Pruefung "alle Funktionen auf Richtigkeit" (Fehler 2-9).

Jeder Test zeigt zuerst den Fehler; danach wurde er behoben.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import testbaum
from fotosort import cli, db
from test_aufraeumen import antwort  # noqa: F401  (Vorrichtung)
from test_bestand import _archiv_von_hand
from test_kopieren import _cli, _zeilen


def _konf_pfad(archiv_basis: Path, ziel: Path) -> Path:
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    return archiv_basis / kennung / "config.toml"


def _eine(nachschauen, ziel: Path, name: str) -> dict:
    treffer = [z for p, z in _zeilen(nachschauen, ziel).items() if Path(db.text_pfad(p)).name == name]
    assert len(treffer) == 1, (name, treffer)
    return treffer[0]


# ------------------------------------- Fehler 2: neue Dateiendung ----


def test_neue_endung_in_den_einstellungen_wirkt_auf_schon_erfasste_dateien(tmp_path, ziel, archiv_basis, nachschauen):
    """Der Bericht raet, fehlende Endungen unter [dateitypen] zu ergaenzen.
    Schon erfasste, unveraenderte Dateien blieben danach aber "uebersprungen
    nach Typ" - der naechste Scan sah sie als unveraendert an."""
    quelle = tmp_path / "Quelle"
    quelle.mkdir()
    (quelle / "urlaub.jpx").write_bytes(testbaum._JPEG + b"jpx")
    assert _cli("scan", "--quelle", quelle, "--ziel", ziel) == cli.OK
    zeile = _eine(nachschauen, ziel, "urlaub.jpx")
    assert (zeile["status"], zeile["dateityp"]) == ("uebersprungen", "sonstiges")

    # Ohne geaenderte Einstellung bleibt es dabei.
    assert _cli("scan", "--ziel", ziel) == cli.OK
    assert _eine(nachschauen, ziel, "urlaub.jpx")["status"] == "uebersprungen"

    konf = _konf_pfad(archiv_basis, ziel)
    text = konf.read_text(encoding="utf-8")
    assert text.count('"insp"]') == 1
    konf.write_text(text.replace('"insp"]', '"insp", "jpx"]'), encoding="utf-8")
    assert _cli("scan", "--ziel", ziel) == cli.OK
    zeile = _eine(nachschauen, ziel, "urlaub.jpx")
    assert (zeile["status"], zeile["dateityp"], zeile["fehlergrund"]) == ("gefunden", "foto", "")
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeile = _eine(nachschauen, ziel, "urlaub.jpx")
    assert zeile["status"] == "kopiert" and Path(db.text_pfad(zeile["zielpfad"])).is_file()


def test_neue_endung_aendert_nichts_an_aus_anderem_grund_uebersprungenen(tmp_path, ziel, nachschauen):
    """Nur "uebersprungen nach Typ" wird neu eingeordnet - eine Datei mit
    bekanntem Typ, die aus anderem Grund uebersprungen ist, bleibt."""
    quelle = tmp_path / "Quelle"
    quelle.mkdir()
    (quelle / "bild.jpg").write_bytes(testbaum._JPEG)
    assert _cli("scan", "--quelle", quelle, "--ziel", ziel) == cli.OK
    with nachschauen(ziel) as d:
        d.verbindung.execute("UPDATE dateien SET status = 'uebersprungen', fehlergrund = 'anderer Grund'")
        d.verbindung.commit()
    assert _cli("scan", "--ziel", ziel) == cli.OK
    zeile = _eine(nachschauen, ziel, "bild.jpg")
    assert (zeile["status"], zeile["fehlergrund"]) == ("uebersprungen", "anderer Grund")


# --------------------- Fehler 3: spaete Begleitdatei, schon importiert ----


@pytest.mark.parametrize("verschieben", [False, True])
def test_spaete_begleitdatei_eines_bereits_importierten_bildes_bleibt(baum, quelle, ziel, nachschauen, antwort,  # noqa: F811
                                                                      verschieben, tmp_path):
    """Ein Bild lag schon im Archiv ("bereits importiert" - bleibt in der Quelle).
    Kommt seine XMP-Datei erst spaeter dazu (Lightroom schreibt sie nach),
    wurde sie kopiert, geprueft und dann aus der Quelle geraeumt - beim
    Verschieben sogar sofort. Sie gehoert aber zum Bild und bleibt mit ihm."""
    xmp = Path(baum["sidecar_form1"])
    jpg = next(p for p in xmp.parent.iterdir() if p.suffix.lower() == ".jpg" and p.stem == xmp.stem)
    beiseite = tmp_path / "beiseite.xmp"
    xmp.rename(beiseite)                         # erster Durchgang ohne XMP
    _archiv_von_hand(ziel, jpg)
    args = ("--verschieben",) if verschieben else ()
    for _ in range(2):
        assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
        assert _cli("analyse", "--ziel", ziel) == cli.OK
        assert _cli("kopieren", "--ziel", ziel, *args) == cli.OK
        assert _cli("pruefen", "--ziel", ziel) == cli.OK
        assert _zeilen(nachschauen, ziel)[str(jpg)]["schon_im_archiv"] == 1
        if beiseite.exists():
            beiseite.rename(xmp)                 # die XMP kommt nach
    zeilen = _zeilen(nachschauen, ziel)
    assert zeilen[str(xmp)]["schon_im_archiv"] == 1, zeilen[str(xmp)]["status"]
    assert xmp.exists()
    if not verschieben:
        antwort.append("loeschen")
        assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    assert jpg.exists() and xmp.exists()


# ------------------------- Fehler 4: Begleitdatei ohne Hauptdatei ----


def test_begleitdatei_ohne_hauptdatei_wird_zugeordnet_wenn_die_hauptdatei_kommt(tmp_path, ziel, nachschauen):
    """Fehlt beim ersten Durchgang die Hauptdatei (Scan abgebrochen, zweite
    Karte), wird die XMP "uebersprungen: Sidecar ohne Hauptdatei". Kam die
    Hauptdatei spaeter, blieb die XMP trotzdem fuer immer uebersprungen - sie
    gehoert aber ins Archiv neben ihr Bild."""
    from fotosort import meldungen
    ordner = tmp_path / "Quelle" / "Karte"
    ordner.mkdir(parents=True)
    xmp = ordner / "DSC00042.xmp"
    xmp.write_text('<?xpacket?><x:xmpmeta xmlns:x="adobe:ns:meta/"/>\n', encoding="utf-8")
    assert _cli("scan", "--quelle", ordner.parent, "--ziel", ziel) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    zeile = _eine(nachschauen, ziel, "DSC00042.xmp")
    assert (zeile["status"], zeile["fehlergrund"]) == ("uebersprungen", meldungen.GRUND_SIDECAR_OHNE_HAUPT)

    (ordner / "DSC00042.JPG").write_bytes(testbaum._JPEG + b"42")
    assert _cli("scan", "--ziel", ziel) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    bild, zeile = _eine(nachschauen, ziel, "DSC00042.JPG"), _eine(nachschauen, ziel, "DSC00042.xmp")
    assert zeile["status"] == "analysiert" and zeile["gruppe"] == bild["quellpfad"], dict(zeile)
    assert Path(db.text_pfad(zeile["zielpfad"])).parent == Path(db.text_pfad(bild["zielpfad"])).parent
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _eine(nachschauen, ziel, "DSC00042.xmp")["status"] == "kopiert"


def test_begleitdatei_bleibt_ohne_hauptdatei_uebersprungen(tmp_path, ziel, nachschauen):
    """Gegenstueck: Ohne Hauptdatei bleibt es beim Uebersprungen, auch nach
    weiteren Laeufen - nichts wird ohne Bild ins Archiv gelegt."""
    from fotosort import meldungen
    ordner = tmp_path / "Quelle"
    ordner.mkdir()
    (ordner / "allein.xmp").write_text('<?xpacket?><x:xmpmeta xmlns:x="adobe:ns:meta/"/>\n', encoding="utf-8")
    assert _cli("scan", "--quelle", ordner, "--ziel", ziel) == cli.OK
    for _ in range(2):
        assert _cli("analyse", "--ziel", ziel) == cli.OK
        assert _cli("kopieren", "--ziel", ziel) == cli.OK
        zeile = _eine(nachschauen, ziel, "allein.xmp")
        assert (zeile["status"], zeile["fehlergrund"]) == ("uebersprungen", meldungen.GRUND_SIDECAR_OHNE_HAUPT)


# ------------------ Fehler 5: Verschieben, Groesse wich danach ab ----


def _verschoben_mit_groessenfehler(quelle, ziel, nachschauen) -> tuple[str, Path]:
    """Wie im Programm nach dem Umbenennen, wenn die Groesse nicht passte
    (Datei zwischen Scan und Verschieben veraendert): Status fehler mit
    GRUND_VERSCHIEBEN_GROESSE, Datei liegt im Archiv, Quelle ist weg."""
    from fotosort import meldungen
    from test_kopieren import _vorbereiten
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    verschoben = [(p, z) for p, z in _zeilen(nachschauen, ziel).items() if z["status"] == "verschoben"]
    p, z = verschoben[0]
    with nachschauen(ziel) as d:
        d.verbindung.execute("UPDATE dateien SET status = 'fehler', fehlergrund = ?, groesse = groesse + 7"
                             " WHERE quellpfad = ?", (meldungen.GRUND_VERSCHIEBEN_GROESSE, p))
        d.verbindung.commit()
    return p, Path(db.text_pfad(z["zielpfad"]))


def test_verschoben_mit_abweichender_groesse_wird_geprueft(baum, quelle, ziel, nachschauen):
    """Die Datei liegt im Archiv, die Quelle ist weg - aber der Status hiess
    "fehler", und danach sah sie niemand mehr an. Jetzt liest "Pruefen" sie
    wie jede verschobene Datei, traegt Groesse und Inhalt nach und meldet sie
    als im Archiv."""
    from fotosort import hashes
    p, archivdatei = _verschoben_mit_groessenfehler(quelle, ziel, nachschauen)
    assert archivdatei.is_file() and not Path(db.text_pfad(p)).exists()
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    z = _zeilen(nachschauen, ziel)[p]
    assert (z["status"], z["fehlergrund"]) == ("verschoben", "")
    assert z["hash"] == hashes.blake3_datei(archivdatei) and z["groesse"] == archivdatei.stat().st_size


def test_verschoben_mit_abweichender_groesse_und_fehlender_archivdatei_bleibt_fehler(baum, quelle, ziel, nachschauen):
    """Gegenstueck: Fehlt die Datei im Archiv, bleibt es ein Fehler - mit einem
    Grund, der sagt, wo nachzusehen ist."""
    p, archivdatei = _verschoben_mit_groessenfehler(quelle, ziel, nachschauen)
    archivdatei.rename(archivdatei.with_name("weg_" + archivdatei.name))
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER        # ein Befund: Rueckgabe 1
    z = _zeilen(nachschauen, ziel)[p]
    assert z["status"] == "fehler" and str(archivdatei) in z["fehlergrund"], z["fehlergrund"]
    # Taucht die Datei wieder auf, nimmt der naechste Lauf sie auf.
    archivdatei.with_name("weg_" + archivdatei.name).rename(archivdatei)
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert _zeilen(nachschauen, ziel)[p]["status"] == "verschoben"


# ------------------ Fehler 6: Uebersicht nach dem Aufraeumen ----


def test_uebersicht_aufraeumen_zahlen_ueber_denselben_zeitraum(tmp_path, ziel, nachschauen, antwort):  # noqa: F811
    """"aus der Quelle entfernt (gesamt)" zaehlte alle Durchgaenge, die Zeile
    darunter ("davon im Ordner _geloescht_") nur den letzten: Nach einem
    zweiten Aufraeumen las sich "12, davon 2 im Ordner _geloescht_" - dabei
    lagen alle 12 dort. Jetzt steht "davon" unter der Zahl desselben
    Durchgangs, und die Gesamtzahl sagt, dass sie alle Durchgaenge meint."""
    from fotosort import meldungen
    from fotosort.oberflaeche import ablauf as ablauf_modul
    quelle = tmp_path / "Quelle"
    quelle.mkdir()
    for i in range(3):
        (quelle / f"erst_{i}.jpg").write_bytes(testbaum._JPEG + bytes([i]))

    def runde() -> None:
        assert _cli("scan", "--quelle", quelle, "--ziel", ziel) == cli.OK
        assert _cli("analyse", "--ziel", ziel) == cli.OK
        assert _cli("kopieren", "--ziel", ziel) == cli.OK
        assert _cli("pruefen", "--ziel", ziel) == cli.OK
        antwort.append("verschieben")
        assert _cli("aufraeumen", "--ziel", ziel) == cli.OK

    runde()
    (quelle / "dazu.jpg").write_bytes(testbaum._JPEG + b"dazu")
    runde()
    zf = ablauf_modul.Ablauf(ziel=str(ziel), ordner=tmp_path / "ob").zusammenfassung("aufraeumen")
    namen = [z[0] for z in zf["zeilen"]]
    werte = dict((z[0], z[1]) for z in zf["zeilen"])
    durchgang = namen.index("entfernt in diesem Durchgang")
    assert werte["entfernt in diesem Durchgang"] == "1"
    assert namen[durchgang + 1] == meldungen.OB_ZEILE_IM_GELOESCHT_ORDNER and werte[namen[durchgang + 1]] == "1"
    assert "alle" in meldungen.OB_ZEILE_QUELLE_ENTFERNT and werte[meldungen.OB_ZEILE_QUELLE_ENTFERNT] == "4"


# --------------- Fehler 8: Schreibschutz nie am Ziel einer Verknuepfung ----


def test_schreibschutz_entfernen_folgt_keiner_verknuepfung(monkeypatch, tmp_path):
    """Seit Python 3.13 folgt os.chmod unter Windows Verknuepfungen. Das
    Aufheben des Schreibschutzes vor einer Loeschung haette dann die Datei
    veraendert, auf die eine Verknuepfung zeigt (womoeglich im Archiv). Jetzt
    nur die Datei selbst, wo das System es kann."""
    import os
    from fotosort import pfade
    aufrufe = []

    def chmod(pfad, modus, *, follow_symlinks=True):
        aufrufe.append(follow_symlinks)

    monkeypatch.setattr(os, "chmod", chmod)
    monkeypatch.setattr(os, "supports_follow_symlinks", set(os.supports_follow_symlinks) | {chmod})
    pfade._schreibschutz_setzen(tmp_path / "x", False)
    pfade._schreibschutz_setzen(tmp_path / "x", True)
    assert aufrufe == [False, False]


@pytest.mark.skipif(not __import__("sys").platform.startswith("win"), reason="Attribut gibt es nur unter Windows")
def test_schreibschutz_der_verknuepften_datei_bleibt_unter_windows(tmp_path):
    import os
    import stat
    from fotosort import pfade
    ziel = tmp_path / "ziel.jpg"
    ziel.write_bytes(b"x")
    os.chmod(ziel, stat.S_IREAD)
    verknuepfung = tmp_path / "verknuepfung.jpg"
    try:
        verknuepfung.symlink_to(ziel)
    except OSError:
        pytest.skip("Verknuepfungen anlegen ist hier nicht erlaubt")
    try:
        pfade._schreibschutz_setzen(verknuepfung, False)
        assert pfade._schreibgeschuetzt(ziel)
    finally:
        os.chmod(ziel, stat.S_IREAD | stat.S_IWRITE)


# -------------------- Fehler 9: Text zu "Alles automatisch" ----


def test_text_alles_automatisch_verspricht_nichts_falsches_zu_kameranamen():
    """Der Text versprach, Kameranamen liessen sich "am Ende aendern". Schon
    Kopiertes bleibt aber, wo es ist; eigene Ordnernamen fuer Kameras wirken
    nur auf noch nicht Kopiertes. Wer sie festlegen will, nimmt "Schritt fuer
    Schritt" - das sagt der Text jetzt."""
    from fotosort import meldungen
    text = meldungen.OB_ABLAUF_TEXT_AUTOMATISCH
    assert "am Ende ändern" not in text
    assert meldungen.OB_ABLAUF_EINZELN in text and "Kamera" in text


# ================================ Befunde des unabhaengigen Testers (v0.14) ====


def _bis_geprueft(quelle, ziel) -> None:
    from test_kopieren import _vorbereiten
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK


def _einzelne_geprueft(nachschauen, ziel) -> tuple[str, Path]:
    """Eine gepruefte Datei, auf deren Archivkopie kein Duplikat zeigt."""
    zeilen = _zeilen(nachschauen, ziel)
    belegt: dict[str, int] = {}
    for z in zeilen.values():
        if z["zielpfad"]:
            belegt[z["zielpfad"]] = belegt.get(z["zielpfad"], 0) + 1
    for p, z in sorted(zeilen.items()):
        if z["status"] == "geprueft" and z["dateityp"] == "foto" and belegt[z["zielpfad"]] == 1:
            return p, Path(db.text_pfad(z["zielpfad"]))
    raise AssertionError("keine passende Datei im Testbaum")


def _beschaedigen(datei: Path) -> None:
    """Ein Byte kippen, Groesse und Aenderungszeit bleiben - wie ein stiller Plattenfehler."""
    import os
    st = datei.stat()
    roh = bytearray(datei.read_bytes())
    roh[len(roh) // 2] ^= 0xFF
    datei.write_bytes(bytes(roh))
    os.utime(datei, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_f2_beschaedigte_archivkopie_wird_neu_kopiert(baum, quelle, ziel, nachschauen, antwort):  # noqa: F811
    """F2: Verweigerte das Aufraeumen die Loeschung, weil die Kopie im Archiv
    beschaedigt war, blieb die Datei fuer immer "fehler" - und im Archiv lag
    nur die kaputte Kopie. Jetzt bringt das naechste Kopieren eine frische
    Kopie (die kaputte bleibt liegen, nichts wird ueberschrieben); danach
    laesst sich die Quelle aufraeumen."""
    from fotosort import hashes, meldungen
    _bis_geprueft(quelle, ziel)
    p, archivdatei = _einzelne_geprueft(nachschauen, ziel)
    _beschaedigen(archivdatei)
    kaputt = archivdatei.read_bytes()
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    z = _zeilen(nachschauen, ziel)[p]
    assert (z["status"], z["fehlergrund"]) == ("fehler", meldungen.GRUND_ZIEL_ABWEICHUNG)
    assert Path(db.text_pfad(p)).exists()                       # Quelle unangetastet
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    z = _zeilen(nachschauen, ziel)[p]
    neu = Path(db.text_pfad(z["zielpfad"]))
    assert z["status"] == "kopiert" and neu != archivdatei and neu.is_file()
    assert archivdatei.read_bytes() == kaputt                    # nichts ueberschrieben
    assert hashes.blake3_datei(neu) == hashes.blake3_datei(Path(db.text_pfad(p)))
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    assert _zeilen(nachschauen, ziel)[p]["status"] == "quelle_geloescht" and not Path(db.text_pfad(p)).exists()


def test_f2_aufraeumen_haelt_an_wenn_das_archiv_wegfaellt(baum, quelle, ziel, nachschauen, antwort, monkeypatch,  # noqa: F811
                                                         tmp_path):
    """F2/F1: Faellt mitten im Aufraeumen das ganze Archiv weg (Platte
    abgezogen), bekam bisher jede weitere Datei "fehler: Zieldatei nicht mehr
    vorhanden" - fuer immer. Jetzt haelt das Aufraeumen an und aendert nichts."""
    from fotosort import loeschen
    _bis_geprueft(quelle, ziel)
    vorher = {p: z["status"] for p, z in _zeilen(nachschauen, ziel).items()}
    weg = tmp_path / "abgezogen"
    echt = loeschen.frisch_lesen
    schon = []

    def frisch_lesen(*a, **k):
        if not schon:
            schon.append(1)
            ziel.rename(weg)                    # die Platte ist weg
        return echt(*a, **k)

    monkeypatch.setattr(loeschen, "frisch_lesen", frisch_lesen)
    antwort.append("verschieben")
    ergebnis = _cli("aufraeumen", "--ziel", ziel)
    weg.rename(ziel)
    assert ergebnis in (cli.FEHLER, cli.ABGEBROCHEN)
    nachher = {p: z["status"] for p, z in _zeilen(nachschauen, ziel).items()}
    assert "fehler" not in nachher.values() or list(nachher.values()).count("fehler") == list(vorher.values()).count("fehler")
    assert all(nachher[p] == s for p, s in vorher.items() if s in ("geprueft", "duplikat_bestaetigt"))


def test_f3_automatik_meldet_verweigerte_loeschungen():
    """F3: Verweigerte das Aufraeumen Loeschungen, meldete der automatische
    Ablauf trotzdem "Alles erledigt"."""
    from fotosort import meldungen, steuerung
    from fotosort.oberflaeche import ablauf as ablauf_modul
    stand = {"analyse": 0, "kopieren": (0, 0), "pruefen": (0, 0), "aufraeumen": (0, 0)}
    assert ablauf_modul.kette_naechster("aufraeumen", steuerung.ZUSTAND_FEHLER, "", stand, False) == (
        "ende", "aufraeumen_befunde")
    assert ablauf_modul.kette_naechster("aufraeumen", steuerung.ZUSTAND_FERTIG, "", stand, False) == ("ende", "fertig")
    text = meldungen.ob_kette_ende("aufraeumen_befunde", 3.0)
    assert "Alles erledigt" not in text and "Fehler" in text and "Quelle" in text


def test_f3_uebersicht_zaehlt_entfernte_nicht_bearbeitete(baum, quelle, ziel, nachschauen, antwort, tmp_path):  # noqa: F811
    """F3: "entfernt in diesem Durchgang" zaehlte die bearbeiteten Dateien,
    auch die verweigerten."""
    from fotosort.oberflaeche import ablauf as ablauf_modul
    _bis_geprueft(quelle, ziel)
    _p, archivdatei = _einzelne_geprueft(nachschauen, ziel)
    _beschaedigen(archivdatei)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.FEHLER
    zeilen = _zeilen(nachschauen, ziel)
    entfernt = sum(1 for z in zeilen.values() if z["status"] == "quelle_geloescht")
    zf = ablauf_modul.Ablauf(ziel=str(ziel), ordner=tmp_path / "ob").zusammenfassung("aufraeumen")
    werte = dict((z[0], z[1]) for z in zf["zeilen"])
    assert werte["entfernt in diesem Durchgang"] == str(entfernt) and werte["Löschung verweigert"] == "1"


def test_f4_testbilder_unter_einer_quelle_kommen_nie_ins_archiv(tmp_path, ziel, nachschauen, capsys):
    """F4: Der Schutz "Testbilder nie in ein echtes Archiv" griff nur, wenn die
    Quelle selbst im Testordner lag. Liegt der Testordner UNTER einer Quelle
    (Desktop, D:\\ - genau dort schlaegt die Anleitung vor, ihn anzulegen),
    kamen Testbilder samt vorbelegtem Ziel ins echte Archiv. Jetzt wird ein
    Testordner unterhalb einer Quelle uebersprungen und gemeldet."""
    from fotosort import testbilder
    desktop = tmp_path / "Desktop"
    test = desktop / "fotosort Testbilder"
    (test / "Quelle").mkdir(parents=True)
    (test / testbilder.MARKE).write_text("{}", encoding="utf-8")
    (test / "Quelle" / "testbild.jpg").write_bytes(testbaum._JPEG + b"t")
    (test / "Ziel" / "2019").mkdir(parents=True)
    (test / "Ziel" / "2019" / "vorbelegt.jpg").write_bytes(testbaum._JPEG + b"z")
    (desktop / "echt.jpg").write_bytes(testbaum._JPEG + b"e")
    capsys.readouterr()
    assert _cli("scan", "--quelle", desktop, "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert {Path(db.text_pfad(p)).name for p in _zeilen(nachschauen, ziel)} == {"echt.jpg"}
    assert "Testbilder" in aus and str(test) in aus, aus


def test_f16_ordner_geloescht_zaehlt_nicht_als_muster_ausschluss(tmp_path, ziel, capsys):
    """F16: Der Ordner _geloescht_ erschien als "nach Muster ausgeschlossen: 1",
    obwohl kein Muster eingestellt war."""
    quelle = tmp_path / "Quelle"
    (quelle / "_geloescht_2026-11-05").mkdir(parents=True)
    (quelle / "_geloescht_2026-11-05" / "alt.jpg").write_bytes(testbaum._JPEG)
    (quelle / "neu.jpg").write_bytes(testbaum._JPEG + b"n")
    capsys.readouterr()
    assert _cli("scan", "--quelle", quelle, "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "nach Muster ausgeschlossen:   0" in aus, aus


# ----------------------- F5: Dateinamen mit 251 bis 255 Zeichen ----


def test_f5_part_name_bleibt_unter_der_grenze():
    """F5: Die Zwischendatei hiess "<voller Name>.part" - bei 251-255 Zeichen
    zu lang fuer jedes Dateisystem. Jetzt wird nur ihr Name gekuerzt, immer
    gleich (der naechste Start findet sie wieder) und eindeutig."""
    from fotosort import kopieren
    kurz = Path("/a/IMG_0001.JPG")
    assert kopieren.part_pfad(kurz) == Path("/a/IMG_0001.JPG.part")
    for laenge in (251, 252, 255):
        name = "b" * (laenge - 4) + ".jpg"
        p = kopieren.part_pfad(Path("/a") / name)
        assert p.parent == Path("/a") and p.name.endswith(".part")
        assert kopieren._name_laenge(p.name) <= 255 and p == kopieren.part_pfad(Path("/a") / name)
    a = kopieren.part_pfad(Path("/a") / ("c" * 250 + "1.jpg"))
    b = kopieren.part_pfad(Path("/a") / ("c" * 250 + "2.jpg"))
    assert a != b
    umlaut = "ä" * 125 + ".jpg"                     # 254 Byte in UTF-8
    assert kopieren._name_laenge(kopieren.part_pfad(Path("/a") / umlaut).name) <= 255


def test_f5_lange_dateinamen_kommen_ins_archiv(tmp_path, ziel, nachschauen):
    from fotosort import hashes
    quelle = tmp_path / "Quelle"
    quelle.mkdir()
    namen = ["b" * 248 + ".jpg", "c" * 251 + ".jpg"]          # 252 und 255 Zeichen
    for i, n in enumerate(namen):
        (quelle / n).write_bytes(testbaum._JPEG + bytes([i]) * 10)
    from test_kopieren import _vorbereiten
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    for n in namen:
        z = _eine(nachschauen, ziel, n)
        assert z["status"] == "geprueft", (n, z["fehlergrund"])
        assert Path(db.text_pfad(z["zielpfad"])).name == n
        assert hashes.blake3_datei(Path(db.text_pfad(z["zielpfad"]))) == hashes.blake3_datei(quelle / n)
    assert not list(ziel.rglob("*.part"))


# ------------------- F6: Duplikate nach dem Aufraeumen im Bericht ----


def test_f6_duplikate_bleiben_nach_dem_aufraeumen_duplikate(baum, quelle, ziel, nachschauen, antwort, tmp_path):  # noqa: F811
    """F6: Nach dem Aufraeumen stehen Originale und Duplikate auf
    quelle_geloescht. Der Bericht zaehlte danach alle als "kopiert" und
    "Duplikate 0", die Liste "Duplikate" war leer."""
    from fotosort.oberflaeche import ablauf as ablauf_modul
    _bis_geprueft(quelle, ziel)
    vorher = _zeilen(nachschauen, ziel)
    doppelt = {p for p, z in vorher.items() if z["status"] == "duplikat_bestaetigt"}
    kopiert = {p for p, z in vorher.items() if z["status"] == "geprueft"}
    assert doppelt and kopiert
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    nachher = _zeilen(nachschauen, ziel)
    assert all(nachher[p]["status"] == "quelle_geloescht" for p in doppelt | kopiert)
    with nachschauen(ziel) as d:
        zahlen = d.bericht_zahlen()["gesamt"]
    assert zahlen["duplikate"] == len(doppelt) and zahlen["kopiert"] == len(kopiert), zahlen
    assert zahlen["geprueft"] == len(kopiert) and zahlen["geloescht"] == len(doppelt | kopiert)
    ab = ablauf_modul.Ablauf(ziel=str(ziel), ordner=tmp_path / "ob")
    assert ab.liste("duplikate", 1)["gesamt"] == len(doppelt)
    assert ab.zusammenfassung("aufraeumen")["duplikate"] == len(doppelt)


def test_f6_anhebung_traegt_fruehere_duplikate_nach(tmp_path):
    """Datenbanken bis v0.13 (Schema 8): Aufgeraeumte Duplikate erkennt die
    Anhebung am Ereignis "duplikat", das beim Kopieren je Datei geschrieben wurde."""
    ordner = tmp_path / "v013"
    d = db.Datenbank.oeffnen(ordner)
    lauf = d.lauf_beginnen("kopieren")
    for name in ("original.jpg", "doppelt.jpg", "offen.jpg"):
        d.datei_gesehen(f"/q/{name}", "/q", 100, 1000.0, "foto", lauf)
    d.stapel_schreiben()
    d.verbindung.execute("UPDATE dateien SET status = 'quelle_geloescht', zielpfad = '/z/a.jpg'"
                         " WHERE quellpfad IN ('/q/original.jpg', '/q/doppelt.jpg')")
    d.verbindung.execute("UPDATE dateien SET status = 'duplikat', zielpfad = '/z/a.jpg' WHERE quellpfad = '/q/offen.jpg'")
    d.ereignis(lauf, "duplikat", "/q/doppelt.jpg", 1, "/z/a.jpg")
    d.stapel_schreiben()
    d.verbindung.execute("ALTER TABLE dateien DROP COLUMN war_duplikat")
    d.verbindung.execute("PRAGMA user_version=8")
    d.schliessen()
    d = db.Datenbank.oeffnen(ordner)
    try:
        assert d.angehoben_von == 8
        assert d.zeile("/q/original.jpg")["war_duplikat"] == 0
        assert d.zeile("/q/doppelt.jpg")["war_duplikat"] == 1
        assert d.zeile("/q/offen.jpg")["war_duplikat"] == 1
    finally:
        d.schliessen()
    assert db.vor_schema_pfad(db.datenbank_pfad(ordner), 8).is_file()


# ------------------------ F7: "Stand vom" beim Wiederherstellen ----


def test_f7_wiederherstellen_nennt_den_stand_der_sicherung(baum, quelle, ziel, archiv_basis, capsys):
    """F7: "Stand vom" zeigte den Zeitpunkt des Wiederherstellens (die Kopie
    bekam eine neue Aenderungszeit), nicht den der Sicherung."""
    import os
    from datetime import datetime
    from test_kopieren import _vorbereiten
    from test_zielindex import _lokal_loeschen
    _vorbereiten(ziel, quelle)
    sicherung = db.sicherung_pfad(ziel)
    alt = datetime(2026, 1, 2, 3, 4, 5).timestamp()
    os.utime(sicherung, (alt, alt))
    _lokal_loeschen(ziel, archiv_basis)
    capsys.readouterr()
    assert _cli("wiederherstellen", "--ziel", ziel) == cli.OK
    assert "Stand vom 2026-01-02 03:04:05" in capsys.readouterr().out


# ------------------------------ F8: Phase in "status" passend zum Stand ----


@pytest.mark.parametrize("zeilen, erwartet", [
    ([("verschoben", 0, "h")], "Alles erledigt"),
    ([("quelle_geloescht", 0, "h"), ("duplikat", 0, "h")], "Pruefen offen"),
    ([("duplikat_bestaetigt", 1, "h")], "Alles erledigt"),          # bereits importiert: bleibt in der Quelle
    ([("geprueft", 0, "h")], "Quelle aufraeumen offen"),
    ([("gefunden", 0, "")], "Analyse offen"),
    ([("uebersprungen", 0, "")], "Alles erledigt"),
])
def test_f8_status_nennt_den_naechsten_schritt(tmp_path, ziel, zeilen, erwartet, capsys):
    """F8: "status" nahm die niedrigste Stufe und meldete nach dem Verschieben
    "Scan offen", nach einem Verschieben ueber Laufwerke "Leere Ordner
    entfernen offen", obwohl Pruefen offen war. Jetzt folgt die Phase dem
    naechsten Schritt mit Arbeit - wie im Fenster."""
    quelle = tmp_path / "Quelle"
    quelle.mkdir()
    (quelle / "x.jpg").write_bytes(testbaum._JPEG)
    assert _cli("scan", "--quelle", quelle, "--ziel", ziel) == cli.OK
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    import os
    d = db.Datenbank.oeffnen(Path(os.environ["FOTOSORT_DATENBANK"]) / kennung)
    try:
        d.verbindung.execute("DELETE FROM dateien")
        for i, (status, schon, h) in enumerate(zeilen):
            d.verbindung.execute(
                "INSERT INTO dateien (quellpfad, quellwurzel, dateityp, status, schon_im_archiv, hash, zielpfad, groesse)"
                " VALUES (?, ?, 'foto', ?, ?, ?, ?, 5)",
                (db.pfad_text(quelle / f"{i}.jpg"), db.pfad_text(quelle), status, schon, h,
                 db.pfad_text(ziel / "2019" / f"{i}.jpg") if status not in ("gefunden", "uebersprungen") else ""))
        d.verbindung.commit()
    finally:
        d.schliessen()
    capsys.readouterr()
    assert _cli("status", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert erwartet in aus, aus
    assert "Scan offen" not in aus


# --------------------- F11: Verschieben im Textfenster nur mit Wort ----


def test_f11_verschieben_ohne_wort_verschiebt_nichts(baum, quelle, ziel, nachschauen, capsys, monkeypatch):
    """F11: "fotosort kopieren --verschieben" entfernte die Originale ohne
    Bestaetigungswort - sogar ohne Terminal (Eingabe aus /dev/null). Die
    Anleitung sagt: Im schwarzen Fenster gelten dieselben Woerter wie im
    Programmfenster. Jetzt: ohne das Wort "verschieben" wird nichts verschoben."""
    from test_kopieren import _vorbereiten
    _vorbereiten(ziel, quelle)
    vorher = _zeilen(nachschauen, ziel)
    capsys.readouterr()
    # Ohne Terminal (keine Eingabe moeglich): verweigert.
    assert cli.main(["kopieren", "--ziel", str(ziel), "--verschieben"]) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "verschieben" in aus and "nichts verschoben" in aus.lower(), aus
    # Falsches Wort: ebenfalls nichts.
    monkeypatch.setenv("FOTOSORT_EINGABE_ERZWINGEN", "1")
    monkeypatch.setattr("builtins.input", lambda: "ja")
    assert cli.main(["kopieren", "--ziel", str(ziel), "--verschieben"]) == cli.FEHLER
    assert _zeilen(nachschauen, ziel) == vorher
    assert all(Path(db.text_pfad(p)).exists() for p, z in vorher.items() if z["dateityp"] != "sonstiges")
    # Der Probelauf sagt, dass die Originale die Quelle verlassen wuerden.
    assert cli.main(["kopieren", "--ziel", str(ziel), "--verschieben", "--dry-run"]) == cli.OK
    assert "Quelle" in capsys.readouterr().out
    # Mit dem richtigen Wort wird verschoben.
    monkeypatch.setattr("builtins.input", lambda: "verschieben")
    assert cli.main(["kopieren", "--ziel", str(ziel), "--verschieben"]) == cli.OK
    assert any(z["status"] == "verschoben" for z in _zeilen(nachschauen, ziel).values())


# ------------------------------ F13: Zahlen in "Stand des Archivs" ----


def test_f13_stand_des_archivs_zahl_und_groesse_passen_zusammen(baum, quelle, ziel, capsys):
    """F13: "kopiert (Pruefen offen): 0 Dateien, 366 B" - die Zahl zaehlte nur
    kopiert, die Groesse auch geprueft. Nach dem Verschieben stand
    "kopiert: 0 Dateien, 8,8 KB"."""
    from fotosort import meldungen
    _bis_geprueft(quelle, ziel)
    capsys.readouterr()
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    zeile = next(z for z in aus.splitlines() if "kopiert (Pruefen offen)" in z)
    assert zeile.strip().endswith("0 Dateien, 0 B"), zeile
    z = {"status": {"verschoben": 3}, "kopiert_bytes": 0, "verschoben_bytes": 9000, "je_quelle": {}}
    text = meldungen.kopieren_zusammenfassung(z)
    assert "verschoben" in text and "3 Dateien" in text


# ------------------------ F12: abgerissene Ausgabe (Pipe zu) ----


def test_f12_abgerissene_ausgabe_bricht_den_lauf_nicht_ab(quelle, ziel, nachschauen):
    """F12: Lief die Ausgabe in ein anderes Programm ("| tee") und war dieses
    weg (Strg+C trifft beide), scheiterte schon die naechste Ausgabezeile -
    der Lauf endete nicht sauber, .part-Dateien blieben liegen. Jetzt geht
    eine abgerissene Ausgabe still verloren, die Arbeit wird ordentlich beendet."""
    import os
    import subprocess
    import sys
    umgebung = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    prozess = subprocess.Popen([sys.executable, "-m", "fotosort", "scan", "--quelle", str(quelle), "--ziel", str(ziel)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=umgebung)
    prozess.stdout.close()                    # der Leser ist weg
    fehler = prozess.stderr.read().decode("utf-8", "replace")
    rc = prozess.wait(timeout=300)
    assert rc == cli.OK, fehler
    with nachschauen(ziel) as d:
        lauf = d.letzter_lauf()
        assert lauf["ende"] and lauf["befehl"].startswith("fotosort scan")
    assert "Traceback" not in fehler, fehler


# ---------------- Beobachtung: das datierte von zwei gleichen Bildern ----


def test_von_gleichen_bildern_kommt_das_datierte_ins_archiv(tmp_path, ziel, nachschauen):
    """Beobachtung des Testers (v0.14): Von inhaltsgleichen Dateien kam die
    zuerst gefundene ins Archiv - auch wenn sie kein Datum hatte und eine
    gleiche mit Datum im Namen daneben lag. Das Bild landete dann unter
    _Ohne_Datum, die datierte Kopie wurde als Duplikat aufgeraeumt. Jetzt
    kommt die datierte ins Archiv; die undatierte ist ihr Duplikat."""
    quelle = tmp_path / "Quelle"
    (quelle / "a").mkdir(parents=True)
    (quelle / "b").mkdir()
    inhalt = testbaum._JPEG + b"gleich"
    (quelle / "a" / "bild.jpg").write_bytes(inhalt)                 # kein Datum (nur Aenderungszeit)
    (quelle / "b" / "2026-01-01 Urlaub.jpg").write_bytes(inhalt)     # Datum im Namen
    from test_kopieren import _vorbereiten
    _vorbereiten(ziel, quelle)
    datiert, ohne = _eine(nachschauen, ziel, "2026-01-01 Urlaub.jpg"), _eine(nachschauen, ziel, "bild.jpg")
    assert datiert["datum_sicher"] == 1 and ohne["datum_sicher"] == 0
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    datiert, ohne = _eine(nachschauen, ziel, "2026-01-01 Urlaub.jpg"), _eine(nachschauen, ziel, "bild.jpg")
    assert datiert["status"] == "kopiert", (datiert["status"], ohne["status"])
    assert "_Ohne_Datum" not in Path(db.text_pfad(datiert["zielpfad"])).parts
    assert ohne["status"] == "duplikat" and ohne["zielpfad"] == datiert["zielpfad"]


# ------------------------ F16: "status" sagt, was gerade gilt ----


def test_f16_status_prueft_die_quelle_jetzt_und_erklaert_die_status(tmp_path, ziel, capsys):
    """F16: "status" nannte eine Quelle "erreichbar", obwohl das Kopieren sie
    gerade als nicht erreichbar gemeldet hatte (der Vermerk stammte vom
    letzten Scan), und zeigte rohe Statuswoerter wie duplikat_bestaetigt."""
    quelle = tmp_path / "Karte"
    quelle.mkdir()
    (quelle / "a.jpg").write_bytes(testbaum._JPEG)
    assert _cli("scan", "--quelle", quelle, "--ziel", ziel) == cli.OK
    capsys.readouterr()
    assert _cli("status", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "noch nicht analysiert" in aus                      # Erklaerung neben "gefunden"
    quelle.rename(tmp_path / "Karte gezogen")
    assert _cli("status", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "gerade nicht erreichbar" in aus and "(erreichbar)" not in aus, aus
