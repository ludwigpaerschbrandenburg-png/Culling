# Prompts für Claude Code – Foto-Sortierer

## Vorbereitung (einmalig)

1. Das Repository `Culling` klonen und in den Repository-Ordner wechseln. Die verbindliche Beschreibung liegt darin unter `docs/SPEC.md`.
2. Python 3.12 oder neuer installieren.
3. ExifTool installieren (Windows: exiftool.org; Linux/Docker: Paket `libimage-exiftool-perl`).
4. Im Repository-Ordner Claude Code starten.
5. Die Prompts unten **einzeln und der Reihe nach** eingeben. Erst weitermachen, wenn die Phase läuft und die Tests grün sind. Nach jeder Phase selbst kurz ausprobieren.

Entwicklung und Tests laufen im Linux-Container, ausschließlich mit dem künstlichen Testbaum (SPEC Abschnitt 11); ExifTool ist dort installiert. Die erste Nutzung mit echten Fotos findet danach auf Windows 11 statt. Der spätere Betrieb läuft auf dem TrueNAS-Server im Container.

Warum in Phasen: Ein einziger Riesen-Prompt führt zu einem halb fertigen Alles. Phasen liefern jedes Mal etwas, das nachweislich funktioniert.

---

## Prompt 0 – Einlesen und Plan (noch kein Code)

Dieser Schritt ist bereits ausgeführt. Die Ergebnisse liegen in `CLAUDE.md`, `docs/architektur.md` und `docs/offene_fragen.md`. Der Prompt bleibt zum Nachlesen stehen.

```
Lies SPEC.md vollständig. Das ist die verbindliche Beschreibung des Projekts.

Schreib noch keinen Code. Ich möchte zuerst:
1. Eine kurze Zusammenfassung in deinen Worten, damit ich sehe, dass du es richtig verstanden hast.
2. Alle Stellen, die unklar oder widersprüchlich sind, als Fragen an mich.
3. Deinen Vorschlag für Projektstruktur (Module, Datenbank-Schema, Abhängigkeiten) und warum.
4. Risiken, bei denen Bilder verloren gehen könnten, und wie du sie absicherst.

Lege danach eine CLAUDE.md an mit den dauerhaften Regeln für dieses Projekt:
- Oberste Regel: Es darf nie ein Bild verloren gehen. Nie überschreiben, nie ungeprüft löschen.
- Nie mit echten Fotos testen, nur mit dem künstlichen Testbaum.
- Plattformneutral (Windows jetzt, Linux/Docker später), nur pathlib.
- Alle Meldungen auf Deutsch, Code und Kommentare dürfen Englisch sein.
- Nach jeder Änderung Tests laufen lassen. Nichts als fertig melden, was nicht getestet ist.
- In Phasen arbeiten, nie über die aktuelle Phase hinaus bauen.
- Ich bin kein Programmierer: erkläre mir Ergebnisse und Bedienung einfach und ohne Fachbegriffe.
```

---

## Prompt 1 – Grundgerüst, Testbaum, Scan

```
Phase 1 laut SPEC.md: Grundgerüst.

Baue:
- Projektstruktur, pyproject.toml, Kommandozeile "fotosort" mit den Unterbefehlen aus der SPEC (noch leer, außer scan und status).
- config.toml mit Kommentaren, wird beim ersten Start erzeugt.
- SQLite-Datenbank (WAL) mit dem Schema für Dateien, Status und Ziel-Index. Die Datenbank liegt laut SPEC Abschnitt 6 immer lokal, nie auf einem Netzlaufwerk; im Ziel liegen unter .fotosortierer/ nur die Archiv-ID, die Berichte und nach jeder abgeschlossenen Phase eine Sicherungskopie der Datenbank.
- Archiv-ID: im Ziel unter .fotosortierer/ anlegen, falls sie fehlt, sonst lesen. Über sie wird die zugehörige lokale Datenbank wiedergefunden.
- Nach jeder abgeschlossenen Phase eine Sicherungskopie der Datenbank über die SQLite-Backup-Funktion ins Ziel schreiben. Nie direkt in einer Datenbank auf dem Netzlaufwerk arbeiten.
- Prüfung, ob der Datenbankpfad auf einem Netzlaufwerk liegt. Wenn ja, mit verständlicher Meldung abbrechen.
- Findet das Programm im Ziel eine Archiv-ID, aber keine zugehörige lokale Datenbank, während im Ziel eine Sicherungskopie liegt: mit verständlicher Meldung abbrechen und auf "fotosort wiederherstellen" hinweisen. Niemals stillschweigend eine leere Datenbank anlegen, sonst gilt das Ziel als leer und alles wird erneut kopiert.
- Das Skript, das den künstlichen Testbaum erzeugt (SPEC Abschnitt 11), mit allen dort genannten Sonderfällen.
- "fotosort scan": Quelle rekursiv mit os.scandir durchlaufen, Dateien nach Typ zählen, Gesamtgröße, in die Datenbank schreiben. Fortschritt anzeigen. Abbrechbar und fortsetzbar.
- Prüfung beim Start, ob ExifTool vorhanden ist.
- Prüfung, ob Ziel in Quelle liegt oder umgekehrt.

Am Ende: Tests grün, und zeig mir die genauen Befehle, mit denen ich den Testbaum erzeuge und den Scan selbst ausprobiere.
```

