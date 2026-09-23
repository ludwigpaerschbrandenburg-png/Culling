"""Das Windows-Paket ausprobieren - wie auf einem frischen PC.

Auf jedem System (auch Linux) wird der Inhalt geprueft:
  - Aufbau: python\\ (das eingebettete Python von python.org), lib\\ (fotosort,
    Einstieg, Bibliotheken), exiftool\\exiftool_files (perl.exe, exiftool.pl),
    start.bat, fotosort.bat, LIESMICH.md, VERSION.txt.
  - Programme: nur python.exe, pythonw.exe und perl.exe - keine eigenen exe.
  - Qt nur mit QtCore, QtGui, QtWidgets; keine Browser-Fassung.
  - Jede Bibliothek, die eine der Dateien braucht, liegt im Paket oder
    gehoert zu Windows selbst (paketinhalt.py).

Nur unter Windows (GitHub Actions) laeuft das Paket wirklich:
  1. Signaturen: python.exe, pythonw.exe und python312.dll gueltig signiert
     von der Python Software Foundation.
  2. Frischer PC: Kopie nach "...\\fotosort-windows (1)\\fotosort", leerer
     Nutzerdatenordner, Suchpfad ohne Python, Perl und ExifTool des Rechners.
  3. start.bat: Das Fenster muss in 20 Sekunden erscheinen, und zwar aus
     python\\pythonw.exe des Pakets; die Datei "schliessen" beendet es.
  4. ExifTool direkt ueber perl.exe mit exiftool.pl: dieselbe Version wie
     exiftool\\VERSION.txt.
  5. Ein kompletter Durchlauf am kuenstlichen Testbaum ueber das Fenster
     (fotosort.bat fenster --durchlauf, Qt offscreen), mit Bildern und mit
     Fensterwache: Es darf kein Konsolenfenster aufgehen. Die Arbeitsschritte
     muessen ueber python\\pythonw.exe gelaufen sein.
  6. fotosort.bat: --version, scan, analyse, kopieren, pruefen, status.
  7. Ein Schritt als Arbeitsprozess, gestartet wie vom Fenster (pythonw.exe).

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

import paketinhalt

WURZEL = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform.startswith("win")
FENSTER_SEKUNDEN = 20
PFLICHT = [
    "start.bat", "fotosort.bat", "LIESMICH.md", "VERSION.txt",
    "python/python.exe", "python/pythonw.exe", "python/python312.dll", "python/python312.zip", "python/python312._pth",
    "lib/fotosort_start.py", "lib/fotosort/__init__.py", "lib/fotosort/__main__.py", "lib/fotosort/restzeit.py",
    "lib/PySide6/QtWidgets.pyd", "lib/PySide6/Qt6Widgets.dll", "lib/PySide6/plugins/platforms/qwindows.dll",
    "lib/shiboken6/Shiboken.pyd", "lib/rich/console.py", "lib/tzdata/__init__.py",
    "exiftool/VERSION.txt", "exiftool/exiftool_files/perl.exe", "exiftool/exiftool_files/exiftool.pl",
]
STATIC = ["index.html", "app.js", "app.css", "styles.css", "fonts.css", "fonts/Inter-latin.woff2",
          "fonts/Inter-Regular.ttf", "fonts/Inter-Medium.ttf", "fonts/Inter-SemiBold.ttf"]
PSF = "Python Software Foundation"


def _lauf(befehl: list[str], umgebung: dict, cwd: Path, zeit: int = 600) -> tuple[int, str]:
    print("$", " ".join(befehl), flush=True)
    aus = subprocess.run(befehl, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=umgebung, cwd=cwd, timeout=zeit)
    text = aus.stdout + aus.stderr
    print(text[-4000:], flush=True)
    return aus.returncode, text


def _bat(bat: Path, argumente: list[str], umgebung: dict, cwd: Path, zeit: int = 600) -> tuple[int, str]:
    """Eine .bat-Datei so aufrufen wie aus der Eingabeaufforderung - mit Pfaden,
    die Leerzeichen und Klammern enthalten. /s: cmd entfernt nur das aeussere
    Anfuehrungszeichenpaar und laesst die inneren stehen."""
    zeile = subprocess.list2cmdline([str(bat), *argumente])
    print("$", zeile, flush=True)
    aus = subprocess.run(f'cmd.exe /d /s /c "{zeile}"', capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=umgebung, cwd=cwd, timeout=zeit)
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


def _programm_von(pid: int) -> str:
    """Voller Pfad des Programms, das als Prozess pid laeuft (Windows)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    griff = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
    if not griff:
        return ""
    try:
        puffer = ctypes.create_unicode_buffer(32768)
        laenge = wintypes.DWORD(32768)
        if not k32.QueryFullProcessImageNameW(griff, 0, puffer, ctypes.byref(laenge)):
            return ""
        return puffer.value
    finally:
        k32.CloseHandle(griff)


