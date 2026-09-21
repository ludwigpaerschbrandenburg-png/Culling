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
- Plattformneutral (Entwicklung und Tests unter Linux im Container, erste Nutzung mit echten Fotos unter Windows, späterer Betrieb auf dem Server), nur pathlib.
- Alle Meldungen auf Deutsch, Code und Kommentare dürfen Englisch sein.
- Nach jeder Änderung Tests laufen lassen. Nichts als fertig melden, was nicht getestet ist.
- In Phasen arbeiten, nie über die aktuelle Phase hinaus bauen.
- Ich bin kein Programmierer: erkläre mir Ergebnisse und Bedienung einfach und ohne Fachbegriffe.
```

---

## Prompt 1 – Grundgerüst, Testbaum, Scan

```
Phase 1 laut SPEC.md: Grundgerüst.

Verbindlich ist SPEC.md. Für den Modulzuschnitt und den Paketnamen src/fotosort/ gilt zusätzlich docs/architektur.md Abschnitt 1, für die Abhängigkeiten Abschnitt 3. Beides steht nur dort und nicht in der SPEC. Erfinde keine eigene Struktur und nimm keine weiteren Bibliotheken dazu.

Baue:
- Projektstruktur und pyproject.toml nach docs/architektur.md Abschnitt 1 und 3. Kommandozeile "fotosort" mit den Unterbefehlen aus SPEC Abschnitt 8 (noch leer, außer scan und status).
- Jeder Befehl außer --help braucht --ziel, ersatzweise die Umgebungsvariable FOTOSORT_ZIEL; die Angabe auf der Kommandozeile hat Vorrang, fehlt beides, bricht der Befehl mit verständlicher Meldung ab (SPEC Abschnitt 8). Nur scan braucht zusätzlich --quelle; die Quelle wird in der Datenbank gespeichert und muss bei den folgenden Befehlen nicht wiederholt werden. Dazu bei jedem Befehl der Schalter --config <pfad>.
- config.toml, beim ersten Scan mit Kommentaren erzeugt. Sie liegt im Archiv-Ordner neben der Datenbank (SPEC Abschnitt 6, "Konfigurationsdatei"). Welche Werte darin stehen, mit Schlüsselnamen, Kurzbeschreibung und Standardwert, steht vollständig in SPEC Abschnitt 9; nimm sie von dort und erfinde keine weiteren. Weil die Konfiguration im Archiv liegt, kann jedes Archiv eigene Kamera-Aliase haben; das ist gewollt.
- Eine vorhandene config.toml wird nie überschrieben und nie umgeschrieben: Fehlende Werte werden beim Lesen im Speicher mit den Standardwerten ergänzt, ohne die Datei anzufassen. Unbekannte Werte bleiben stehen und werden einmal je Lauf gemeldet, damit ein Tippfehler im Schlüsselnamen sichtbar bleibt. Mit --config <pfad> lässt sich eine andere Datei angeben.
- Achtung, hier ist die Bauweise eine andere als sonst: tomli-w kann keine Kommentare schreiben. Die kommentierte Datei entsteht deshalb nicht aus tomli-w, sondern aus einer Vorlage im Code, in der Kommentartext und Wert je Schlüssel nebeneinander stehen. Aus derselben Vorlage kommen auch die Standardwerte, die beim Lesen ergänzt werden, damit Datei und Programm nicht auseinanderlaufen.
- SQLite-Datenbank (WAL) mit dem vollständigen Schema aus SPEC Abschnitt 6 ("Tabellen und Spalten"): die drei Tabellen mit allen dort aufgezählten Spalten, auch denen, die erst spätere Phasen füllen. Die Metadaten bekommen eigene Spalten, kein JSON-Feld. Die gespeicherten Statuswerte lauten genau wie in SPEC Abschnitt 6, ohne Umlaute. Die Datenbank liegt laut SPEC Abschnitt 6 immer lokal, nie auf einem Netzlaufwerk; im Ziel liegen unter .fotosortierer/ nur die Archiv-ID, die Berichte und nach jeder abgeschlossenen Phase eine Sicherungskopie der Datenbank.
- Lauf-Verwaltung: Ein Lauf ist ein Programmstart (SPEC Abschnitt 6, "Was ein Lauf ist"). Jeder Start legt eine Zeile in der Tabelle laeufe an, beim Beenden wird dort das Ende eingetragen. Die Lauf-Nummer brauchen die späteren Phasen; der Scan trägt sie schon jetzt in die dafür vorgesehenen Spalten ein.
- Archiv-ID nach SPEC Abschnitt 6 ("Archiv-ID"): Form, Ort, Dateiname und Kodierung stehen dort. Beim ersten Scan eines Ziels anlegen, sonst lesen. Ist die Datei vorhanden, aber ihr Inhalt keine gültige ID, mit verständlicher Meldung abbrechen und Datei und Inhalt nennen; niemals eine neue ID erzeugen. Über die ID wird der Archiv-Ordner und darüber die lokale Datenbank wiedergefunden.
- Archiv-Ordner mit der Datenbank und der Konfiguration. Die Namen der Datenbankdatei und der Sicherungsstände im Ziel stehen in SPEC Abschnitt 6 ("Ort der Datenbank", "Sicherungskopie der Datenbank"); nimm sie genau von dort. Vorrang beim Ort: Umgebungsvariable, dann Konfigurationswert, dann Standardpfad des Betriebssystems (SPEC Abschnitt 6).
- Nach jeder abgeschlossenen Phase eine Sicherungskopie der Datenbank über die SQLite-Backup-Funktion ins Ziel schreiben, in den Schritten aus SPEC Abschnitt 6 ("Sicherungskopie der Datenbank"): erst die neue Fassung schreiben, dann den bisherigen Stand umbenennen, dann die neue atomar an ihren Platz. Es gibt genau zwei Stände, keine weitere Versionierung. Nie direkt in einer Datenbank auf dem Netzlaufwerk arbeiten.
- Prüfung, ob der Datenbankpfad auf einem Netzlaufwerk liegt. Die Liste der als Netz geltenden Dateisystemtypen steht in SPEC Abschnitt 6. Wenn ja, mit verständlicher Meldung abbrechen.
- Findet das Programm im Ziel eine Archiv-ID, aber keine zugehörige lokale Datenbank, während im Ziel eine Sicherungskopie liegt: mit verständlicher Meldung abbrechen und auf "fotosort wiederherstellen" hinweisen. Niemals stillschweigend eine leere Datenbank anlegen, sonst gilt das Ziel als leer und alles wird erneut kopiert.
- Das Skript, das den künstlichen Testbaum erzeugt (SPEC Abschnitt 11), mit allen dort genannten Sonderfällen. Ausdrücklich dazu: ein Video mit Zeitzonen-Offset und eines ohne, letzteres so gewählt, dass die Umrechnung den Tag wechselt; das Sony-Paar aus Video und zugehörigem XML-Sidecar; beide einfachen Sidecar-Schreibweisen zur selben Hauptdatei; ein im Ziel bereits belegter Zielname mit anderem Inhalt; eine Datei, deren Quelle sich nach dem Kopieren ändert; ein Ordner, auf den nur eine Verknüpfung zeigt; ein Pfad, den ein Ausschlussmuster trifft.
- "fotosort scan": Quelle rekursiv mit os.scandir durchlaufen, Dateien nach Typ zählen, Gesamtgröße, in die Datenbank schreiben. Fortschritt anzeigen. Abbrechbar und fortsetzbar.
- Fortsetzbar heißt genau das aus SPEC Abschnitt 6 ("Zweiter Scan"): eine Zeile je Quellpfad, der Quellpfad ist eindeutig. Sind Größe und Änderungsdatum unverändert, bleibt die Zeile, wie sie ist. Sind sie verändert, fällt der Status auf gefunden zurück, Hash und Zielpfad werden geleert, und die Datei erscheint im Bericht als "Quelle verändert, wird neu eingeordnet". Ist der Quellpfad nicht mehr vorhanden, bleibt die Zeile in der Datenbank und erscheint im Bericht als "Quelle nicht mehr vorhanden". Es wird nie eine Zeile gelöscht.
- Ausschlussmuster aus der Konfiguration anwenden, verglichen wie in SPEC Abschnitt 9 beschrieben. Ausgeschlossene Pfade kommen nicht in die Datenbank und werden gezählt.
- Ordner-Verknüpfungen (Symlinks, Windows-Junctions) werden standardmäßig nicht verfolgt (SPEC Abschnitt 4 Phase 1). Sie werden gezählt und im Bericht aufgeführt. Grund: Ein Ring aus Verknüpfungen ließe den Scan endlos laufen, und dieselbe Datei erschiene unter zwei Pfaden. Versteckte Ordner werden normal erfasst.
- Prüfung beim Start, ob ExifTool vorhanden ist, nach SPEC Abschnitt 2: harter Abbruch nur bei den Befehlen, die Metadaten brauchen, und beim Erzeuger des Testbaums. Der Scan braucht ExifTool nicht; scan, status und bericht geben höchstens einen Hinweis aus. Gesucht wird über PATH, überschreibbar über Umgebungsvariable und Konfigurationswert in der Reihenfolge aus SPEC Abschnitt 2.
- Prüfung, ob Ziel in Quelle liegt oder umgekehrt, genau nach SPEC Abschnitt 4 Phase 1: Beide Pfade mit Path.resolve() auflösen, Verknüpfungen also mit auflösen. Danach gilt: Quelle gleich Ziel bricht ab, ein Ziel innerhalb der Quelle wird vom Scan ausgeschlossen und gemeldet, eine Quelle innerhalb des Ziels bricht ab. Die Prüfung endet nicht am Anfang: Während des Durchlaufs wird der aufgelöste Pfad jedes Ordners gegen das aufgelöste Ziel geprüft, damit auch eine Verknüpfung aus der Quelle ins Ziel gefunden wird, die ein reiner Textvergleich der Pfade übersähe.
- "fotosort status": zeigt Zähler je Status und die aktuelle Phase (SPEC Abschnitt 8). Bau ihn hier einmal vollständig: Er kennt alle Statuswerte aus SPEC Abschnitt 6 und zählt auch die, die es in Phase 1 noch nicht gibt, dann eben mit 0. In Phase 1 vergibt nur der Scan Status. Prompt 4 beauftragt denselben Befehl noch einmal; dort kommt nichts hinzu, was er können muss, sondern nur die Status der späteren Phasen und die getrennte Ausweisung der per Umbenennen verschobenen Dateien. Bau ihn dort nicht neu.

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
- Kopieren in eine temporäre Datei im Zielordner, dann atomar umbenennen. Änderungsdatum erhalten.
- Name der temporären Datei: der vollständige Zieldateiname plus .part, also DSC01234.ARW.part, nicht der Stammname (SPEC Abschnitt 5). Sonst ergäbe ein RAW+JPG-Paar zweimal denselben .part-Namen. Der Zielname ist im Zielordner eindeutig, damit ist es auch der .part-Name.
- Auch das abschließende Umbenennen der .part-Datei auf den endgültigen Namen darf niemals eine vorhandene Datei überschreiben. os.rename und Path.rename ersetzen unter POSIX eine vorhandene Zieldatei stillschweigend; das ist ein Verlustpfad. Benutze das nicht überschreibende Verfahren aus SPEC Abschnitt 5. Ist der Zielname belegt, schlägt der Vorgang fehl, und es greift die Regel "Niemals überschreiben" (Duplikat oder Anhang _1, _2).
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
- Sauberer Abbruch mit Strg+C, liegengebliebene .part-Dateien beim nächsten Start aufräumen. Entfernt werden sie nur, wenn keine Zeile in der Datenbank sie beansprucht (SPEC Abschnitt 5); beanspruchte bleiben stehen und werden neu geschrieben.

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
- Fehlt auf dem Ziel-Dateisystem ein nicht überschreibendes Verfahren, wird nicht doch einfach umbenannt. Auf exFAT und FAT32, dem üblichen Format externer Platten, gibt es keine harten Verknüpfungen, os.link schlägt fehl. Dann wird auf Kopieren, Prüfen und Löschen zurückgefallen, und das Kopieren verzichtet auf die .part-Datei und legt die Zieldatei exklusiv unter ihrem endgültigen Namen an (SPEC Abschnitt 5). Ein einfaches Umbenennen, das überschreiben könnte, ist nie erlaubt, auch nicht als letzter Ausweg und auch nicht nach einer vorherigen Existenzprüfung. Dass der Rückfall gegriffen hat, steht mit Anzahl im Bericht.
- Ein Netzlaufwerk gilt nie als "gleiches Laufwerk". Liegt mindestens einer der beiden Pfade auf einem Netzlaufwerk (UNC, SMB, CIFS, NFS), gilt "gleiches Laufwerk" als nicht nachgewiesen und es wird kopiert statt umbenannt. Erkennung: unter Windows über das UNC-Präfix bzw. GetDriveType gleich DRIVE_REMOTE, auch für verbundene Laufwerksbuchstaben aufgelöst; unter Linux über den Dateisystemtyp des Einhängepunkts; die vollständige Liste der als Netz geltenden Typen steht in SPEC Abschnitt 6 und gilt für beide Prüfungen.
- "fotosort aufraeumen": löscht in der Quelle ausschließlich Dateien mit Status "geprueft" oder "duplikat_bestaetigt". Kein anderer Status berechtigt zum Löschen. Vorher Anzahl und Größe anzeigen und ausdrücklich bestätigen lassen. --dry-run zeigt die Liste.
- "fotosort aufraeumen --leere-ordner": nur wirklich leere Ordner entfernen, Reste-Dateien laut Konfiguration zählen als leer. Quell-Wurzelordner bleibt stehen.
- Die Reste-Ausnahme wird durchgesetzt, nicht geglaubt. Eine Datei gilt nur dann als Rest, wenn das Programm selbst feststellt, dass es für sie keine Zeile in der Datenbank mit einem echten Dateityp gibt (SPEC Abschnitt 3, Abschnitt 5). Diese Prüfung läuft vor jeder einzelnen Löschung und lässt sich nicht abschalten. Sonst könnte ein Eintrag wie ".jpg" oder "*" in reste_dateien die gesamte Löschregel aushebeln. Trifft ein Name aus der Liste auf eine solche Datei, wird sie nicht gelöscht, der Ordner gilt als nicht leer, und der Fall kommt in den Bericht.
- Die Statusregel gilt für Quelldateien aus dem Bestand der Datenbank. Eng begrenzte, ausdrücklich benannte Ausnahmen sind die Reste-Dateien aus Phase 6 (Thumbs.db, .DS_Store, desktop.ini, Liste konfigurierbar) und liegengebliebene .part-Dateien. Beide stehen nie in der Datenbank. Weitere Ausnahmen gibt es nicht.
- Direkt vor jedem Löschen beide Dateien im aktuellen Lauf frisch lesen: die Zieldatei und die Quelldatei. Beide Hashes werden mit dem gespeicherten Quell-Hash verglichen (SPEC Abschnitt 4 Phase 5, Abschnitt 5). Existenz und Größe allein genügen nicht, der Ziel-Index allein auch nicht.
- Warum die Quelle mitgelesen wird: Würde nur die Zieldatei frisch gelesen und ihr Hash mit dem beim Kopieren gespeicherten Quell-Hash verglichen, beschrieben beide Werte denselben alten Stand. Ändert sich die Quelldatei nach dem Kopieren durch Bearbeitung, Synchronisierung oder eine neue Fassung, stimmen die beiden Werte weiterhin überein. Die geänderte Quelle würde gelöscht, obwohl ihr aktueller Inhalt nie im Ziel angekommen ist. Das ist der wichtigste Verlustpfad dieser Phase.
- Gelöscht wird genau dann, wenn der Status geprueft oder duplikat_bestaetigt ist und Quelle und Ziel im aktuellen Lauf beide frisch gelesen wurden und beide denselben Hash tragen wie der gespeicherte Quell-Hash. Fehlt auch nur eine dieser Bedingungen, wird nicht gelöscht.
- Weicht die Quelle ab: nicht löschen. Der Status fällt auf analysiert zurück, weil die Datei neu kopiert werden muss; gespeicherter Hash und bestaetigt_in_lauf werden geleert. Die Datei erscheint im Bericht in der Liste "Quelle seit dem Kopieren geändert" (SPEC Abschnitt 10). Weicht das Ziel ab: nicht löschen, Status fehler mit Grund, im Bericht aufführen.
- Der Status ist notwendig, nicht hinreichend. Diese Frischlesung gilt für beide löschberechtigenden Status, also auch bei "geprueft" und nicht nur bei "duplikat_bestaetigt". Die Lauf-Kennzeichnung (Spalte bestaetigt_in_lauf) wird deshalb für beide Status geführt. Gehört der Eintrag nicht zum aktuellen Lauf, wird nicht gelöscht, sondern im Bericht aufgeführt.
- Option byte_vergleich_vor_loeschen (Standard: aus): vergleicht Quelle und Ziel vor dem Löschen zusätzlich Byte für Byte.

Pflicht-Tests:
- Ungeprüfte Datei wird nie gelöscht, auch nicht mit Gewalt-Optionen.
- Datei, deren Zielkopie fehlt oder verändert wurde, wird nicht gelöscht.
- Eine nach dem Kopieren geänderte Quelldatei wird nicht gelöscht: Datei kopieren und prüfen, dann den Inhalt der Quelldatei ändern, dann aufräumen lassen. Erwartung: Die Quelldatei ist danach noch da und trägt ihren neuen Inhalt, die Zieldatei ist unverändert, der Status steht auf analysiert, und die Datei erscheint im Bericht unter "Quelle seit dem Kopieren geändert".
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
