# Prompts für Claude Code – Foto-Sortierer

## Vorbereitung (einmalig)

1. Leeren Ordner anlegen, z. B. `C:\Projekte\fotosortierer`.
2. Die Datei `SPEC.md` in diesen Ordner legen.
3. ExifTool installieren (exiftool.org) und Python 3.12 oder neuer.
4. In dem Ordner Claude Code starten.
5. Die Prompts unten **einzeln und der Reihe nach** eingeben. Erst weitermachen, wenn die Phase läuft und die Tests grün sind. Nach jeder Phase selbst kurz ausprobieren.

Warum in Phasen: Ein einziger Riesen-Prompt führt zu einem halb fertigen Alles. Phasen liefern jedes Mal etwas, das nachweislich funktioniert.

---

## Prompt 0 – Einlesen und Plan (noch kein Code)

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
- SQLite-Datenbank (WAL) mit dem Schema für Dateien, Status und Ziel-Index.
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
- Datumsermittlung exakt in der Reihenfolge aus SPEC Abschnitt 3, inklusive kaputter Daten, Video-UTC, Datum aus Dateinamen, unsicheres Datum, Tagesgrenze.
- Kamera-Ordner über die Alias-Tabelle, inklusive Scanner → Analog und Unbekannte_Kamera.
- Zusammengehörige Dateien (RAW+JPG, Sidecars) als Gruppe behandeln.
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
- Quell-Hash während des Kopierens mitberechnen (xxh3_128 oder blake3, Blöcke >= 1 MiB).
- Niemals überschreiben. Gleicher Name + gleicher Hash = Duplikat. Gleicher Name + anderer Inhalt = Anhang _1, _2, für die ganze Dateigruppe gleich.
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
- "fotosort pruefen": jede Zieldatei vollständig neu lesen, Hash mit Quell-Hash vergleichen, Status "geprüft" oder "fehler" setzen. Parallel, fortsetzbar.
- "fotosort bericht": Text- und CSV-Bericht nach SPEC Abschnitt 10.
- "fotosort status": jederzeit aufrufbar, zeigt Zähler je Status und die aktuelle Phase.

Test: Eine Zieldatei nach dem Kopieren absichtlich verändern, die Prüfung muss sie finden und melden.
```

---

## Prompt 5 – Verschieben, Quelle aufräumen, leere Ordner

```
Phase 5 laut SPEC.md: alles, was löscht. Hier besonders vorsichtig arbeiten.

Baue:
- "fotosort kopieren --verschieben": pro Datei kopieren, prüfen, erst dann Quelle löschen. Auf demselben Laufwerk direkt umbenennen.
- "fotosort aufraeumen": löscht in der Quelle ausschließlich Dateien mit Status "geprüft" (und Duplikate, deren Inhalt nachweislich per Hash im Ziel liegt). Vorher Anzahl und Größe anzeigen und ausdrücklich bestätigen lassen. --dry-run zeigt die Liste.
- "fotosort aufraeumen --leere-ordner": nur wirklich leere Ordner entfernen, Reste-Dateien laut Konfiguration zählen als leer. Quell-Wurzelordner bleibt stehen.
- Direkt vor jedem Löschen noch einmal prüfen, dass die Zieldatei existiert und die Größe stimmt.

Pflicht-Tests:
- Ungeprüfte Datei wird nie gelöscht, auch nicht mit Gewalt-Optionen.
- Datei, deren Zielkopie fehlt oder verändert wurde, wird nicht gelöscht.
- Ordner mit einer einzigen nicht erfassten Datei (z. B. .txt) bleibt stehen.

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
- Quelle, Ziel und der Ordner .fotosortierer als eingebundene Pfade (Volumes). Benutzer- und Gruppen-ID einstellbar, damit die Dateien auf dem Server dem richtigen Benutzer gehören.
- Prüfe den gesamten Code auf Windows-Annahmen (Pfadtrenner, Groß-/Kleinschreibung von Dateinamen, verbotene Zeichen).
- Anleitung in der LIESMICH.md, wie ich das auf TrueNAS als eigene App einrichte, Schritt für Schritt.
```

---

## Wenn etwas nicht passt

Beschreib Claude Code genau: was du gemacht hast, was passiert ist, was du erwartet hättest. Fehlermeldungen komplett hineinkopieren. Und immer dazusagen: „Schreib zuerst einen Test, der das Problem zeigt, dann behebe es."
