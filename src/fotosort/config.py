"""config.toml lesen und beim ersten Start erzeugen (SPEC Abschnitt 6 und 9).

tomli-w kann keine Kommentare schreiben. Die kommentierte Datei entsteht
deshalb aus der Vorlage _VORLAGE in diesem Modul, in der Kommentartext und
Wert je Schluessel nebeneinander stehen. Aus derselben Vorlage kommen die
Standardwerte, die beim Lesen im Speicher ergaenzt werden - so koennen Datei
und Programm nicht auseinanderlaufen.

Eine vorhandene Datei wird nie ueberschrieben und nie umgeschrieben.
"""

from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from . import FotosortFehler, meldungen

DATEINAME = "config.toml"

# Die Alias-Tabelle steht als fertiger Textblock hier, weil SPEC Abschnitt 9
# genau diese Zeilen verlangt - nicht mehr und nicht weniger.
_ALIASE: dict[str, str] = {
    "ILCE-7CM2": "A7C2",
    "ILCE-7C": "A7C",
    "Noritsu Koki QSS-32_33": "Analog",
    "Noritsu Koki EZ Controller": "Analog",
    "SP-3000": "Analog",
    "Frontier SP-3000": "Analog",
    "Frontier SP-500": "Analog",
    "EPSON Perfection V600": "Analog",
    "EPSON Perfection V800": "Analog",
    "EPSON Perfection V850": "Analog",
    "PLUSTEK OpticFilm 8200i": "Analog",
    "PLUSTEK OpticFilm 120": "Analog",
}

_ALIASE_BLOCK = """[kamera.aliase]
"ILCE-7CM2" = "A7C2"
"ILCE-7C"   = "A7C"
# Scanner zaehlen als Analog-Material
"Noritsu Koki QSS-32_33"      = "Analog"
"Noritsu Koki EZ Controller"  = "Analog"
"SP-3000"                     = "Analog"
"Frontier SP-3000"            = "Analog"
"Frontier SP-500"             = "Analog"
"EPSON Perfection V600"       = "Analog"
"EPSON Perfection V800"       = "Analog"
"EPSON Perfection V850"       = "Analog"
"PLUSTEK OpticFilm 8200i"     = "Analog"
"PLUSTEK OpticFilm 120"       = "Analog"
"""