---

## Prompt 2 – Analyse: Metadaten, Datum, Kamera, Plan

```
Phase 2 laut SPEC.md: Analyse.

Baue "fotosort analyse":
- Metadaten über mehrere dauerhaft laufende ExifTool-Prozesse (-stay_open, Stapel, JSON, nur benötigte Felder, -fast2). Anzahl Prozesse einstellbar, Standard = Anzahl Kerne.
- Datumsermittlung exakt in der Reihenfolge aus SPEC Abschnitt 3, inklusive kaputter Daten, Datum aus Dateinamen, unsicheres Datum, Tagesgrenze. Bei Videos zuerst die Felder mit Zeitzonen-Offset (QuickTime CreationDate, Sony-XML-Sidecar); fehlt ein solches Feld, CreateDate als UTC behandeln und in die eingestellte Heimat-Zeitzone umrechnen (Standard Europe/Berlin) und die Datei im Bericht als "Zeitzone angenommen" kennzeichnen. Die UTC-Annahme gilt ausschließlich für Video-Dateitypen. Bei Fotos werden CreateDate und DateTimeDigitized als Kamera-Ortszeit gelesen, nie als UTC; dort wird nicht umgerechnet und nichts als "Zeitzone angenommen" gekennzeichnet. Ein umgerechnetes Datum gilt als sicher, die Kennzeichnung dient nur dem Bericht; ebenso gilt ein Datum aus dem Dateinamen als sicher. Unsicher ist ausschließlich das Datum aus dem Änderungsdatum der Datei. Die Tagesgrenze bei einem Datum aus dem Dateinamen nur anwenden, wenn der Dateiname auch eine Uhrzeit enthält.
- Kamera-Ordner über die Alias-Tabelle, inklusive Scanner → Analog und Unbekannte_Kamera.
- Zusammengehörige Dateien (RAW+JPG, Sidecars) als Gruppe behandeln. Ein Sidecar gehört zur Hauptdatei, wenn sein Name eine von drei Formen hat: Stammname plus Sidecar-Endung (DSC01234.xmp), vollständiger Dateiname plus Sidecar-Endung (DSC01234.ARW.xmp) oder Stammname plus konfigurierbares Zusatzmuster plus Sidecar-Endung (C0001M01.XML gehört zu C0001.MP4). Die ersten beiden Formen gelten für alle Sidecar-Endungen. Die dritte Form deckt die Sony-Video-Sidecars ab, die die ersten beiden nicht erfassen; die Zusatzmuster stehen in der Konfiguration (sidecar_zusatzmuster, Standard M01, M02 und so weiter).
- Bestehende Zielstruktur erkennen, auch Ordner mit Zusatz wie "2026-01-01 Geburtstag Oma".
- Zielpfad für jede Datei berechnen und speichern. Noch nichts kopieren.
- Zusammenfassung ausgeben: Dateien pro Jahr, gefundene Kameramodelle mit Anzahl (damit ich Aliase ergänzen kann), Anzahl ohne sicheres Datum, Durchsatz in Dateien pro Sekunde.

Miss die Geschwindigkeit am Testbaum mit 1, 8, 16 und 32 Prozessen und sag mir, was am schnellsten war.
Tests für jeden Sonderfall der Datums- und Kameraerkennung.
```