def _signatur(pfad: Path) -> tuple[str, str]:
    """(Status, Unterzeichner) der Authenticode-Signatur einer Datei (Windows)."""
    literal = str(pfad).replace("'", "''")
    befehl = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
              f"$s = Get-AuthenticodeSignature -LiteralPath '{literal}'; "
              "Write-Output ([string]$s.Status + '|' + [string]$s.SignerCertificate.Subject)"]
    aus = subprocess.run(befehl, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    status, _, wer = aus.stdout.strip().partition("|")
    return status, wer


def inhalt_pruefen(paket: Path) -> list[str]:
    fehler: list[str] = []
    for name in PFLICHT:
        if not (paket / name).is_file():
            fehler.append(f"{name} fehlt im Paket")
    static = paket / "lib" / "fotosort" / "oberflaeche" / "static"
    for name in STATIC:
        if not (static / name).is_file():
            fehler.append(f"Seite/Schrift: static/{name} fehlt im Paket")
    for name in ("styles.css", "app.css", "fonts.css", "index.html"):
        try:
            if "https://" in (static / name).read_text(encoding="utf-8", errors="replace"):
                fehler.append(f"static/{name} verweist auf eine Internetadresse")
        except OSError:
            pass
    try:
        pth = [z.strip() for z in (paket / "python" / "python312._pth").read_text(encoding="utf-8").splitlines()]
        if "..\\lib" not in pth or "python312.zip" not in pth:
            fehler.append(f"python312._pth nennt den Suchpfad ..\\lib nicht: {pth}")
        if any(z.startswith("import") for z in pth):
            fehler.append(f"python312._pth darf nichts importieren (kein 'import site'): {pth}")
    except OSError:
        pass
    programme = paketinhalt.programme(paket)
    fremd = [p for p in programme if p not in paketinhalt.ERLAUBTE_PROGRAMME]
    if fremd:
        fehler.append("fremde Programme im Paket (nur das signierte Python und perl.exe sind erlaubt): " + ", ".join(fremd))
    print("Programme im Paket:", ", ".join(programme), flush=True)
    qt = sorted(p.name for p in (paket / "lib" / "PySide6").glob("Qt*.pyd"))
    if qt != ["QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd"]:
        fehler.append(f"Qt-Module im Paket: {qt} (erwartet nur QtCore, QtGui, QtWidgets)")
    for name in ("fastapi", "uvicorn", "pygments"):
        if (paket / "lib" / name).exists():
            fehler.append(f"lib/{name} gehoert nicht ins Windows-Paket")
    fehlt, hinweise = paketinhalt.fehlende_abhaengigkeiten(paket)
    fehler += fehlt
    for h in hinweise:
        print("  Hinweis:", h, flush=True)
    version = (paket / "VERSION.txt").read_text(encoding="utf-8").split()[1] if (paket / "VERSION.txt").is_file() else "?"
    init = (paket / "lib" / "fotosort" / "__init__.py")
    if init.is_file() and f'"{version}"' not in init.read_text(encoding="utf-8"):
        fehler.append(f"VERSION.txt ({version}) passt nicht zu lib/fotosort/__init__.py")
    groesse = sum(p.stat().st_size for p in paket.rglob("*") if p.is_file())
    print(f"Inhalt: {sum(1 for p in paket.rglob('*') if p.is_file())} Dateien, {groesse / 1e6:.1f} MB, Version {version}", flush=True)
    return fehler


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

    # -- Inhalt (auf jedem System) ------------------------------------------------
    fehler = inhalt_pruefen(paket)
    if fehler:
        return _ende(fehler)
    if not WINDOWS:
        print("Nicht unter Windows: nur der Inhalt wurde geprueft. Starten laesst sich das Paket "
              "nur unter Windows (GitHub Actions, windows-latest).", flush=True)
        return _ende(fehler, nur_inhalt=True)

    # -- 1. Signaturen ----------------------------------------------------------------
    for name in ("python/python.exe", "python/pythonw.exe", "python/python312.dll"):
        status, wer = _signatur(paket / name)
        print(f"Signatur {name}: {status} - {wer}", flush=True)
        if status != "Valid" or PSF not in wer:
            fehler.append(f"{name} ist nicht gueltig von der {PSF} signiert ({status}, {wer})")
    for name in ("exiftool/exiftool_files/perl.exe", "lib/PySide6/Qt6Core.dll"):
        status, wer = _signatur(paket / name)
        print(f"Signatur {name} (nur zur Information): {status} - {wer or 'ohne Unterzeichner'}", flush=True)

    # -- 2. Frischer PC -----------------------------------------------------------------
    shutil.rmtree(arbeit, ignore_errors=True)
    arbeit.mkdir(parents=True)
    start_ordner = arbeit / "fotosort-windows (1)" / "fotosort"
    shutil.copytree(paket, start_ordner)
    lokal = arbeit / "Nutzer (neu)" / "AppData" / "Local"   # existiert noch nicht
    python = start_ordner / "python" / "python.exe"
    pythonw = start_ordner / "python" / "pythonw.exe"
    perl = start_ordner / "exiftool" / "exiftool_files" / "perl.exe"
    skript = start_ordner / "exiftool" / "exiftool_files" / "exiftool.pl"
    bat = start_ordner / "fotosort.bat"
    fremde_pfade = ("python", "perl", "strawberry", "exiftool", "hostedtoolcache", "chocolatey")
    umgebung = {k: v for k, v in os.environ.items() if not k.upper().startswith(("FOTOSORT_", "PYTHON", "PERL", "QT_"))}
    umgebung["PATH"] = os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep) if p and not any(f in p.lower() for f in fremde_pfade))
    umgebung["LOCALAPPDATA"] = str(lokal)
    daten_ordner = lokal / "fotosortierer"
    ob_ordner = daten_ordner / "oberflaeche"

    # -- 3. start.bat -> Fenster in 20 s, aus python\\pythonw.exe ---------------------------
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
        programm = _programm_von(int(stand.get("pid") or 0))
        print(f"Fenster erschienen nach {dauer:.1f} s (Version {stand.get('version')}, PID {stand.get('pid')}, "
              f"Programm {programm})", flush=True)
        if Path(programm or ".").resolve() != pythonw.resolve():
            fehler.append(f"Das Fenster laeuft nicht ueber python\\pythonw.exe des Pakets, sondern ueber {programm!r}")
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

    # -- 4. ExifTool direkt ueber perl.exe --------------------------------------------------
    erwartet = re.search(r"ExifTool (\d+\.\d+)", (start_ordner / "exiftool" / "VERSION.txt").read_text(encoding="utf-8"))
    rc, text = _lauf([str(perl), str(skript), "-ver"], umgebung, start_ordner, zeit=120)
    if rc != 0 or not erwartet or text.strip() != erwartet.group(1):
        fehler.append(f"perl.exe mit exiftool.pl: Rueckgabewert {rc}, Ausgabe {text.strip()!r}, erwartet {erwartet and erwartet.group(1)}")
    else:
        print(f"ExifTool {text.strip()} startet direkt ueber perl.exe (ohne Starter exiftool.exe).", flush=True)

    # -- 5. Durchlauf ueber das Fenster, mit Fensterwache ---------------------------------------
    erzeuger = dict(umgebung, FOTOSORT_EXIFTOOL=str(skript), PYTHONPATH=str(WURZEL / "src"))
    erzeuger["PATH"] = os.environ.get("PATH", "")        # der Testbaum-Erzeuger ist Werkzeug der CI
    rc, text = _lauf([sys.executable, str(WURZEL / "tests" / "testbaum.py"), str(arbeit / "baum")], erzeuger, WURZEL)
    if rc != 0:
        return _ende(fehler + ["Testbaum liess sich nicht erzeugen"])
    quelle = arbeit / "baum" / "Quelle"
    ziel_fenster = arbeit / "Ziel (Fenster)"
    ziel_fenster.mkdir()
    fotos = arbeit / "fotos"
    beweiskraft = _gegenproben()
    print({"unsichtbar": "Die Fensterwache zaehlt jedes neue Konsolenfenster, auch unsichtbare - aussagekraeftig.",
           "sichtbar": "Die Fensterwache kann nur sichtbare Konsolenfenster erkennen.",
           "": "Konsolenfenster sind in dieser Umgebung nicht beobachtbar - die Fensterwache kann hier nichts finden."}[beweiskraft],
          flush=True)
    waechter = _FensterWaechter().start()
    rc, text = _bat(bat, ["fenster", "--durchlauf", str(ziel_fenster), str(quelle), "--fotos", str(fotos)],
                    dict(umgebung, QT_QPA_PLATFORM="offscreen"), start_ordner, zeit=900)
    neue = waechter.stop()
    if rc != 0 or "Durchlauf bestanden" not in text:
        fehler.append(f"Durchlauf ueber das Fenster: Rueckgabewert {rc}")
    konsolen = waechter.konsolen(nur_sichtbare=(beweiskraft != "unsichtbar"))
    if konsolen:
        fehler.append(f"Waehrend des Durchlaufs gingen {len(konsolen)} Konsolenfenster auf: "
                      + "; ".join(f"'{t}' (PID {pid}{', sichtbar' if sichtbar else ''})" for _k, t, pid, sichtbar in konsolen[:5]))
    andere = [f for f in neue if f[0] != waechter.KONSOLE]
    print(f"Waehrend des Durchlaufs neu: {len(waechter.konsolen())} Konsolenfenster "
          f"({len(waechter.konsolen(nur_sichtbare=True))} sichtbar), {len(andere)} andere sichtbare Fenster"
          + (" (" + "; ".join(f"{k} '{t}'" for k, t, _p, _s in andere[:5]) + ")" if andere else ""), flush=True)
    bilder = sorted(fotos.glob("*.png")) if fotos.is_dir() else []
    if len(bilder) < 12:
        fehler.append(f"Durchlauf: nur {len(bilder)} Bilder statt 12")
    else:
        print(f"{len(bilder)} Bilder unter {fotos}", flush=True)
    try:
        lauf = json.loads((ob_ordner / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lauf = {}
    if Path(str(lauf.get("programm") or ".")).resolve() != pythonw.resolve():
        fehler.append(f"Die Arbeitsschritte liefen nicht ueber python\\pythonw.exe, sondern ueber {lauf.get('programm')!r}")
    else:
        print(f"Arbeitsschritte liefen ueber {lauf.get('programm')}", flush=True)

    # -- 6. fotosort.bat: Version und Befehle -------------------------------------------------
    rc, text = _bat(bat, ["--version"], umgebung, start_ordner)
    version = (start_ordner / "VERSION.txt").read_text(encoding="utf-8").split()[1]
    if rc != 0 or not re.search(rf"^fotosort {re.escape(version)}$", text, re.M):
        fehler.append(f"--version nennt nicht fotosort {version}")
    if not re.search(r"^ExifTool \d+\.\d+ \(.*exiftool\.pl \(im Programmordner mitgeliefert, gestartet ueber perl\.exe\)\)", text, re.M):
        fehler.append("--version: ExifTool laeuft nicht ueber perl.exe aus dem Programmordner")
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
    for argumente, erwartet_text in schritte:
        rc, text = _bat(bat, argumente, umgebung, start_ordner)
        if rc != 0:
            fehler.append(f"{argumente[0]}: Rueckgabewert {rc}")
        if erwartet_text not in text:
            fehler.append(f"{argumente[0]}: '{erwartet_text}' fehlt in der Ausgabe")
    if not any(p.is_file() and ".fotosortierer" not in p.parts for p in ziel.rglob("*")):
        fehler.append("im Ziel liegen keine kopierten Dateien")

    # -- 7. Ein Schritt als Arbeitsprozess, gestartet wie vom Fenster --------------------------------
    auftrag = arbeit / "auftrag.json"
    status = arbeit / "status.json"
    auftrag.write_text(json.dumps({
        "schritt": "scan", "ziel": str(ziel), "quellen": [], "ziel_anlegen": False,
        "status_datei": str(status), "steuer_datei": str(arbeit / "steuer.json"),
    }), encoding="utf-8")
    rc, text = _lauf([str(pythonw), "-X", "utf8", "-m", "fotosort", "arbeit", "--auftrag", str(auftrag)],
                     umgebung, start_ordner)
    try:
        stand = json.loads(status.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stand = {}
    if rc != 0 or stand.get("zustand") != "fertig" or not stand.get("dateien"):
        fehler.append(f"Arbeitsprozess ueber pythonw.exe: Rueckgabewert {rc}, Stand {stand}")
    if not daten_ordner.is_dir():
        fehler.append("Nutzerdatenordner wurde nicht angelegt")
    return _ende(fehler)


def _ende(fehler: list[str], nur_inhalt: bool = False) -> int:
    if fehler:
        print("PAKETPRUEFUNG FEHLGESCHLAGEN:")
        for f in fehler:
            print("  -", f)
        return 1
    if nur_inhalt:
        print("PAKETINHALT IN ORDNUNG: nur das signierte Python und perl.exe als Programme, Qt gekuerzt, "
              "alle Bibliotheken vorhanden.")
        return 0
    print("PAKETPRUEFUNG BESTANDEN: signiertes Python, Fenster ueber pythonw.exe aus einem Ordner mit Leerzeichen, "
          "ExifTool direkt ueber perl.exe, Durchlauf ueber das Fenster ohne Konsolenfenster, Befehle und "
          "Arbeitsprozess laufen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
