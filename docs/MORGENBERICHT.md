# Morgenbericht – Nacht-Auftrag (v0.4 → v0.5)

**Neues Paket zum Testen:** https://github.com/ludwigpaerschbrandenburg-png/Culling/releases/tag/v0.5
(Datei `fotosort-windows.zip`). Der Zwischenstand v0.4 liegt unter
https://github.com/ludwigpaerschbrandenburg-png/Culling/releases/tag/v0.4.

Alle fünf Teile des Auftrags sind abgearbeitet. Alle Tests sind grün, auf Linux und Windows
(640 Tests). Jeder Teil ist einzeln eingecheckt und hochgeladen.

---

## Was gebaut wurde

**Teil 1 – v0.4 abgeschlossen.** Die Prüfung war zunächst rot (siehe unten), nach der Korrektur
grün. Release v0.4 ist veröffentlicht: das Desktop-Programm mit Qt-Fenster, ohne Browser.

**Teil 2 – Rückmeldungen aus Ihrem Testlauf mit 36.000 Dateien**

- **Keine schwarzen Fenster mehr.** Jedes Hilfsprogramm (die ExifTool-Programme, die während
  der Analyse die Aufnahmedaten lesen, und der Arbeitsprozess hinter dem Fenster) startet
  jetzt unsichtbar – auch aus dem fertigen Paket heraus. Die Ursache war: Ein
  Hilfsprogramm, das aus einem Programm ohne eigenes Konsolenfenster gestartet wird,
  bekommt von Windows ein neues Fenster geschenkt; das passierte je ExifTool einmal.
- **Nicht mehr 32 ExifTool-Programme auf einer Festplatte.** Die Zahl richtet sich jetzt nach
  der Einstellung „Zielordner liegt auf": Festplatte 4, Netzlaufwerk 4, SSD so viele wie
  Prozessorkerne (höchstens 16). Sie starten nacheinander mit kleinem Abstand, nicht alle
  gleichzeitig. Wer es anders will: `fotosort.bat analyse --ziel … --prozesse 2` (oder
  `metadaten_prozesse` in der Einstellungsdatei).
- **Reihenfolge geprüft.** Die Dateien gehen in der Reihenfolge der Quellordner an ExifTool,
  in Paketen zu 200 Dateien gleicher Art – das passt zu einer Festplatte. Messung im
  Container (Dateien im Zwischenspeicher, also nicht wie eine echte Platte): 4 Prozesse
  etwa 1.500 Dateien pro Sekunde, 32 Prozesse etwa 1.000. Mehr Prozesse als Kerne bremsen
  sogar ohne Platte. Was Ihre Festplatte wirklich schafft, zeigt erst der nächste Testlauf.