---

## Prompt 3 – Kopieren, Duplikate, Absturzsicherheit

```
Phase 3 laut SPEC.md: Übertragen im Kopier-Modus.

Baue "fotosort kopieren" (nur Kopieren, Verschieben kommt in Phase 5):
- Kopieren in <name>.part, dann atomar umbenennen. Änderungsdatum erhalten.
- Quell-Hash während des Kopierens mitberechnen (BLAKE3, Blöcke >= 1 MiB).
- Niemals überschreiben. Gleicher Name + gleicher Hash = Duplikat, Status "duplikat"; die Quelldatei ist damit noch nicht zum Löschen freigegeben. Gleicher Name + anderer Inhalt = Anhang _1, _2, für die ganze Dateigruppe gleich.
- Status "duplikat_bestaetigt" nur dann, wenn die Zieldatei im aktuellen Lauf vollständig neu gelesen wurde und ihr Hash mit dem Quell-Hash übereinstimmt. Ein Hash aus einem früheren Lauf oder aus dem Ziel-Index genügt dafür nicht.
- Duplikate innerhalb der Quelle nur einmal kopieren.
- Ziel-Index nutzen und pflegen, damit spätere Läufe das Ziel nicht neu hashen müssen.
- Getrennte Worker-Zahlen für Kopieren und Hashing, Profile hdd / ssd / netzwerk.
- Reihenfolge nach Quellordner, damit Festplatten sequentiell lesen.
- Statuswechsel in Blöcken in die Datenbank schreiben.
- Freien Platz im Ziel vorher prüfen.
- Fehler bei einzelnen Dateien brechen den Lauf nicht ab.
- --dry-run.
- Sauberer Abbruch mit Strg+C, liegengebliebene .part-Dateien beim nächsten Start aufräumen.

Pflicht-Tests:
- Prozess mitten im Kopieren hart beenden, neu starten: Ergebnis identisch zu einem ungestörten Lauf, keine Datei doppelt, keine fehlt.
- Zweiter Lauf mit denselben Quelldateien kopiert nichts.
- Lauf in ein Ziel, in dem schon Dateien und Ordner mit Zusatznamen liegen.
```

---

## Prompt 4 – Prüfen und Bericht

```
Phase 4 laut SPEC.md: Prüfen und Bericht.

Baue:
- "fotosort pruefen": jede Zieldatei vollständig neu lesen, Hash mit Quell-Hash vergleichen, Status "geprueft" oder "fehler" setzen. Parallel, fortsetzbar.
- Sonderfall Status "verschoben" (durch Umbenennen ins Ziel gebracht): Dort gibt es keine Quelle mehr, gegen die verglichen werden könnte. Existenz und Größe wurden schon in Phase 3 geprüft. In dieser Phase wird der Hash aus der Zieldatei berechnet und in den Ziel-Index geschrieben. Im Bericht werden diese Dateien getrennt ausgewiesen.
- "fotosort bericht": Text- und CSV-Bericht nach SPEC Abschnitt 10.
- "fotosort status": jederzeit aufrufbar, zeigt Zähler je Status und die aktuelle Phase.

Test: Eine Zieldatei nach dem Kopieren absichtlich verändern, die Prüfung muss sie finden und melden.
```

---

## Prompt 5 – Verschieben, Quelle aufräumen, leere Ordner

