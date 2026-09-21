"""Tests fuer cli.py (SPEC Abschnitt 2, 6 und 8)."""

from __future__ import annotations

import os

import pytest

import testbaum
from fotosort import cli, config, db


def _laufen(capsys, *argumente) -> tuple[int, str]:
    rueckgabe = cli.main(list(argumente))
    return rueckgabe, capsys.readouterr().out


# ------------------------------------------------- Unterbefehle vollzaehlig ----


def test_alle_unterbefehle_aus_der_spec_gibt_es():
    eltern = cli.parser_bauen()
    aktionen = [
        a for a in eltern._actions if getattr(a, "choices", None) and a.dest == "befehl"
    ]
    vorhanden = set(aktionen[0].choices)
    assert vorhanden == {
        "scan",
        "analyse",
        "kopieren",
        "pruefen",
        "aufraeumen",
        "status",
        "bericht",
        "ziel-index",
        "wiederherstellen",
        "config",
        "start",
    }


@pytest.mark.parametrize(
    "befehl,phase",
    [
        ("analyse", 2),
        ("kopieren", 3),
        ("ziel-index", 3),
        ("wiederherstellen", 3),
        ("pruefen", 4),
        ("bericht", 4),
        ("aufraeumen", 5),
        ("start", 6),
    ],
)
def test_spaetere_phase_meldet_freundlich_und_endet_ungleich_null(
    befehl, phase, ziel, capsys
):
    rueckgabe, ausgabe = _laufen(capsys, befehl, "--ziel", str(ziel))
    assert rueckgabe != 0
    assert befehl in ausgabe
    assert f"Phase {phase}" in ausgabe


# -------------------------------------------------------------- --ziel ----


def test_ohne_ziel_verstaendliche_meldung(capsys, monkeypatch):
    monkeypatch.delenv("FOTOSORT_ZIEL", raising=False)
    rueckgabe, ausgabe = _laufen(capsys, "status")
    assert rueckgabe != 0
    assert "Ziel" in ausgabe
    assert "FOTOSORT_ZIEL" in ausgabe


def test_ziel_aus_umgebungsvariable(capsys, monkeypatch, quelle, ziel):
    monkeypatch.setenv("FOTOSORT_ZIEL", str(ziel))
    rueckgabe, _ = _laufen(capsys, "scan", "--quelle", str(quelle))
    assert rueckgabe == cli.OK


def test_kommandozeile_hat_vorrang_vor_der_umgebungsvariablen(
    capsys, monkeypatch, quelle, ziel, tmp_path
):
    anderes = tmp_path / "Anderes"
    anderes.mkdir()
    monkeypatch.setenv("FOTOSORT_ZIEL", str(anderes))
    rueckgabe, _ = _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    assert rueckgabe == cli.OK
    assert db.archiv_id_vorhanden(ziel)
    assert not db.archiv_id_vorhanden(anderes)


def test_jeder_befehl_kennt_config(ziel):
    eltern = cli.parser_bauen()
    for befehl in ("scan", "analyse", "kopieren", "status", "config", "start"):
        args = eltern.parse_args([befehl, "--ziel", str(ziel), "--config", "/x.toml"])
        assert args.config == "/x.toml"


# ---------------------------------------------------------------- scan ----


def test_scan_ohne_quelle_meldet_das(capsys, ziel):
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--ziel", str(ziel))
    assert rueckgabe != 0
    assert "Quelle" in ausgabe


def test_scan_auf_frischem_ziel_legt_alles_an(capsys, quelle, tmp_path, archiv_basis):
    # Ein noch nicht vorhandenes Ziel entsteht nur auf ausdrueckliche Ansage.
    ziel = tmp_path / "FrischesZiel"
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel), "--ziel-anlegen"
    )
    assert rueckgabe == cli.OK

    # Archiv-Kennung im Ziel
    kennung_datei = db.archiv_id_datei(ziel)
    assert kennung_datei.is_file()
    kennung = kennung_datei.read_text(encoding="utf-8").strip()
    assert len(kennung) == 32

    # Datenbank und Konfiguration im lokalen Archiv-Ordner
    ordner = archiv_basis / kennung
    assert (ordner / db.DATEINAME).is_file()
    assert (ordner / config.DATEINAME).is_file()
    assert (ordner / config.DATEINAME).read_text(encoding="utf-8").lstrip().startswith("#")

    # Sicherungskopie und Konfiguration im Ziel
    assert db.sicherung_pfad(ziel).is_file()
    assert (ziel / ".fotosortierer" / config.DATEINAME).is_file()

    assert "Archiv-Kennung" in ausgabe
    assert str(testbaum.ERWARTET_GESAMT) in ausgabe


