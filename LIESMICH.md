# fotosort – Anleitung für Windows

fotosort sortiert Fotos und Videos aus einem unaufgeräumten Ordner in ein Archiv
nach Aufnahmedatum und Kamera. Es kopiert jede Datei, liest die Kopie danach noch
einmal vollständig und vergleicht sie mit dem Original. Erst wenn das stimmt, darf
das Original – und nur auf ausdrücklichen Befehl – aus dem Quellordner weg.

**Die eiserne Regel des Programms: Es darf nie ein Bild verloren gehen.** Es
überschreibt nie eine vorhandene Datei, es löscht nie etwas, dessen Inhalt nicht
nachweislich im Archiv liegt, und im Zweifel hört es auf und sagt, warum.

Diese Anleitung ist für Menschen ohne Programmierkenntnisse geschrieben. Fachwörter
werden dort erklärt, wo sie vorkommen.

---

## 1. Installation: ZIP entpacken, start.bat doppelklicken

Das fertige Windows-Programm braucht keine Installation. Python und ExifTool sind
schon im Paket enthalten.

1. Auf der Release-Seite des Projekts die Datei **`fotosort-windows.zip`** herunterladen.
2. **Vor dem Entpacken freigeben** – das erspart Rückfragen von Windows: Rechtsklick auf die
   ZIP-Datei, „Eigenschaften", unten bei „Sicherheit" das Häkchen **„Zulassen"** setzen, „OK".
   Gibt es das Häkchen nicht, ist nichts zu tun.
3. Die ZIP-Datei entpacken (Rechtsklick, „Alle extrahieren…"), zum Beispiel nach
   `C:\fotosort`. Es entsteht ein Ordner `fotosort` mit `start.bat`, `fotosort.bat`, dieser
   Anleitung und den Unterordnern `python`, `lib` und `exiftool`. Der Ordner darf überall
   liegen, auch mit Leerzeichen oder Klammern im Namen.
4. **`start.bat` doppelklicken.** Es öffnet sich das Programmfenster mit Knöpfen und
   Ordnerauswahl (Abschnitt 2). Ein schwarzes Fenster blitzt dabei kurz auf und schließt
   sich gleich wieder – das ist `start.bat` selbst.

**Was im Paket startet:** nur das offizielle Python von python.org im Ordner `python`
(`pythonw.exe` für das Fenster und seine Arbeitsschritte, `python.exe` für `fotosort.bat`),
digital signiert von der Python Software Foundation – dasselbe Programm, mit dem auch jedes
andere Python-Skript läuft. Dazu `perl.exe` im Ordner `exiftool\exiftool_files`: Das ist
ExifTool, das die Aufnahmedaten aus den Bildern liest. Eigens gebaute Programmdateien (.exe)
gibt es seit Version 0.6 nicht mehr. Im Ordner `lib` liegen fotosort selbst und die
Bibliotheken, die es braucht. Installiert wird nichts, und außerhalb des Ordners ändert das
Programm nur seinen Datenordner (Abschnitt 7).

**Wenn Windows beim ersten Start fragt:** Erscheint „Sicherheitswarnung – Möchten Sie diese
Datei ausführen?" oder das blaue Fenster „Der Computer wurde durch Windows geschützt", wurde
die ZIP-Datei nicht wie in Schritt 2 freigegeben. Dann „Ausführen" bzw. „Weitere
Informationen" und „Trotzdem ausführen" klicken – oder den Ordner löschen, die ZIP-Datei
freigeben und neu entpacken.

**Wenn sich kein Fenster öffnet:** Dann zeigt das Programm ein Meldungsfenster mit dem Grund,
einem Rat und dem Ort des Protokolls
(`C:\Users\<Name>\AppData\Local\fotosortierer\oberflaeche\fenster.log`). Meist hilft es, die
ZIP-Datei noch einmal vollständig zu entpacken. Das Fenster braucht keine zusätzliche
Software auf dem PC.

### Wenn der Virenscanner anschlägt

Das Paket startet nur Programme, die Virenscanner kennen: das signierte Python und das Perl
von ExifTool. Hält ein Virenscanner fotosort trotzdem auf – der Start dauert sehr lange, oder
es kommt eine Meldung zu `pythonw.exe`, `python.exe` oder `perl.exe` aus dem fotosort-Ordner –,
richten Sie für den **ganzen fotosort-Ordner** (zum Beispiel `C:\fotosort`) eine Ausnahme ein.
Nur für diesen Ordner, nicht für die Fotoordner und nicht für ganze Laufwerke. Die Menünamen
unterscheiden sich je nach Version etwas; sinngemäß heißen sie so:

**Microsoft Defender (in Windows eingebaut):**
1. Startmenü öffnen, „Windows-Sicherheit" eintippen und öffnen.
2. „Viren- & Bedrohungsschutz" wählen.
3. Unter „Einstellungen für Viren- & Bedrohungsschutz" auf „Einstellungen verwalten" klicken.
4. Ganz nach unten zu „Ausschlüsse" blättern und „Ausschlüsse hinzufügen oder entfernen"
   wählen; Windows fragt nach der Erlaubnis – „Ja".
5. „Ausschluss hinzufügen", dann „Ordner", den fotosort-Ordner wählen, „Ordner auswählen".

**Norton (Norton 360, Norton AntiVirus):**
1. Norton öffnen und „Einstellungen" wählen (bei neueren Versionen vorher bei
   „Gerätesicherheit" auf „Öffnen" klicken).
