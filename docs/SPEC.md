# SPEC – Foto-Sortierer

Das Programm heißt **fotosort**. Das Repository heißt aus historischen Gründen `Culling`.

Diese Datei ist die verbindliche Beschreibung des Projekts. Bei Widersprüchen zwischen einem Prompt und dieser Datei: nachfragen, nicht raten.

## 1. Ziel

Ein Werkzeug, das einen großen, chaotischen Ordnerbaum mit Fotos und Videos einliest und alle Dateien in eine saubere Zielstruktur nach **Aufnahmedatum** und **Kamera** einsortiert. Es wird alle paar Monate erneut mit neuen Bildern gefüttert und muss dann in die bereits bestehende Zielstruktur einsortieren.

Oberste Regel: **Es darf niemals ein Bild verloren gehen.** Geschwindigkeit ist wichtig, kommt aber immer nach Sicherheit.

## 2. Umgebung

- Entwicklung und erste Nutzung: Windows 11, AMD Ryzen 9 (16 Kerne / 32 Threads), viel RAM.
- Später: Betrieb auf einem TrueNAS-Server (Linux, als Docker-Container). Deshalb von Anfang an plattformneutral: nur `pathlib`, keine Windows-Sonderwege, keine fest eingebauten Pfade. Einzige Ausnahme ist das Pfad-Präfix für lange Windows-Pfade (§5).
- Quelle und Ziel können lokale Platten, externe SSDs oder SMB-Netzlaufwerke sein (auch UNC-Pfade wie `\\truenas\Daten\...`).
- Sprache: Python 3.12+. Metadaten über **ExifTool** (extern, muss installiert sein; beim Start prüfen und verständlich melden, wenn es fehlt).
- Oberfläche und alle Meldungen auf Deutsch.

## 3. Zielstruktur

```
<Ziel>/
  2026/
    2026-01 Januar/
      2026-01-01/
        A7C2/
          DSC01234.ARW
          DSC01234.JPG
        A7C/
        Analog/
        Unbekannte_Kamera/
  _Ohne_Datum/
    <Kamera>/
```

- Das Muster ist in der Konfiguration als Vorlage einstellbar (Standard: `{jahr}/{jahr}-{monat} {monatsname}/{jahr}-{monat}-{tag}/{kamera}`).
- Dateien ohne verwertbares Datum haben eine eigene, ebenfalls einstellbare Vorlage (Standard: `_Ohne_Datum/{kamera}`). Der Pfad steht nicht fest im Programm.
- **Bestehende Struktur erkennen:** Existiert im Ziel schon ein Tagesordner, der mit dem Datum beginnt und einen Zusatz hat (z. B. `2026-01-01 Geburtstag Oma`), wird dieser benutzt und kein zweiter angelegt. Gleiches gilt für Monats- und Jahresordner mit Zusatz. Gibt es mehrere passende Ordner, wird der ohne Zusatz bevorzugt, sonst der erste alphabetisch, und der Fall im Bericht vermerkt.
- Originaldateinamen bleiben erhalten.

### Kamera-Ordner

- Quelle ist das EXIF-Feld `Model` (ersatzweise `Make` + `Model`).
- Eine Alias-Tabelle in der Konfiguration übersetzt Modellnamen in Ordnernamen, z. B. `ILCE-7CM2 → A7C2`, `ILCE-7C → A7C`. Scanner-Modelle (Noritsu, Frontier, Epson, Plustek …) → `Analog`.
- Unbekanntes Modell ohne Alias: bereinigter Modellname als Ordnername (keine Sonderzeichen, die unter Windows oder Linux verboten sind).
- Kein Modell vorhanden: `Unbekannte_Kamera`.
- Nach dem Scan zeigt das Programm alle gefundenen Modelle mit Anzahl, damit der Nutzer Aliase ergänzen kann, **bevor** kopiert wird.

### Datum

Reihenfolge der Quellen, die erste gültige gewinnt:

1. `DateTimeOriginal`
2. Video-Felder **mit** Zeitzonen-Offset (z. B. QuickTime `CreationDate`, Sony-XML-Sidecar). Sie geben die Ortszeit der Aufnahme direkt an und werden bevorzugt.
3. `CreateDate` / `MediaCreateDate` (Videos ohne Offset) – der Wert wird als UTC behandelt und in die eingestellte **Heimat-Zeitzone** umgerechnet (Standard `Europe/Berlin`). Diese Dateien werden im Bericht als „Zeitzone angenommen" gekennzeichnet.
4. Datum im Dateinamen (Muster wie `IMG_20260101_…`, `2026-01-01 …`, `PXL_20260101…`)
5. Änderungsdatum der Datei – gilt als **unsicher**