def test_scan_zeigt_anzahl_groesse_typen_und_durchsatz(capsys, quelle, ziel):
    _, ausgabe = _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    assert "Dateien gesamt" in ausgabe
    assert "Gesamtgroesse" in ausgabe
    for typ in ("foto", "raw", "video", "sidecar", "sonstiges"):
        assert typ in ausgabe
    assert "Durchsatz" in ausgabe


def test_scan_quelle_gleich_ziel_bricht_ab(capsys, quelle):
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(quelle))
    assert rueckgabe == cli.FEHLER
    assert "derselbe Ordner" in ausgabe
    # Es wurde kein halbes Archiv angelegt.
    assert not db.archiv_id_vorhanden(quelle)


def test_scan_quelle_in_ziel_bricht_ab(capsys, quelle, baum):
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(baum["wurzel"])
    )
    assert rueckgabe == cli.FEHLER
    assert "innerhalb des Ziels" in ausgabe


def test_scan_ziel_in_quelle_meldet_und_laeuft_weiter(capsys, quelle):
    inneres_ziel = quelle / "_Ziel"
    inneres_ziel.mkdir()
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(inneres_ziel)
    )
    assert rueckgabe == cli.OK
    assert "innerhalb der Quelle" in ausgabe
    assert "ausgeschlossen" in ausgabe


def test_scan_ist_fortsetzbar(capsys, quelle, ziel):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    assert rueckgabe == cli.OK
    assert "unveraendert uebernommen" in ausgabe
    assert f"{testbaum.ERWARTET_GESAMT}" in ausgabe


def test_kaputte_archiv_id_bricht_ab_und_bleibt_stehen(capsys, quelle, ziel):
    datei = db.archiv_id_datei(ziel)
    datei.parent.mkdir(parents=True)
    datei.write_text("voellig kaputt", encoding="utf-8")
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    assert rueckgabe == cli.FEHLER
    assert "voellig kaputt" in ausgabe
    assert datei.read_text(encoding="utf-8") == "voellig kaputt"


def test_fehlende_datenbank_mit_sicherung_weist_auf_wiederherstellen_hin(
    capsys, quelle, ziel, archiv_basis
):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    for name in (db.DATEINAME, db.DATEINAME + "-wal", db.DATEINAME + "-shm"):
        pfad = archiv_basis / kennung / name
        if pfad.exists():
            pfad.unlink()

    rueckgabe, ausgabe = _laufen(capsys, "status", "--ziel", str(ziel))
    assert rueckgabe == cli.FEHLER
    assert "wiederherstellen" in ausgabe


def test_fehlende_datenbank_ohne_sicherung(capsys, quelle, ziel, archiv_basis):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    for name in (db.DATEINAME, db.DATEINAME + "-wal", db.DATEINAME + "-shm"):
        pfad = archiv_basis / kennung / name
        if pfad.exists():
            pfad.unlink()
    db.sicherung_pfad(ziel).unlink()

    rueckgabe, ausgabe = _laufen(capsys, "status", "--ziel", str(ziel))
    assert rueckgabe == cli.FEHLER
    assert "ziel-index" in ausgabe


# -------------------------------------------------------------- status ----


def test_status_ohne_archiv_meldet_das(capsys, ziel):
    rueckgabe, ausgabe = _laufen(capsys, "status", "--ziel", str(ziel))
    assert rueckgabe == cli.FEHLER
    assert "kein Archiv" in ausgabe


