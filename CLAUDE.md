# Projektregeln – Foto-Sortierer

Diese Regeln gelten dauerhaft für jede Arbeit an diesem Projekt.

Verbindliche Projektbeschreibung: [`docs/SPEC.md`](docs/SPEC.md).
Bei einem Widerspruch zwischen einem Prompt und der SPEC: **nachfragen, nicht raten.**
Protokoll der entschiedenen Punkte aus der SPEC-Prüfung: [`docs/offene_fragen.md`](docs/offene_fragen.md).

## 1. Oberste Regel

**Es darf niemals ein Bild verloren gehen.** Geschwindigkeit kommt immer danach.

Konkret heißt das:

- Nie eine bestehende Datei überschreiben. Bei Namenskonflikt: neuer Name, nie ersetzen.
- **Umbenennen darf nie überschreiben** — weder beim Verschieben auf demselben Laufwerk noch
  beim Umbenennen der `.part`-Datei. Nicht `os.rename` oder `Path.rename`, sondern ein
  nicht überschreibendes Verfahren.
- Nie löschen, was nicht durch einen Hash-Vergleich als im Ziel vorhanden nachgewiesen ist.
- Nie auf Basis von Dateiname oder Größe allein löschen.
- Kopieren immer über eine `.part`-Datei mit anschließendem atomaren Umbenennen.
- Im Zweifel: abbrechen und fragen, nicht weitermachen.
- Gelöscht werden darf **ausschließlich** aus den Status `geprueft` und `duplikat_bestaetigt`.
  Kein anderer Status berechtigt zum Löschen.
- Diese Statusregel gilt für Quelldateien aus dem Bestand der Datenbank. Ausgenommen sind
  allein zwei Arten von Dateien, die nie in der Datenbank stehen: die Reste-Dateien aus
  SPEC §4 Phase 6 (`Thumbs.db`, `.DS_Store`, `desktop.ini`, konfigurierbar) und
  liegengebliebene `.part`-Dateien. Weitere Ausnahmen gibt es nicht.
- Die Reste-Ausnahme wird **geprüft, nicht geglaubt.** Eine Datei gilt nur dann als Rest, wenn
  es für sie keine Zeile in der Datenbank mit einem echten Dateityp (Foto, RAW, Video,
  Sidecar) gibt. Das stellt das Programm vor jeder einzelnen Löschung selbst fest. Sonst
  könnte ein Eintrag wie `.jpg` in der Liste die ganze Löschregel aushebeln.
- Der Status allein genügt nie. Vor **jeder** Löschung werden **Quelldatei und Zieldatei**
  im aktuellen Lauf vollständig neu gelesen und beide Hashes mit dem gespeicherten Quell-Hash
  verglichen — bei `geprueft` genauso wie bei `duplikat_bestaetigt`. Ein Hash aus einem
  früheren Lauf genügt für keinen von beiden.
- **Auch die Quelle wird frisch gelesen, nicht nur das Ziel.** Würde nur das Ziel gelesen und
  gegen den beim Kopieren gespeicherten Quell-Hash gehalten, beschrieben beide Werte denselben
  alten Stand; eine nach dem Kopieren geänderte Quelldatei würde gelöscht, obwohl ihr aktueller
  Inhalt nie im Ziel ankam. Weicht der frisch gelesene Quell-Hash vom gespeicherten ab, wird
  **nicht** gelöscht: Die Datei fällt auf Status `analysiert` zurück und muss neu kopiert
  werden.
- Die Statuswerte werden **umlautfrei** gespeichert: `gefunden`, `analysiert`, `kopiert`,
  `geprueft`, `verschoben`, `duplikat`, `duplikat_bestaetigt`, `quelle_geloescht`,
  `uebersprungen`, `fehler`. Wer eine Statusprüfung schreibt, vergleicht gegen genau diese
  Zeichenketten. Andere Schreibweisen gibt es nicht.