2. „Antivirus" wählen, dann den Reiter „Scans und Risiken".
3. Zum Abschnitt „Ausschlüsse / Niedrige Risiken" blättern.
4. Beim Eintrag „Von Auto-Protect, Skriptsteuerung, SONAR und Download-Insight
   auszuschließende Elemente" auf „Konfigurieren" klicken, dann „Ordner hinzufügen", den
   fotosort-Ordner wählen, „OK". **Das ist der wichtige Eintrag** – er betrifft die Prüfung
   beim Start, die bis zu einer Minute dauern kann.
5. Dasselbe beim Eintrag „Von Scans auszuschließende Elemente".
6. Mit „Anwenden" und „Schließen" bestätigen.

**Avast (Avast Free Antivirus, Avast One):**
1. Avast öffnen, oben rechts auf „Menü" (☰) und dann auf „Einstellungen" klicken.
2. „Allgemein" und dann „Ausnahmen" wählen.
3. „Ausnahme hinzufügen" klicken, den fotosort-Ordner über „Durchsuchen" wählen oder den Pfad
   eintippen (zum Beispiel `C:\fotosort\*`), dann „Ausnahme hinzufügen".

Danach `start.bat` erneut doppelklicken. Wer das Programm weitergibt: Die Ausnahme gilt nur
auf dem eigenen PC. Der Empfänger richtet sie auf seinem Rechner selbst ein, falls sein
Virenscanner anschlägt.

Ob alles zusammenpasst, zeigt `fotosort.bat --version` im schwarzen Fenster: Es nennt die
Programmversion und das mitgelieferte ExifTool („gestartet ueber perl.exe").

Wer das Programm aus dem Quellcode einrichten will, findet den Weg mit Python und
ExifTool im Anhang am Ende dieser Anleitung.

---

## 2. Der erste Probelauf – mit Kopien!

**Bitte zuerst mit Kopien einiger Fotos üben, nie gleich mit den Originalen.**
Das Programm ist vorsichtig gebaut, aber ein Probelauf zeigt Ihnen, was passiert,
bevor es um Ihre Bilder geht.

1. Einen Ordner `D:\Probe\Quelle` anlegen und **Kopien** von etwa 50 Fotos und
   Videos hineinlegen, gern durcheinander und in Unterordnern.
2. Einen leeren Ordner `D:\Probe\Archiv` anlegen. Das wird das Ziel.
3. `start.bat` doppelklicken. Es öffnet sich das Programmfenster (dunkel, oben die
   Titelzeile mit dem Zielordner, unten eine Statusleiste). Bilder jeder Ansicht liegen im
   Ordner `docs/oberflaeche` des Projekts.

Auf der Startseite tragen Sie ein:

| Feld | Was Sie tun |
|---|---|
| **Zielordner** | „Auswählen…" drücken und `D:\Probe\Archiv` im Windows-Ordnerdialog wählen. Gibt es den Ordner noch nicht, fragt das Programm bei „Los geht's", ob es ihn anlegen soll. |
| **Quellordner** | „Quelle hinzufügen…" drücken und `D:\Probe\Quelle` wählen. Jede Quelle erscheint als Schildchen; das × daran nimmt sie wieder heraus. Beliebig viele Quellen sind möglich. Getippt wird nirgends. Wählen Sie ein ganzes Laufwerk (`C:\`) oder Ihren Benutzerordner, fragt das Programm nach – meist ist ein Unterordner wie „Bilder" gemeint. |
| **Modus** | „kopieren" lassen – die Quelle bleibt unverändert. |
| **Zielordner liegt auf** | „hdd" lassen (Festplatte); bei einer SSD oder einem Netzlaufwerk das Passende wählen. Das steuert nur, wie viele Dateien gleichzeitig kopiert werden. |

Rechts daneben steht eine Karte: Liegt im Zielordner schon ein angefangenes Archiv, zeigt sie
dessen Stand und die bekannten Quellen, und **„Weitermachen"** springt zum offenen Schritt, ohne
die Quellen erneut zu durchsuchen. **„Los geht's"** unten links durchsucht immer zuerst – das ist
der richtige Knopf, wenn neue Dateien in der Quelle liegen. Ist der Zielordner nicht leer, enthält
aber noch kein Archiv, fragt „Los geht's" erst, ob es dort weitergehen soll (es wird nichts
gelöscht oder überschrieben; die Fotos kommen zu dem, was schon da liegt).

**„Archiv verwerfen…"** auf derselben Karte ist der Neuanfang: Es entfernt das Gedächtnis des
Programms zu diesem Zielordner – die Datenbank auf dem Rechner und den Ordner `.fotosortierer`
im Ziel mit Sicherung und Berichten. **Kopierte Fotos und Videos bleiben unangetastet, die
Quellordner ebenso.** Das Programm verlangt dafür das getippte Wort `verwerfen`, tut es nicht,
solange ein Schritt läuft, und weigert sich, wenn in einem der beiden Ordner eine Bild-, Video-
oder Sidecar-Datei liegt. Es geht auch dann, wenn die Datenbank kaputt ist – dafür ist es da. Danach ist die Startseite leer. Sinnvoll nach einem Probelauf, den Sie nicht mehr
brauchen, oder wenn ein Archiv neu begonnen werden soll.