def test_status_zeigt_alle_elf_status_und_die_phase(capsys, quelle, ziel):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    rueckgabe, ausgabe = _laufen(capsys, "status", "--ziel", str(ziel))
    assert rueckgabe == cli.OK
    for name in db.STATUS:
        assert name in ausgabe
    assert "Aktuelle Phase: 2" in ausgabe
    assert "Letzter Lauf" in ausgabe


def test_status_phase_folgt_dem_niedrigsten_status(capsys, quelle, ziel, archiv_basis):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    datenbank = db.Datenbank.oeffnen(archiv_basis / kennung)
    try:
        datenbank.verbindung.execute(
            "UPDATE dateien SET status='analysiert' WHERE status='gefunden'"
        )
        datenbank.stapel_schreiben()
    finally:
        datenbank.schliessen()
    _, ausgabe = _laufen(capsys, "status", "--ziel", str(ziel))
    assert "Aktuelle Phase: 3" in ausgabe


# -------------------------------------------------------------- config ----


def test_config_nur_pfad_gibt_nur_den_pfad_aus(capsys, quelle, ziel, archiv_basis):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    rueckgabe, ausgabe = _laufen(capsys, "config", "--nur-pfad", "--ziel", str(ziel))
    assert rueckgabe == cli.OK
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    erwartet = archiv_basis / kennung / config.DATEINAME
    assert ausgabe.strip().endswith(str(erwartet))


def test_config_zeigt_den_pfad_und_aendert_nichts(capsys, quelle, ziel, monkeypatch):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    monkeypatch.setattr(cli, "_editor_oeffnen", lambda pfad: False)
    _, pfad_ausgabe = _laufen(capsys, "config", "--nur-pfad", "--ziel", str(ziel))
    pfad = pfad_ausgabe.strip()
    vorher = open(pfad, "rb").read()

    rueckgabe, ausgabe = _laufen(capsys, "config", "--ziel", str(ziel))
    assert rueckgabe == cli.OK
    assert pfad in ausgabe
    assert "kein Editor" in ausgabe
    assert open(pfad, "rb").read() == vorher


def test_unbekannte_konfigurationswerte_werden_gemeldet(capsys, quelle, ziel, tmp_path):
    eigene = tmp_path / "eigene.toml"
    eigene.write_text('[ordner]\nvorlaage = "Tippfehler"\n', encoding="utf-8")
    vorher = eigene.read_bytes()
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel), "--config", str(eigene)
    )
    assert rueckgabe == cli.OK
    assert "ordner.vorlaage" in ausgabe
    assert eigene.read_bytes() == vorher


def test_config_mit_ausschlussmuster_wirkt(capsys, quelle, ziel, tmp_path, baum):
    eigene = tmp_path / "eigene.toml"
    eigene.write_text(
        f'[quelle]\nausschlussmuster = ["{testbaum.AUSSCHLUSSMUSTER_BEISPIEL}"]\n',
        encoding="utf-8",
    )
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel), "--config", str(eigene)
    )
    assert rueckgabe == cli.OK
    assert f"  Dateien gesamt:  {testbaum.ERWARTET_GESAMT_OHNE_PAPIERKORB}" in ausgabe


# ------------------------------------------------------------ ExifTool ----


def test_exiftool_pruefung_bricht_scan_nicht_ab(capsys, quelle, ziel, monkeypatch):
    monkeypatch.setattr(cli, "exiftool_finden", lambda konf=None: (None, "nirgends"))
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    assert rueckgabe == cli.OK
    assert "Hinweis" in ausgabe
    assert "ExifTool" in ausgabe


@pytest.mark.parametrize("befehl", ["status", "config"])
def test_exiftool_fehlt_stoert_status_und_config_nicht(
    befehl, capsys, quelle, ziel, monkeypatch
):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    monkeypatch.setattr(cli, "exiftool_finden", lambda konf=None: (None, "nirgends"))
    monkeypatch.setattr(cli, "_editor_oeffnen", lambda pfad: False)
    zusatz = ["--nur-pfad"] if befehl == "config" else []
    rueckgabe, _ = _laufen(capsys, befehl, *zusatz, "--ziel", str(ziel))
    assert rueckgabe == cli.OK


