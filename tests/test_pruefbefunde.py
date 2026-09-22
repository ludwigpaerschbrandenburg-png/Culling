"""Phase 5, Nacharbeit: Befunde der zwei unabhaengigen Pruefer (SPEC §4 Phase 1/3/5/6, §5).

Jeder Fund hat hier einen Test, der beweist, dass der Verlustweg zu ist bzw.
das Programm sich weigert. Reihenfolge wie im Pruefbericht.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import testbaum
from fotosort import cli, config, db, dateitypen, hashes, kopieren, loeschen, meldungen, pfade
from test_aufraeumen import _bis_geprueft, _echte, _papierkorb, _quelldateien, antwort  # noqa: F401
from test_kopieren import _cli, _ereignisse, _parts, _vorbereiten, _zeilen, _zieldateien

NUR_POSIX = pytest.mark.skipif(sys.platform.startswith("win"), reason="Linux-Dateisystem noetig")


# --- Fund 1: Quelle und Ziel sind dieselbe Datei ------------------------------


def test_dieselbe_datei_ueber_hardlink_wird_nie_geloescht(baum, quelle, ziel, nachschauen, antwort, capsys):
    """Zielpfad und Quellpfad zeigen auf denselben Inode (Hardlink, Bind-Mount,
    zweite Freigabe): Loeschen wuerde das Archivbild selbst treffen (SPEC §4 Phase 1)."""
    _bis_geprueft(ziel, quelle)
    zeilen = _zeilen(nachschauen, ziel)
    z = zeilen[str(baum["analog"])]
    zp = Path(z["zielpfad"])
    inhalt = zp.read_bytes()
    zp.unlink()
    os.link(baum["analog"], zp)          # jetzt EIN Inode unter zwei Namen
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    assert baum["analog"].exists() and zp.exists() and zp.read_bytes() == inhalt
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "fehler" and "dieselbe Datei" in z["fehlergrund"]
    assert z["bestaetigt_in_lauf"] is None
    assert any("dieselbe Datei" in e["text"] for e in _ereignisse(nachschauen, ziel, loeschen.ART_LOESCHUNG_VERWEIGERT))


def test_dieselbe_datei_auch_im_verschieben_modus(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    """Verschieben ueber den Kopierweg: Wird das Ziel nach dem Kopieren zum
    Hardlink der Quelle, wird die Quelle nicht geloescht."""
    monkeypatch.setattr(kopieren.pfade, "gleiches_laufwerk", lambda a, b: False)
    _vorbereiten(ziel, quelle)
    original = loeschen.frisch_lesen

    def hardlink_dann_lesen(q, z, byte_vergleich, stop=None, lauf=0):
        if Path(q) == baum["analog"]:
            Path(z).unlink()
            os.link(q, z)
        return original(q, z, byte_vergleich, stop, lauf)

    monkeypatch.setattr(kopieren.loeschen, "frisch_lesen", hardlink_dann_lesen)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert baum["analog"].exists() and z["status"] == "fehler" and "dieselbe Datei" in z["fehlergrund"]


def test_lage_pruefen_erkennt_denselben_ordner_ueber_inode(tmp_path, monkeypatch):
    """Zwei verschiedene Pfade, dieselbe Geraete-/Inode-Nummer (Bind-Mount):
    gilt als 'gleich' bzw. 'in', obwohl resolve() sie nicht zusammenfuehrt."""
    a = tmp_path / "echt"
    b = tmp_path / "sicht"
    a.mkdir()
    b.mkdir()
    (a / "unten").mkdir()
    kennung_a = pfade.ordner_kennung(a)
    original = pfade.ordner_kennung

    def wie_bind_mount(p):
        if pfade.aufloesen(Path(p)) == pfade.aufloesen(b):
            return kennung_a
        return original(p)

    monkeypatch.setattr(pfade, "ordner_kennung", wie_bind_mount)
    assert pfade.lage_pruefen(a, b) == "gleich"
    assert pfade.lage_pruefen(a / "unten", b) == "quelle_in_ziel"
    assert pfade.lage_pruefen(b, a / "unten") == "ziel_in_quelle"


def test_scan_erkennt_ziel_ueber_zweiten_pfad(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    """Ein Unterordner der Quelle ist derselbe Ordner wie das Ziel (nur ueber
    einen anderen Pfad): Der Scan ueberspringt ihn als 'zeigt ins Ziel'."""
    alias = quelle / "Sicht_aufs_Archiv"
    alias.mkdir()
    (alias / "im_archiv.jpg").write_bytes(testbaum._JPEG + b"archiv")
    kennung_ziel = pfade.ordner_kennung(ziel)
    original = pfade.ordner_kennung

    def wie_bind_mount(p):
        if pfade.aufloesen(Path(p)) == pfade.aufloesen(alias):
            return kennung_ziel
        return original(p)

    monkeypatch.setattr(pfade, "ordner_kennung", wie_bind_mount)
    _cli("scan", "--ziel", ziel, "--quelle", quelle)
    zeilen = _zeilen(nachschauen, ziel)
    assert str(alias / "im_archiv.jpg") not in zeilen
    from fotosort import scan
    assert any(Path(e["pfad"]) == alias for e in _ereignisse(nachschauen, ziel, scan.ART_INS_ZIEL))


# --- Fund 2: der Ordner _geloescht_ wird nie wieder erfasst -------------------


def test_papierkorb_wird_vom_scan_und_aufraeumen_nie_angefasst(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    korb = _papierkorb(quelle)
    assert korb is not None
    im_korb = _quelldateien(korb)
    assert im_korb
    vorher = set(_zeilen(nachschauen, ziel))
    assert _cli("scan", "--ziel", ziel) in (cli.OK, cli.FEHLER)
    zeilen = _zeilen(nachschauen, ziel)
    assert set(zeilen) == vorher, "Dateien im Papierkorb duerfen keine neuen Zeilen bekommen"
    assert not any(loeschen.ist_papierkorb(Path(qp).relative_to(quelle).parts[0]) for qp in zeilen)
    assert "ausgeschlossen" in capsys.readouterr().out
    # Auch eine (fremde, alte) Zeile unter dem Papierkorb ist nie Loeschkandidat.
    with nachschauen(ziel) as d:
        z = d.zeile(baum["analog"])
        fremd = db.pfad_text(korb / "alt.jpg")
        d.verbindung.execute(
            "INSERT INTO dateien (quellpfad, quellwurzel, groesse, mtime, dateityp, status, hash, zielpfad)"
            " VALUES (?, ?, 1, 1.0, 'foto', 'geprueft', ?, ?)", (fremd, z["quellwurzel"], z["hash"], z["zielpfad"]))
        d.verbindung.commit()
        assert all(r["quellpfad"] != fremd for r in d.zu_loeschen(z["quellwurzel"]))
        assert sum(n for n, _ in d.zu_loeschen_summe().values()) == 0
    antwort.append("verschieben")
    _cli("aufraeumen", "--ziel", ziel)
    assert _quelldateien(korb) == im_korb, "Papierkorb unveraendert"


# --- Fund 3: Betriebssystemfehler beim Entfernen bricht den Lauf nicht ab -----


def test_schreibschutz_beim_loeschen_gibt_fehler_und_lauf_geht_weiter(baum, quelle, ziel, nachschauen, antwort, monkeypatch, capsys):
    _bis_geprueft(ziel, quelle)
    original = os.unlink

    def gesperrt(pfad, *a, **k):
        if Path(pfad) == baum["analog"]:
            raise PermissionError(13, "Read-only file system", str(pfad))
        return original(pfad, *a, **k)

    monkeypatch.setattr(loeschen.os, "unlink", gesperrt)
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    zeilen = _echte(_zeilen(nachschauen, ziel))
    z = zeilen[str(baum["analog"])]
    assert baum["analog"].exists()
    assert z["status"] == "fehler" and "Read-only" in z["fehlergrund"] and z["bestaetigt_in_lauf"] is None
    # Die uebrigen wurden trotzdem bearbeitet, der Lauf ist beendet, der Bericht da.
    assert sum(1 for v in zeilen.values() if v["status"] == "quelle_geloescht") >= 10
    with nachschauen(ziel) as d:
        assert d.letzter_lauf()["ende"]
    assert "Bericht geschrieben" in capsys.readouterr().out


def test_schreibschutz_im_papierkorb_modus(baum, quelle, ziel, nachschauen, antwort, monkeypatch):
    _bis_geprueft(ziel, quelle)
    original = pfade.umbenennen_ohne_ueberschreiben

    def gesperrt(von, nach):
        if Path(von) == baum["analog"]:
            raise PermissionError(13, "Permission denied", str(von))
        return original(von, nach)

    monkeypatch.setattr(loeschen.pfade, "umbenennen_ohne_ueberschreiben", gesperrt)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.FEHLER
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert baum["analog"].exists() and z["status"] == "fehler" and z["bestaetigt_in_lauf"] is None


def test_papierkorb_rueckfall_raeumt_eigene_kopie_bei_schreibschutz_weg(baum, quelle, ziel, nachschauen, antwort, monkeypatch):
    """exFAT-Rueckfall: kopiert, geprueft - dann scheitert das Entfernen der
    Quelle. Die eigene Kopie im Papierkorb wird zurueckgenommen."""
    _bis_geprueft(ziel, quelle)
    monkeypatch.setattr(loeschen.pfade, "umbenennen_ohne_ueberschreiben",
                        lambda von, nach: (_ for _ in ()).throw(pfade.KeinNoReplace("exFAT")))
    original = os.unlink

    def gesperrt(pfad, *a, **k):
        if Path(pfad) == baum["analog"]:
            raise PermissionError(13, "Permission denied", str(pfad))
        return original(pfad, *a, **k)

    monkeypatch.setattr(loeschen.os, "unlink", gesperrt)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.FEHLER
    korb = _papierkorb(quelle)
    assert baum["analog"].exists()
    assert not any(p.name == "scan_001.tif" for p in korb.rglob("*"))


# --- Fund 4: Absturz nach dem Umbenennen, vor dem Festschreiben ----------------


def test_absturz_nach_umbenennen_wird_beim_neustart_nachgetragen(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    _vorbereiten(ziel, quelle)
    original = db.Datenbank.verschoben_setzen
    getroffen = []

    def absturz(self, quellpfad, zielpfad, lauf):
        if Path(db.text_pfad(quellpfad)) == baum["analog"] and not getroffen:
            getroffen.append(1)
            raise KeyboardInterrupt   # wie ein Abschuss: Umbenennen fertig, Status nie geschrieben
        return original(self, quellpfad, zielpfad, lauf)

    monkeypatch.setattr(db.Datenbank, "verschoben_setzen", absturz)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.ABGEBROCHEN
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "kopieren_laeuft" and z["umbenannt"] == 1
    assert not baum["analog"].exists() and Path(z["schreibpfad"]).exists()
    monkeypatch.setattr(db.Datenbank, "verschoben_setzen", original)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "verschoben" and Path(z["zielpfad"]).exists()
    assert any("Umbenennen aus abgebrochenem Lauf" in e["text"] for e in _ereignisse(nachschauen, ziel, kopieren.ART_NACHTRAEGLICH_BESTAETIGT))
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert _zeilen(nachschauen, ziel)[str(baum["analog"])]["hash"] == hashes.blake3_datei(Path(z["zielpfad"]))


# --- Fund 5 / Angriff 3 und 13: Quelle aendert sich zwischen Lesung und Loeschung ---


def _nach_lesung_veraendern(datei: Path, monkeypatch, modul):
    """frisch_lesen umhuellen: nach der Lesung das letzte Byte der Quelle kippen
    (gleiche Groesse) und die Aenderungszeit zurueckstellen - so tueckisch wie moeglich."""
    original = loeschen.frisch_lesen

    def lesen_dann_kippen(q, z, byte_vergleich, stop=None, lauf=0):
        L = original(q, z, byte_vergleich, stop, lauf)
        if Path(q) == datei:
            st = os.stat(q)
            b = bytearray(datei.read_bytes())
            b[-1] ^= 0xFF
            datei.write_bytes(bytes(b))
            os.utime(q, ns=(st.st_atime_ns, st.st_mtime_ns))
        return L

    monkeypatch.setattr(modul, "frisch_lesen", lesen_dann_kippen)


def test_quelle_zwischen_lesung_und_loeschung_geaendert_endgueltig(baum, quelle, ziel, nachschauen, antwort, monkeypatch, capsys):
    _bis_geprueft(ziel, quelle)
    datei = baum["analog"]
    _nach_lesung_veraendern(datei, monkeypatch, loeschen)
    neu = None
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    z = _zeilen(nachschauen, ziel)[str(datei)]
    assert datei.exists()
    neu = hashes.blake3_datei(datei)
    assert neu != z["hash"] or z["hash"] == ""
    assert z["status"] == "analysiert" and z["hash"] == "" and z["bestaetigt_in_lauf"] is None
    assert _ereignisse(nachschauen, ziel, loeschen.ART_QUELLE_SEIT_KOPIEREN_GEAENDERT)
    assert "Quelle seit dem Kopieren geaendert" in capsys.readouterr().out


def test_quelle_zwischen_lesung_und_loeschung_geaendert_verschieben(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    monkeypatch.setattr(kopieren.pfade, "gleiches_laufwerk", lambda a, b: False)
    _vorbereiten(ziel, quelle)
    datei = baum["analog"]
    _nach_lesung_veraendern(datei, monkeypatch, kopieren.loeschen)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    z = _zeilen(nachschauen, ziel)[str(datei)]
    assert datei.exists() and z["status"] == "analysiert" and z["hash"] == ""
    assert "Quelle seit dem Kopieren geaendert (nicht geloescht): 1" in capsys.readouterr().out


def test_quelle_zwischen_lesung_und_papierkorb_geaendert_geht_nicht_verloren(baum, quelle, ziel, nachschauen, antwort, monkeypatch):
    """Im Papierkorb-Modus wandert der AKTUELLE Inhalt mit - oder die Datei
    bleibt stehen. Verloren geht der neue Inhalt in keinem Fall."""
    _bis_geprueft(ziel, quelle)
    datei = baum["analog"]
    _nach_lesung_veraendern(datei, monkeypatch, loeschen)
    antwort.append("verschieben")
    _cli("aufraeumen", "--ziel", ziel)
    korb = _papierkorb(quelle)
    alle = [datei] + (list(korb.rglob("scan_001*")) if korb else [])
    inhalte = [p.read_bytes() for p in alle if p.exists()]
    assert any(b[-1] == (testbaum._tiff()[-1] ^ 0xFF) for b in inhalte), "der neue Inhalt muss irgendwo liegen"


# --- Fund 6: bestaetigt_in_lauf verliert bei Neukopie seine Beweiskraft --------


def test_bestaetigt_kennung_wird_bei_jedem_neuanfang_geleert(baum, quelle, ziel, nachschauen):
    _bis_geprueft(ziel, quelle)
    with nachschauen(ziel) as d:
        qp = db.pfad_text(baum["analog"])
        z = d.zeile(qp)
        for setzen in (
            lambda: d.zurueck_auf_analysiert(qp, z["zielpfad"]),
            lambda: d.kopieren_beanspruchen(qp, z["zielpfad"], z["zielpfad"] + ".part", 7),
            lambda: d.kopiert_setzen(qp, z["zielpfad"], z["hash"], 7),
            lambda: d.duplikat_setzen(qp, z["zielpfad"], z["hash"], 7),
            lambda: d.status_setzen(qp, "fehler", "x"),
        ):
            d.bestaetigt_setzen(qp, 5, None)
            assert d.zeile(qp)["bestaetigt_in_lauf"] == 5
            setzen()
            assert d.zeile(qp)["bestaetigt_in_lauf"] is None


def test_alte_kennung_nach_neukopie_traegt_nichts_nach(baum, quelle, ziel, nachschauen, antwort, monkeypatch, capsys):
    """Loeschung scheitert (Kennung war gesetzt) -> Neukopie -> Nutzer loescht
    die Quelle selbst: Das darf NICHT als 'unsere Loeschung' nachgetragen werden."""
    _bis_geprueft(ziel, quelle)
    original = os.unlink

    def gesperrt(pfad, *a, **k):
        if Path(pfad) == baum["analog"]:
            raise PermissionError(13, "Permission denied", str(pfad))
        return original(pfad, *a, **k)

    monkeypatch.setattr(loeschen.os, "unlink", gesperrt)
    antwort.append("loeschen")
    _cli("aufraeumen", "--ziel", ziel, "--endgueltig")
    monkeypatch.setattr(loeschen.os, "unlink", original)
    # Neu kopieren (fehler -> analysiert -> kopiert -> geprueft), dann Quelle weg.
    with nachschauen(ziel) as d:
        d.zurueck_auf_analysiert(db.pfad_text(baum["analog"]), _zeilen(nachschauen, ziel)[str(baum["analog"])]["zielpfad"])
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    baum["analog"].unlink()
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "fehler" and "nicht mehr vorhanden" in z["fehlergrund"]
    assert not _ereignisse(nachschauen, ziel, loeschen.ART_LOESCHUNG_NACHGETRAGEN)


# --- Fund 7: Papierkorb-Rueckfall liest die Kopie zurueck ----------------------


@pytest.fixture
def exfat_papierkorb(monkeypatch):
    def kein_link(von, nach):
        raise pfade.KeinNoReplace("exFAT")
    monkeypatch.setattr(loeschen.pfade, "umbenennen_ohne_ueberschreiben", kein_link)


def test_papierkorb_rueckfall_kopiert_prueft_und_entfernt(baum, quelle, ziel, nachschauen, antwort, exfat_papierkorb):
    _bis_geprueft(ziel, quelle)
    vorher = _quelldateien(quelle)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    korb = _papierkorb(quelle)
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in zeilen.values()} == {"quelle_geloescht"}
    nachher = _quelldateien(korb)
    for qp, z in zeilen.items():
        rel = str(Path(qp).relative_to(quelle))
        assert not Path(qp).exists() and nachher[rel] == vorher[rel] == z["hash"]


def test_papierkorb_rueckfall_verweigert_bei_kaputter_kopie(baum, quelle, ziel, nachschauen, antwort, exfat_papierkorb, monkeypatch):
    _bis_geprueft(ziel, quelle)
    original = hashes.kopieren_mit_hash

    def kopieren_dann_beschaedigen(q, z, *a, **k):
        h, n = original(q, z, *a, **k)
        if Path(q) == baum["analog"]:
            Path(z).write_bytes(b"kaputt auf der Platte")   # Strom war gut, Platte nicht
        return h, n

    monkeypatch.setattr(loeschen.hashes, "kopieren_mit_hash", kopieren_dann_beschaedigen)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.FEHLER
    korb = _papierkorb(quelle)
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert baum["analog"].exists() and z["status"] == "fehler" and "stimmt nicht ueberein" in z["fehlergrund"]
    assert not list(korb.rglob("scan_001*")), "die kaputte eigene Kopie ist weg"


def test_papierkorb_namenskollision_und_gleiche_namen_in_unterordnern(baum, quelle, ziel, nachschauen, antwort):
    """Belegter Name im Papierkorb -> Anhang _1; zwei gleichnamige Dateien aus
    verschiedenen Unterordnern behalten ihre Unterordner."""
    _bis_geprueft(ziel, quelle)
    korb = loeschen.papierkorb_ordner(quelle)
    belegt = korb / "Analog" / "scan_001.tif"
    belegt.parent.mkdir(parents=True)
    belegt.write_bytes(b"fremd")
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    assert belegt.read_bytes() == b"fremd"
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert Path(z["schreibpfad"]).name == "scan_001_1.tif" and hashes.blake3_datei(Path(z["schreibpfad"])) == z["hash"]
    # DSC01234.JPG gibt es in "2026" und in "Namenskonflikt": beide im Papierkorb, getrennt.
    a = _zeilen(nachschauen, ziel)[str(baum["jpg"])]
    b = _zeilen(nachschauen, ziel)[str(baum["namenskonflikt"])]
    assert Path(a["schreibpfad"]).parent.name == "2026" and Path(b["schreibpfad"]).parent.name == "Namenskonflikt"
    assert Path(a["schreibpfad"]).exists() and Path(b["schreibpfad"]).exists()


# --- Fund 8 / Angriff 8b: Reste-Regel kann kein Foto treffen -------------------


def test_reste_eintrag_mit_foto_endung_loescht_nie_ein_foto(baum, quelle, ziel, nachschauen, antwort, tmp_path, archiv_basis, capsys):
    _bis_geprueft(ziel, quelle)
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    konf_pfad = archiv_basis / kennung / "config.toml"
    text = konf_pfad.read_text(encoding="utf-8").replace(
        'reste_dateien = ["Thumbs.db", ".DS_Store", "desktop.ini"]',
        'reste_dateien = ["Thumbs.db", ".DS_Store", "desktop.ini", "beute.jpg", "Thumbs.db"]')
    assert "beute.jpg" in text
    konf_pfad.write_text(text, encoding="utf-8")
    # Nach dem Scan dazugekommen: keine Zeile in der Datenbank.
    nur_rest = quelle / "nurrest"
    nur_rest.mkdir()
    beute = nur_rest / "beute.jpg"
    beute.write_bytes(testbaum._JPEG + b"echtes Bild")
    nur_thumbs = quelle / "nurthumbs"
    nur_thumbs.mkdir()
    (nur_thumbs / "Thumbs.db").write_bytes(b"rest")
    antwort.extend(["", "entfernen"])
    _cli("aufraeumen", "--ziel", ziel, "--leere-ordner")
    assert beute.exists() and nur_rest.exists()
    assert not nur_thumbs.exists()


# --- Fund 9: Verknuepfungen tief im Baum ---------------------------------------


@NUR_POSIX
def test_leere_ordner_mit_verknuepfung_in_unterordner(baum, quelle, ziel, nachschauen, antwort):
    _bis_geprueft(ziel, quelle)
    tief = quelle / "tief_leer" / "noch_tiefer"
    tief.mkdir(parents=True)
    os.symlink(baum["ausserhalb"], tief / "link", target_is_directory=True)
    (quelle / "wirklich_leer").mkdir()
    antwort.extend(["", "entfernen"])
    _cli("aufraeumen", "--ziel", ziel, "--leere-ordner")
    assert (tief / "link").is_symlink() and tief.exists()
    assert baum["nur_ueber_verknuepfung"].exists()
    assert not (quelle / "wirklich_leer").exists()


# --- Fund 10: Abbruch im Rueckfall ohne .part ---------------------------------


def test_abbruch_im_rueckfall_laesst_keine_leeren_dateien_zurueck(baum, quelle, ziel, nachschauen, monkeypatch):
    monkeypatch.setattr(kopieren.pfade, "kann_ohne_ueberschreiben", lambda ordner: False)
    _vorbereiten(ziel, quelle)
    original = kopieren.wait

    def sofort_abbrechen(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(kopieren, "wait", sofort_abbrechen)
    assert _cli("kopieren", "--ziel", ziel) == cli.ABGEBROCHEN
    zeilen = _zeilen(nachschauen, ziel)
    kopiert = {Path(z["zielpfad"]) for z in zeilen.values() if z["status"] == "kopiert"}
    for p in Path(ziel).rglob("*"):
        if p.is_file() and ".fotosortierer" not in p.parts:
            assert p in kopiert, f"Datei ohne kopierte Zeile: {p}"
            assert p.stat().st_size > 0
    assert not _parts(ziel)


# --- Fund 11: Anhang weicht innerhalb der Gruppe ab -> sichtbar ---------------


def test_anhang_abweichend_in_gruppe_wird_gemeldet(baum, quelle, ziel, nachschauen, monkeypatch):
    _vorbereiten(ziel, quelle)
    original = pfade.umbenennen_ohne_ueberschreiben
    einmal = []

    def fremder_dazwischen(von, nach):
        if Path(nach).name == "DSC01234.JPG" and not einmal:
            einmal.append(1)
            Path(nach).write_bytes(b"fremd")     # ein anderes Programm legt den Namen an
        return original(von, nach)

    monkeypatch.setattr(kopieren.pfade, "umbenennen_ohne_ueberschreiben", fremder_dazwischen)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    jpg = Path(zeilen[str(baum["jpg"])]["zielpfad"])
    raw = Path(zeilen[str(baum["raw"])]["zielpfad"])
    assert jpg.exists() and raw.exists() and jpg.read_bytes() != b"fremd"
    assert (jpg.stem.endswith("_1")) != (raw.stem.endswith("_1"))
    assert _ereignisse(nachschauen, ziel, kopieren.ART_ANHANG_ABWEICHEND)


# --- Nebenbefund: Meldung nennt die Quelle nicht faelschlich als defekt --------


def test_groessenmeldung_nennt_die_richtige_seite():
    assert "Quelle ist in Ordnung" in meldungen.grund_groesse_abweichung(160, 160, 159)
    assert "Quelle 161" in meldungen.grund_groesse_abweichung(160, 161, 160)