# (Gruppe, Kopfkommentar, [(Schluessel, Kommentar, Standardwert)])
_VORLAGE: list[tuple[str, str, list[tuple[str, str, Any]]]] = [
    (
        "ordner",
        "Wie die Zielordner gebildet werden.",
        [
            (
                "vorlage",
                "Ordner-Vorlage fuer Dateien mit Datum.",
                "{jahr}/{jahr}-{monat} {monatsname}/{jahr}-{monat}-{tag}/{kamera}",
            ),
            (
                "vorlage_ohne_datum",
                "Ordner-Vorlage fuer Dateien ohne verwertbares Datum.",
                "_Ohne_Datum/{kamera}",
            ),
        ],
    ),
    (
        "datum",
        "Wie das Aufnahmedatum gelesen und umgerechnet wird.",
        [
            (
                "heimat_zeitzone",
                "Zeitzone, in die Video-Zeiten ohne Offset aus UTC umgerechnet werden.",
                "Europe/Berlin",
            ),
            (
                "tagesgrenze",
                'Uhrzeit, ab der ein neuer Tagesordner beginnt; "04:00" zaehlt\n'
                "# Aufnahmen bis 04:00 noch zum Vortag.",
                "00:00",
            ),
            (
                "unsicheres_datum",
                "Was mit einem unsicheren Datum geschieht (nur Aenderungsdatum der\n"
                '# Datei). Erlaubt: "ohne_datum" oder "mtime".',
                "ohne_datum",
            ),
        ],
    ),
    (
        "kamera",
        "Kameramodell zu Ordnername.",
        [
            (
                "unbekannt",
                "Ordnername, wenn kein Kameramodell gefunden wurde.",
                "Unbekannte_Kamera",
            ),
        ],
    ),
    (
        "dateitypen",
        "Welche Endungen als was gelten. Gross- und Kleinschreibung egal.",
        [
            (
                "foto",
                "Endungen, die als Foto gelten.",
                ["jpg", "jpeg", "heic", "hif", "png", "tif", "tiff", "webp"],
            ),
            (
                "raw",
                "Endungen, die als RAW gelten.",
                ["arw", "cr2", "cr3", "nef", "dng", "raf", "orf", "rw2", "srw"],
            ),
            (
                "video",
                "Endungen, die als Video gelten.",
                ["mp4", "mov", "mts", "m2ts", "avi", "mkv"],
            ),
            (
                "sidecar",
                "Endungen, die als Sidecar gelten; eigener Dateityp, nie\n"
                '# "uebersprungen nach Typ".',
                ["xmp", "dop", "pp3", "thm", "aae", "xml"],
            ),
            (
                "sidecar_zusatzmuster",
                "Glob-Muster fuer die dritte Sidecar-Form, den Zusatz zwischen\n"
                "# Stammname und Endung (C0001M01.XML zu C0001.MP4).",
                ["M[0-9][0-9]"],
            ),
        ],
    ),
    (
        "quelle",
        "Was der Scan in der Quelle ueberspringt.",
        [
            (
                "ausschlussmuster",
                "Glob-Muster fuer Pfade in der Quelle, die der Scan ueberspringt.\n"
                "# Verglichen wird gegen den Pfad relativ zur Quellwurzel, mit\n"
                "# Schraegstrich als Trenner, Gross- und Kleinschreibung egal.\n"
                '# Beispiel: ["*/Papierkorb/*"]',
                [],
            ),
            (
                "verknuepfungen_folgen",
                "Ob der Scan Ordner-Verknuepfungen (Symlinks, Junctions) verfolgt.",
                False,
            ),
        ],
    ),
    (
        "sicherheit",
        "Zusaetzliche Sicherungen.",
        [
            (
                "byte_vergleich_vor_loeschen",
                "Zusaetzlich zum Hash-Vergleich vor dem Loeschen Byte fuer Byte\n"
                "# vergleichen.",
                False,
            ),
        ],
    ),
    (
        "datenbank",
        "Wo die Datenbank liegt.",
        [
            (
                "datenbank_ort",
                "Ordner, unter dem die Archiv-Ordner angelegt werden; leer bedeutet\n"
                "# Standardpfad des Betriebssystems. Vorrang: FOTOSORT_DATENBANK vor\n"
                "# datenbank_ort vor Standardpfad. Wirkt nur aus einer mit --config\n"
                "# angegebenen Datei. Nie ein Netzlaufwerk.",
                "",
            ),
        ],
    ),
    (
        "aufraeumen",
        "Leere Ordner entfernen.",
        [
            (
                "reste_dateien",
                'Dateinamen, die beim Entfernen leerer Ordner als "zaehlt als leer"\n'
                "# gelten. Ein Name allein genuegt nicht: Steht die Datei mit echtem\n"
                "# Dateityp in der Datenbank, wird sie nicht geloescht.",
                ["Thumbs.db", ".DS_Store", "desktop.ini"],
            ),
        ],
    ),
    (
        "leistung",
        "Geschwindigkeit. 0 bedeutet automatisch.",
        [
            (
                "profil",
                'Grobe Voreinstellung fuer die Worker-Zahlen. Erlaubt: "hdd",\n'
                '# "ssd", "netzwerk".',
                "hdd",
            ),
            (
                "metadaten_prozesse",
                "Anzahl dauerhaft laufender ExifTool-Prozesse. 0 = Anzahl Kerne.",
                0,
            ),
            (
                "kopier_worker",
                "Anzahl gleichzeitiger Kopiervorgaenge. 0 = automatisch nach Profil\n"
                "# (hdd 2, netzwerk 4, ssd 8).",
                0,
            ),
            (
                "hash_worker",
                "Anzahl gleichzeitiger Hash-Berechnungen. 0 = Anzahl Kerne.",
                0,
            ),
            (
                "exiftool_pfad",
                "Pfad zum ExifTool-Programm; leer bedeutet ueber PATH suchen.\n"
                "# Vorrang: FOTOSORT_EXIFTOOL vor exiftool_pfad vor PATH.",
                "",
            ),
        ],
    ),
]