- Verhalten bei unsicherem Datum ist einstellbar: Standard ist die Vorlage für Dateien ohne Datum (`_Ohne_Datum/{kamera}`), alternativ nach Änderungsdatum einsortieren.
- Offensichtlich kaputte Daten (vor 1990, in der Zukunft, `0000:00:00`) gelten als nicht vorhanden.
- Es wird die Kamera-Ortszeit genommen, keine Umrechnung bei Fotos.
- Option „Tagesgrenze" (Standard 00:00, z. B. auf 04:00 stellbar), damit Aufnahmen nach Mitternacht noch zum Vortag zählen.
- Stammt das Datum aus dem Dateinamen, wird die Tagesgrenze nur angewendet, wenn der Dateiname auch eine Uhrzeit enthält (z. B. `IMG_20260101_013000`). Steht dort nur ein Datum (z. B. `2026-01-01 Urlaub.jpg`), wird es genommen, wie es dasteht. Wie oft das vorkam, steht im Bericht.

### Zusammengehörige Dateien

Dateien mit gleichem Stammnamen im selben Quellordner wandern gemeinsam und bekommen Datum/Kamera der Hauptdatei (Priorität RAW > JPG/HEIF > Video):

- RAW + JPG/HIF-Paare
- Sidecars: `.xmp`, `.dop`, `.pp3`, Sony-Video-`M01.XML`, `.thm`, `.aae`

Ein Sidecar gehört zur Hauptdatei, wenn sein Name entweder **Stammname + Sidecar-Endung** (`DSC01234.xmp`) oder **vollständiger Dateiname + Sidecar-Endung** (`DSC01234.ARW.xmp`) ist. Beide Schreibweisen gelten für alle Sidecar-Endungen.

### Dateitypen