@pytest.mark.parametrize("befehl", ["analyse", "start"])
def test_ohne_exiftool_harter_abbruch_fuer_metadaten_befehle(
    befehl, capsys, ziel, monkeypatch
):
    monkeypatch.setattr(cli, "exiftool_finden", lambda konf=None: (None, "nirgends"))
    rueckgabe, ausgabe = _laufen(capsys, befehl, "--ziel", str(ziel))
    assert rueckgabe == cli.FEHLER
    assert "ExifTool wurde nicht gefunden" in ausgabe
    assert "FOTOSORT_EXIFTOOL" in ausgabe


def test_exiftool_vorrang_umgebungsvariable(monkeypatch):
    monkeypatch.setenv("FOTOSORT_EXIFTOOL", "/usr/bin/exiftool")
    gefunden, wo = cli.exiftool_finden()
    assert "FOTOSORT_EXIFTOOL" in wo


def test_exiftool_dann_konfigurationswert(monkeypatch):
    monkeypatch.delenv("FOTOSORT_EXIFTOOL", raising=False)
    k = config.Konfiguration()
    k.alle()["leistung"]["exiftool_pfad"] = "/usr/bin/exiftool"
    gefunden, wo = cli.exiftool_finden(k)
    assert "exiftool_pfad" in wo


def test_exiftool_zuletzt_ueber_path(monkeypatch):
    monkeypatch.delenv("FOTOSORT_EXIFTOOL", raising=False)
    gefunden, wo = cli.exiftool_finden(config.Konfiguration())
    assert "PATH" in wo
    assert gefunden and os.path.basename(gefunden).startswith("exiftool")


def test_exiftool_im_container_wirklich_startbar():
    gefunden, _ = cli.exiftool_finden()
    assert gefunden
    assert cli.exiftool_startbar(gefunden) is True


# --------------------------- ExifTool: der Konfigurationswert wirkt ----


def _config_mit(tmp_path, inhalt: str):
    pfad = tmp_path / "eigene.toml"
    pfad.write_text(inhalt, encoding="utf-8")
    return pfad


def test_exiftool_pfad_aus_der_konfiguration_wirkt_beim_aufruf(
    capsys, quelle, ziel, tmp_path, monkeypatch
):
    """SPEC Abschnitt 2: FOTOSORT_EXIFTOOL, dann exiftool_pfad, dann PATH.

    Frueher wurde exiftool_finden() ohne Konfiguration aufgerufen; die
    mittlere Stufe fehlte damit vollstaendig. Unter Windows, wo ExifTool
    selten im PATH liegt, ist sie die wahrscheinlichste Einstellung.
    """
    monkeypatch.setenv("PATH", str(tmp_path / "leer"))
    eigene = _config_mit(tmp_path, '[leistung]\nexiftool_pfad = "/usr/bin/exiftool"\n')

    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel),
        "--config", str(eigene),
    )
    assert rueckgabe == cli.OK
    # Kein Hinweis: ExifTool wurde ueber den Konfigurationswert gefunden.
    assert "ExifTool wurde nicht gefunden" not in ausgabe
    assert "Hinweis: ExifTool" not in ausgabe


def test_falscher_exiftool_pfad_aus_der_konfiguration_wird_gemeldet(
    capsys, quelle, ziel, tmp_path, monkeypatch
):
    monkeypatch.setenv("PATH", str(tmp_path / "leer"))
    eigene = _config_mit(
        tmp_path, '[leistung]\nexiftool_pfad = "/gibt/es/nicht/exiftool"\n'
    )
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel),
        "--config", str(eigene),
    )
    assert rueckgabe == cli.OK  # der Scan braucht ExifTool nicht
    assert "/gibt/es/nicht/exiftool" in ausgabe
    assert "exiftool_pfad" in ausgabe