def _standard_aus_vorlage() -> dict[str, Any]:
    fertig: dict[str, Any] = {}
    for gruppe, _kopf, eintraege in _VORLAGE:
        fertig[gruppe] = {
            name: (list(wert) if isinstance(wert, list) else wert)
            for name, _kommentar, wert in eintraege
        }
    fertig["kamera"]["aliase"] = dict(_ALIASE)
    return fertig


#: Alle Standardwerte, verschachtelt nach Gruppen (SPEC Abschnitt 9).
STANDARD: dict[str, Any] = _standard_aus_vorlage()


def _toml_wert(wert: Any) -> str:
    """Ein einzelner TOML-Wert; das Schreiben uebernimmt tomli-w."""
    if isinstance(wert, list):
        return "[" + ", ".join(_toml_wert(e) for e in wert) + "]"
    text = tomli_w.dumps({"x": wert}).rstrip("\n")
    return text[len("x = ") :]


def _toml_zeile(name: str, wert: Any) -> str:
    """Eine gueltige TOML-Zeile; kurze Listen bleiben einzeilig."""
    return f"{name} = {_toml_wert(wert)}"


def vorlage_text() -> str:
    """Die vollstaendige, kommentierte config.toml als Text."""
    zeilen: list[str] = [
        "# Konfiguration des Foto-Sortierers.",
        "#",
        "# Diese Datei wird vom Programm nie umgeschrieben. Fehlende Werte",
        "# werden beim Lesen im Speicher mit den Standardwerten ergaenzt.",
        "# Unbekannte Werte bleiben stehen und werden einmal je Lauf gemeldet.",
        "",
    ]
    for gruppe, kopf, eintraege in _VORLAGE:
        zeilen.append(f"# {kopf}")
        zeilen.append(f"[{gruppe}]")
        for name, kommentar, wert in eintraege:
            for stueck in kommentar.split("\n"):
                zeilen.append(stueck if stueck.startswith("#") else f"# {stueck}")
            zeilen.append(_toml_zeile(name, wert))
            zeilen.append("")
        if gruppe == "kamera":
            zeilen.append("# Modellname zu Ordnername. Nach dem Scan zeigt das Programm")
            zeilen.append("# alle gefundenen Modelle mit Anzahl; fehlende Zuordnungen")
            zeilen.append("# traegt man hier selbst nach.")
            zeilen.append(_ALIASE_BLOCK.rstrip("\n"))
            zeilen.append("")
    return "\n".join(zeilen).rstrip("\n") + "\n"


class Konfiguration:
    """Die geltenden Werte - Datei plus ergaenzte Standardwerte."""

    def __init__(
        self,
        werte: dict[str, Any] | None = None,
        unbekannte: list[str] | None = None,
        pfad: Path | None = None,
        aus_datei: bool = False,
    ) -> None:
        self._werte: dict[str, Any] = werte if werte is not None else _standard_aus_vorlage()
        self.unbekannte: list[str] = unbekannte or []
        self.pfad: Path | None = pfad
        self.aus_datei: bool = aus_datei

    def wert(self, pfad: str, /) -> Any:
        """konf.wert("ordner.vorlage")."""
        stelle: Any = self._werte
        for stueck in pfad.split("."):
            if not isinstance(stelle, dict) or stueck not in stelle:
                raise KeyError(f"Unbekannter Konfigurationswert: {pfad}")
            stelle = stelle[stueck]
        return stelle

    def alle(self) -> dict[str, Any]:
        return self._werte


def erzeugen(pfad: Path) -> None:
    """Kommentierte config.toml anlegen. Eine vorhandene bleibt unberuehrt."""
    pfad = Path(pfad)
    if pfad.exists():
        return
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(vorlage_text(), encoding="utf-8")


