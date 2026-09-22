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
2. Die ZIP-Datei entpacken (Rechtsklick, „Alle extrahieren…"), zum Beispiel nach
   `C:\fotosort`. Es entsteht ein Ordner `fotosort` mit `start.bat`, `fotosort-fenster.exe`,
   `fotosort.exe`, `fotosort.bat`, dieser Anleitung und den Unterordnern `_internal` und
   `exiftool`.
3. **`start.bat` doppelklicken.** Es öffnet sich ein Fenster mit Knöpfen und Ordnerauswahl
   (Abschnitt 2). Genauso geht ein Doppelklick auf `fotosort-fenster.exe`.

**Wenn Windows beim ersten Start warnt:** Zeigt SmartScreen das blaue Fenster „Der
Computer wurde durch Windows geschützt", klicken Sie auf „Weitere Informationen" und dann
auf „Trotzdem ausführen". Meldet der Virenscanner `fotosort-fenster.exe` oder `fotosort.exe`,
ist das ein Fehlalarm, der bei selbst gebauten Programmen ohne Herstellersignatur vorkommt;
lassen Sie die Datei als Ausnahme zu. Beides fragt Windows nur beim ersten Mal.

**Wenn sich kein Fenster öffnet:** Das Fenster braucht die „WebView2-Laufzeit" von Microsoft
Edge, die auf Windows 11 und aktuellem Windows 10 vorhanden ist. Fehlt sie, steht der Grund in
`C:\Users\<Name>\AppData\Local\fotosortierer\oberflaeche\fenster.log`. Ausweg: In einem
schwarzen Fenster (Eingabeaufforderung) im Programmordner `fotosort.bat fenster --ohne-fenster`
eingeben und die genannte Adresse im Browser öffnen – dieselbe Oberfläche, nur den Ordnerpfad
tippen Sie dann selbst.

Ob alles zusammenpasst, zeigt `fotosort.bat --version` im schwarzen Fenster: Es nennt die
Programmversion und das mitgelieferte ExifTool.

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
3. `start.bat` doppelklicken. Es öffnet sich das Fenster des Foto-Sortierers.

Auf der Startseite tragen Sie ein:

| Feld | Was Sie tun |
|---|---|
| **Zielordner** | „Auswählen…" drücken und `D:\Probe\Archiv` wählen (oder den Pfad eintippen). Gibt es den Ordner noch nicht, fragt das Programm bei „Los geht's", ob es ihn anlegen soll. |
| **Quellordner** | „Quelle hinzufügen…" drücken und `D:\Probe\Quelle` wählen. Mehrere Quellen sind möglich; „Entfernen" nimmt eine wieder heraus. |
| **Kopieren oder verschieben?** | „Kopieren" lassen – die Quelle bleibt unverändert. |
| **Art des Laufwerks** | „Festplatte" lassen; bei einer SSD oder einem Netzlaufwerk das Passende wählen. Das steuert nur, wie viele Dateien gleichzeitig kopiert werden. |

Dann den großen grünen Knopf **„Los geht's"** drücken. Danach laufen die Schritte
nacheinander. Während eines Schritts sehen Sie einen Balken, die erledigten Dateien und die
Datenmenge, die Geschwindigkeit und die geschätzte Restzeit, dazu die Knöpfe **Pause**,
**Fortsetzen** und **Abbrechen**. **Nach jedem Schritt zeigt das Fenster eine Zusammenfassung**
und einen Knopf „Weiter: …", der sagt, was als Nächstes kommt. Nichts läuft ohne diesen Knopf.
Alles Bisherige bleibt gespeichert; wer das Fenster schließt, hält den laufenden Schritt nicht
an, und beim nächsten `start.bat` zeigt die Startseite den Stand und bietet **„Weitermachen"**
an.

Liegt im Zielordner schon ein angefangenes Archiv, sagt die Startseite das in einem Satz.
„Weitermachen" springt zum offenen Schritt, ohne die Quellen erneut zu durchsuchen; „Los geht's"
durchsucht immer zuerst – das ist der richtige Knopf, wenn neue Dateien in der Quelle liegen.

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

Die Zusammenfassung im Fenster zeigt die Kameras als Tabelle: links das Modell, wie es in den
Dateien steht, rechts ein Feld mit dem Ordnernamen. **Tippen Sie dort einfach den gewünschten
Namen hinein** (etwa `Sony A7C` statt `ILCE-7CM2`) und drücken Sie „Weiter". Der Eintrag wird
dauerhaft in die Einstellungen geschrieben (siehe Abschnitt 6), und die betroffenen Dateien
werden noch einmal analysiert. Im schwarzen Fenster fragt der geführte Ablauf stattdessen:
**Soll ein Kameramodell einen anderen Ordnernamen bekommen?** – Modell eintippen, dann den
Ordnernamen; Enter allein heißt „nichts ändern".

### Schritt 3: Kopieren

Zuerst sagt das Fenster, wie viele Dateien und wie viel Speicher kopiert werden (im
schwarzen Fenster ist das der **Probelauf**). Nach „Jetzt kopieren" wird kopiert. Jede Datei wird zuerst unter einem Zwischennamen
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

Das Aufräumen hat eine eigene Seite. Sie zeigt je Quellordner, wie viele Dateien eine
geprüfte Kopie im Archiv haben und wie groß sie sind. **Beim ersten Mal: „Überspringen –
nichts löschen" oder den sicheren Standard.** Der Standard verschiebt die Originale nicht ins
Nichts, sondern in einen Ordner `_geloescht_<Datum>` innerhalb der Quelle. Dort können Sie in
Ruhe nachsehen und den Ordner später selbst löschen. Vor jeder einzelnen Datei werden
Original und Archivkopie noch einmal vollständig gelesen und verglichen; stimmt etwas nicht,
bleibt die Datei stehen und wird gemeldet.

Zum Bestätigen tippen Sie ein ganzes Wort in das Feld (`verschieben` für den Ordner
`_geloescht_`, `loeschen` für endgültiges Löschen). Ein leeres Feld oder ein anderes Wort
heißt: keine Datei anfassen – das Programm sagt dann, dass nichts gestartet wurde. Wer das
Häkchen **„Leere Ordner entfernen"** setzt, tippt dafür das Wort `entfernen`. Haben Sie auf
der Startseite **Verschieben** gewählt, verlangt das Fenster schon vor Schritt 3 das Wort
`verschieben`, weil dort die Quelle geleert wird. Im schwarzen Fenster gelten dieselben
Wörter.

Am Ende steht **Alles erledigt** mit der Anzahl der Dateien je Status (Abschnitt 5 erklärt
die Wörter), dazu die Knöpfe „Bericht öffnen" und „Quelle aufräumen…".

### Der Ablauf im schwarzen Fenster (Alternative ohne Oberfläche)

Wer lieber Fragen im Textfenster beantwortet, ruft im Programmordner `fotosort.bat start`
auf (Eingabeaufforderung öffnen: in der Adresszeile des Explorers `cmd` eintippen). Die
Fragen dort:

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
fotosort.bat analyse    --ziel D:\Archiv
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
Sekunde und der geschätzten Restzeit, höchstens zweimal je Sekunde erneuert. **Pause** hält
nach der laufenden Datei an, **Fortsetzen** macht weiter, **Abbrechen** beendet den Schritt
sauber – das Bisherige bleibt gespeichert, der nächste Lauf macht dort weiter. Reagiert ein
Schritt nicht auf „Abbrechen", erscheint nach einer Weile „Sofort beenden". Im schwarzen
Fenster zeigt beim Kopieren und Prüfen eine Zeile dasselbe. Am Ende jeder Phase stehen Dauer
und Durchsatz.

Die Listen **Fehler**, **Doppelte Dateien** und **Dateien ohne Datum** öffnen sich über die
Knöpfe auf der Startseite und in den Zusammenfassungen – immer seitenweise mit 100 Zeilen,
nie alles auf einmal.

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
- `metadaten_prozesse` – wie viele ExifTool-Programme gleichzeitig laufen. `0` = Anzahl der Prozessorkerne.
- `kopier_worker` / `hash_worker` – gleichzeitige Kopier- bzw. Lesevorgänge; `0` = automatisch.
  `fotosort.bat messen` schlägt passende Werte vor.
- `exiftool_pfad` – Pfad zu `exiftool.exe`, falls ein anderes ExifTool benutzt werden soll.
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
`exiftool` neben `fotosort.exe`. Kommt die Meldung trotzdem, ist der Ordner beim Entpacken
verloren gegangen: die ZIP-Datei noch einmal vollständig entpacken. Aus dem Quellcode
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
- **Eigene Ordnervorlage:** Steht `{kamera}` in derselben Ebene wie das Datum
  (`{jahr}-{monat}-{tag} {kamera}`), kann ein Tagesordner mit Zusatz für die falsche
  Kamera wiederverwendet werden. Mit der Standardvorlage passiert das nicht.

---

## 10. Was noch nicht gebaut ist

- `fotosort wiederherstellen` (Datenbank aus der Sicherungskopie holen) und
  `fotosort ziel-index --neu-aufbauen` (das Archiv neu einlesen) melden sich mit
  „Er kommt in Phase 3" und tun noch nichts. Der Weg von Hand steht in Abschnitt 8.
- Der Betrieb auf dem TrueNAS-Server (im Browser, mit eigenem Ordner-Browser statt des
  Windows-Dialogs) ist eine spätere Phase. Die Oberfläche läuft dort schon jetzt mit
  `fotosort fenster --ohne-fenster`; der Ordnerpfad wird dann eingetippt.

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

**Das Paket selbst bauen** (wie es die GitHub-Actions tun): `python paket/exiftool_holen.py
build/exiftool`, dann `python paket/bauen.py --exiftool build/exiftool`, dann
`python paket/pruefen.py build/paket/dist/fotosort build/pruefung`. Das Ergebnis liegt unter
`build/paket/dist/fotosort`.