def test_umgebungsvariable_hat_vorrang_vor_dem_konfigurationswert(
    capsys, quelle, ziel, tmp_path, monkeypatch
):
    monkeypatch.setenv("PATH", str(tmp_path / "leer"))
    monkeypatch.setenv("FOTOSORT_EXIFTOOL", "/auch/nicht/da/exiftool")
    eigene = _config_mit(tmp_path, '[leistung]\nexiftool_pfad = "/usr/bin/exiftool"\n')
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel),
        "--config", str(eigene),
    )
    assert rueckgabe == cli.OK
    assert "/auch/nicht/da/exiftool" in ausgabe
    assert "FOTOSORT_EXIFTOOL" in ausgabe


# ------------------------------------------------ Ausgabe ohne Markup ----


def test_eckige_klammern_bleiben_in_der_ausgabe_stehen(capsys, quelle, tmp_path):
    """Ein Ordner "[urlaub] 2026" darf nicht als " 2026" erscheinen."""
    ziel = tmp_path / "[urlaub] 2026"
    ziel.mkdir()
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel)
    )
    assert rueckgabe == cli.OK
    assert "[urlaub] 2026" in ausgabe


def test_exiftool_hinweis_nennt_die_gruppe_leistung(capsys, quelle, ziel, monkeypatch):
    monkeypatch.setattr(cli, "exiftool_finden", lambda konf=None: (None, "nirgends"))
    _, ausgabe = _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    assert "[leistung]" in ausgabe


def test_netzlaufwerk_meldung_nennt_die_gruppe_datenbank(
    capsys, quelle, ziel, monkeypatch
):
    from fotosort import pfade

    monkeypatch.setattr(pfade, "ist_netzpfad", lambda p: True)
    monkeypatch.setattr(pfade, "dateisystem_typ", lambda p: "cifs")
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel)
    )
    assert rueckgabe == cli.FEHLER
    assert "[datenbank]" in ausgabe


# ------------------------------------------------------- Ziel anlegen ----


def test_fehlendes_ziel_wird_nicht_stillschweigend_angelegt(capsys, quelle, tmp_path):
    ziel = tmp_path / "vertippt"
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel)
    )
    assert rueckgabe == cli.FEHLER
    assert "--ziel-anlegen" in ausgabe
    assert not ziel.exists()


def test_ziel_anlegen_legt_es_an(capsys, quelle, tmp_path):
    ziel = tmp_path / "NeuesZiel"
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel), "--ziel-anlegen"
    )
    assert rueckgabe == cli.OK
    assert ziel.is_dir()
    assert "Neuer Zielordner angelegt" in ausgabe


def test_ziel_anlegen_ohne_elternordner_bricht_ab(capsys, quelle, tmp_path):
    ziel = tmp_path / "gibt" / "es" / "nicht"
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel), "--ziel-anlegen"
    )
    assert rueckgabe == cli.FEHLER
    assert "fehlender Ort" in ausgabe
    assert not ziel.exists()


# ----------------------------------------- Deutsche Meldungen statt Absturz ----


def test_ziel_zeigt_auf_eine_datei(capsys, quelle, tmp_path):
    datei = tmp_path / "keine-mappe.txt"
    datei.write_text("kein Ordner\n", encoding="utf-8")
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(datei)
    )
    assert rueckgabe == cli.FEHLER
    assert "Traceback" not in ausgabe
    assert "Abbruch" in ausgabe
    assert str(datei) in ausgabe


def test_quelle_ohne_leserechte_meldet_deutsch(capsys, quelle, ziel, monkeypatch):
    from pathlib import Path as _Path

    echt = _Path.is_dir

    def gestoert(self):
        if str(self) == str(quelle):
            raise PermissionError(13, "Permission denied", str(quelle))
        return echt(self)

    monkeypatch.setattr(_Path, "is_dir", gestoert)
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel)
    )
    assert rueckgabe == cli.FEHLER
    assert "Traceback" not in ausgabe
    assert "Permission denied" in ausgabe
    assert str(quelle) in ausgabe


