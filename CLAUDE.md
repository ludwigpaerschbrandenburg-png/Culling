# Projektregeln – Foto-Sortierer

Diese Regeln gelten dauerhaft für jede Arbeit an diesem Projekt.

Verbindliche Projektbeschreibung: [`docs/SPEC.md`](docs/SPEC.md).
Bei einem Widerspruch zwischen einem Prompt und der SPEC: **nachfragen, nicht raten.**
Protokoll der entschiedenen Punkte aus der SPEC-Prüfung: [`docs/offene_fragen.md`](docs/offene_fragen.md).

## 1. Oberste Regel

**Es darf niemals ein Bild verloren gehen.** Geschwindigkeit kommt immer danach.

Konkret heißt das:

- Nie eine bestehende Datei überschreiben. Bei Namenskonflikt: neuer Name, nie ersetzen.
- Nie löschen, was nicht durch einen Hash-Vergleich als im Ziel vorhanden nachgewiesen ist.
- Nie auf Basis von Dateiname oder Größe allein löschen.
- Kopieren immer über eine `.part`-Datei mit anschließendem atomaren Umbenennen.
- Im Zweifel: abbrechen und fragen, nicht weitermachen.
- Gelöscht werden darf **ausschließlich** aus den Status `geprüft` und `duplikat_bestaetigt`.
  Kein anderer Status berechtigt zum Löschen.
- `duplikat_bestaetigt` setzt voraus, dass die Zieldatei **im aktuellen Lauf** vollständig neu
  gelesen und ihr Hash mit dem der Quelle verglichen wurde. Ein Hash aus einem früheren Lauf
  genügt nicht.
- Der Ziel-Index rechtfertigt **nie allein** eine Löschung. Er dient nur dazu, Kandidaten für
  Duplikate schnell zu finden.
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

- Windows 11 jetzt, Linux im Docker-Container später. Von Anfang an beides im Blick.
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