# Wie die Art eines Wertes auf Deutsch heisst.
_ARTEN: list[tuple[type, str]] = [
    (bool, "Wahrheitswert (true oder false)"),
    (int, "Zahl"),
    (float, "Zahl"),
    (str, "Zeichenkette (in Anfuehrungszeichen)"),
    (list, "Liste (in eckigen Klammern)"),
    (dict, "Tabelle"),
]


def _art(wert: Any) -> str:
    for typ, name in _ARTEN:
        if isinstance(wert, typ):
            return name
    return type(wert).__name__


def _passt(wert: Any, standard: Any) -> bool:
    """Hat der Wert dieselbe Art wie der Standardwert?

    Streng, weil zwei falsche Arten die Bedeutung umkehren: Eine
    Zeichenkette statt einer Liste wird Zeichen fuer Zeichen gelesen - das
    Muster "*" darin trifft dann alles -, und aus "nein" wird als
    Wahrheitswert ein Ja.
    """
    if isinstance(standard, bool):
        return isinstance(wert, bool)
    if isinstance(standard, int):
        return isinstance(wert, int) and not isinstance(wert, bool)
    if isinstance(standard, str):
        return isinstance(wert, str)
    if isinstance(standard, list):
        return isinstance(wert, list)
    if isinstance(standard, dict):
        return isinstance(wert, dict)
    return True


def _zusammenfuehren(
    datei: dict[str, Any], pfad: Path | None = None
) -> tuple[dict[str, Any], list[str]]:
    werte = _standard_aus_vorlage()
    unbekannte: list[str] = []
    for gruppe, inhalt in datei.items():
        if gruppe not in werte or not isinstance(werte[gruppe], dict):
            unbekannte.append(gruppe)
            continue
        if not isinstance(inhalt, dict):
            unbekannte.append(gruppe)
            continue
        for name, wert in inhalt.items():
            if name not in werte[gruppe]:
                unbekannte.append(f"{gruppe}.{name}")
                continue
            if gruppe == "kamera" and name == "aliase":
                # Freie Tabelle: jeder Modellname ist erlaubt.
                if not isinstance(wert, dict):
                    raise FotosortFehler(
                        meldungen.config_falscher_typ(
                            f"{gruppe}.{name}", _art(wert), _art({}), pfad
                        )
                    )
                werte[gruppe][name] = dict(wert)
                continue
            if not _passt(wert, werte[gruppe][name]):
                raise FotosortFehler(
                    meldungen.config_falscher_typ(
                        f"{gruppe}.{name}", _art(wert), _art(werte[gruppe][name]), pfad
                    )
                )
            werte[gruppe][name] = wert
    return werte, unbekannte


def laden(pfad: Path) -> Konfiguration:
    """Konfiguration lesen. Die Datei wird dabei nie angefasst."""
    pfad = Path(pfad)
    if not pfad.exists():
        return Konfiguration(pfad=pfad, aus_datei=False)
    try:
        with open(pfad, "rb") as fh:
            datei = tomllib.load(fh)
    except tomllib.TOMLDecodeError as fehler:
        zeile, spalte = _stelle(fehler)
        raise FotosortFehler(
            meldungen.config_kaputt(pfad, zeile, spalte, str(fehler))
        ) from fehler
    werte, unbekannte = _zusammenfuehren(datei, pfad)
    return Konfiguration(werte=werte, unbekannte=unbekannte, pfad=pfad, aus_datei=True)


def _stelle(fehler: Exception) -> tuple[int | None, int | None]:
    """Zeile und Spalte aus der Fehlermeldung von tomllib herausziehen."""
    treffer = re.search(r"line (\d+), column (\d+)", str(fehler))
    if not treffer:
        return None, None
    return int(treffer.group(1)), int(treffer.group(2))