def test_kaputte_config_meldet_zeile_und_spalte(capsys, quelle, ziel, tmp_path):
    eigene = _config_mit(tmp_path, '[ordner]\nvorlage = "ohne Ende\n')
    vorher = eigene.read_bytes()
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel),
        "--config", str(eigene),
    )
    assert rueckgabe == cli.FEHLER
    assert "Traceback" not in ausgabe
    assert "Konfigurationsdatei" in ausgabe
    assert "Zeile 2" in ausgabe
    assert str(eigene) in ausgabe
    assert eigene.read_bytes() == vorher


def test_falscher_typ_in_der_config_bricht_ab(capsys, quelle, ziel, tmp_path):
    """Eine Zeichenkette statt einer Liste wuerde die ganze Quelle ausschliessen."""
    eigene = _config_mit(tmp_path, '[quelle]\nausschlussmuster = "*/Papierkorb/*"\n')
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel),
        "--config", str(eigene),
    )
    assert rueckgabe == cli.FEHLER
    assert "quelle.ausschlussmuster" in ausgabe
    assert "Liste" in ausgabe
    assert "Dateien gesamt" not in ausgabe


def test_falscher_wahrheitswert_in_der_config_bricht_ab(capsys, quelle, ziel, tmp_path):
    """bool("nein") waere True - aus dem Nein wuerde ein Ja."""
    eigene = _config_mit(tmp_path, '[quelle]\nverknuepfungen_folgen = "nein"\n')
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel),
        "--config", str(eigene),
    )
    assert rueckgabe == cli.FEHLER
    assert "quelle.verknuepfungen_folgen" in ausgabe
    assert "Wahrheitswert" in ausgabe


# ---------------------------------------------- Nicht lesbarer Ordner ----


def test_nicht_lesbarer_ordner_ergibt_einen_fehler_rueckgabewert(
    capsys, quelle, ziel, monkeypatch
):
    import os as _os

    from fotosort import scan as _scan

    gesperrt = (quelle / "Duplikate").resolve()
    echt = _os.scandir

    def gestoert(pfad="."):
        if str(pfad) == str(gesperrt):
            raise PermissionError(13, "Permission denied")
        return echt(pfad)

    monkeypatch.setattr(_scan.os, "scandir", gestoert)
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel)
    )
    assert rueckgabe != cli.OK
    assert "Ordner nicht lesbar:" in ausgabe
    assert str(gesperrt) in ausgabe
    assert "Quelle nicht mehr vorhanden:  nicht geprueft" in ausgabe


# ------------------------------------------------------------ Sperre ----


def test_zweiter_gleichzeitiger_lauf_bricht_verstaendlich_ab(
    capsys, quelle, ziel, archiv_basis
):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    erste = db.Datenbank.oeffnen(archiv_basis / kennung, sperren=True)
    try:
        rueckgabe, ausgabe = _laufen(
            capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel)
        )
        assert rueckgabe == cli.FEHLER
        assert "laeuft bereits ein Vorgang" in ausgabe
        assert "Traceback" not in ausgabe
    finally:
        erste.schliessen()


# ---------------------------------------------------------- status ----


def test_status_ohne_stufe_aber_mit_dateien(capsys, quelle, ziel, archiv_basis):
    """Nur uebersprungene Dateien: "keine Dateien erfasst" waere falsch."""
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    datenbank = db.Datenbank.oeffnen(archiv_basis / kennung)
    try:
        datenbank.verbindung.execute("UPDATE dateien SET status='uebersprungen'")
        datenbank.stapel_schreiben()
    finally:
        datenbank.schliessen()

    rueckgabe, ausgabe = _laufen(capsys, "status", "--ziel", str(ziel))
    assert rueckgabe == cli.OK
    assert "Aktuelle Phase: 1" in ausgabe
    assert "keine Dateien erfasst" not in ausgabe


def test_status_auf_leerem_archiv_sagt_keine_dateien(capsys, quelle, ziel, archiv_basis):
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    datenbank = db.Datenbank.oeffnen(archiv_basis / kennung)
    try:
        datenbank.verbindung.execute("DELETE FROM dateien")
        datenbank.stapel_schreiben()
    finally:
        datenbank.schliessen()
    _, ausgabe = _laufen(capsys, "status", "--ziel", str(ziel))
    assert "keine Dateien erfasst" in ausgabe