Standardliste, in der Konfiguration erweiterbar: Fotos (`jpg jpeg heic hif png tif tiff webp`), RAW (`arw cr2 cr3 nef dng raf orf rw2 srw`), Video (`mp4 mov mts m2ts avi mkv`). Alles andere wird nicht angefasst, aber im Bericht gezählt („übersprungen nach Typ").

## 4. Ablauf in Phasen

Jede Phase ist einzeln startbar und **fortsetzbar**. Zwischen den Phasen wartet das Programm auf den Nutzer.

1. **Scan** – Quelle rekursiv durchlaufen (`os.scandir`), Dateien zählen, Gesamtgröße ermitteln. Ergebnis sofort anzeigen: Anzahl Dateien, Größe, Aufteilung nach Typ.
2. **Analyse** – Metadaten lesen, Ziel für jede Datei berechnen, Duplikate und Namenskonflikte erkennen. Ergebnis: Plan plus Zusammenfassung (wie viele Dateien in welche Jahre, gefundene Kameras, Anzahl Duplikate, Anzahl ohne Datum). **Noch keine Datei wird angefasst.**
3. **Übertragen** – wahlweise
   - **Kopieren** (Standard): Quelle bleibt unberührt.
   - **Verschieben**: jede Datei wird einzeln kopiert, geprüft und erst dann in der Quelle gelöscht.
     Liegen Quelle und Ziel nachweislich auf demselben Laufwerk, wird stattdessen umbenannt. Das ist erlaubt, weil dabei keine Daten kopiert werden, sondern nur ein Verzeichniseintrag geändert wird. Danach wird geprüft, dass die Zieldatei existiert und die Größe stimmt; die Datei bekommt den Status `verschoben`. Den Hash für den Ziel-Index berechnet erst die Prüf-Phase aus der Zieldatei.
     Ob zwei Pfade wirklich auf demselben Laufwerk liegen, muss sicher festgestellt werden (Kennung des Dateisystems, nicht der Laufwerksbuchstabe im Pfad). Lässt es sich nicht sicher feststellen, wird kopiert statt umbenannt.
4. **Prüfen** – jede Zieldatei wird erneut vollständig gelesen und ihr Hash mit dem der Quelle verglichen. Ergebnis: „X von Y geprüft, Z Fehler".
   Für umbenannte Dateien (Status `verschoben`) gibt es keine Quelle mehr, gegen die verglichen werden könnte. Für sie wird in dieser Phase der Hash aus der Zieldatei berechnet und in den Ziel-Index geschrieben. Im Bericht werden sie getrennt ausgewiesen.
5. **Quelle aufräumen** (nur im Kopier-Modus, nur auf ausdrücklichen Befehl) – gelöscht werden ausschließlich Dateien mit Status `geprüft` oder `duplikat_bestaetigt` (§5). Kein anderer Status berechtigt zum Löschen. Vorher Anzahl und Größe anzeigen und bestätigen lassen.
6. **Leere Ordner entfernen** (eigener, optionaler Schritt) – nur wirklich leere Ordner. Reste wie `Thumbs.db`, `.DS_Store`, `desktop.ini` zählen als leer und dürfen mit entfernt werden (Liste konfigurierbar). Der angegebene Quell-Wurzelordner selbst bleibt stehen.

## 5. Sicherheit

- Kopieren immer in eine temporäre Datei (`<name>.part`) im Zielordner, danach atomar umbenennen. Liegengebliebene `.part`-Dateien werden beim nächsten Start erkannt und entfernt.
- **Niemals überschreiben.** Existiert der Zielname schon:
  - gleicher Hash → Duplikat, wird nicht erneut kopiert. Gelöscht werden darf die Quelldatei deswegen noch nicht; dafür braucht sie den Status `duplikat_bestaetigt` (siehe unten).
  - anderer Inhalt → neuer Name mit Anhang `_1`, `_2` …; zusammengehörige Dateien bekommen denselben Anhang.
- Duplikate innerhalb der Quelle (gleicher Hash): nur eine Kopie ins Ziel, alle im Bericht auflisten.
- Änderungsdatum der Dateien bleibt beim Kopieren erhalten.
- **Status `duplikat_bestaetigt`:** Eine Quelldatei bekommt ihn nur, wenn die inhaltsgleiche Zieldatei **im aktuellen Lauf** vollständig neu gelesen wurde und ihr Hash mit dem Quell-Hash übereinstimmt. Ein Hash aus einem früheren Lauf oder aus dem Ziel-Index genügt dafür nicht.
- **Der Ziel-Index rechtfertigt niemals eine Löschung.** Er dient nur dazu, Kandidaten für Duplikate schnell zu finden und zu entscheiden, ob kopiert werden muss. Vor jeder Löschung wird die Zieldatei frisch gelesen und verglichen — ohne Ausnahme und ohne Abschaltmöglichkeit.
- Löschen nur nach bestandener Hash-Prüfung, nie auf Basis von Name oder Größe allein. Gelöscht werden darf ausschließlich aus den Status `geprüft` und `duplikat_bestaetigt`.
- Option `byte_vergleich_vor_loeschen` (Standard: aus): vergleicht vor dem Löschen Quelle und Ziel zusätzlich Byte für Byte. Beide Dateien werden dafür ohnehin gelesen.
- **Lange Pfade unter Windows werden umgangen, nicht nur gemeldet:** Pfade werden intern mit dem Präfix `\\?\` (bei Netzpfaden `\\?\UNC\`) angesprochen, damit die 260-Zeichen-Grenze nicht greift. Der Fehlergrund „Pfad zu lang" bleibt bestehen, greift aber nur noch, wenn es trotzdem scheitert.
- Ein `--dry-run` für jede Phase, die etwas verändert.
- Liegt das Ziel innerhalb der Quelle (oder umgekehrt): Zielordner beim Scan ausschließen bzw. mit klarer Meldung abbrechen.
- Vor dem Übertragen prüfen, ob im Ziel genug Platz ist.
- Einzelne fehlerhafte Dateien (nicht lesbar, Pfad zu lang, Rechteproblem) brechen den Lauf nicht ab, sondern bekommen Status „Fehler" mit Grund und erscheinen im Bericht.

## 6. Fortschritt speichern (Absturzsicherheit)

- Eine **SQLite-Datenbank** pro Archiv speichert jede Datei mit: Quellpfad, Größe, Änderungsdatum, Hash, Metadaten, Zielpfad, Status.
- Statuswerte: `gefunden → analysiert → kopiert → geprüft → quelle_gelöscht`, dazu `verschoben`, `duplikat`, `duplikat_bestaetigt`, `übersprungen`, `fehler`.
  - `verschoben`: durch Umbenennen auf demselben Laufwerk ins Ziel gebracht; Existenz und Größe geprüft (§4 Phase 3). Der Hash wird in der Prüf-Phase aus der Zieldatei nachgetragen.
  - `duplikat`: im Ziel liegt vermutlich dieselbe Datei, im aktuellen Lauf aber noch nicht nachgewiesen.
  - `duplikat_bestaetigt`: Zieldatei im aktuellen Lauf frisch gelesen, Hash stimmt mit dem der Quelle überein (§5).
  - Zum Löschen berechtigen ausschließlich `geprüft` und `duplikat_bestaetigt`.
- Statuswechsel werden in Blöcken geschrieben (z. B. alle 500 Dateien oder alle 2 Sekunden), damit die Datenbank nicht bremst.
- Nach Absturz, Stromausfall oder Abbruch mit Strg+C: Neustart setzt genau dort fort. Nichts wird doppelt gemacht, nichts vergessen.

### Ort der Datenbank

- Die Datenbank liegt **immer lokal**, nie auf einem Netzlaufwerk.
  - Windows: `%LOCALAPPDATA%\fotosortierer\<archiv-id>\`
  - Linux/Docker: ein eigener lokaler Pfad bzw. ein Volume.
- Der Ort ist in der Konfiguration einstellbar. Erkennt das Programm, dass der Datenbankpfad auf einem Netzlaufwerk liegt, bricht es mit einer verständlichen Meldung ab.
- **Archiv-ID:** Jeder Zielordner bekommt eine Archiv-ID. Sie verbindet den Zielordner mit der zugehörigen lokalen Datenbank, damit ein späterer Lauf die richtige Datenbank wiederfindet.
- Im Zielordner liegt unter `.fotosortierer/` nur noch:
  - eine Datei mit der Archiv-ID,
  - die Berichte (§10),
  - nach jeder abgeschlossenen Phase eine **Sicherungskopie der Datenbank**. Sie wird über die SQLite-Backup-Funktion geschrieben und als normale Datei ins Ziel gelegt. Es wird nie direkt in einer Datenbank auf dem Netzlaufwerk gearbeitet.
- Ein eigener Befehl stellt die lokale Datenbank aus dieser Sicherungskopie wieder her (§8).

### Ziel-Index

- Die Datenbank merkt sich auch, was im Ziel liegt (Pfad, Größe, Änderungsdatum, Hash). Bei späteren Läufen wird das Ziel nur auf Änderungen geprüft (Größe + Änderungsdatum), nicht komplett neu gehasht. Ein Befehl zum vollständigen Neuaufbau des Index existiert.
- Der Index darf nur entscheiden, ob **kopiert** wird. Er darf **niemals allein eine Löschung erlauben**; er dient dort nur dazu, Kandidaten für Duplikate schnell zu finden. Vor jeder Löschung gilt §5: Die Zieldatei wird im aktuellen Lauf frisch gelesen und verglichen.

## 7. Geschwindigkeit

Ehrliche Einordnung: Der Prozessor ist selten der Engpass, meistens ist es die Festplatte oder das Netzwerk. Deshalb getrennte, einstellbare Parallelität:

- **Metadaten:** ExifTool nicht pro Datei starten. Mehrere dauerhaft laufende ExifTool-Prozesse (`-stay_open`), jeweils mit Stapeln von Dateien, JSON-Ausgabe, nur die benötigten Felder, `-fast2`. Anzahl Prozesse: Standard = Anzahl Kerne.
- **Hashing:** durchgehend **BLAKE3** im ganzen Projekt (schnell und kryptografisch), parallel, in großen Blöcken (≥ 1 MiB) lesen. Der Quell-Hash wird **während des Kopierens** mitberechnet, damit die Quelle nur einmal gelesen wird.
- **Kopieren:** eigene, kleine Worker-Zahl. Standard: 2–4 bei Festplatte/NAS, 8+ bei SSD. Zu viele gleichzeitige Kopien auf eine Festplatte machen es langsamer. Option `--profil hdd|ssd|netzwerk` plus manuelle Werte.
- Kleine Dateien (Sidecars) zuerst nicht bevorzugen; Reihenfolge nach Quellordner, damit die Platte sequentiell lesen kann.
- Am Ende jeder Phase: Durchsatz (Dateien/s, MB/s) ausgeben, damit man die Einstellungen vergleichen kann.

## 8. Bedienung

**Kern + Kommandozeile zuerst**, Weboberfläche danach als dünne Schicht über demselben Kern.

Kommandozeile (Beispiel):

```
fotosort scan      --quelle D:\Chaos --ziel \\truenas\Daten\Lightroom\Medien
fotosort analyse
fotosort kopieren  [--verschieben] [--dry-run]
fotosort pruefen
fotosort aufraeumen [--leere-ordner]
fotosort status
fotosort bericht
fotosort wiederherstellen --ziel \\truenas\Daten\Lightroom\Medien
```

`fotosort wiederherstellen` holt die lokale Datenbank aus der Sicherungskopie im Zielordner zurück (§6).

Dazu ein geführter Modus `fotosort start`, der die Phasen nacheinander durchgeht und zwischen den Schritten fragt.

**Weboberfläche** (spätere Phase, lokal im Browser, später im Container auf dem Server):

- Zeigt **nur Zusammenfassungen**: Zähler, Fortschrittsbalken, Durchsatz, Restzeit, Fehlerliste. Niemals alle Dateien auf einmal in die Seite laden.
- Listen (Fehler, Duplikate, Dateien ohne Datum) nur seitenweise, serverseitig geblättert.
- Fortschritt höchstens 1–2× pro Sekunde aktualisieren (Polling oder SSE), nicht ein Ereignis pro Datei.
- Die Arbeit läuft in einem eigenen Prozess. Browser schließen oder Seite neu laden darf den Lauf nicht beeinflussen.
- Knöpfe für die Phasen, Auswahl Kopieren/Verschieben, Pause/Fortsetzen, Alias-Tabelle bearbeiten.

## 9. Konfiguration

Eine `config.toml` (wird beim ersten Start mit Kommentaren erzeugt): Ordner-Vorlage, Vorlage für Dateien ohne Datum, Kamera-Aliase, Dateitypen, Sidecar-Endungen, Verhalten bei unsicherem Datum, Tagesgrenze, Heimat-Zeitzone, Byte-Vergleich vor dem Löschen, Ort der Datenbank, Worker-Zahlen/Profil, Liste der „zählt als leer"-Dateien, Ausschlussmuster für die Quelle.

Standardwerte der Werte, die an anderer Stelle dieser SPEC festgelegt sind:

- `vorlage_ohne_datum` = `_Ohne_Datum/{kamera}` (§3)
- `heimat_zeitzone` = `Europe/Berlin` (§3)
- `byte_vergleich_vor_loeschen` = aus (§5)
- `datenbank_ort` = lokaler Standardpfad je Betriebssystem, nie ein Netzlaufwerk (§6)

## 10. Bericht

Nach jedem Lauf ein Bericht als Textdatei und CSV im Ordner `.fotosortierer/berichte/`: Anzahl gefunden / kopiert / verschoben / geprüft / Duplikate / ohne Datum / Fehler, Dauer und Durchsatz je Phase, Liste aller Fehler mit Grund, Liste aller Umbenennungen wegen Namenskonflikt.

Dazu gehören:

- Dateien, deren Zeitzone angenommen wurde („Zeitzone angenommen", §3), als eigene Liste.
- Anzahl der Dateien, bei denen das Datum aus dem Dateinamen ohne Uhrzeit stammt und die Tagesgrenze deshalb nicht angewendet wurde (§3).
- Dateien, die per Umbenennen verschoben wurden (Status `verschoben`, §4), getrennt ausgewiesen.

## 11. Tests

- `pytest`. Ein Skript erzeugt einen künstlichen Testbaum (kleine Dummy-Bilder mit gesetzten EXIF-Daten, Duplikate, Namenskonflikte, RAW+JPG-Paare, Sidecars, Dateien ohne Datum, kaputte Daten, tiefe und lange Pfade, Umlaute und Leerzeichen).
- Pflicht-Tests: Absturz mitten im Kopieren → Fortsetzen ergibt dasselbe Ergebnis; zweiter Lauf mit denselben Dateien kopiert nichts doppelt; Löschen verweigert ungeprüfte Dateien; bestehender Tagesordner mit Zusatz wird wiederverwendet.
- **Nie mit echten Fotos testen**, solange Löschen/Verschieben nicht durch die Tests abgesichert ist.

## 12. Nicht Teil des Projekts

Bilder ansehen oder bewerten, Bildinhalte erkennen, Gesichter, systematisches Umbenennen von Dateien (etwa nach Datum oder Kamera), Bearbeiten von Metadaten, Lightroom-Katalog anpassen.

Einzige Ausnahme beim Umbenennen ist der Anhang `_1`, `_2` … bei Namenskonflikten (§5). Er bleibt bestehen und wird im Bericht aufgelistet.
