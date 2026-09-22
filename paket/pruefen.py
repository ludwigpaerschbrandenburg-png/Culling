"""Das gepackte Programm wirklich ausprobieren - wie auf einem frischen PC.

In GitHub Actions unter Windows (lokal auch unter Linux, dann ohne start.bat):
  1. Das Paket liegt in einem Ordner mit Leerzeichen und Klammern
     ("fotosort-windows (1)\\fotosort"), der Nutzerdatenordner
     (%LOCALAPPDATA%\\fotosortierer) existiert noch nicht.
  2. Start nur ueber start.bat. Das Fenster muss innerhalb von 20 Sekunden
     erscheinen (es schreibt beim Erscheinen fenster.json); dann wird es ueber
     die Datei "schliessen" beendet.
  3. Ein kompletter Durchlauf am kuenstlichen Testbaum ueber die Oberflaeche
     (fotosort-konsole.exe fenster --durchlauf, Qt offscreen), mit Bildern.
  4. Die Befehle: --version (mitgeliefertes ExifTool), scan, analyse, kopieren,
     pruefen, status, und ein Schritt als Arbeitsprozess der Oberflaeche.

Aufruf:
    python paket/pruefen.py <paketordner> <arbeitsordner>

Rueckgabe 0, wenn alles stimmt; sonst 1 mit Begruendung. Es werden nur
Dateien im Arbeitsordner angelegt.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform.startswith("win")
FENSTER_SEKUNDEN = 20


def _lauf(befehl: list[str], umgebung: dict, cwd: Path, zeit: int = 600) -> tuple[int, str]:
    print("$", " ".join(befehl), flush=True)
    aus = subprocess.run(befehl, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=umgebung, cwd=cwd, timeout=zeit)
    text = aus.stdout + aus.stderr
    print(text[-4000:], flush=True)
    return aus.returncode, text


def _pid_lebt(pid: int) -> bool:
    sys.path.insert(0, str(WURZEL / "src"))
    from fotosort.oberflaeche.ablauf import pid_lebt
    return pid_lebt(pid)


def main() -> int:
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) != 3:
        print("Aufruf: pruefen.py <paketordner> <arbeitsordner>")
        return 2
    paket = Path(sys.argv[1]).resolve()
    arbeit = Path(sys.argv[2]).resolve()
    endung = ".exe" if WINDOWS else ""
    fehler: list[str] = []

    # -- Inhalt des Pakets ----------------------------------------------------
    for name in ("fotosort" + endung, "fotosort-konsole" + endung, "fotosort.bat", "start.bat", "LIESMICH.md", "VERSION.txt",
                 "exiftool/exiftool" + endung):
        if not (paket / name).is_file():
            fehler.append(f"{name} fehlt im Paket")
    if WINDOWS and not (paket / "exiftool" / "exiftool_files").is_dir():
        fehler.append("Ordner exiftool_files (Perl-Bibliotheken) fehlt neben exiftool.exe")
    static = paket / "_internal" / "fotosort" / "oberflaeche" / "static"
    for name in ("index.html", "app.js", "app.css", "styles.css", "fonts.css", "fonts/Inter-latin.woff2",
                 "fonts/Inter-Regular.ttf", "fonts/Inter-Medium.ttf", "fonts/Inter-SemiBold.ttf"):
        if not (static / name).is_file():
            fehler.append(f"Seite/Schrift: static/{name} fehlt im Paket")
    for name in ("styles.css", "app.css", "fonts.css", "index.html"):
        try:
            if "https://" in (static / name).read_text(encoding="utf-8", errors="replace"):
                fehler.append(f"static/{name} verweist auf eine Internetadresse")
        except OSError:
            pass
    if fehler:
        return _ende(fehler)

    # -- Frischer PC: Ordner mit Leerzeichen und Klammern, leerer Nutzerdatenordner --
    shutil.rmtree(arbeit, ignore_errors=True)
    arbeit.mkdir(parents=True)
    start_ordner = arbeit / "fotosort-windows (1)" / "fotosort"
    shutil.copytree(paket, start_ordner)
    lokal = arbeit / "Nutzer (neu)" / "AppData" / "Local"   # existiert noch nicht
    exe = start_ordner / ("fotosort" + endung)
    konsole = start_ordner / ("fotosort-konsole" + endung)
    exiftool = start_ordner / "exiftool" / ("exiftool" + endung)
    umgebung = {k: v for k, v in os.environ.items()
                if k not in ("FOTOSORT_EXIFTOOL", "FOTOSORT_ZIEL", "FOTOSORT_DATENBANK", "QT_QPA_PLATFORM")}
    umgebung["PYTHONUTF8"] = "1"
    umgebung["PATH"] = os.pathsep.join(
        p for p in umgebung.get("PATH", "").split(os.pathsep) if shutil.which("exiftool", path=p) is None
    )
    if WINDOWS:
        umgebung["LOCALAPPDATA"] = str(lokal)
    else:
        umgebung["XDG_DATA_HOME"] = str(lokal)
    daten_ordner = lokal / "fotosortierer"
    ob_ordner = daten_ordner / "oberflaeche"

    if WINDOWS:
        print(f"$ start.bat  (in {start_ordner}, LOCALAPPDATA={lokal})", flush=True)
        beginn = time.monotonic()
        subprocess.run(["cmd.exe", "/c", "start.bat"], cwd=str(start_ordner), env=umgebung, timeout=60)
        marker = ob_ordner / "fenster.json"
        stand: dict = {}
        while time.monotonic() - beginn < FENSTER_SEKUNDEN:
            try:
                stand = json.loads(marker.read_text(encoding="utf-8"))
                if stand.get("sichtbar"):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.25)
        dauer = time.monotonic() - beginn
        if stand.get("sichtbar"):
            print(f"Fenster erschienen nach {dauer:.1f} s (Version {stand.get('version')}, PID {stand.get('pid')})", flush=True)
        else:
            fehler.append(f"Fenster ist nach {FENSTER_SEKUNDEN} s nicht erschienen (start.bat)")
            protokoll = ob_ordner / "fenster.log"
            if protokoll.is_file():
                print(protokoll.read_text(encoding="utf-8", errors="replace")[-3000:], flush=True)
        if stand.get("pid"):
            (ob_ordner / "schliessen").write_text("", encoding="utf-8")
            ende = time.monotonic() + 20
            while time.monotonic() < ende and _pid_lebt(int(stand["pid"])):
                time.sleep(0.25)
            if _pid_lebt(int(stand["pid"])):
                fehler.append("Fenster hat sich auf die Datei 'schliessen' nicht beendet")
            else:
                print("Fenster ueber die Datei 'schliessen' beendet.", flush=True)
    else:
        print("(start.bat gibt es nur unter Windows; hier: Fenster-Selbsttest offscreen)", flush=True)
        rc, text = _lauf([str(exe), "fenster", "--selbsttest"], dict(umgebung, QT_QPA_PLATFORM="offscreen"), start_ordner)
        if rc != 0 or "Selbsttest bestanden" not in text:
            fehler.append("Fenster-Selbsttest nicht bestanden")

    # -- Durchlauf ueber die Oberflaeche am Testbaum (offscreen) ---------------
    erzeuger = dict(umgebung, FOTOSORT_EXIFTOOL=str(exiftool), PYTHONPATH=str(WURZEL / "src"))
    rc, text = _lauf([sys.executable, str(WURZEL / "tests" / "testbaum.py"), str(arbeit / "baum")], erzeuger, WURZEL)
    if rc != 0:
        return _ende(fehler + ["Testbaum liess sich nicht erzeugen"])
    quelle = arbeit / "baum" / "Quelle"
    ziel_fenster = arbeit / "Ziel (Fenster)"
    ziel_fenster.mkdir()
    fotos = arbeit / "fotos"
    rc, text = _lauf([str(konsole), "fenster", "--durchlauf", str(ziel_fenster), str(quelle), "--fotos", str(fotos)],
                     dict(umgebung, QT_QPA_PLATFORM="offscreen"), start_ordner, zeit=900)
    if rc != 0 or "Durchlauf bestanden" not in text:
        fehler.append(f"Durchlauf ueber das Fenster: Rueckgabewert {rc}")
    bilder = sorted(fotos.glob("*.png")) if fotos.is_dir() else []
    if len(bilder) < 12:
        fehler.append(f"Durchlauf: nur {len(bilder)} Bilder statt 12")
    else:
        print(f"{len(bilder)} Bilder unter {fotos}", flush=True)

    # -- Befehle mit Ausgabe (fotosort-konsole) --------------------------------
    rc, text = _lauf([str(konsole), "--version"], umgebung, start_ordner)
    if rc != 0 or not re.search(r"^fotosort \d+\.\d+", text, re.M):
        fehler.append("--version nennt keine Programmversion")
    if not re.search(r"^ExifTool \d+\.\d+ \(.*mitgeliefert\)", text, re.M):
        fehler.append("--version findet das mitgelieferte ExifTool nicht")
    rc, text = _lauf([sys.executable, str(WURZEL / "tests" / "testbaum.py"), str(arbeit / "baum2")], erzeuger, WURZEL)
    quelle2 = arbeit / "baum2" / "Quelle"
    ziel = arbeit / "Ziel (Befehle)"
    schritte = [
        (["scan", "--ziel", str(ziel), "--quelle", str(quelle2), "--ziel-anlegen"], "Dateien gesamt:"),
        (["analyse", "--ziel", str(ziel)], "ILCE-7CM2"),
        (["kopieren", "--ziel", str(ziel)], "kopiert:"),
        (["pruefen", "--ziel", str(ziel)], "geprueft (Zieldatei stimmt):"),
        (["status", "--ziel", str(ziel)], "Aktuelle Phase: 5"),
    ]
    for argumente, erwartet in schritte:
        rc, text = _lauf([str(konsole), *argumente], umgebung, start_ordner)
        if rc != 0:
            fehler.append(f"{argumente[0]}: Rueckgabewert {rc}")
        if erwartet not in text:
            fehler.append(f"{argumente[0]}: '{erwartet}' fehlt in der Ausgabe")
    if not any(p.is_file() and ".fotosortierer" not in p.parts for p in ziel.rglob("*")):
        fehler.append("im Ziel liegen keine kopierten Dateien")

    # -- Ein Schritt als Arbeitsprozess der Oberflaeche -----------------------------
    auftrag = arbeit / "auftrag.json"
    status = arbeit / "status.json"
    auftrag.write_text(json.dumps({
        "schritt": "scan", "ziel": str(ziel), "quellen": [], "ziel_anlegen": False,
        "status_datei": str(status), "steuer_datei": str(arbeit / "steuer.json"),
    }), encoding="utf-8")
    rc, text = _lauf([str(konsole), "arbeit", "--auftrag", str(auftrag)], umgebung, start_ordner)
    try:
        stand = json.loads(status.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stand = {}
    if rc != 0 or stand.get("zustand") != "fertig" or not stand.get("dateien"):
        fehler.append(f"Arbeitsprozess der Oberflaeche: Rueckgabewert {rc}, Stand {stand}")
    if not daten_ordner.is_dir():
        fehler.append("Nutzerdatenordner wurde nicht angelegt")
    return _ende(fehler)


def _ende(fehler: list[str]) -> int:
    if fehler:
        print("PAKETPRUEFUNG FEHLGESCHLAGEN:")
        for f in fehler:
            print("  -", f)
        return 1
    print("PAKETPRUEFUNG BESTANDEN: Fenster aus Ordner mit Leerzeichen gestartet, Durchlauf ueber das Fenster, "
          "Befehle und Arbeitsprozess laufen, ExifTool mitgeliefert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