```
Phase 5 laut SPEC.md: alles, was löscht. Hier besonders vorsichtig arbeiten.

Baue:
- "fotosort kopieren --verschieben": pro Datei kopieren, prüfen, erst dann Quelle löschen. Liegen Quelle und Ziel nachweislich auf demselben Laufwerk, stattdessen umbenennen; danach prüfen, dass die Zieldatei existiert und die Größe stimmt, Status "verschoben". Lässt sich nicht sicher feststellen, ob es dasselbe Laufwerk ist, wird kopiert statt umbenannt.
- Das Umbenennen darf niemals eine vorhandene Zieldatei überschreiben. os.rename und Path.rename ersetzen unter POSIX eine vorhandene Zieldatei stillschweigend; das ist ein Verlustpfad. Benutze ein nicht überschreibendes Verfahren: unter Linux os.link auf den Zielnamen und danach os.unlink der Quelle (oder renameat2 mit RENAME_NOREPLACE), unter Windows MoveFileEx ohne MOVEFILE_REPLACE_EXISTING. Ist der Zielname belegt, schlägt der Vorgang fehl und es greift die Regel "Niemals überschreiben" (Duplikat oder Anhang _1, _2). Das gilt auch für das abschließende Umbenennen der .part-Datei.
- Ein Netzlaufwerk gilt nie als "gleiches Laufwerk". Liegt mindestens einer der beiden Pfade auf einem Netzlaufwerk (UNC, SMB, CIFS, NFS), gilt "gleiches Laufwerk" als nicht nachgewiesen und es wird kopiert statt umbenannt. Erkennung: unter Windows über das UNC-Präfix bzw. GetDriveType gleich DRIVE_REMOTE, auch für verbundene Laufwerksbuchstaben aufgelöst; unter Linux über den Dateisystemtyp des Einhängepunkts (cifs, smb3, nfs, nfs4, fuse.sshfs).
- "fotosort aufraeumen": löscht in der Quelle ausschließlich Dateien mit Status "geprueft" oder "duplikat_bestaetigt". Kein anderer Status berechtigt zum Löschen. Vorher Anzahl und Größe anzeigen und ausdrücklich bestätigen lassen. --dry-run zeigt die Liste.
- "fotosort aufraeumen --leere-ordner": nur wirklich leere Ordner entfernen, Reste-Dateien laut Konfiguration zählen als leer. Quell-Wurzelordner bleibt stehen.
- Die Statusregel gilt für Quelldateien aus dem Bestand der Datenbank. Eng begrenzte, ausdrücklich benannte Ausnahmen sind die Reste-Dateien aus Phase 6 (Thumbs.db, .DS_Store, desktop.ini, Liste konfigurierbar) und liegengebliebene .part-Dateien. Beide stehen nie in der Datenbank. Weitere Ausnahmen gibt es nicht.
- Direkt vor jedem Löschen die Zieldatei im aktuellen Lauf frisch lesen und ihren Hash mit dem Quell-Hash vergleichen. Existenz und Größe allein genügen nicht, der Ziel-Index allein auch nicht.
- Der Status ist notwendig, nicht hinreichend. Diese Frischlesung gilt für beide löschberechtigenden Status, also auch bei "geprueft" und nicht nur bei "duplikat_bestaetigt". Die Lauf-Kennzeichnung (Spalte bestaetigt_in_lauf) wird deshalb für beide Status geführt. Gehört der Eintrag nicht zum aktuellen Lauf, wird nicht gelöscht, sondern im Bericht aufgeführt.
- Option byte_vergleich_vor_loeschen (Standard: aus): vergleicht Quelle und Ziel vor dem Löschen zusätzlich Byte für Byte.

Pflicht-Tests:
- Ungeprüfte Datei wird nie gelöscht, auch nicht mit Gewalt-Optionen.
- Datei, deren Zielkopie fehlt oder verändert wurde, wird nicht gelöscht.
- Ordner mit einer einzigen nicht erfassten Datei (z. B. .txt) bleibt stehen.
- Umbenennen auf einen bereits belegten Zielnamen überschreibt nichts: Die vorhandene Zieldatei bleibt unverändert, und die Quelldatei ist danach noch da.

Geh danach den gesamten Lösch-Code noch einmal Zeile für Zeile durch und such aktiv nach Wegen, wie ein Bild verloren gehen könnte. Berichte mir, was du gefunden und geändert hast.
```

---

## Prompt 6 – Geführter Modus und Feinschliff Geschwindigkeit

```
Phase 6: Bedienung und Tempo.

- "fotosort start": geführter Ablauf durch alle Phasen mit einfachen Fragen auf Deutsch (Quelle? Ziel? Kopieren oder Verschieben? Profil?). Zwischen den Phasen die Zusammenfassung zeigen und auf mein OK warten. Nach der Analyse die gefundenen Kameramodelle zeigen und fragen, ob ich Aliase ergänzen will.
- Erzeuge einen großen Testbaum (mindestens 50.000 Dateien, gemischte Größen) und miss jede Phase. Finde den Engpass mit einem Profiler und behebe die größten drei Bremsen. Zeig mir vorher/nachher in Dateien pro Sekunde und MB pro Sekunde.
- Schreib eine LIESMICH.md: Installation, erster Lauf Schritt für Schritt, was jede Einstellung bedeutet, was ich tun soll, wenn etwas abbricht. Für jemanden ohne Programmierkenntnisse.
```