# --------------------------------------------------- config --nur-pfad ----


def test_nur_pfad_schreibt_genau_eine_zeile_auf_die_standardausgabe(
    capsys, quelle, ziel, monkeypatch
):
    """SPEC Abschnitt 8: Der Schalter soll sich in Skripten weiterverwenden lassen."""
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    capsys.readouterr()
    monkeypatch.setattr(cli, "exiftool_finden", lambda konf=None: (None, "nirgends"))

    rueckgabe = cli.main(["config", "--nur-pfad", "--ziel", str(ziel)])
    fertig = capsys.readouterr()
    assert rueckgabe == cli.OK
    assert len(fertig.out.strip().splitlines()) == 1
    assert fertig.out.strip().endswith("config.toml")
    # Der Hinweis ist nicht verschwunden, er steht auf der Fehlerausgabe.
    assert "ExifTool" in fertig.err


# ----------------------------------------------------------- Signale ----


def test_sigterm_wird_behandelt():
    """SIGTERM ist das Signal von "docker stop" und von TrueNAS."""
    import signal

    vorher = signal.getsignal(signal.SIGTERM)
    try:
        cli._signale_einrichten()
        behandler = signal.getsignal(signal.SIGTERM)
        assert callable(behandler)
        assert behandler is not signal.SIG_DFL
        with pytest.raises(KeyboardInterrupt):
            behandler(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, vorher)


# --------------------------------------------- Geordneter Abbruch ----


def test_geordneter_abbruch_schliesst_den_lauf(
    capsys, quelle, ziel, archiv_basis, monkeypatch
):
    """Ein Abbruch mit Meldung ist kein Absturz.

    Sonst zeigte "fotosort status" hinterher dauerhaft "nicht beendet
    (abgebrochen oder abgestuerzt)", obwohl nichts abgestuerzt ist.
    """
    from fotosort import FotosortFehler
    from fotosort import scan as _scan

    def scheitern(*args, **kwargs):
        raise FotosortFehler("Abbruch: aus Gruenden")

    monkeypatch.setattr(cli.scan, "ausfuehren", scheitern)
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel)
    )
    assert rueckgabe == cli.FEHLER
    assert "aus Gruenden" in ausgabe

    monkeypatch.undo()
    _, status = _laufen(capsys, "status", "--ziel", str(ziel))
    assert "nicht beendet" not in status

    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    datenbank = db.Datenbank.oeffnen(archiv_basis / kennung)
    try:
        zeile = datenbank.verbindung.execute(
            "SELECT art, text FROM lauf_ereignisse WHERE art = ?",
            (_scan.ART_ABGEBROCHEN,),
        ).fetchone()
        assert zeile is not None
        assert zeile["text"] == "sauber abgebrochen"
    finally:
        datenbank.schliessen()


def test_muster_das_alles_trifft_wird_dem_nutzer_gesagt(
    capsys, quelle, ziel, tmp_path
):
    eigene = _config_mit(tmp_path, '[quelle]\nausschlussmuster = ["*"]\n')
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel),
        "--config", str(eigene),
    )
    assert rueckgabe == cli.OK
    assert "gesamte Quelle" in ausgabe
    assert "ausschlussmuster" in ausgabe


def test_status_geht_auch_waehrend_ein_scan_laeuft(capsys, quelle, ziel, archiv_basis):
    """Nur verändernde Befehle belegen das Archiv."""
    _laufen(capsys, "scan", "--quelle", str(quelle), "--ziel", str(ziel))
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    laufender_scan = db.Datenbank.oeffnen(archiv_basis / kennung, sperren=True)
    try:
        rueckgabe, ausgabe = _laufen(capsys, "status", "--ziel", str(ziel))
        assert rueckgabe == cli.OK
        assert "Dateien je Status" in ausgabe
        rueckgabe, _ = _laufen(capsys, "config", "--nur-pfad", "--ziel", str(ziel))
        assert rueckgabe == cli.OK
    finally:
        laufender_scan.schliessen()
