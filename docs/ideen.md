# Ideensammlung: Was professionelle Culling-Software kann

Stand 26.10.2026, Auftrag des Nutzers: „alles, was professionelle Culling-Software kann,
soll diese Software können“. Grundlage für die Runden 3a–3f (`docs/todo.md`).
Die Regeln aus `CLAUDE.md` gelten für jede Idee unverändert: nie ein Bild verlieren, nie
überschreiben, löschen nur nach frischem Prüfsummen-Vergleich.

## Teil 1: Was professionelle Software kann

Verglichen mit Photo Mechanic, Lightroom Classic (Import/Bibliothek), Capture One, Narrative Select, AfterShoot, FilterPixel, Excire, digiKam, Mylio, Immich und PhotoPrism.

Zeichen: ✅ gebaut · ◐ teilweise · ○ fehlt

### A. Programm-Verhalten
- ◐ Öffnen per Doppelklick, ein Fenster. Schließen beendet heute aber nicht.
- ○ **Schließen = aus**: der laufende Schritt hält sicher an, die Datenbank bleibt in Ordnung, und beim nächsten Start geht es dort weiter.
- ○ Nur eine Instanz zugleich; ein zweiter Start holt das offene Fenster nach vorn.
- ○ Einstellungen im Fenster statt in `config.toml`.
- ✅ Komplett offline, nichts geht ins Internet.
- ○ Die Browser-Fassung gibt es unter Windows nicht mehr, nur später auf TrueNAS.
- ○ Fortschritt in der Taskleiste (grüner Balken im Symbol).
- ○ Ruhezustand von Windows verhindern, solange gearbeitet wird.

### B. Tempo / Prozessor
- ○ **Alle Kerne für Rechenarbeit**: Prüfsummen, Vorschaubilder, Bildanalyse.
- ◐ Plattenzugriffe je Laufwerk passend dosieren (Profil). Auf einer Festplatte bremsen viele gleichzeitige Leser – Rechnen und Lesen werden deshalb getrennt.
- ○ Vorschaubilder einmal erzeugen und auf der Platte zwischenspeichern.
- ○ Vorab laden: die nächsten Bilder liegen schon bereit.
- ○ Hintergrund-Indexierung, während man schon sichtet.

### C. Ordnerstrukturen verstehen (Wunsch des Nutzers, Kern dieser Runde)
- ○ **Datum in jeder Schreibweise im Ordnernamen erkennen**:
  - `2021.01`, `2021-01`, `2021_01_15`, `01.2021`, `15.01.2021`, `20210115`;
  - `Januar 2021`, `Jan 2021`;
  - `2021/01/15` über mehrere Ebenen;
  - Ereignisse mit Datum: `2021-01-15 Hochzeit`;
  - Bereiche: `2021-07-01 bis 14 Italien`.
- ○ **Bestehendes Schema des Archivs lernen** und als Vorlage vorschlagen, z. B. „Ihr Archiv ist nach `Jahr/Jahr.Monat` sortiert – so weitermachen?“.
- ○ **Neue Bilder in vorhandene Ordner anderer Schreibweise einsortieren**: Januar 2021 kommt nach `2021.01`, nicht daneben.
- ○ **„Liegt schon richtig“ erkennen**:
  - Eine Datei liegt in einem Ordner, dessen Datum zu ihrem Aufnahmedatum passt. Dann bleibt sie, wo sie ist, und ist erledigt.
  - In der Quelle: Ein schon sortierter Ordner wird nicht noch einmal umsortiert.
- ○ **Falsch einsortiert erkennen**: Ordner sagt März, Bild ist vom Mai. Das wird gemeldet und eine Verschiebung vorgeschlagen, nie stillschweigend.
- ○ Ereignisordner über mehrere Tage erkennen. Bilder, die zeitlich in eine Reise fallen, gehören in den Reiseordner.
- ○ Ordner ohne Datum (`Hochzeit Anna`): Datum aus dem Inhalt schätzen und anzeigen.
- ○ **Umbau-Vorschlag mit Vorschau**:
  - „So sähe Ihr Archiv danach aus“, als Baum vorher/nachher.
  - Übernehmen nur nach Bestätigung, mit Protokoll und Rückgängig.
- ○ Ganze Ordner, die schon vollständig im Archiv liegen, erkennen (Prüfsummen).
- ○ Ordnerarten erkennen und getrennt behandeln:
  - Exporte (bearbeitete, verkleinerte JPGs);
  - Lightroom-, Capture-One- und darktable-Kataloge;
  - WhatsApp-, Screenshot- und Download-Ordner;
  - Backups von Handys.

### D. Datum und Zeit
- ✅ Datum aus EXIF, Video, Dateiname, XMP; Zeitzone; „Datum auffällig“.
- ○ **Kamerauhr korrigieren**: „Diese Kamera ging 1 h 12 min nach“ – für alle Bilder dieser Kamera an diesem Tag.
- ○ Mehrere Kameras über ein gemeinsames Motiv abgleichen.
- ○ Zeitzone je Reise oder aus GPS.
- ○ Datum aus Dateinamen von WhatsApp, Signal und Screenshots (`IMG-20210115-WA0003`).
- ○ Gescannte Bilder ohne Datum: Datum von Hand setzen, ohne die Datei zu verändern (als Notiz).