---

## Prompt 7 – Weboberfläche

```
Phase 7 laut SPEC.md Abschnitt 8: Weboberfläche als dünne Schicht über dem bestehenden Kern.

Wichtig, weil eine frühere Version genau daran gescheitert ist:
- Die Seite zeigt nur Zusammenfassungen. Niemals alle Dateien laden oder darstellen.
- Listen nur seitenweise, serverseitig geblättert (z. B. 100 Einträge pro Seite).
- Fortschritt höchstens 1–2 Mal pro Sekunde aktualisieren, zusammengefasst, nicht pro Datei.
- Die Arbeit läuft in einem eigenen Prozess. Browser schließen oder neu laden darf den Lauf nicht stören. Beim Wiederöffnen sieht man den aktuellen Stand aus der Datenbank.
- Leichtgewichtig: FastAPI plus einfache HTML-Seite, kein schweres Frontend-Framework.

Funktionen: Quelle und Ziel wählen, Phasen starten, Kopieren oder Verschieben wählen, Pause und Fortsetzen, Fortschritt mit Durchsatz und Restzeit, Fehler- und Duplikatliste, Kamera-Aliase bearbeiten, Bericht herunterladen. Löschen nur mit Bestätigungsdialog, der Anzahl und Größe nennt.

Test: Oberfläche mit der Datenbank des 50.000-Dateien-Testbaums öffnen und nachweisen, dass sie flüssig bleibt.
```

---

## Prompt 8 – Server (später)

```
Phase 8: Betrieb auf dem TrueNAS-Server.

- Dockerfile und docker-compose.yml (Python, ExifTool, das Programm, Weboberfläche auf einem Port).
- Quelle, Ziel und der Ordner der lokalen Datenbank als eingebundene Pfade (Volumes). Der Ordner .fotosortierer liegt im Ziel und braucht kein eigenes Volume; ein eigenes Volume braucht die Datenbank, weil sie lokal liegt. Benutzer- und Gruppen-ID einstellbar, damit die Dateien auf dem Server dem richtigen Benutzer gehören.
- Prüfe den gesamten Code auf Windows-Annahmen (Pfadtrenner, Groß-/Kleinschreibung von Dateinamen, verbotene Zeichen). Einzige erlaubte Windows-Sonderbehandlung ist das Pfad-Präfix für lange Pfade (\\?\ bzw. \\?\UNC\, SPEC Abschnitt 5), das die 260-Zeichen-Grenze aktiv umgeht; unter Linux greift es nicht.
- Die Datenbank liegt laut SPEC Abschnitt 6 lokal, im Container also in einem eigenen Volume und nie auf einem eingebundenen Netzpfad. Beim Start prüfen und mit verständlicher Meldung abbrechen, wenn der Datenbankpfad auf einem Netzlaufwerk liegt.
- Standardpfad der Datenbank unter Linux: ${XDG_DATA_HOME:-~/.local/share}/fotosortierer/<archiv-id>/. Genau dieser Pfad wird im Container als Volume eingebunden, damit die Datenbank einen Neustart des Containers übersteht. Überschreibbar über den Konfigurationswert datenbank_ort und die Umgebungsvariable FOTOSORT_DATENBANK.
- tzdata als Abhängigkeit aufnehmen und im Image mitliefern, nicht nur für Windows. Sonst hängt die Umrechnung der Video-Zeitstempel davon ab, ob das Container-Image zufällig eine Zeitzonendatenbank mitbringt.
- Anleitung in der LIESMICH.md, wie ich das auf TrueNAS als eigene App einrichte, Schritt für Schritt.
```

---

## Wenn etwas nicht passt

Beschreib Claude Code genau: was du gemacht hast, was passiert ist, was du erwartet hättest. Fehlermeldungen komplett hineinkopieren. Und immer dazusagen: „Schreib zuerst einen Test, der das Problem zeigt, dann behebe es."