- **Zwei Rückfragen auf der Startseite.** Wählt man ein ganzes Laufwerk (`C:\`) oder den
  eigenen Benutzerordner als Quelle, fragt das Programm mit Erklärung nach, bevor es den
  Ordner nimmt. Ist der Zielordner nicht leer und noch kein Archiv, fragt „Los geht's", ob es
  dort weitergehen soll.
- **Knopf „Archiv verwerfen…"** auf der Startseite (in der Karte des angefangenen Archivs).
  Er löscht das Gedächtnis des Programms zu diesem Ziel – die Datenbank auf dem Rechner und
  den Ordner `.fotosortierer` im Ziel – **niemals kopierte Fotos, niemals etwas in einer
  Quelle.** Er verlangt das getippte Wort `verwerfen`, geht nicht, solange etwas läuft, und
  weigert sich, wenn in einem der beiden Programmordner eine Bilddatei liegt. Danach ist die
  Startseite leer.
- **Datenmenge je Quelle** zählt nur noch die erfassten Fotos, RAW-Dateien, Videos und
  Sidecars, nicht mehr die „sonstigen" Dateien.

**Teil 3 – Abbrechen, Fenster schließen, Weitermachen.** In jeder Kombination getestet, mit
2.000 eindeutigen Dateien und einem ungestörten Vergleichslauf als Maßstab: Abbrechen mitten
im Kopieren → Fenster zu → neu auf → Weitermachen; das Programm dreimal mitten im Kopieren
hart abgeschossen (wie im Task-Manager) und danach weitergemacht; „Sofort beenden"; Pause →
Fenster zu → neues Fenster übernimmt den angehaltenen Lauf → Fortsetzen; Fenster zu während
des Scans; ein zweites Fenster kann nichts doppelt starten. Ergebnis jedes Mal: Zielordner
Datei für Datei gleich wie beim ungestörten Lauf, keine halben Dateien, nichts doppelt, nichts
verloren, und das Fenster zeigt den richtigen Stand („abgebrochen", „unerwartet beendet" mit
Protokoll, Knopf „Weitermachen" beim richtigen Schritt). **Kein Fehler gefunden.** Eine
Eigenheit, die so bleibt: Pause und Abbrechen greifen bei der nächsten Fortschrittsmeldung,
frühestens eine halbe Sekunde nach der vorigen – ein Schritt, der schneller fertig ist, läuft
einfach zu Ende.

**Teil 4 – Offene Punkte aus der Aufgabenliste (Phase 1–7).**

- Neu gebaut: **Zeitlimit für ExifTool.** Bleibt ExifTool an einer kaputten Datei hängen,
  wartet das Programm gut eine Minute, beendet es, startet es neu und liest die übrigen Dateien
  des Pakets einzeln nach. Nur die eine Datei bekommt den Status „fehler".
- Als erledigt eingetragen, weil inzwischen gebaut oder in der Windows-Prüfung abgedeckt:
  Verschieben (Phase 5), Gruppen-Anhang bei Fremdzugriff (steht im Bericht), Windows-Umbenennen
  (läuft in der Windows-Prüfung mit), Hinweis zur eigenen Ordnervorlage (steht in der
  LIESMICH), Messung der doppelten Lesezeit beim Verschieben (Zahlen stehen in der Liste).
- Offen bleibt, was echte Hardware braucht oder Ihre Entscheidung (siehe unten).

**Prüf-Agent zu Teil 2.** Ein unabhängiger Prüfer hat den Code gelesen und ausprobiert. Kein
Weg, auf dem ein Bild verloren gehen kann. Behoben wurden: „Archiv verwerfen" hätte bei einer
kaputten Datenbank mit einem unverständlichen Fehler versagt (jetzt geht es gerade dann);
eine Verknüpfung an Stelle des Ordners `.fotosortierer` hätte in eine Sackgasse geführt;
Sidecar-Dateien fehlten im Sicherheitsnetz; eine negative Prozesszahl wurde angenommen; die
Rückfrage „Ziel nicht leer" kam vor anderen Prüfungen und damit womöglich zweimal; vier
Stellen in der Dokumentation stimmten nicht mit dem Programm überein. Für jeden Punkt gibt
es einen Test.

---

## Was rot war und behoben ist

- **Beim Abschluss von v0.4:** Die Paket-Prüfung in der Cloud lief gar nicht erst an, weil ein
  Doppelpunkt in einem Schrittnamen die Ablaufdatei ungültig machte; und ein Windows-Test
  öffnete ein echtes Meldungsfenster und wartete ewig auf einen Klick. Beides behoben, danach
  alles grün, dann Release v0.4.
- **In der Nacht:** Ein roter Lauf, und der war wertvoll: Der neue Test für das
  ExifTool-Zeitlimit hing unter Windows fest. Grund: Unter Windows ist `exiftool.exe` nur ein
  kleines Startprogramm, das im Hintergrund `perl.exe` laufen lässt; wer nur das Startprogramm
  beendet, lässt Perl weiterlaufen, und das Programm hätte im Ernstfall ewig auf die Antwort
  gewartet. Jetzt wird bei einem Zeitlimit der ganze Prozessbaum beendet. Ohne die
  Windows-Prüfung wäre das erst bei Ihnen aufgefallen. Ein weiterer Testlauf wurde von der
  Cloud abgebrochen, weil kurz danach schon der nächste Stand hochgeladen wurde – das ist
  normal.

## Was offen ist

- **Der Beweis „keine schwarzen Fenster" steht auf Ihrem PC aus.** Auf dem Prüfrechner in der
  Cloud gibt es keinen Bildschirm; die Fensterwache der Paket-Prüfung meldet dort ehrlich,
  dass sie kein Konsolenfenster beobachten kann. Die Einstellung selbst ist unter Windows
  getestet. Bitte beim nächsten Lauf darauf achten.
- **Geschwindigkeit auf der Festplatte** ist im Container nicht messbar. Wenn die Analyse mit
  4 Prozessen immer noch bei etwa 8 Dateien pro Sekunde liegt, bitte einmal
  `fotosort.bat analyse --ziel D:\Archiv --prozesse 1` gegen `--prozesse 2` vergleichen (die
  Zusammenfassung nennt „Dateien/s") und mir die Zahlen nennen.
- **Netzlaufwerk und zweite Platte** (TrueNAS, exFAT-Karte, zwei Laufwerksbuchstaben auf einer
  Platte) lassen sich nur mit echter Hardware prüfen.
- **Phase 8 (Server im Container)** ist nicht begonnen.

## Entscheidungen, die bei Ihnen liegen

(Alle auch in `docs/todo.md` unter „Entscheidungen für den Nutzer".)

1. **4 ExifTool-Prozesse für Festplatte und Netzlaufwerk** sind eine begründete Schätzung.
   Nach dem nächsten Testlauf: bleibt es bei 4, oder besser 2?
2. **Welche Ordner eine Rückfrage auslösen:** nur ganze Laufwerke, der eigene Benutzerordner
   und der Ordner aller Benutzer. „Dokumente" oder „Downloads" fragen nicht. Reicht das?
3. **„Ziel nicht leer" fragt bei jedem Eintrag im Zielordner,** auch bei einer einzelnen
   `Thumbs.db`. Lieber einmal zu oft?
4. **„Archiv verwerfen" behält die Protokolle** (`arbeit.log`, `fenster.log`) und lässt die
   kopierten Fotos im Ziel liegen. Wer den Zielordner leeren will, tut das selbst.
5. **Gruppenmitglieder, die schon kopiert sind,** bleiben bei einer erneuten Analyse der
   Hauptdatei liegen. Soll das als eigener Eintrag in den Bericht?
6. Aus den Vortagen weiterhin offen: Paketgröße (73 MB durch Qt), zwei Programme im Paket,
   „Weitermachen" scannt nicht neu, Pause-Genauigkeit, „Sofort beenden", Probelauf-Knopf,
   Zusammenfassung ohne Fließtext, Signatur des Programms (SmartScreen), ExifTool-Version
   festnageln.

## So geht der nächste Test

1. Das ZIP von https://github.com/ludwigpaerschbrandenburg-png/Culling/releases/tag/v0.5
   herunterladen und **vollständig entpacken**, zum Beispiel nach `C:\fotosort` (ein Ordner
   mit Leerzeichen oder Klammern im Namen ist auch erlaubt).
2. `start.bat` doppelklicken. Es öffnet sich das Programmfenster. SmartScreen: „Weitere
   Informationen" → „Trotzdem ausführen" (das Programm ist nicht signiert).
3. Im Fenster: Zielordner wählen, Quelle hinzufügen, „Los geht's". Bitte zuerst wieder mit
   Kopien arbeiten.
4. Darauf achten: **kein schwarzes Fenster** während der Analyse; in der Zusammenfassung nach
   der Analyse die Zeile „Dateien/s"; die Rückfragen beim Wählen eines ganzen Laufwerks;
   „Archiv verwerfen…" auf der Startseite, wenn ein Probe-Archiv weg soll.
5. Wenn etwas klemmt: Das Protokoll liegt unter
   `C:\Users\<Name>\AppData\Local\fotosortierer\oberflaeche\arbeit.log` (Arbeitsprozess) und
   `fenster.log` (Fenster). Den Text der Meldung und die letzten Zeilen daraus genügen mir.

Die Befehle, mit denen sich alles selbst prüfen lässt (Linux-Container, künstlicher Testbaum):

```
cd /home/user/Culling
PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_unterbrechungen.py
```