### E. Doppelte und Ähnliche
- ✅ Exakt gleiche Dateien (Prüfsumme).
- ○ **Fast gleiche** (Wahrnehmungs-Prüfsumme): dasselbe Bild verkleinert, neu gespeichert, WhatsApp-Kopie, Export.
- ○ Serien und Burst-Aufnahmen gruppieren; ähnliche Motive stapeln.
- ○ Bestes Bild einer Serie vorschlagen (siehe F).
- ○ Kopien aus Downloads erkennen (`Bild (1).jpg`, `-Kopie`, `_bearbeitet`).

### F. Sichten (Culling im engeren Sinn)
- ✅ Ordnerbaum, Vorschau, Sterne 0–5, Auswahl/Ausschuss, Filter, große Ansicht, RAW-Vorschau.
- ○ Farbmarken (5 Farben) wie in Lightroom.
- ○ **Vergleichsansicht**: 2–4 Bilder nebeneinander, Zoom 100 % gleichzeitig.
- ○ Lupe 100 % mit einem Tastendruck; Gesichter vergrößern.
- ○ Automatisch weiter nach der Bewertung (einstellbar).
- ○ Anzeigen beim Sichten:
  - Kameradaten (Blende, Zeit, ISO, Objektiv) und Histogramm;
  - Warnung bei Über- und Unterbelichtung;
  - Schärfe-Anzeige (Fokus-Peaking).
- ○ Stapel: RAW+JPG ✅, Serien, Belichtungsreihen (HDR), Panorama.
- ○ Videos abspielen und vorspulen; Live Photos (HEIC + MOV) als eine Aufnahme.
- ○ Vollbild, zweiter Bildschirm, Diashow.
- ○ Tasten frei belegen.
- ○ Suchen und Filtern:
  - Filter nach Kamera, Objektiv, Datum, Bewertung, Farbe, Stichwort;
  - gespeicherte Filter („Smart-Sammlungen“).
- ○ Zeitleiste und Kalenderansicht, Statistik (Bilder je Jahr, je Kamera).

### G. Hilfe durch Bildanalyse (lokal, offline, auf allen Kernen)
- ○ Unscharf, verwackelt, Augen zu, über- oder unterbelichtet erkennen.
- ○ Bestes Bild einer Serie vorschlagen.
- ○ Vorschlag „Ausschuss“ – nur ein Vorschlag, der Nutzer entscheidet.
- ○ Gesichter finden; Personen wiedererkennen, mit Namen versehen.
- ○ Inhalte erkennen (Strand, Hund, Schnee) als Stichworte, um zu suchen.
- ○ Ähnlichkeitssuche „mehr wie dieses“.
- Braucht Bildanalyse-Modelle als Dateien (einige hundert MB), die einmal ins Paket kommen. Laufen nur auf dem Rechner, nie im Internet.

### H. Metadaten
- ○ **Bewertungen, Farben und Stichworte als XMP-Datei neben dem Bild**:
  - Lightroom, Capture One und darktable sehen sie;
  - ein vorhandenes XMP wird gelesen;
  - geschrieben wird nur das XMP, nie das Bild.
- ○ Copyright, Name und Stichworte beim Übernehmen eintragen (IPTC-Vorlage, als XMP).
- ○ Geotagging aus einer GPX-Spur; Ortsnamen offline aus GPS, z. B. als Ordnername „Rom“.
- ○ Karte mit allen Aufnahmeorten.

### I. Übernehmen (Import) – stark vorhanden
- ✅ Mehrere Quellen, Prüfsummen, `.part`-Kopie, Prüfen, Aufräumen, Zurücklegen, Bericht, fortsetzbar.
- ○ **Speicherkarte erkennen**, sobald sie eingesteckt wird, und den Import anbieten. Nur neue Bilder seit dem letzten Mal ✅ (Datenbank).
- ○ **Zwei Ziele zugleich** (Archiv + Sicherungsplatte), beide geprüft.
- ○ Umbenennen nach Muster beim Übernehmen, z. B. `2021-01-15_Hochzeit_0001.CR3`, mit Rückgängig-Liste.
- ○ Karte nach geprüfter Kopie auswerfen.

### J. Ausgeben
- ○ Auswahl in einen Ordner kopieren (für Kunden, zum Bearbeiten).
- ○ Verkleinerte JPGs zum Teilen.
- ○ Kontaktabzug als PDF; Liste der Auswahl als CSV.
- ○ Ausschuss: verschieben in `_Ausschuss` oder löschen. Dafür braucht es eine neue Regel in CLAUDE.md – Entscheidung des Nutzers (Frage 4).

### K. Sicherheit (Stärke dieses Programms, bleibt)
- ✅ Nie überschreiben, Hash vor jedem Löschen, Prüfsummen-Liste, Archiv nachprüfen, Sicherung der Datenbank, Bericht.
- ○ Jede Änderung im Archiv kommt in ein Protokoll mit „Rückgängig“: Umbau, Umbenennen, Ausschuss.
- ○ `bewertungen.db` mit ins Ziel sichern.