def aus_ziel_uebernehmen(ziel: Path, nach: Path) -> bool:
    """Erster Start auf einem neuen Rechner (SPEC Abschnitt 6).

    Liegt lokal noch keine config.toml, aber eine im Ziel unter
    .fotosortierer/, wird diese uebernommen. Gibt True zurueck, wenn das
    geschehen ist.
    """
    nach = Path(nach)
    if nach.exists():
        return False
    im_ziel = Path(ziel) / ".fotosortierer" / DATEINAME
    if not im_ziel.is_file():
        return False
    nach.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(im_ziel, nach)
    return True


def _zeilenkommentar(zeile: str, schluessel: str) -> str:
    """Der Kommentar am Ende einer TOML-Zeile (mit fuehrendem Leerraum),
    sonst leer. Ein '#' innerhalb des Wertes zaehlt nicht."""
    for i, zeichen in enumerate(zeile):
        if zeichen != "#":
            continue
        try:
            if schluessel in tomllib.loads(zeile[:i]):
                return " " + zeile[i:].rstrip("\r\n")
        except tomllib.TOMLDecodeError:
            continue
    return ""


def aliase_ergaenzen(pfad: Path, neue: dict[str, str]) -> None:
    """Alias-Zeilen in die Tabelle [kamera.aliase] der config.toml eintragen.

    Der einzige Fall, in dem das Programm die Konfigurationsdatei anfasst -
    und nur, weil der Nutzer es im gefuehrten Modus ausdruecklich verlangt
    hat. Kommentare und alle anderen Zeilen bleiben unveraendert. Ein schon
    vorhandener Alias fuer dasselbe Modell wird ersetzt. Geschrieben wird
    erst, wenn das Ergebnis als TOML gueltig ist und die neuen Werte darin
    stehen; sonst bleibt die Datei, wie sie war.
    """
    import os
    pfad = Path(pfad)
    if not neue:
        return
    text = pfad.read_text(encoding="utf-8") if pfad.exists() else vorlage_text()
    zeilen = text.splitlines(keepends=True)
    if zeilen and not zeilen[-1].endswith("\n"):
        zeilen[-1] += "\n"
    kopf = next((i for i, z in enumerate(zeilen) if z.strip() == "[kamera.aliase]"), None)
    if kopf is None:
        zeilen += ["\n", "[kamera.aliase]\n"]
        kopf = len(zeilen) - 1
    ende = len(zeilen)
    for j in range(kopf + 1, len(zeilen)):
        if zeilen[j].lstrip().startswith("["):
            ende = j
            break
    # Vorhandene Eintraege fuer dieselben Modelle ersetzen (Vergleich ohne
    # Gross-/Kleinschreibung, so wie kamera.py die Tabelle liest).
    rest = dict(neue)
    for j in range(kopf + 1, ende):
        try:
            paar = tomllib.loads(zeilen[j])
        except tomllib.TOMLDecodeError:
            continue
        for schluessel in list(paar):
            for modell in list(rest):
                if schluessel.strip().lower() == modell.strip().lower():
                    kommentar = _zeilenkommentar(zeilen[j], schluessel)
                    zeilen[j] = f"{_toml_wert(modell)} = {_toml_wert(rest.pop(modell))}{kommentar}\n"
    while ende > kopf + 1 and zeilen[ende - 1].strip() == "":
        ende -= 1
    zeilen[ende:ende] = [f"{_toml_wert(k)} = {_toml_wert(v)}\n" for k, v in rest.items()]
    neu = "".join(zeilen)
    try:
        geparst = tomllib.loads(neu)
    except tomllib.TOMLDecodeError as fehler:
        raise FotosortFehler(meldungen.config_alias_nicht_geschrieben(pfad, next(iter(neue)))) from fehler
    tabelle = geparst.get("kamera", {}).get("aliase", {})
    for modell, name in neue.items():
        if tabelle.get(modell) != name:
            raise FotosortFehler(meldungen.config_alias_nicht_geschrieben(pfad, modell))
    pfad.parent.mkdir(parents=True, exist_ok=True)
    vorlaeufig = pfad.with_name(pfad.name + ".neu")
    vorlaeufig.write_text(neu, encoding="utf-8")
    os.replace(vorlaeufig, pfad)
