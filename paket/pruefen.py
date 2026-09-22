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
     Waehrenddessen darf unter Windows kein Konsolenfenster aufgehen (im
     ersten echten Testlauf oeffnete jeder ExifTool-Prozess ein schwarzes
     Fenster). Eine Gegenprobe zeigt vorher, dass die Umgebung solche
     Fenster ueberhaupt sichtbar machen wuerde.
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
import threading
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


class _FensterWaechter:
    """Merkt sich unter Windows jedes Fenster, das waehrend eines Vorgangs neu
    aufgeht (Klasse, Titel, PID, sichtbar). Konsolenfenster haben die Klasse
    ConsoleWindowClass und werden auch unsichtbar gezaehlt - in einer Sitzung
    ohne Bildschirm (CI) existiert das Fenster, ist aber nie sichtbar."""

    KONSOLE = "ConsoleWindowClass"
    ABSTAND = 0.05

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.u32 = ctypes.windll.user32
        self.rueckruf_typ = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        self.anfang = self._fenster()
        self.neue: dict[int, tuple[str, str, int, bool]] = {}
        self._laeuft = False
        self._thread = threading.Thread(target=self._schleife, daemon=True)

    def _fenster(self) -> dict[int, tuple[str, str, int, bool]]:
        """Alle Fenster der obersten Ebene: sichtbare jeder Klasse, Konsolenfenster
        auch unsichtbar."""
        ctypes, wintypes, u32 = self.ctypes, self.wintypes, self.u32
        gefunden: dict[int, tuple[str, str, int, bool]] = {}

        def rueckruf(hwnd, _lp):
            klasse = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hwnd, klasse, 256)
            sichtbar = bool(u32.IsWindowVisible(hwnd))
            if sichtbar or klasse.value == self.KONSOLE:
                titel = ctypes.create_unicode_buffer(512)
                u32.GetWindowTextW(hwnd, titel, 512)
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                gefunden[int(hwnd)] = (klasse.value, titel.value, int(pid.value), sichtbar)
            return True

        u32.EnumWindows(self.rueckruf_typ(rueckruf), 0)
        return gefunden

    def _schleife(self) -> None:
        while self._laeuft:
            for hwnd, fenster in self._fenster().items():
                if hwnd not in self.anfang and hwnd not in self.neue:
                    self.neue[hwnd] = fenster
            time.sleep(self.ABSTAND)

    def start(self) -> "_FensterWaechter":
        self._laeuft = True
        self._thread.start()
        return self

    def stop(self) -> list[tuple[str, str, int, bool]]:
        self._laeuft = False
        self._thread.join(3)
        return list(self.neue.values())

    def konsolen(self, nur_sichtbare: bool = False) -> list[tuple[str, str, int, bool]]:
        return [f for f in self.neue.values() if f[0] == self.KONSOLE and (f[3] or not nur_sichtbare)]


def _gegenprobe(flagge: int) -> tuple[int, int]:
    """Ein Python-Kind mit dieser Erzeugungsflagge starten: (Konsolenfenster
    insgesamt, davon sichtbar), die der Waechter dabei neu gesehen hat."""
    w = _FensterWaechter().start()
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"], creationflags=flagge)
    try:
        p.wait(timeout=60)
    finally:
        w.stop()
    return len(w.konsolen()), len(w.konsolen(nur_sichtbare=True))


def _gegenproben() -> str:
    """Was die Fensterwache in dieser Umgebung beweisen kann.

    "unsichtbar": Ein Kind mit CREATE_NEW_CONSOLE erzeugt ein Konsolenfenster
    (auch wenn niemand es sieht), eines mit CREATE_NO_WINDOW keines - dann
    zaehlt waehrend des Durchlaufs jedes neue Konsolenfenster, sichtbar oder
    nicht. "sichtbar": nur sichtbare Fenster sind unterscheidbar. "": nichts
    davon ist hier beobachtbar, die Wache kann nichts finden.
    """
    mit, mit_sichtbar = _gegenprobe(subprocess.CREATE_NEW_CONSOLE)  # type: ignore[attr-defined]
    ohne, ohne_sichtbar = _gegenprobe(subprocess.CREATE_NO_WINDOW)  # type: ignore[attr-defined]
    print(f"Gegenprobe: CREATE_NEW_CONSOLE -> {mit} Konsolenfenster ({mit_sichtbar} sichtbar), "
          f"CREATE_NO_WINDOW -> {ohne} ({ohne_sichtbar} sichtbar).", flush=True)
    if mit and not ohne:
        return "unsichtbar"
    if mit_sichtbar and not ohne_sichtbar:
        return "sichtbar"
    return ""


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
    waechter = None
    beweiskraft = ""
    if WINDOWS:
        beweiskraft = _gegenproben()
        print({"unsichtbar": "Die Fensterwache zaehlt jedes neue Konsolenfenster, auch unsichtbare - aussagekraeftig.",
               "sichtbar": "Die Fensterwache kann nur sichtbare Konsolenfenster erkennen.",
               "": "Konsolenfenster sind in dieser Umgebung nicht beobachtbar - die Fensterwache kann hier nichts finden."}[beweiskraft],
              flush=True)
        waechter = _FensterWaechter().start()
    rc, text = _lauf([str(konsole), "fenster", "--durchlauf", str(ziel_fenster), str(quelle), "--fotos", str(fotos)],
                     dict(umgebung, QT_QPA_PLATFORM="offscreen"), start_ordner, zeit=900)
    if rc != 0 or "Durchlauf bestanden" not in text:
        fehler.append(f"Durchlauf ueber das Fenster: Rueckgabewert {rc}")
    if waechter is not None:
        neue = waechter.stop()
        konsolen = waechter.konsolen(nur_sichtbare=(beweiskraft != "unsichtbar"))
        if konsolen:
            fehler.append(f"Waehrend des Durchlaufs gingen {len(konsolen)} Konsolenfenster auf: "
                          + "; ".join(f"'{t}' (PID {pid}{', sichtbar' if sichtbar else ''})"
                                      for _k, t, pid, sichtbar in konsolen[:5]))
        andere = [f for f in neue if f[0] != waechter.KONSOLE]
        print(f"Waehrend des Durchlaufs neu: {len(waechter.konsolen())} Konsolenfenster "
              f"({len(waechter.konsolen(nur_sichtbare=True))} sichtbar), {len(andere)} andere sichtbare Fenster"
              + (" (" + "; ".join(f"{k} '{t}'" for k, t, _p, _s in andere[:5]) + ")" if andere else ""), flush=True)
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
    print("PAKETPRUEFUNG BESTANDEN: Fenster aus Ordner mit Leerzeichen gestartet, Durchlauf ueber das Fenster "
          "ohne Konsolenfenster, Befehle und Arbeitsprozess laufen, ExifTool mitgeliefert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
