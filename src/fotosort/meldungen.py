"""Alle deutschen Texte an einer Stelle (docs/architektur.md Abschnitt 1).

Jede Funktion gibt einen fertigen String zurueck. Kein Modul ausserhalb dieser
Datei formuliert eigene Texte fuer den Nutzer.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- Zahlen ----


def anzahl(n: int) -> str:
    """1234 -> "1.234" (Punkt als Tausendertrenner)."""
    return f"{int(n):,}".replace(",", ".")


def groesse(bytes_: int) -> str:
    """1288490189 -> "1,2 GB" (Komma als Dezimaltrenner)."""
    wert = float(bytes_)
    if wert < 1024:
        return f"{int(wert)} B"
    for einheit in ("KB", "MB", "GB", "TB", "PB"):
        wert /= 1024.0
        if wert < 1024 or einheit == "PB":
            return f"{wert:.1f}".replace(".", ",") + f" {einheit}"
    raise AssertionError("unerreichbar")


def dauer(sekunden: float) -> str:
    sekunden = max(0.0, float(sekunden))
    if sekunden < 60:
        return f"{sekunden:.1f}".replace(".", ",") + " s"
    minuten, rest = divmod(int(sekunden), 60)
    stunden, minuten = divmod(minuten, 60)
    if stunden:
        return f"{stunden} h {minuten} min {rest} s"
    return f"{minuten} min {rest} s"


def durchsatz(dateien: int, bytes_: int, sekunden: float) -> str:
    if sekunden <= 0:
        sekunden = 0.001
    pro_sekunde = dateien / sekunden
    mb_pro_sekunde = (bytes_ / 1024 / 1024) / sekunden
    d = f"{pro_sekunde:.1f}".replace(".", ",")
    m = f"{mb_pro_sekunde:.1f}".replace(".", ",")
    return f"{d} Dateien/s, {m} MB/s"


# ------------------------------------------------------------- ExifTool ----


def exiftool_fehlt(gesucht: str = "") -> str:
    """Harter Abbruch, wenn ein Befehl Metadaten braucht (SPEC Abschnitt 2)."""
    wo = gesucht or "ueber PATH"
    return (
        "ExifTool wurde nicht gefunden.\n"
        f"Gesucht wurde: {wo}\n"
        "Ohne ExifTool gibt es weder Aufnahmedatum noch Kamera; alle Dateien\n"
        "landeten unter _Ohne_Datum/Unbekannte_Kamera. Deshalb wird gar nicht\n"
        "erst angefangen.\n"
        "So laesst sich der Pfad setzen:\n"
        "  1. Umgebungsvariable FOTOSORT_EXIFTOOL\n"
        "  2. Konfigurationswert exiftool_pfad in der Gruppe [leistung]\n"
        "Zu beziehen ist ExifTool unter https://exiftool.org"
    )


def exiftool_hinweis(gesucht: str = "") -> str:
    """Weicher Hinweis fuer Befehle, die ohne ExifTool auskommen."""
    wo = gesucht or "ueber PATH"
    return (
        f"Hinweis: ExifTool wurde nicht gefunden (gesucht: {wo}).\n"
        "Dieser Befehl braucht es nicht, aber die Analyse wird ohne ExifTool\n"
        "nicht laufen. Pfad setzbar ueber FOTOSORT_EXIFTOOL oder den\n"
        "Konfigurationswert exiftool_pfad in der Gruppe [leistung]."
    )


# ------------------------------------------------- Lage Quelle und Ziel ----


def quelle_gleich_ziel(pfad) -> str:
    return (
        "Abbruch: Quelle und Ziel sind derselbe Ordner.\n"
        f"  {pfad}\n"
        "Das Programm wuerde Dateien in sich selbst einsortieren. Bitte ein\n"
        "anderes Ziel angeben."
    )


def ziel_in_quelle(ziel) -> str:
    return (
        "Das Ziel liegt innerhalb der Quelle:\n"
        f"  {ziel}\n"
        "Der Zielordner wird vom Scan ausgeschlossen. Der Lauf geht weiter."
    )


def quelle_in_ziel(quelle) -> str:
    return (
        "Abbruch: Die Quelle liegt innerhalb des Ziels.\n"
        f"  {quelle}\n"
        "Das Programm wuerde bereits einsortierte Bilder noch einmal einlesen.\n"
        "Bitte eine Quelle ausserhalb des Ziels angeben."
    )


def datei_zeigt_ins_ziel(pfad) -> str:
    return f"Uebersprungen, weil der Pfad ins Ziel zeigt: {pfad}"


# ------------------------------------------------------------ Datenbank ----


def datenbank_auf_netzlaufwerk(pfad, typ) -> str:
    art = typ if typ else "unbekannt"
    return (
        "Abbruch: Die Datenbank soll auf einem Netzlaufwerk liegen.\n"
        f"  {pfad}\n"
        f"  Dateisystem: {art}\n"
        "Die Datenbank muss immer auf einer lokalen Platte liegen. Ueber das\n"
        "Netz sind die Dateisperren unzuverlaessig; die Datenbank koennte\n"
        "beschaedigt werden, und sie ist das Gedaechtnis des Archivs.\n"
        "Anderer Ort: Umgebungsvariable FOTOSORT_DATENBANK oder der\n"
        "Konfigurationswert datenbank_ort in der Gruppe [datenbank]."
    )


def datenbank_fehlt_sicherung_da(ziel) -> str:
    return (
        "Abbruch: Zu diesem Ziel gibt es eine Archiv-Kennung, aber die lokale\n"
        "Datenbank fehlt. Im Ziel liegt eine Sicherungskopie:\n"
        f"  {ziel}\n"
        "Bitte zuerst zurueckholen mit:\n"
        "  fotosort wiederherstellen --ziel <Ziel>\n"
        "Es wird jetzt keine leere Datenbank angelegt - das Ziel wuerde sonst\n"
        "als leer gelten und alles noch einmal kopiert."
    )


def datenbank_fehlt_keine_sicherung(ziel) -> str:
    return (
        "Abbruch: Zu diesem Ziel gibt es eine Archiv-Kennung, aber weder eine\n"
        "lokale Datenbank noch eine Sicherungskopie im Ziel:\n"
        f"  {ziel}\n"
        "Hier hilft nur der vollstaendige Neuaufbau:\n"
        "  fotosort ziel-index --neu-aufbauen --ziel <Ziel>\n"
        "Es wird jetzt keine leere Datenbank angelegt - das Ziel wuerde sonst\n"
        "als leer gelten und alles noch einmal kopiert."
    )


def datenbank_gesichert(pfad) -> str:
    return f"Sicherungskopie der Datenbank geschrieben: {pfad}"


# ------------------------------------------------------------ Archiv-ID ----


def archiv_id_kaputt(pfad, inhalt) -> str:
    gezeigt = str(inhalt).strip()
    if len(gezeigt) > 120:
        gezeigt = gezeigt[:120] + " ..."
    return (
        "Abbruch: Die Archiv-Kennung des Ziels ist unlesbar.\n"
        f"  Datei:  {pfad}\n"
        f"  Inhalt: {gezeigt!r}\n"
        "Erwartet werden genau 32 Zeichen aus 0-9 und a-f.\n"
        "Es wird bewusst keine neue Kennung erzeugt: Eine neue Kennung zeigte\n"
        "auf eine neue, leere Datenbank; das Programm hielte das Ziel fuer\n"
        "leer und kopierte alles noch einmal."
    )


def archiv_id_angelegt(archiv_id, pfad) -> str:
    return f"Neue Archiv-Kennung angelegt: {archiv_id}\n  in {pfad}"


def archiv_id_fehlt(ziel) -> str:
    return (
        "Abbruch: In diesem Ziel gibt es noch kein Archiv.\n"
        f"  {ziel}\n"
        "Ein Archiv entsteht beim ersten Scan:\n"
        "  fotosort scan --quelle <Quelle> --ziel <Ziel>"
    )


# -------------------------------------------------------- Konfiguration ----


def config_erzeugt(pfad) -> str:
    return f"Neue Konfiguration mit Standardwerten angelegt: {pfad}"


def config_aus_ziel_uebernommen(pfad) -> str:
    return (
        "Die Konfiguration aus dem Ziel wurde uebernommen, statt eine neue\n"
        f"anzulegen: {pfad}"
    )


def config_unbekannte_werte(namen: list[str], pfad) -> str:
    liste = ", ".join(str(n) for n in namen)
    return (
        f"Hinweis: In der Konfiguration stehen unbekannte Werte: {liste}\n"
        f"  {pfad}\n"
        "Sie bleiben unangetastet stehen und wirken nicht. Meist ist es ein\n"
        "Tippfehler im Schluesselnamen."
    )


def config_datenbank_ort_ignoriert(pfad) -> str:
    return (
        "Hinweis: Der Wert datenbank_ort steht in der Konfiguration im\n"
        f"Archiv-Ordner selbst und wird ignoriert: {pfad}\n"
        "Der Ordner ist an dieser Stelle bereits gefunden; die Konfiguration\n"
        "kann ihn nicht selbst verschieben. Wirksam ist er nur aus einer mit\n"
        "--config angegebenen Datei."
    )


def editor_nicht_gefunden(pfad) -> str:
    return (
        "Es konnte kein Editor geoeffnet werden. Die Datei laesst sich von\n"
        f"Hand oeffnen: {pfad}"
    )


# -------------------------------------------------------------- Aufrufe ----


def ziel_fehlt() -> str:
    return (
        "Es fehlt die Angabe des Ziels.\n"
        "  fotosort <befehl> --ziel <Zielordner>\n"
        "Ersatzweise laesst sich das Ziel in der Umgebungsvariablen\n"
        "FOTOSORT_ZIEL hinterlegen; --ziel hat Vorrang."
    )


def quelle_fehlt() -> str:
    return (
        "Es fehlt die Angabe der Quelle.\n"
        "  fotosort scan --quelle <Quellordner> --ziel <Zielordner>\n"
        "Nur der Scan braucht die Quelle; sie wird in der Datenbank gemerkt."
    )


def quelle_existiert_nicht(pfad) -> str:
    return f"Abbruch: Diesen Quellordner gibt es nicht:\n  {pfad}"


def ziel_existiert_nicht(pfad) -> str:
    return f"Abbruch: Diesen Zielordner gibt es nicht:\n  {pfad}"


def noch_nicht_gebaut(befehl, phase: int) -> str:
    return (
        f"Der Befehl „{befehl}“ ist noch nicht gebaut. Er kommt in Phase {phase}.\n"
        "Fertig sind bisher: scan, status und config."
    )


# ----------------------------------------------------------------- Scan ----


def scan_beginnt(quelle, ziel) -> str:
    return f"Scan laeuft.\n  Quelle: {quelle}\n  Ziel:   {ziel}"


def scan_laeuft(gefunden: int) -> str:
    return f"{anzahl(gefunden)} Dateien gefunden"


def scan_abgebrochen() -> str:
    return (
        "Abgebrochen. Das Bisherige ist gespeichert; ein neuer Scan derselben\n"
        "Quelle macht genau dort weiter."
    )


def scan_ergebnis(
    dateien: int,
    bytes_: int,
    je_typ: dict[str, int],
    sekunden: float,
) -> str:
    zeilen = [
        "",
        "Ergebnis des Scans",
        f"  Dateien gesamt:  {anzahl(dateien)}",
        f"  Gesamtgroesse:   {groesse(bytes_)}",
        "  Aufteilung nach Typ:",
    ]
    for typ in ("foto", "raw", "video", "sidecar", "sonstiges"):
        zeilen.append(f"    {typ:<10} {anzahl(je_typ.get(typ, 0)):>12}")
    zeilen.append(f"  Dauer:           {dauer(sekunden)}")
    zeilen.append(f"  Durchsatz:       {durchsatz(dateien, bytes_, sekunden)}")
    return "\n".join(zeilen)


def scan_besonderheiten(
    neu: int,
    unveraendert: int,
    veraendert: int,
    verschwunden: int,
    ausgeschlossen: int,
    verknuepfungen: int,
    ins_ziel: int,
    fehler: int,
    ordner_nicht_lesbar: int = 0,
    verschwunden_ausgewertet: bool = True,
) -> str:
    zeilen = ["", "Dazu im Einzelnen"]
    zeilen.append(f"  neu aufgenommen:              {anzahl(neu)}")
    zeilen.append(f"  unveraendert uebernommen:     {anzahl(unveraendert)}")
    zeilen.append(f"  veraendert, neu einzuordnen:  {anzahl(veraendert)}")
    if verschwunden_ausgewertet:
        zeilen.append(f"  Quelle nicht mehr vorhanden:  {anzahl(verschwunden)}")
    else:
        zeilen.append("  Quelle nicht mehr vorhanden:  nicht geprueft")
    zeilen.append(f"  nach Muster ausgeschlossen:   {anzahl(ausgeschlossen)}")
    zeilen.append(f"  Verknuepfungen nicht verfolgt:{anzahl(verknuepfungen):>6}")
    zeilen.append(f"  zeigt ins Ziel, uebersprungen:{anzahl(ins_ziel):>6}")
    zeilen.append(f"  nicht lesbar (Fehler):        {anzahl(fehler)}")
    zeilen.append(f"  Ordner nicht lesbar:          {anzahl(ordner_nicht_lesbar)}")
    return "\n".join(zeilen)


def scan_ordner_nicht_lesbar(anzahl_ordner: int, beispiele: list) -> str:
    """Mindestens ein Ordner liess sich nicht oeffnen (SPEC Abschnitt 4 Phase 1).

    Das ist der Windows-Langpfad- und der Netzlaufwerk-Aussetzer-Fall. Der
    Scan hat dann nicht alles gesehen; das muss der Nutzer erfahren.
    """
    satz = (
        "1 Ordner liess sich nicht oeffnen"
        if anzahl_ordner == 1
        else f"{anzahl(anzahl_ordner)} Ordner liessen sich nicht oeffnen"
    )
    zeilen = [
        "",
        f"Achtung: {satz}.",
        "Was darin liegt, ist nicht erfasst worden. Der Scan ist damit nicht",
        "vollstaendig.",
    ]
    for pfad in beispiele:
        zeilen.append(f"  {pfad}")
    if len(beispiele) < anzahl_ordner:
        zeilen.append(f"  ... und {anzahl(anzahl_ordner - len(beispiele))} weitere")
    zeilen.append("Haeufige Ursachen: fehlende Leserechte, ein Netzlaufwerk mit")
    zeilen.append("kurzem Aussetzer, oder ein zu langer Pfad.")
    zeilen.append("Die Liste \u201eQuelle nicht mehr vorhanden\u201c wird deshalb nicht")
    zeilen.append("ausgewertet: Dateien in einem ungelesenen Ordner gelten sonst")
    zeilen.append("faelschlich als verschwunden.")
    return "\n".join(zeilen)


def scan_alles_ausgeschlossen(muster: list) -> str:
    """Die Ausschlussmuster haben die ganze Quelle getroffen."""
    liste = ", ".join(repr(str(m)) for m in muster)
    return (
        "Achtung: Es ist keine einzige Datei uebrig geblieben - die\n"
        f"Ausschlussmuster treffen die gesamte Quelle: {liste}\n"
        "Zu pruefen ist der Wert ausschlussmuster in der Gruppe [quelle]."
    )


# --------------------------------------------------------------- Status ----

# Reihenfolge der Stufen aus SPEC Abschnitt 8; die uebrigen Status sind
# Abzweigungen und zaehlen fuer die Phase nicht mit.
PHASE_JE_STATUS: dict[str, tuple[int, str]] = {
    "gefunden": (2, "Analyse offen"),
    "analysiert": (3, "Kopieren offen"),
    "kopieren_laeuft": (3, "Kopieren offen (ein Lauf wurde abgebrochen)"),
    "kopiert": (4, "Pruefen offen"),
    "geprueft": (5, "Quelle aufraeumen offen"),
    "quelle_geloescht": (6, "Leere Ordner entfernen offen"),
}


def status_phase(niedrigster: str | None, dateien_erfasst: bool = False) -> str:
    """Die aktuelle Phase (SPEC Abschnitt 8).

    Steht keine Datei in einer Stufe, haengt der Klammerzusatz davon ab, ob
    ueberhaupt schon Dateien erfasst sind: Stehen alle Zeilen in einem
    Abzweig-Status (uebersprungen, fehler ...), sind sie sehr wohl erfasst.
    """
    if niedrigster is None:
        if dateien_erfasst:
            return (
                "Aktuelle Phase: 1 - Scan offen (erfasste Dateien stehen alle in\n"
                "einem Status, der keine Stufe ist - etwa uebersprungen oder fehler)"
            )
        return "Aktuelle Phase: 1 - Scan offen (es sind noch keine Dateien erfasst)"
    phase, text = PHASE_JE_STATUS[niedrigster]
    return f"Aktuelle Phase: {phase} - {text}"


def status_zaehler(zaehler: dict[str, int]) -> str:
    zeilen = ["Dateien je Status"]
    for name, wert in zaehler.items():
        zeilen.append(f"  {name:<20} {anzahl(wert):>12}")
    return "\n".join(zeilen)


def status_letzter_lauf(nummer, befehl, start, ende) -> str:
    if nummer is None:
        return "Es gab noch keinen Lauf."
    schluss = ende if ende else "nicht beendet (abgebrochen oder abgestuerzt)"
    return (
        "Letzter Lauf\n"
        f"  Nummer:  {nummer}\n"
        f"  Befehl:  {befehl}\n"
        f"  Start:   {start}\n"
        f"  Ende:    {schluss}"
    )


# --------------------------------------------------------------- config ----


def config_pfad_zeigen(pfad: Path) -> str:
    return f"Die geltende Konfiguration liegt hier:\n  {pfad}"


def config_wird_geoeffnet(pfad: Path) -> str:
    return f"Wird im Editor geoeffnet: {pfad}"


# ----------------------------------------------------------- Archivsperre ----


def archiv_belegt(pfad) -> str:
    """Ein zweiter Lauf auf dasselbe Archiv (SPEC Abschnitt 6)."""
    return (
        "Fuer dieses Archiv laeuft bereits ein Vorgang.\n"
        f"  {pfad}\n"
        "Es kann immer nur ein Lauf gleichzeitig an einem Archiv arbeiten;\n"
        "sonst kaemen sich die Schreibvorgaenge in die Quere und die\n"
        "Datenbank - das Gedaechtnis des Archivs - koennte Schaden nehmen.\n"
        "Bitte warten, bis der andere Lauf fertig ist, und es dann erneut\n"
        "versuchen."
    )


def datenbank_belegt(pfad) -> str:
    """SQLite meldet die Datenbank als gesperrt."""
    return (
        "Die Datenbank des Archivs ist gerade belegt.\n"
        f"  {pfad}\n"
        "Vermutlich arbeitet ein zweiter Lauf daran. Es wurde nichts\n"
        "veraendert; bitte spaeter noch einmal versuchen."
    )


# ---------------------------------------------------- Fehler des Systems ----


def system_fehler(pfad, grund: str) -> str:
    """Ein Fehler des Betriebssystems, in verstaendlichen Worten."""
    return (
        "Abbruch: Auf diesen Pfad konnte nicht zugegriffen werden.\n"
        f"  {pfad}\n"
        f"  Grund: {grund}\n"
        "Haeufige Ursachen: fehlende Rechte, ein Netzlaufwerk, das gerade\n"
        "nicht erreichbar ist, oder ein Name, der auf eine Datei statt auf\n"
        "einen Ordner zeigt."
    )


def config_kaputt(pfad, zeile, spalte, grund: str) -> str:
    """Tippfehler in der von Hand gepflegten config.toml."""
    stelle = ""
    if zeile is not None:
        stelle = f"  Stelle: Zeile {zeile}, Spalte {spalte}\n"
    return (
        "Abbruch: Die Konfigurationsdatei laesst sich nicht lesen.\n"
        f"  Datei:  {pfad}\n"
        f"{stelle}"
        f"  Grund:  {grund}\n"
        "Die Datei bleibt unveraendert stehen - es wird nichts ueberschrieben.\n"
        "Meist fehlt ein Anfuehrungszeichen, eine eckige Klammer oder ein\n"
        "Gleichheitszeichen. Nach dem Berichtigen laeuft der Befehl wieder."
    )


def config_falscher_typ(schluessel: str, gefunden: str, erwartet: str, pfad) -> str:
    """Ein Konfigurationswert hat die falsche Art (Liste, Wahrheitswert ...)."""
    return (
        "Abbruch: Ein Wert in der Konfiguration hat die falsche Form.\n"
        f"  Datei:     {pfad}\n"
        f"  Schluessel: {schluessel}\n"
        f"  gefunden:  {gefunden}\n"
        f"  erwartet:  {erwartet}\n"
        "Der Wert wird nicht benutzt, weil eine falsche Form die Bedeutung\n"
        'umkehren kann: Eine Zeichenkette statt einer Liste wird Zeichen fuer\n'
        'Zeichen gelesen, und aus "nein" wird ein Ja.\n'
        "Die Datei bleibt unveraendert stehen."
    )


# -------------------------------------------------------- Ziel anlegen ----


def ziel_wird_nicht_angelegt(ziel) -> str:
    """Ein nicht vorhandenes Ziel wird nicht stillschweigend angelegt."""
    return (
        "Abbruch: Diesen Zielordner gibt es nicht:\n"
        f"  {ziel}\n"
        "Er wird bewusst nicht von selbst angelegt. Ein Tippfehler im Pfad -\n"
        "oder ein Netzlaufwerk, das gerade nicht eingebunden ist - ergaebe\n"
        "sonst ein zweites, leeres Archiv mit einer neuen Kennung; das\n"
        "richtige Archiv gaelte danach als unbekannt und alles wuerde noch\n"
        "einmal kopiert.\n"
        "Ist der Pfad richtig und der Ordner soll wirklich neu entstehen:\n"
        "  fotosort scan --quelle <Quelle> --ziel <Ziel> --ziel-anlegen"
    )


def ziel_eltern_fehlt(ziel, eltern) -> str:
    return (
        "Abbruch: Der Ordner, in dem das Ziel angelegt werden soll, gibt es\n"
        "nicht:\n"
        f"  Ziel:          {ziel}\n"
        f"  fehlender Ort: {eltern}\n"
        "Bitte den Pfad pruefen. Liegt das Ziel auf einem Netzlaufwerk, ist\n"
        "es vermutlich gerade nicht eingebunden."
    )


def ziel_angelegt(ziel) -> str:
    return f"Neuer Zielordner angelegt: {ziel}"


# ------------------------------------------------------------- Abbrueche ----


def lauf_abgebrochen_vermerkt() -> str:
    return "Der Lauf wurde als sauber abgebrochen vermerkt."


def abbruch_durch_signal() -> str:
    """SIGTERM - das Signal von "docker stop" und von TrueNAS."""
    return (
        "Das Programm wurde vom System zum Beenden aufgefordert.\n"
        "Das Bisherige ist gespeichert; ein neuer Lauf macht dort weiter."
    )


# ---------------------------------------------------------- Quellen -----


def datenbank_schema_veraltet(pfad, gefunden: int, erwartet: int) -> str:
    return (
        f"Die Datenbank {pfad} stammt aus einem frueheren Stand des Programms\n"
        f"(Schema-Version {gefunden}, erwartet {erwartet}). Sie wird nicht\n"
        "stillschweigend weiterbenutzt. Da es noch keine echten Archive gibt,\n"
        "hilft: den Archiv-Ordner loeschen und neu scannen."
    )


def quelle_nicht_erreichbar(pfad) -> str:
    return (
        f"Quelle nicht erreichbar: {pfad}\n"
        "  Sie bleibt bekannt und wird uebersprungen. Ihre Dateien gelten\n"
        "  nicht als verschwunden. Platte eingesteckt, Netzlaufwerk eingebunden?"
    )


def quelle_abgelehnt_ueberschneidung(pfad, andere) -> str:
    return (
        f"Quelle abgelehnt: {pfad}\n"
        f"  Sie ueberschneidet sich mit der Quelle {andere}. Dieselbe Datei\n"
        "  wuerde sonst zweimal erfasst. Die uebrigen Quellen laufen weiter."
    )


def keine_quellen_bekannt() -> str:
    return (
        "Dieses Archiv kennt noch keine Quelle. Beim ersten Scan muss\n"
        "mindestens eine angegeben werden: fotosort scan --quelle <Ordner> --ziel <Ziel>"
    )


def scan_quellen_beginnt(quellen: list, ziel) -> str:
    zeilen = ["Scan laeuft."]
    for q in quellen:
        zeilen.append(f"  Quelle: {q}")
    zeilen.append(f"  Ziel:   {ziel}")
    return "\n".join(zeilen)


def scan_neue_quellen(neue: list) -> str:
    if not neue:
        return ""
    zeilen = [f"Neu aufgenommene Quelle{'n' if len(neue) != 1 else ''}:"]
    zeilen += [f"  {q}" for q in neue]
    return "\n".join(zeilen)


def scan_laufwerke(anzahl_laufwerke: int, anzahl_quellen: int) -> str:
    if anzahl_quellen <= 1:
        return ""
    if anzahl_laufwerke == 1:
        return f"{anzahl(anzahl_quellen)} Quellen auf einem Laufwerk, nacheinander gelesen."
    return (
        f"{anzahl(anzahl_quellen)} Quellen auf {anzahl(anzahl_laufwerke)} Laufwerken,"
        " je Laufwerk parallel gelesen."
    )


def scan_je_quelle(je_quelle: dict) -> str:
    """Eine Zeile je Quelle: Dateien, Groesse, neu/unveraendert/veraendert."""
    if len(je_quelle) <= 1:
        return ""
    zeilen = ["Je Quelle"]
    for wurzel, e in je_quelle.items():
        zeilen.append(f"  {wurzel}")
        zeilen.append(
            f"    {anzahl(e.dateien)} Dateien, {groesse(e.bytes_gesamt)}"
            f" — neu {anzahl(e.neu)}, unveraendert {anzahl(e.unveraendert)},"
            f" veraendert {anzahl(e.veraendert)}"
            + (f", nicht mehr vorhanden {anzahl(e.verschwunden)}" if e.verschwunden_ausgewertet else "")
            + (f", Fehler {anzahl(e.fehler)}" if e.fehler else "")
        )
    return "\n".join(zeilen)


def scan_nichts_zu_tun(abgelehnt: list, nicht_erreichbar: list) -> str:
    return (
        "Keine Quelle konnte durchlaufen werden"
        f" ({anzahl(len(abgelehnt))} abgelehnt, {anzahl(len(nicht_erreichbar))} nicht erreichbar)."
    )


def status_je_quelle(quellen: list, je_quelle: dict, je_status: dict) -> str:
    """Fuer 'fotosort status': eine Zeile je bekannter Quelle."""
    if not quellen:
        return "Quellen: noch keine bekannt."
    zeilen = ["Quellen"]
    for z in quellen:
        wurzel = z["wurzel"]
        zaehler = je_quelle.get(wurzel, {})
        stati = je_status.get(wurzel, {})
        stand = "erreichbar" if int(z["erreichbar"] or 0) else "NICHT ERREICHBAR beim letzten Scan"
        zeilen.append(f"  {wurzel}  ({stand})")
        zeilen.append(
            f"    {anzahl(zaehler.get('gesamt', 0))} Dateien, {groesse(zaehler.get('bytes', 0))}"
            + (
                "  —  " + ", ".join(f"{s} {anzahl(n)}" for s, n in sorted(stati.items()))
                if stati
                else ""
            )
        )
    return "\n".join(zeilen)


# ---------------------------------------------------------- Analyse -----


def analyse_beginnt(prozesse: int, offen: int) -> str:
    return (
        f"Analyse laeuft: {anzahl(offen)} Dateien zu bearbeiten,"
        f" {anzahl(prozesse)} ExifTool-Prozess{'e' if prozesse != 1 else ''}."
    )


def analyse_laeuft(bisher: int, gesamt: int) -> str:
    return f"Analyse: {anzahl(bisher)} von {anzahl(gesamt)} Dateien"


def analyse_nichts_zu_tun() -> str:
    return "Nichts zu analysieren: Es gibt keine Dateien mit Status gefunden."


def analyse_abgebrochen() -> str:
    return "Abgebrochen. Das Bisherige ist gespeichert; der naechste Lauf macht dort weiter."


def analyse_ergebnis(e) -> str:
    """Zaehler dieses Laufs (ein analyse.Ergebnis)."""
    zeilen = [
        "Ergebnis der Analyse (dieser Lauf)",
        f"  bearbeitet:                  {anzahl(e.bearbeitet)}",
        f"  Gruppen (RAW+JPG, Sidecars): {anzahl(e.gruppen)}",
        f"  Sidecars ohne Hauptdatei:    {anzahl(e.sidecar_ohne_haupt)}",
        f"  Fehler (nicht lesbar):       {anzahl(e.fehler)}",
        f"  Zielordner mit Zusatz wiederverwendet: {anzahl(e.wiederverwendet)}",
    ]
    if e.mehrdeutig:
        zeilen.append(f"  davon mehrdeutig (alphabetisch gewaehlt): {anzahl(e.mehrdeutig)}")
    zeilen.append(f"  Dauer:           {dauer(e.sekunden)}")
    if e.sekunden > 0:
        zeilen.append(f"  Durchsatz:       {e.bearbeitet / e.sekunden:,.1f} Dateien/s".replace(",", "."))
    zeilen.append(f"  ExifTool-Prozesse: {anzahl(e.prozesse)}")
    return "\n".join(zeilen)


def analyse_zusammenfassung(z: dict) -> str:
    """Der Plan als Ganzes (alle analysierten Dateien, nicht nur dieser Lauf)."""
    zeilen = ["Zusammenfassung des Plans"]
    je = z.get("je_jahr_quelle", {})
    jahre: dict[str, int] = {}
    for wurzel, nach_jahr in je.items():
        for jahr, n in nach_jahr.items():
            jahre[jahr] = jahre.get(jahr, 0) + n
    zeilen.append("  Dateien pro Jahr (gesamt):")
    for jahr in sorted(jahre, key=lambda j: (j == "ohne Datum", j)):
        zeilen.append(f"    {jahr:<12}{anzahl(jahre[jahr]):>8}")
    if len(je) > 1:
        zeilen.append("  Dateien pro Jahr je Quelle:")
        for wurzel in sorted(je):
            zeilen.append(f"    {wurzel}")
            for jahr in sorted(je[wurzel], key=lambda j: (j == "ohne Datum", j)):
                zeilen.append(f"      {jahr:<12}{anzahl(je[wurzel][jahr]):>8}")
    zeilen.append("  Gefundene Kameramodelle (Modell -> Ordner):")
    for roh, ordner, n in z.get("modelle", []):
        zeilen.append(f"    {(roh or '(kein Modell)'):<28} -> {ordner:<20}{anzahl(n):>8}")
    zeilen.append(
        "  Aliase fuer unbekannte Modelle traegt man in der config.toml unter"
        " [kamera.aliase] nach (fotosort config), BEVOR kopiert wird."
    )
    zeilen.append(f"  Ohne sicheres Datum (nur Aenderungsdatum):    {anzahl(z.get('unsicher', 0))}")
    zeilen.append(f"  Namenskonflikte (gleicher Zielname, Phase 3): {anzahl(z.get('namenskonflikte', 0))}")
    zeilen.append(f"  Zeitzone angenommen (Video ohne Offset):     {anzahl(z.get('zeitzone_angenommen', 0))}")
    zeilen.append(f"  Datum aus Dateiname ohne Uhrzeit:            {anzahl(z.get('ohne_uhrzeit', 0))}")
    zeilen.append(f"  Sidecars ohne Hauptdatei:                    {anzahl(z.get('sidecar_ohne_haupt', 0))}")
    zeilen.append(f"  Fehler:                                      {anzahl(z.get('fehler', 0))}")
    zeilen.append(f"  Noch nicht analysiert:                       {anzahl(z.get('offen', 0))}")
    return "\n".join(zeilen)


def abbruch_allgemein() -> str:
    return "Abgebrochen. Das Bisherige ist gespeichert; der naechste Lauf macht dort weiter."


def zeitzone_ungueltig(name) -> str:
    return (
        f"Die Heimat-Zeitzone \"{name}\" ist unbekannt (config.toml, [datum] heimat_zeitzone).\n"
        "Erwartet wird ein Name wie \"Europe/Berlin\". Ohne gueltige Zeitzone wuerden alle\n"
        "Videos ohne Offset falsch einsortiert; deshalb wird abgebrochen."
    )