Danach zeigt das Fenster die **Übersicht**: oben die Pfade (Quellen → Ziel) und die
Phasenleiste **Scan · Analyse · Kopieren · Prüfen · Aufräumen** (die violette Linie zeigt, wie
weit es ist), links der Balken mit erledigten Dateien, Datenmenge, MB/s und Restzeit, darunter
die Zähler des letzten Schritts, rechts die Karten **Aufräumen**, **Leere Ordner** und **Letzter
Bericht**. Unten stehen die Knöpfe: Der umrandete Hauptknopf ist immer der nächste sinnvolle
Schritt („Analyse starten", „Kopieren starten · 3.912 Dateien", „Prüfen starten"); solange ein
Schritt läuft, ist er gesperrt, und daneben stehen **Pause** und **Abbrechen**. Nichts läuft
ohne Ihren Klick. Alles Bisherige bleibt gespeichert; wer das Fenster schließt, hält den
laufenden Schritt nicht an, und beim nächsten `start.bat` zeigt die Startseite den Stand.

### Schritt 1: Quellen durchsuchen (Scan)

Das Programm geht durch den Quellordner und merkt sich jede Datei mit Größe und
Änderungsdatum – es liest die Bilder noch nicht. Ausgabe:

- **Dateien gesamt / Gesamtgröße / Aufteilung nach Typ** – wie viele Fotos, RAW-Dateien,
  Videos, Sidecars (kleine Begleitdateien wie `.xmp`) und Sonstiges gefunden wurden.
- **neu aufgenommen / unverändert übernommen / verändert** – beim ersten Lauf ist alles
  neu; bei einem späteren Lauf zählt das Programm, was sich seit dem letzten Mal
  geändert hat.
- **Quelle nicht mehr vorhanden** – Dateien, die beim letzten Mal da waren und jetzt
  fehlen (nur gemeldet, nichts wird deswegen getan).
- **Verknüpfungen nicht verfolgt** – Ordner-Verknüpfungen werden übersprungen, damit
  keine Datei doppelt erfasst wird.
- **zeigt ins Ziel, übersprungen** – Dateien, die in Wahrheit im Archiv liegen (etwa
  über eine Verknüpfung), werden nie als Quelle behandelt.

### Schritt 2: Analyse (Datum, Kamera, Zielordner)

Jetzt liest ExifTool aus jeder Datei das Aufnahmedatum und das Kameramodell, und
das Programm berechnet für jede Datei den Zielordner. Ausgabe:

- **Dateien pro Jahr** und **Gefundene Kameramodelle (Modell -> Ordner)** – die
  wichtigste Liste. Links steht das Modell, wie es in der Datei steht (z. B.
  `ILCE-7CM2`), rechts der Ordnername, den das Programm daraus macht (z. B. `A7C2`).
- **Ohne sicheres Datum** – Dateien ohne Aufnahmedatum; sie landen unter `_Ohne_Datum`.
- **Zeitzone angenommen** – Videos, deren Uhrzeit in Weltzeit (UTC) gespeichert ist;
  das Programm rechnet sie in Ihre Zeitzone um.
- **Mögliche Duplikate (Schätzung)** – gleiche Größe und Aufnahmezeit; sicher weiß es
  das Programm erst beim Kopieren.

Die Übersicht im Fenster zeigt nach der Analyse die Kameras als Tabelle: links das Modell,
wie es in den Dateien steht, rechts ein Feld mit dem Ordnernamen. **Tippen Sie dort einfach den
gewünschten Namen hinein** (etwa `Sony A7C` statt `ILCE-7CM2`) und drücken Sie „Ordnernamen
übernehmen". Der Eintrag wird dauerhaft in die Einstellungen geschrieben (siehe Abschnitt 6),
und die betroffenen Dateien werden noch einmal analysiert. Im schwarzen Fenster fragt der geführte Ablauf stattdessen:
**Soll ein Kameramodell einen anderen Ordnernamen bekommen?** – Modell eintippen, dann den
Ordnernamen; Enter allein heißt „nichts ändern".

### Schritt 3: Kopieren

Der Hauptknopf sagt, wie viele Dateien anstehen („Kopieren starten · 3.912 Dateien"); im
schwarzen Fenster ist das der **Probelauf**. Nach dem Klick wird kopiert. Jede Datei wird zuerst unter einem Zwischennamen
(`.part`) geschrieben, dabei wird eine Prüfsumme berechnet (ein Fingerabdruck des
Inhalts), und erst am Ende bekommt sie ihren richtigen Namen. Ausgabe:

- **kopiert** – so viele Dateien liegen jetzt im Archiv.
- **Duplikate** – Dateien, deren Inhalt schon im Archiv lag. Sie werden nicht ein
  zweites Mal kopiert; das Programm merkt sich, zu welcher Archivdatei sie gehören.
- **Namenskonflikte** – zwei verschiedene Bilder mit gleichem Namen; das zweite bekommt
  den Anhang `_1`. Es wird nie etwas überschrieben.
- **Fehler** – Dateien, die sich nicht lesen ließen. Sie bleiben in der Quelle und
  stehen im Bericht.

### Schritt 4: Prüfen

Jede Archivdatei wird noch einmal **vollständig gelesen** und ihr Fingerabdruck mit
dem der Quelldatei verglichen. Ausgabe: **geprüft (Zieldatei stimmt)** und, falls
etwas nicht stimmt, **Fehler** mit Grund. Eine fehlerhafte Kopie wird nie gelöscht
oder überschrieben; ein erneutes Kopieren legt eine frische Kopie daneben.

### Schritt 5: Quelle aufräumen

Das Aufräumen ist die Karte rechts in der Übersicht. Sie zeigt je Quellordner, wie viele
Dateien eine geprüfte Kopie im Archiv haben und wie groß sie sind; vor dem Prüfen ist die Karte
abgeblendet. **Beim ersten Mal: die Karte einfach unbenutzt lassen oder den sicheren Standard
„_geloescht_" nehmen.** Der Standard verschiebt die Originale nicht ins
Nichts, sondern in einen Ordner `_geloescht_<Datum>` innerhalb der Quelle. Dort können Sie in
Ruhe nachsehen und den Ordner später selbst löschen. Vor jeder einzelnen Datei werden
Original und Archivkopie noch einmal vollständig gelesen und verglichen; stimmt etwas nicht,
bleibt die Datei stehen und wird gemeldet.

Zum Bestätigen tippen Sie das angezeigte Wort in das Feld der Karte (`verschieben` für den
Ordner `_geloescht_`, `loeschen` für endgültiges Löschen). Der Knopf darunter wird erst
anklickbar, wenn das Wort genau stimmt. Die Karte **„Leere Ordner"** arbeitet genauso mit dem
Wort `entfernen`. Haben Sie auf
der Startseite **Verschieben** gewählt, verlangt das Fenster schon vor Schritt 3 das Wort
`verschieben`, weil dort die Quelle geleert wird. Im schwarzen Fenster gelten dieselben
Wörter.

Am Ende sind alle fünf Phasen in der Leiste erledigt, der Hauptknopf heißt „Bericht öffnen",
und die Karte „Letzter Bericht" öffnet den Bericht oder die CSV-Tabelle (Abschnitt 5 erklärt
die Statuswörter in den Zählern).

### Der Ablauf im schwarzen Fenster (Alternative ohne Oberfläche)

Wer lieber Fragen im Textfenster beantwortet, ruft im Programmordner `fotosort.bat start`
auf (Eingabeaufforderung öffnen: in der Adresszeile des Explorers `cmd` eintippen;
`fotosort.bat` benutzt dafür das mitgelieferte `python\python.exe`). Die Fragen dort:

| Frage | Was Sie eingeben |
|---|---|
| Zielordner des Archivs | `D:\Probe\Archiv` |
| Soll er angelegt werden? (nur wenn es den Ordner noch nicht gibt) | `ja` |
| Quellordner mit den unsortierten Bildern | `D:\Probe\Quelle` |
| Weiterer Quellordner (leer = keiner mehr) | nur Enter |
| Kopieren oder Verschieben? (k/v) | Enter (= kopieren; die Quelle bleibt unverändert) |
| Wo liegt das Ziel? hdd / ssd / netzwerk | `hdd` für eine Festplatte, `ssd` für eine SSD, `netzwerk` für ein Netzlaufwerk |
| Stimmt das so? | Enter |

Vor jedem Schritt fragt das Programm; Enter heißt „ja", `n` heißt „hier aufhören".

---

## 3. Die Befehle im Einzelnen

Alles, was der geführte Ablauf tut, gibt es auch als einzelne Befehle. Dazu ein
Eingabeaufforderungs-Fenster öffnen (Windows-Taste, `cmd` tippen, Enter), in den
Ordner wechseln (`cd C:\fotosort`) und `fotosort.bat` mit dem Befehl aufrufen.
Jeder Befehl braucht `--ziel <Archivordner>`; darüber findet das Programm sein
Gedächtnis (die Datenbank, Abschnitt 7).

```
fotosort.bat scan       --quelle D:\Chaos --quelle E:\Karte --ziel D:\Archiv
fotosort.bat scan       --ziel D:\Archiv                    (alle bekannten Quellen erneut)
fotosort.bat analyse    --ziel D:\Archiv                    (ExifTool-Prozesse nach Profil; --prozesse N erzwingt eine Zahl)
fotosort.bat kopieren   --ziel D:\Archiv --dry-run          (nur zeigen, was passieren wuerde)
fotosort.bat kopieren   --ziel D:\Archiv
fotosort.bat kopieren   --ziel D:\Archiv --verschieben      (Original nach gelungener Pruefung loeschen)
fotosort.bat pruefen    --ziel D:\Archiv
fotosort.bat aufraeumen --ziel D:\Archiv --dry-run          (Liste zeigen, nichts tun)
fotosort.bat aufraeumen --ziel D:\Archiv                    (in den Ordner _geloescht_<Datum>)
fotosort.bat aufraeumen --ziel D:\Archiv --endgueltig       (wirklich loeschen)
fotosort.bat aufraeumen --ziel D:\Archiv --leere-ordner     (leere Ordner in der Quelle entfernen)
fotosort.bat status     --ziel D:\Archiv                    (wo steht das Archiv?)
fotosort.bat bericht    --ziel D:\Archiv                    (Bericht als Text und Tabellen)
fotosort.bat config     --ziel D:\Archiv                    (Einstellungsdatei oeffnen)
fotosort.bat messen     --quelle D:\Chaos --ziel D:\Archiv  (Lese- und Schreibtempo messen)
fotosort.bat start      --ziel D:\Archiv                    (der gefuehrte Ablauf)
```

Ein Netzlaufwerk wird genauso angegeben, etwa `--ziel \\truenas\Daten\Archiv` oder
über den Laufwerksbuchstaben `--ziel Z:\Archiv`.

**Hinweise zu einzelnen Befehlen**

- `scan --ziel-anlegen` legt einen noch nicht vorhandenen Zielordner an. Ohne den
  Schalter bricht `scan` bei einem fehlenden Ziel ab – damit ein Tippfehler im Pfad
  nicht stillschweigend ein zweites, leeres Archiv anlegt.
- `kopieren --verschieben`: Liegen Quelle und Ziel auf demselben Laufwerk, wird nur
  umbenannt (schnell, keine Daten fließen). Sonst wird kopiert, Kopie und Original
  werden beide neu gelesen, und erst dann wird das Original endgültig gelöscht. Ein
  Netzlaufwerk gilt nie als „gleiches Laufwerk".
- `aufraeumen --quelle D:\Chaos` beschränkt das Aufräumen auf diese eine Quelle;
  ohne Angabe wird je Quelle einzeln gefragt.
- `--profil hdd|ssd|netzwerk`, `--kopier-worker N`, `--hash-worker N` bestimmen, wie
  viele Dateien gleichzeitig kopiert bzw. gelesen werden. Was auf Ihrem Rechner am
  besten ist, sagt `fotosort.bat messen`.
- `messen` legt im Ziel nur einen vorübergehenden Messordner an, der am Ende wieder
  verschwindet, und schlägt am Ende Werte für die Einstellungen vor.

---

## 4. Was während eines Laufs zu sehen ist

Im Fenster zeigt jeder Schritt einen Balken mit erledigten Dateien und Datenmenge, MB pro
Sekunde und der geschätzten Restzeit, höchstens zweimal je Sekunde erneuert.

**Die Restzeit** erscheint erst, wenn der Schritt eine Minute gearbeitet und mindestens 3 %
geschafft hat; bis dahin steht dort „wird berechnet". Der Grund: Die ersten Dateien liefert
Windows oft aus seinem Zwischenspeicher, viel schneller als den Rest – eine Schätzung aus
diesem Anfang wäre viel zu kurz. Danach rechnet das Programm mit dem Tempo der letzten Minute,
erneuert die Zahl höchstens alle 5 Sekunden und rundet ab: auf ganze Minuten, unter 2 Minuten
auf 10 Sekunden. Pausen zählen nicht mit. Ging in der letzten Minute gar nichts voran (etwa bei
einem sehr großen Video), bleibt die letzte Zahl stehen. Beim Scan gibt es keine Restzeit, weil
die Gesamtzahl der Dateien erst am Ende feststeht.

**Pause** hält
nach der laufenden Datei an, **Fortsetzen** macht weiter, **Abbrechen** beendet den Schritt
sauber – das Bisherige bleibt gespeichert, der nächste Lauf macht dort weiter. Reagiert ein
Schritt nicht auf „Abbrechen", erscheint nach einer Weile „Sofort beenden". Im schwarzen
Fenster zeigt beim Kopieren und Prüfen eine Zeile dasselbe. Am Ende jeder Phase stehen Dauer
und Durchsatz.

Die Listen **Fehler**, **Duplikate** und **Ohne Datum** öffnen sich über die Knöpfe unten in
der Übersicht – immer seitenweise mit 100 Zeilen (‹ › blättert), nie alles auf einmal.

Nach jeder Phase schreibt das Programm

- eine **Sicherungskopie** seines Gedächtnisses ins Archiv
  (`<Ziel>\.fotosortierer\fotosort.db.sicherung`) und
- einen **Bericht** (`<Ziel>\.fotosortierer\berichte\bericht_<Zeit>_lauf<N>.txt` und zwei
  `.csv`-Tabellen, die sich mit Excel öffnen lassen – Trennzeichen ist das Semikolon).

Der Bericht enthält alle Zahlen und Listen: Fehler mit Grund, Duplikate mit ihrer
Partnerdatei, Dateien ohne Datum, Namenskonflikte, übersprungene Dateien und alles,
was beim Aufräumen verweigert wurde.

---

## 5. Die Status-Wörter

Jede erfasste Datei hat einen Status. `fotosort.bat status` zeigt die Anzahl je Status
und daraus die **aktuelle Phase**; der Bericht nennt den Status je Datei.

| Status | Bedeutung |
|---|---|
| `gefunden` | beim Scan gesehen, noch nicht analysiert |
| `analysiert` | Datum, Kamera und Zielordner stehen fest, noch nicht kopiert |
| `kopieren_laeuft` | wird gerade kopiert (bleibt das nach einem Absturz stehen, räumt der nächste Lauf auf) |
| `kopiert` | im Archiv, noch nicht nachgeprüft |
| `geprueft` | Archivkopie vollständig gelesen und stimmt mit dem Original überein |
| `duplikat` | Inhalt lag schon im Archiv; nicht kopiert |
| `duplikat_bestaetigt` | die Archivdatei, auf die das Duplikat zeigt, wurde geprüft |
| `verschoben` | auf demselben Laufwerk umbenannt statt kopiert |
| `quelle_geloescht` | Original entfernt (endgültig oder in `_geloescht_<Datum>`) |
| `uebersprungen` | nicht bearbeitet, z. B. Sidecar ohne Hauptdatei oder Datei zeigt ins Ziel |
| `fehler` | etwas ging schief; der Grund steht im Bericht. Nichts wurde gelöscht. |

Gelöscht werden darf **ausschließlich** aus `geprueft` und `duplikat_bestaetigt`, und
auch dann erst nach erneutem vollständigem Lesen von Original und Archivkopie.

---

## 6. Alle Einstellungen (config.toml)

Die Einstellungen liegen in einer Textdatei `config.toml`, eine je Archiv. Wo sie
liegt, sagt `fotosort.bat config --ziel D:\Archiv --nur-pfad`; `fotosort.bat config
--ziel D:\Archiv` öffnet sie direkt im Editor. Änderungen gelten ab dem nächsten
Befehl. Eine Zeile, die mit `#` beginnt, ist nur ein Kommentar.

**[ordner]**
- `vorlage` – wie die Zielordner heißen. Standard:
  `{jahr}/{jahr}-{monat} {monatsname}/{jahr}-{monat}-{tag}/{kamera}` ergibt zum Beispiel
  `2026\2026-01 Januar\2026-01-01\A7C2`. Ein Tagesordner darf einen Zusatz tragen
  (`2026-01-01 Geburtstag Oma`); das Programm erkennt ihn und benutzt ihn weiter.
- `vorlage_ohne_datum` – Ordner für Dateien ohne verwertbares Datum. Standard `_Ohne_Datum/{kamera}`.

**[datum]**
- `heimat_zeitzone` – Ihre Zeitzone (Standard `Europe/Berlin`). Videos speichern die
  Uhrzeit oft in Weltzeit; sie wird hierhin umgerechnet.
- `tagesgrenze` – Uhrzeit, ab der ein neuer Tag beginnt. `"04:00"` zählt Aufnahmen bis
  4 Uhr morgens noch zum Vortag (Feiern, die über Mitternacht gehen). Standard `"00:00"`.
- `unsicheres_datum` – was mit Dateien ohne Aufnahmedatum geschieht: `"ohne_datum"`
  (Standard, Ordner `_Ohne_Datum`) oder `"mtime"` (das Änderungsdatum der Datei nehmen).

**[kamera]**
- `unbekannt` – Ordnername, wenn kein Kameramodell gefunden wurde. Standard `Unbekannte_Kamera`.
- `[kamera.aliase]` – Zuordnung Modellname → Ordnername, eine Zeile je Modell, zum Beispiel
  `"ILCE-7CM2" = "A7C2"`. Alles, was hier nicht steht, bekommt den Modellnamen
  selbst als Ordner. Scanner sind als `Analog` vorbelegt. Der geführte Ablauf trägt
  neue Zeilen für Sie ein.

**[dateitypen]**
- `foto`, `raw`, `video`, `sidecar` – welche Dateiendungen als was gelten (Groß- und
  Kleinschreibung ist egal). Alles andere ist „Sonstiges" und wird nur gezählt, nie
  kopiert.
- `sidecar_zusatzmuster` – für Sony-Videos: `C0001M01.XML` gehört zu `C0001.MP4`.

**[quelle]**
- `ausschlussmuster` – Pfade in der Quelle, die der Scan überspringt, zum Beispiel
  `["*/Papierkorb/*", "*.tmp"]`. Verglichen wird gegen den Pfad relativ zum Quellordner
  mit Schrägstrich als Trenner.
- `verknuepfungen_folgen` – ob Ordner-Verknüpfungen verfolgt werden. Standard `false`
  (sonst könnten Dateien doppelt erfasst werden oder der Scan im Kreis laufen).

**[sicherheit]**
- `byte_vergleich_vor_loeschen` – `true` vergleicht Original und Kopie vor dem Löschen
  zusätzlich Byte für Byte (langsamer, noch vorsichtiger). Standard `false`; der
  Fingerabdruck-Vergleich findet ohnehin immer statt.

**[datenbank]**
- `datenbank_ort` – anderer Ordner für das Gedächtnis des Programms. Leer = Standardort
  (Abschnitt 7). **Nie ein Netzlaufwerk.** Wirkt nur aus einer mit `--config` angegebenen Datei.

**[aufraeumen]**
- `reste_dateien` – Dateinamen, die beim Entfernen leerer Ordner als „zählt als leer"
  gelten (Standard `Thumbs.db`, `.DS_Store`, `desktop.ini`). Ein Name allein genügt
  nicht: Ein Foto wird darüber nie gelöscht.

**[leistung]**
- `profil` – `"hdd"` (Festplatte, 2 gleichzeitige Kopien), `"ssd"` (8) oder `"netzwerk"` (4).
- `metadaten_prozesse` – wie viele ExifTool-Programme gleichzeitig laufen. `0` = nach Profil:
  Festplatte und Netzlaufwerk 4, SSD Anzahl der Prozessorkerne (höchstens 16). Auf einer
  Festplatte bremsen viele gleichzeitige Leser, weil der Lesekopf springt.
- `kopier_worker` / `hash_worker` – gleichzeitige Kopier- bzw. Lesevorgänge; `0` = automatisch.
  `fotosort.bat messen` schlägt passende Werte vor.
- `exiftool_pfad` – Pfad zu `exiftool.exe`, falls ein anderes ExifTool benutzt werden soll.
  Liegt daneben der Ordner `exiftool_files`, startet das Programm dort `perl.exe` mit
  `exiftool.pl` direkt – dasselbe, was `exiftool.exe` selbst täte, nur ohne den Umweg.
  Normalerweise nicht nötig: Das fertige Paket findet sein mitgeliefertes ExifTool selbst,
  und aus dem Quellcode heraus gibt `fotosort.bat` den von `einrichten.bat` gemerkten Pfad mit.

---

## 7. Wo das Programm seine Daten ablegt

- **Datenbank** (das Gedächtnis: jede Datei mit Status und Fingerabdruck):
  `C:\Users\<Name>\AppData\Local\fotosortierer\<Archiv-Kennung>\fotosort.db`. Sie liegt
  bewusst auf dem Rechner, nie auf dem Netzlaufwerk. Daneben liegt die `config.toml`.
- **Archiv-Kennung**: `<Ziel>\.fotosortierer\archiv-id.txt`. Darüber findet das Programm
  die richtige Datenbank, auch wenn das Ziel unter einem anderen Laufwerksbuchstaben
  eingebunden ist.
- **Sicherungskopie und Berichte**: `<Ziel>\.fotosortierer\` (siehe Abschnitt 4).
- **Ordner `_geloescht_<Datum>`**: in der Quelle, nur wenn Sie aufgeräumt haben.
- **Oberfläche**: `C:\Users\<Name>\AppData\Local\fotosortierer\oberflaeche\` – der Stand des
  laufenden Schritts, die Ausgabe der Arbeitsprozesse (`arbeit.log`) und die des Fensters
  (`fenster.log`). Bei einer Fehlermeldung im Fenster lohnt ein Blick in `arbeit.log`.

---

## 8. Wenn etwas abbricht

**Sie schließen das Fenster, drücken Abbrechen oder Strg+C, der Rechner geht aus, das
Netzlaufwerk fällt weg:** Nichts ist verloren. Alles bis dahin Erledigte ist gespeichert.
Ein geschlossenes Fenster hält den laufenden Schritt nicht einmal an. Starten Sie einfach
`start.bat` (oder denselben Befehl) noch einmal – das Programm zeigt den Stand und macht
genau dort weiter. Meldet das Fenster „unerwartet beendet", ist der Arbeitsprozess abgestürzt
oder wurde beendet; die letzten Zeilen seiner Ausgabe stehen dann im Fenster.
Halbfertige Kopien (`.part`-Dateien) räumt es beim nächsten Kopieren selbst weg und
kopiert die betroffenen Dateien erneut.

**„Fuer dieses Archiv laeuft bereits ein Vorgang" / „Die Datenbank des Archivs ist gerade belegt":**
Es läuft noch ein zweiter fotosort-Lauf auf dasselbe Archiv, oder ein abgestürzter
Lauf hat seine Sperre hinterlassen. Erst prüfen, ob noch ein Fenster offen ist; dann
den Befehl erneut versuchen.

**„ExifTool wurde nicht gefunden":** Im fertigen Paket liegt ExifTool im Unterordner
`exiftool\exiftool_files` (`perl.exe` und `exiftool.pl`). Kommt die Meldung trotzdem, ist der
Ordner beim Entpacken verloren gegangen oder vom Virenscanner in Quarantäne genommen worden:
die ZIP-Datei noch einmal vollständig entpacken und gegebenenfalls die Ausnahme aus
Abschnitt 1 einrichten. Aus dem Quellcode
heraus: Anhang lesen und `einrichten.bat` erneut starten.

**„Es gibt eine Archiv-Kennung, aber die lokale Datenbank fehlt":** Das passiert,
wenn das Archiv auf einem anderen Rechner angelegt wurde oder die Datenbank gelöscht
wurde. Der Befehl `fotosort wiederherstellen` ist noch nicht gebaut; bis dahin von Hand:
die Datei `<Ziel>\.fotosortierer\fotosort.db.sicherung` nach
`C:\Users\<Name>\AppData\Local\fotosortierer\<Archiv-Kennung>\fotosort.db` kopieren
(die Kennung steht in `<Ziel>\.fotosortierer\archiv-id.txt`). Legen Sie **keine** neue
Kennung an und löschen Sie die Datei `archiv-id.txt` nicht – sonst gälte das Archiv als
leer, und alles würde noch einmal kopiert.

**Eine Datei steht auf `fehler`:** Der Grund steht im Bericht. Meist ist die Datei
nicht lesbar, oder die Kopie stimmte nicht. Die Quelldatei bleibt unangetastet. Nach
dem Beheben der Ursache (Kabel, Rechte, Platz) einfach `kopieren` erneut aufrufen.

**Eine Datei steht nach dem Aufräumen unter „Quelle seit dem Kopieren geändert":**
Die Datei wurde nach dem Kopieren noch bearbeitet. Sie wurde **nicht** gelöscht. Der
Weg zur frischen Kopie ist `scan` → `analyse` → `kopieren`; die neue Fassung bekommt
neben der alten den Anhang `_1`.

---

## 9. Wichtige Hinweise

- **Erst mit Kopien üben.** Ein Probeordner mit 50 Dateien reicht.
- **Beim ersten Aufräumen den Standard nehmen** (Ordner `_geloescht_<Datum>`), nicht
  `--endgueltig`. Den Ordner löschen Sie selbst, wenn Sie das Archiv gesehen haben.
- **Nie zwei Läufe gleichzeitig** auf dasselbe Archiv. Das Programm sperrt das Archiv,
  und das Fenster startet keinen zweiten Schritt, solange einer läuft – aber starten Sie
  nicht zusätzlich Befehle im schwarzen Fenster, während das Fenster arbeitet.
- **Die Datenbank bleibt auf dem Rechner.** Beim Wechsel auf einen anderen Rechner
  übernimmt das Programm nur die Einstellungen aus dem Archiv; die Datenbank selbst holen
  Sie wie in Abschnitt 8 beschrieben von Hand zurück, solange `wiederherstellen` fehlt.
- **Sidecars** (`.xmp` usw.) wandern immer zusammen mit ihrer Hauptdatei.
- **Videos ohne Zeitzone** werden aus Weltzeit umgerechnet; steht `heimat_zeitzone`
  falsch, rutscht eine Abendaufnahme in den nächsten Tag.
- **Keine schwarzen Fenster:** Während der Analyse laufen mehrere ExifTool-Programme
  (`perl.exe`) im Hintergrund. Sie öffnen kein eigenes Fenster (seit v0.5). Meldet der
  Virenscanner trotzdem `perl.exe` aus dem Programmordner, ist das ein Fehlalarm auf das
  mitgelieferte ExifTool – Abschnitt 1, „Wenn der Virenscanner anschlägt".
- **Hängt ExifTool an einer Datei,** wartet das Programm gut eine Minute, beendet es dann und
  startet es neu; nur diese eine Datei bekommt den Status `fehler` (Grund: Zeitlimit), alle
  anderen werden normal gelesen.
- **Eigene Ordnervorlage:** Steht `{kamera}` in derselben Ebene wie das Datum
  (`{jahr}-{monat}-{tag} {kamera}`), kann ein Tagesordner mit Zusatz für die falsche
  Kamera wiederverwendet werden. Mit der Standardvorlage passiert das nicht.

---

## 10. Was noch nicht gebaut ist

- `fotosort wiederherstellen` (Datenbank aus der Sicherungskopie holen) und
  `fotosort ziel-index --neu-aufbauen` (das Archiv neu einlesen) melden sich mit
  „Er kommt in Phase 3" und tun noch nichts. Der Weg von Hand steht in Abschnitt 8.
- Der Betrieb auf dem TrueNAS-Server (im Browser, mit eigenem Ordner-Browser statt des
  Windows-Dialogs) ist eine spätere Phase. Die Browser-Fassung der Oberfläche läuft dort schon
  jetzt mit `fotosort fenster --ohne-fenster`; der Ordnerpfad wird dann eingetippt. Auf dem
  Windows-PC ist sie nicht gedacht – dort gibt es das Programmfenster.

---

## Anhang für Entwickler: Einrichtung aus dem Quellcode

Nur nötig, wenn Sie nicht das fertige Paket, sondern den Quellcode benutzen wollen.

1. **Quellcode holen:** Auf der Seite des Projekts auf GitHub auf **Code** und
   **Download ZIP** klicken, die ZIP-Datei entpacken, zum Beispiel nach `C:\fotosort-quellcode`.
2. **Python 3.12 oder neuer** von https://www.python.org/downloads/windows/ als
   „Windows installer (64-bit)" installieren, dabei **das Häkchen „Add python.exe to PATH"
   setzen**.
3. **ExifTool** von https://exiftool.org als „Windows Executable" (ZIP) laden, entpacken,
   den ganzen Ordner nach `C:\ExifTool` verschieben und dort `exiftool(-k).exe` in
   `exiftool.exe` umbenennen. Der Unterordner `exiftool_files` muss daneben bleiben.
4. **`einrichten.bat`** doppelklicken. Das Skript prüft Python und ExifTool, sagt, was fehlt,
   legt im Unterordner `.venv` eine eigene Python-Umgebung an, installiert fotosort hinein
   (braucht Internet) und meldet FERTIG. Es kann beliebig oft laufen.
5. Danach funktionieren `start.bat` und `fotosort.bat` genauso wie im fertigen Paket.

**Das Paket selbst bauen** (wie es die GitHub-Actions tun; geht mit Python 3.12 auf jedem
System, auch Linux, braucht Internet): `python paket/exiftool_holen.py build/exiftool`, dann
`python paket/bauen.py --exiftool build/exiftool`, dann
`python paket/pruefen.py build/paket/fotosort build/pruefung`. Das Ergebnis liegt unter
`build/paket/fotosort`. Der Bau holt das eingebettete Python von python.org und die
Bibliotheken aus `paket/windows-bibliotheken.txt`, jeweils mit geprüfter Prüfsumme; starten
lässt sich das Ergebnis nur unter Windows.