- Der Ziel-Index rechtfertigt **nie allein** eine Löschung. Er dient nur dazu, Kandidaten für
  Duplikate schnell zu finden.
- Vor jeder Löschung werden **Quelle UND Ziel** im aktuellen Lauf frisch gelesen. Nur das Ziel
  zu prüfen genügt nicht: Der gespeicherte Quell-Hash beschreibt denselben alten Stand wie die
  Zieldatei, eine nach dem Kopieren geänderte Quelle fiele nicht auf und würde gelöscht.
- Diese Bedingung gilt für **jeden** Löschvorgang, auch für den im Verschieben-Modus, der schon
  in Phase 3 stattfindet — nicht nur für Phase 5.
- Unter dem endgültigen Zielnamen wird **nie** etwas gelöscht, nur weil ein Status fehlt.
  Status fallen zurück; dort könnte ein fertiges Archivbild liegen.
- Gehasht wird durchgehend mit **BLAKE3** — im ganzen Projekt dasselbe Verfahren.

## 2. Testen

- **Nie mit echten Fotos testen.** Ausschließlich der künstliche Testbaum aus SPEC §11.
- Entwicklung und Tests laufen im Linux-Container mit diesem künstlichen Testbaum.
  ExifTool ist dort installiert.
- Nach jeder Änderung die Tests laufen lassen.
- **Nichts als fertig melden, was nicht getestet ist.** Kein „sollte jetzt funktionieren".
- Bei einem Fehler zuerst einen Test schreiben, der ihn zeigt, dann beheben.
- Alles, was löscht oder verschiebt, braucht einen Test, der beweist, dass es sich weigert,
  wenn die Voraussetzungen nicht erfüllt sind.

## 3. Plattform

- Entwickelt und getestet wird **jetzt im Linux-Container** (SPEC §11, künstlicher Testbaum).
  Windows 11 ist die erste Nutzung mit echten Fotos, danach folgt TrueNAS im Container.
  Alle drei Umgebungen von Anfang an im Blick.
- Ausschließlich `pathlib`. Keine fest eingebauten Pfade, keine Windows-Sonderwege,
  keine Annahme über Pfadtrenner oder Groß-/Kleinschreibung von Dateinamen.
- Quelle und Ziel können lokale Platten, externe SSDs oder SMB-Netzlaufwerke sein.
  Netzlaufwerke verhalten sich anders als lokale Platten — besonders beim Sperren von Dateien.
- Lange Pfade unter Windows werden **aktiv umgangen**, nicht nur gemeldet: intern mit dem
  Präfix `\\?\` angesprochen, bei Netzpfaden mit `\\?\UNC\`. Ein Fehler „Pfad zu lang"
  nur, wenn es trotzdem scheitert.
- Die Datenbank liegt **immer lokal**, nie auf einem Netzlaufwerk.

## 4. Sprache

- Alle Ausgaben, Meldungen, Fehlertexte und Dokumentation auf **Deutsch**.
- Code, Bezeichner und Kommentare dürfen Englisch sein.
- Deutsche Texte an einer Stelle sammeln, nicht im Code verstreuen.

## 5. Arbeitsweise

- **In Phasen arbeiten.** Die Phasen stehen in [`docs/PROMPTS.md`](docs/PROMPTS.md).
  Nie über die aktuelle Phase hinausbauen, auch nicht „schon mal vorbereitend".
- Am Ende jeder Phase: Tests grün, und die genauen Befehle nennen, mit denen sich das
  Ergebnis selbst ausprobieren lässt.

## 6. Erklären

Der Nutzer ist kein Programmierer.

- Ergebnisse und Bedienung ohne Fachbegriffe erklären.
- Wenn ein Fachbegriff unvermeidlich ist, in einem Halbsatz erklären, was er bedeutet.
- Keine Code-Auszüge als Antwort auf „funktioniert es?" — sondern sagen, was passiert ist.