---

## Teil 2: Reihenfolge der Umsetzung (Vorschlag, je Runde Test zuerst, Prüfer, CI, Release)

**Runde 3a – die drei Grundwünsche (zuerst):**
1. **Schließen = aus.**
   - Der Arbeitsprozess hängt am Fenster. Beim Schließen bekommt er „sicher anhalten“: die aktuelle Datei fertig, die Datenbank geschrieben.
   - Das Fenster wartet sichtbar „wird beendet …“, dann ist alles aus.
   - Beim nächsten Start geht es dort weiter.
   - Betrifft `ablauf.py` (`_losgeloest`, Lauf-Übernahme in `_laden`), `prozesse.py`, `desktop.py` (`closeEvent`), SPEC §8.
2. **Eine Instanz:** Ein zweiter Doppelklick holt das offene Fenster nach vorn.
3. **Alle Kerne:**
   - Rechenarbeit (BLAKE3-Prüfsummen, Vorschaubilder) läuft auf allen Kernen.
   - Das Lesen von der Platte bleibt je Laufwerk dosiert: getrennte Leser- und Rechner-Stränge in `kopieren.py`, `pruefen.py`, `nachpruefen.py`, `zielindex.py`.
   - `worker_zahlen` und `HASH_JE_PROFIL` werden angepasst; vorher und nachher messen (`messen.py`, `tests/tempo_analyse.py`).
4. **Ordnerstrukturen verstehen:**
   - Neues Modul `strukturen.py`: Datum aus Ordnernamen in allen Schreibweisen, über mehrere Ebenen.
   - `ziel.py` nutzt es, damit neue Bilder in vorhandene Ordner anderer Schreibweise einsortiert werden.
   - In der Quelle: eine Datei in einem passend datierten Ordner gilt als „liegt schon richtig“.
   - Das genaue Verhalten folgt aus Frage 2.
   - Schema-Erkennung des Archivs mit Vorschlag auf der Startseite; Bericht „liegt schon richtig“ und „passt nicht zum Ordner“.

**Runde 3b – Sichten wie ein Profi:** Vergleichsansicht, Lupe, Farbmarken, Kameradaten-Leiste, automatisch weiter, Vorschau-Zwischenspeicher, Vorab-Laden, Video abspielen, Live-Photo-Paare, Burst-Stapel, XMP schreiben und lesen, Tasten frei belegen.

**Runde 3c – Doppelte und Ähnliche:** Wahrnehmungs-Prüfsumme, fast gleiche Bilder, Kopien aus Downloads, ganze Ordner schon im Archiv, Serien.

**Runde 3d – Struktur umbauen:** Umbau-Vorschlag mit Vorher/Nachher-Baum, Protokoll und Rückgängig. Verschoben wird nur nicht überschreibend, im selben Archiv. Dazu falsch einsortierte Bilder melden und Kamerauhr korrigieren.

**Runde 3e – Bildanalyse (lokal):** Schärfe, Augen, Belichtung, bestes Bild der Serie, Gesichter, Stichworte. Nur nach Frage 3.

**Runde 3f – Import und Ausgabe:** Karte erkennen, zwei Ziele, Umbenennen nach Muster, Export der Auswahl, verkleinerte JPGs, Kontaktabzug, Einstellungen im Fenster.

Jede Runde endet mit Tests, Prüfern, CI (Linux, Windows, Paket), Release und einem Bericht in einfachen Worten mit den Befehlen zum Ausprobieren.

---

## Entscheidungen des Nutzers (26.10.2026)

1. **Schließen während eines Schritts:**
   - Kurze Rückfrage „Es läuft noch ein Schritt – wirklich beenden?“.
   - Bei Ja: die aktuelle Datei sauber fertig, alles gespeichert, Programm aus.
   - Beim nächsten Öffnen geht es dort weiter.
2. **Schon vorhandene Bilder:**
   - Bilder der Quelle, die schon im Archiv liegen, egal in welchem Ordner oder welcher Schreibweise (`2021.01`), werden nur gemeldet: „So und so viele Bilder dieser Quelle sind bereits importiert“. Sonst geschieht mit ihnen nichts.
   - Die Meldung kommt früh: nach Scan und Analyse aus Größe, Datum und Ziel-Index geschätzt, nach dem Kopieren über Prüfsummen sicher.
   - Sie erscheint je Quelle in der Zusammenfassung, im Fenster und im Bericht.
   - Neue Bilder kommen ins Archiv, in einen vorhandenen Ordner passender Schreibweise.
3. **Bildanalyse:** ja, als eigene spätere Runde (3e).
4. **Ausschuss:**
   - Auf Knopfdruck mit Bestätigungswort in einen Ordner `_Ausschuss` im Archiv verschieben – nie überschreiben, rückgängig machbar.
   - Gelöscht wird nie.
   - Dafür kommt eine neue Regel in CLAUDE.md (Runde 3d): verschoben wird nur nicht überschreibend, innerhalb des Archivs, mit Protokoll.
