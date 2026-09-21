# SPEC – Foto-Sortierer

Das Programm heißt **fotosort**. Das Repository heißt aus historischen Gründen `Culling`.

Diese Datei ist die verbindliche Beschreibung des Projekts. Bei Widersprüchen zwischen einem Prompt und dieser Datei: nachfragen, nicht raten.

## 1. Ziel

Ein Werkzeug, das einen großen, chaotischen Ordnerbaum mit Fotos und Videos einliest und alle Dateien in eine saubere Zielstruktur nach **Aufnahmedatum** und **Kamera** einsortiert. Es wird alle paar Monate erneut mit neuen Bildern gefüttert und muss dann in die bereits bestehende Zielstruktur einsortieren.

Oberste Regel: **Es darf niemals ein Bild verloren gehen.** Geschwindigkeit ist wichtig, kommt aber immer nach Sicherheit.

## 2. Umgebung

- **Entwicklung und Tests:** Linux im Docker-Container, ausschließlich mit dem künstlichen Testbaum (§11). ExifTool ist dort installiert.
- **Erste Nutzung mit echten Fotos:** Windows 11, AMD Ryzen 9 (16 Kerne / 32 Threads), viel RAM.
- **Späterer Betrieb:** TrueNAS-Server (Linux, als Docker-Container).
- Deshalb von Anfang an plattformneutral: nur `pathlib`, keine Windows-Sonderwege, keine fest eingebauten Pfade. Benannte Ausnahmen sind das Pfad-Präfix für lange Windows-Pfade (§5) und die betriebssystemabhängige Erkennung von Netzlaufwerken und Laufwerksgrenzen (§4 Phase 3).
- Quelle und Ziel können lokale Platten, externe SSDs oder SMB-Netzlaufwerke sein (auch UNC-Pfade wie `\\truenas\Daten\...`).
- Sprache: Python 3.12+. Metadaten über **ExifTool** (extern, muss installiert sein).
- Oberfläche und alle Meldungen auf Deutsch.

### ExifTool finden und fehlendes ExifTool behandeln

- **Gesucht** wird ExifTool über `PATH`. Der Pfad ist überschreibbar. Vorrang: Umgebungsvariable `FOTOSORT_EXIFTOOL`, dann der Konfigurationswert `exiftool_pfad` (Gruppe `[leistung]`, §9), dann `PATH`.
- Bei jedem Start wird geprüft, ob ExifTool vorhanden und startbar ist. Fehlt es, hängt die Folge vom Befehl ab:
  - **Harter Abbruch** bei allen Befehlen, die Metadaten brauchen: `analyse` und `start` (§8) sowie der Erzeuger des Testbaums (§11). Ohne ExifTool gäbe es weder Aufnahmedatum noch Kamera; alle Dateien landeten unter `_Ohne_Datum/Unbekannte_Kamera`. Das wäre kein brauchbares, sondern ein stillschweigend falsches Ergebnis, deshalb wird gar nicht erst angefangen.
  - **Kein Abbruch** bei allen übrigen Befehlen: `scan`, `status`, `bericht`, `kopieren`, `pruefen`, `aufraeumen`, `ziel-index` und `wiederherstellen` (§8). Sie lesen keine Metadaten, sondern arbeiten mit dem, was die Analyse bereits in die Datenbank geschrieben hat. Fehlt ExifTool, geben sie höchstens den Hinweis aus, dass die Analyse ohne ExifTool nicht laufen wird.
- Die Meldung nennt den gesuchten Pfad und die beiden Wege, ihn zu setzen (`FOTOSORT_EXIFTOOL`, `exiftool_pfad`).

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
2. Video-Felder **mit** Zeitzonen-Offset. Sie geben die Ortszeit der Aufnahme direkt an und werden bevorzugt, in dieser Reihenfolge:
   1. ein Feld mit Offset **aus der Videodatei selbst** — QuickTime `CreationDate` (Apple, viele Kameras) oder die in Sony-MP4-Dateien eingebetteten Sony-XML-Metadaten (ExifTool-Feld `CreationDateValue`, Sony A7C, A7C II und andere);
   2. der **Sony-XML-Sidecar** `C0001M01.XML` (Feld `CreationDate` mit Offset, dritte Sidecar-Form, siehe „Zusammengehörige Dateien"); er wird für die Videodatei gelesen, zu der er gehört.
   Für Videos wird ExifTool ohne `-fast2` aufgerufen, falls diese Felder damit nicht mehr geliefert werden (Sony legt seine XML-Metadaten am Ende der Datei ab; das wird beim Bau geprüft und im Code festgehalten).
3. **Nur bei Video-Dateitypen:** `CreateDate` / `MediaCreateDate` ohne Zeitzonen-Offset – der Wert wird als UTC behandelt und in die eingestellte **Heimat-Zeitzone** umgerechnet (Standard `Europe/Berlin`). Diese Dateien werden im Bericht als „Zeitzone angenommen" gekennzeichnet.
4. **Nur bei Fotos:** `CreateDate` / `DateTimeDigitized` – der Wert wird als Kamera-Ortszeit gelesen, **nie als UTC**. Es wird nicht umgerechnet, und es wird nichts als „Zeitzone angenommen" gekennzeichnet. Die UTC-Annahme aus Quelle 3 gilt ausschließlich für Videos.
5. Datum im Dateinamen (Muster wie `IMG_20260101_…`, `2026-01-01 …`, `PXL_20260101…`)
6. Änderungsdatum der Datei – gilt als **unsicher**

**Sicher und unsicher:** Die Quellen 1 bis 5 liefern ein **sicheres** Datum. Das gilt ausdrücklich auch für das aus UTC umgerechnete Datum aus Quelle 3 und für das Datum aus dem Dateinamen (Quelle 5). Die Kennzeichnung „Zeitzone angenommen" ist nur eine Angabe für den Bericht; sie macht das Datum nicht unsicher und führt nicht nach `_Ohne_Datum`. **Unsicher ist ausschließlich das Datum aus Quelle 6** (Änderungsdatum der Datei).

- Verhalten bei unsicherem Datum ist einstellbar: Standard ist die Vorlage für Dateien ohne Datum (`_Ohne_Datum/{kamera}`), alternativ nach Änderungsdatum einsortieren.
- Offensichtlich kaputte Daten (vor 1990, in der Zukunft, `0000:00:00`) gelten als nicht vorhanden.
- Es wird die Kamera-Ortszeit genommen, keine Umrechnung bei Fotos.
- Option „Tagesgrenze" (Standard 00:00, z. B. auf 04:00 stellbar), damit Aufnahmen nach Mitternacht noch zum Vortag zählen.
- Stammt das Datum aus dem Dateinamen, wird die Tagesgrenze nur angewendet, wenn der Dateiname auch eine Uhrzeit enthält (z. B. `IMG_20260101_013000`). Steht dort nur ein Datum (z. B. `2026-01-01 Urlaub.jpg`), wird es genommen, wie es dasteht. Wie oft das vorkam, steht im Bericht.

### Zusammengehörige Dateien

Dateien mit gleichem Stammnamen im selben Quellordner wandern gemeinsam und bekommen Datum/Kamera der Hauptdatei (Priorität RAW > JPG/HEIF > Video):

- RAW + JPG/HIF-Paare
- Sidecars: `.xmp`, `.dop`, `.pp3`, Sony-Video-`M01.XML`, `.thm`, `.aae`

Ein Sidecar gehört zur Hauptdatei, wenn sein Name eine der drei folgenden Formen hat:

1. **Stammname + Sidecar-Endung** (`DSC01234.xmp`),
2. **vollständiger Dateiname + Sidecar-Endung** (`DSC01234.ARW.xmp`),
3. **Stammname + Zusatzmuster + Sidecar-Endung** (`C0001M01.XML` gehört zu `C0001.MP4`). Diese dritte Form deckt die Sony-Video-Sidecars ab, die die ersten beiden nicht erfassen. Die Zusatzmuster stehen in der Konfiguration (`sidecar_zusatzmuster`, Standard `M[0-9][0-9]`, also `M01` bis `M99`, §9).

Die Formen 1 und 2 gelten für alle Sidecar-Endungen.

### Dateitypen

Standardliste, in der Konfiguration erweiterbar. In Klammern steht der Schlüsselname aus §9:

- **Foto** (`foto`): `jpg jpeg heic hif png tif tiff webp`
- **RAW** (`raw`): `arw cr2 cr3 nef dng raf orf rw2 srw`
- **Video** (`video`): `mp4 mov mts m2ts avi mkv`
- **Sidecar** (`sidecar`): `xmp dop pp3 thm aae xml`

Alles andere wird nicht angefasst, aber im Bericht gezählt („übersprungen nach Typ").

**Jede gefundene Datei bekommt eine Zeile in der Datenbank** — auch eine, die zu keiner der vier Gruppen gehört. Sie bekommt dann `dateityp` = `sonstiges`, Status `uebersprungen` und als `fehlergrund` „übersprungen nach Typ". Der Scan muss diese Entscheidung für jede Datei treffen können, ohne zu raten; und nur so lässt sich später feststellen, ob eine Datei schon einmal gesehen wurde. `sonstiges` ist **kein** echter Dateityp (siehe unten).

**Der Vergleich der Endung** ist unabhängig von Groß- und Kleinschreibung: `.JPG`, `.jpg` und `.Jpg` sind dieselbe Endung.

**Sidecars sind ein eigener Dateityp, kein Sonderfall.** Ihre Endungen stehen als eigene Gruppe in dieser Liste. Eine Sidecar-Datei ist deshalb **nie** „übersprungen nach Typ". Sie wird aber auch nie für sich allein einsortiert, sondern wandert immer mit ihrer Hauptdatei (siehe „Zusammengehörige Dateien"). Findet sich keine Hauptdatei, bekommt sie den Status `uebersprungen` mit dem Grund „Sidecar ohne Hauptdatei" und erscheint so im Bericht (§10). Die Endung `xml` steht in der Liste, weil sonst das Sony-Sidecar `C0001M01.XML` als „übersprungen nach Typ" gälte und seine Video-Datei ohne Sidecar im Ziel läge.

Diese vier Gruppen sind die **echten Dateitypen**. `sonstiges` gehört nicht dazu. Der Begriff wird in §4 Phase 6 und §5 gebraucht: Eine Datei, für die es eine Zeile in der Datenbank mit einem echten Dateityp gibt, ist nie eine Reste-Datei.

## 4. Ablauf in Phasen

Jede Phase ist einzeln startbar und **fortsetzbar**. Zwischen den Phasen wartet das Programm auf den Nutzer.

1. **Scan** – jede Quelle rekursiv durchlaufen (`os.scandir`), Dateien zählen, Gesamtgröße ermitteln. Ergebnis sofort anzeigen: Anzahl Dateien, Größe, Aufteilung nach Typ — **je Quelle und gesamt**.
   **Ein Archiv hat eine Liste von Quellen**, nicht eine einzige (Tabelle `quellen`, §6; Bedienung in §8). Alle gehen in dasselbe Ziel. Jede Datei merkt sich ihre Quelle (`quellwurzel`).
   **Überschneidungen werden abgefangen**, je Quelle und auf aufgelösten Pfaden, bevor sie durchlaufen wird: Ist eine neue Quelle gleich einer bekannten, wird sie nicht doppelt aufgenommen. Liegt sie **innerhalb** einer bekannten Quelle oder **enthält** sie eine bekannte, wird sie mit Meldung **abgelehnt** (Ereignis `quelle_abgelehnt`) und die übrigen Quellen laufen weiter — sonst würde dieselbe Datei zweimal erfasst. Gegen das Ziel gelten die Regeln unten je Quelle.
   **Nicht erreichbare Quelle:** Ist eine bekannte Quelle beim Scan kein Ordner (Platte nicht eingesteckt, Netzlaufwerk nicht eingebunden), wird sie als `quelle_nicht_erreichbar` gemeldet und in `quellen` mit `erreichbar` = 0 vermerkt; der Rest läuft weiter. **Ihre Dateien gelten dabei nicht als „Quelle nicht mehr vorhanden"** — die Auswertung aus §6 läuft nur für Quellen, die in diesem Lauf tatsächlich durchlaufen wurden. Sonst ließe eine abgezogene Platte alle ihre Bilder als verschwunden erscheinen.
   **Parallel je physischem Laufwerk:** Quellen werden nach der Laufwerkskennung gruppiert (`quellen.laufwerk`). Gruppen laufen parallel, innerhalb einer Gruppe nacheinander — zwei gleichzeitige Durchläufe auf derselben Platte machen sie nur langsamer. Kennung: unter Linux die Gerätenummer (`st_dev`) der Wurzel; unter Windows der Laufwerksbuchstabe, bei Netzpfaden der **Server** (`\\server`), nicht die Freigabe, weil mehrere Freigaben meist auf denselben Platten liegen. Dass zwei Laufwerksbuchstaben auf derselben physischen Platte liegen können, wird hier nicht erkannt (vermerkt für Phase 6). Der Zugriff auf die Datenbank bleibt einsträngig: Die parallelen Durchläufe sammeln nur, verbucht wird an einer Stelle.
   **Vor dem Durchlauf wird die Lage von Quelle und Ziel geprüft.** Beide Pfade werden mit `Path.resolve()` aufgelöst, Verknüpfungen also mit aufgelöst. Danach gilt genau das:
   - Quelle gleich Ziel → **Abbruch** mit Meldung.
   - Ziel liegt innerhalb der Quelle → der Zielordner wird **vom Scan ausgeschlossen**, mit Meldung. Der Lauf geht weiter.
   - Quelle liegt innerhalb des Ziels → **Abbruch** mit Meldung.

   Diese Prüfung endet nicht am Anfang: Während des Durchlaufs wird der aufgelöste Pfad **jedes** Ordners gegen das aufgelöste Ziel geprüft. So wird auch eine Verknüpfung gefunden, die aus der Quelle ins Ziel zeigt und die ein reiner Textvergleich der Pfade übersehen würde.
   **Auch für jede einzelne Datei** wird der aufgelöste Pfad gegen das aufgelöste Ziel geprüft, nicht nur für Ordner. Eine Verknüpfung, die auf eine *Datei* im Ziel zeigt (etwa `Lieblingsbilder/DSC01234.ARW` → `<Ziel>/2026/…/DSC01234.ARW`), wäre sonst eine gewöhnliche Quelldatei, deren `quellpfad` auf eine Archivdatei zeigt — und ein späteres Aufräumen der Quelle würde das Archivbild selbst löschen. Liegt der aufgelöste Pfad einer Datei im Ziel, wird sie mit Status `uebersprungen` und dem Grund „zeigt ins Ziel" vermerkt und im Bericht aufgeführt (§10). Zusätzlich wird unmittelbar vor jeder Löschung festgestellt, dass Quelldatei und Zieldatei nicht dieselbe Datei sind (gleiche Geräte- und Inode-Nummer bzw. gleicher aufgelöster Pfad).
   **Ordner-Verknüpfungen** (Symlinks unter Linux, Junctions und Verzeichnis-Symlinks unter Windows) werden standardmäßig **nicht verfolgt** (`verknuepfungen_folgen` = `false`, §9). Sie werden gezählt und im Bericht aufgeführt (§10). Grund: Ein Ring aus Verknüpfungen ließe den Scan endlos laufen, und dieselbe Datei erschiene unter zwei Pfaden, also zweimal in der Datenbank. **Versteckte Ordner** werden dagegen normal erfasst.
   **Ausschlussmuster** aus der Konfiguration (`ausschlussmuster`, §9) werden in dieser Phase angewendet; ausgeschlossene Pfade werden gezählt und im Bericht aufgeführt.
   Beim ersten Scan eines Ziels werden die Archiv-ID, die lokale Datenbank und die `config.toml` angelegt (§6). Der Scan ist fortsetzbar; wie ein zweiter Scan eine bereits bekannte Zeile behandelt, steht in §6 („Zweiter Scan").
2. **Analyse** – Metadaten lesen, Ziel für jede Datei berechnen, Namenskonflikte erkennen (mehrere Dateien mit demselben berechneten Zielpfad). Ergebnis: Plan plus Zusammenfassung (wie viele Dateien in welche Jahre, je Quelle und gesamt; gefundene Kameras mit Anzahl; Anzahl Namenskonflikte; Anzahl ohne sicheres Datum; Anzahl „Zeitzone angenommen"). **Noch keine Datei wird angefasst.**
   **Duplikate werden hier nicht erkannt.** Dafür braucht es den Hash, und der entsteht laut §7 erst beim Kopieren, damit die Quelle nur einmal gelesen wird — Duplikate erkennt Phase 3. Die Analyse gibt lediglich eine **Schätzung „mögliche Duplikate"** aus: Dateien, die in Größe **und** Aufnahmezeit mit einer anderen übereinstimmen (ohne Sidecars). Sie ist ausdrücklich als Schätzung gekennzeichnet, entscheidet nichts und dient nur der Orientierung.
3. **Übertragen** – wahlweise
   - **Kopieren** (Standard): Quelle bleibt unberührt.
   - **Verschieben**: jede Datei wird einzeln kopiert, geprüft und erst dann in der Quelle gelöscht.
     **Die Löschbedingung aus §5 gilt hier unverändert.** Sie gilt für *jeden* Löschvorgang des Programms, nicht nur für Phase 5. Im Verschieben-Modus wird die Quelle nämlich schon hier gelöscht, Datei für Datei — und ohne diese Klarstellung liefe genau der Verlustpfad, den §5 schließt: Liegt die Quelle auf einem synchronisierten Ordner oder einem langsamen Netzlaufwerk, kann sie sich zwischen Kopieren und Löschen ändern; der Vergleich des frischen Ziel-Hashes mit dem gespeicherten Quell-Hash merkt davon nichts, weil beide denselben alten Stand beschreiben. Der Ablauf je Datei ist deshalb: kopieren → **Zieldatei frisch lesen** → **Quelldatei frisch lesen** → beide Hashes gegen den gespeicherten Quell-Hash → Status `geprueft` und `bestaetigt_in_lauf` auf den laufenden Lauf setzen → **erst dann** löschen. Weicht die Quelle ab, wird nicht gelöscht; es gilt dieselbe Folge wie in Phase 5 (Status zurück auf `analysiert`, Eintrag im Bericht unter „Quelle seit dem Kopieren geändert").
     **Quellinterne Duplikate** verschwinden auch im Verschieben-Modus nur über den Weg `duplikat` → `duplikat_bestaetigt` (§5), also nach Frischlesung von Quelle und Ziel. Sie wurden nie kopiert; ohne diese Regel gäbe es für sie gar keine Prüfung.
     **Gebaut (Phase 5):** Nach dem Kopieren wird die Frischlesung beider Seiten im Hash-Worker gemacht; stimmen beide Hashes mit dem beim Kopieren berechneten überein, geht die Datei durch dieselbe Löschstelle wie beim Aufräumen (endgültig; einen Ordner `_geloescht_` gibt es im Verschieben-Modus nicht, denn Verschieben soll die Quelle freigeben). Weicht die Quelle ab: `analysiert`, Hash geleert, Ereignis `quelle_seit_kopieren_geaendert`, die schon geschriebene Kopie bleibt im Ziel. Weicht das Ziel ab: `fehler`, Ereignis `loeschung_verweigert`. Duplikate (gleicher Inhalt schon im Ziel) bleiben in der Quelle, bis `pruefen` sie bestätigt und `aufraeumen` sie entfernt.
     Liegen Quelle und Ziel nachweislich auf demselben Laufwerk, wird stattdessen umbenannt. Das ist erlaubt, weil dabei keine Daten kopiert werden, sondern nur ein Verzeichniseintrag geändert wird. Danach wird geprüft, dass die Zieldatei existiert und die Größe stimmt; die Datei bekommt den Status `verschoben`. Den Hash für den Ziel-Index berechnet erst die Prüf-Phase aus der Zieldatei.
     **Das Umbenennen darf niemals eine vorhandene Zieldatei überschreiben.** `os.rename` bzw. `Path.rename` ersetzt unter POSIX eine vorhandene Zieldatei stillschweigend und ohne Fehler; das wäre ein Verlustpfad. Deshalb wird ein nicht überschreibendes Verfahren benutzt: unter Linux `os.link` auf den Zielnamen und danach `os.unlink` der Quelle (oder `renameat2` mit `RENAME_NOREPLACE`), unter Windows `MoveFileEx` **ohne** `MOVEFILE_REPLACE_EXISTING`. Ist der Zielname schon belegt, schlägt der Vorgang fehl, und es greift die Regel „Niemals überschreiben" aus §5 (Duplikat oder neuer Name mit Anhang `_1`, `_2` …).
     Ob zwei Pfade wirklich auf demselben Laufwerk liegen, muss sicher festgestellt werden (Kennung des Dateisystems, nicht der Laufwerksbuchstabe im Pfad). Lässt es sich nicht sicher feststellen, wird kopiert statt umbenannt.
     **Ein Netzlaufwerk gilt nie als „gleiches Laufwerk".** Liegt mindestens einer der beiden Pfade auf einem Netzlaufwerk (UNC, SMB, CIFS, NFS), gilt „gleiches Laufwerk" grundsätzlich als **nicht nachgewiesen**; es wird kopiert statt umbenannt. Erkennung: unter Windows über das UNC-Präfix bzw. `GetDriveType` gleich `DRIVE_REMOTE` (auch für verbundene Laufwerksbuchstaben aufgelöst), unter Linux über den Dateisystemtyp des Einhängepunkts (`cifs`, `smb3`, `nfs`, `nfs4`, `fuse.sshfs`, `9p`, `virtiofs`; die vollständige Liste steht in §6 und gilt für beide Prüfungen).
4. **Prüfen** – jede Zieldatei wird erneut vollständig gelesen und ihr Hash mit dem der Quelle verglichen. Ergebnis: „X von Y geprüft, Z Fehler".
   Gelesen wird parallel mit den Hash-Workern des Profils (§7, §9), in Ordnerreihenfolge des Ziels; entschieden und gespeichert wird nur im Hauptstrang. Die Phase ist fortsetzbar (bearbeitet werden nur Zeilen mit Status `kopiert`, `duplikat` oder `verschoben`) und lässt sich mit Strg+C sauber abbrechen. Der Ziel-Index bekommt die frisch gelesenen Hashes.
   - `kopiert` → `geprueft`, wenn der frisch gelesene Hash der Zieldatei dem gespeicherten Quell-Hash entspricht.
   - `duplikat` → `duplikat_bestaetigt`, wenn die Partnerdatei im Ziel frisch gelesen wurde und ihr Hash dem Quell-Hash entspricht (§5). Zeigen viele Duplikate auf dieselbe Partnerdatei, wird sie je Lauf nur einmal gelesen; Größe und Hash werden trotzdem für **jede** Zeile einzeln gegen deren gespeicherte Werte geprüft.
   - `verschoben` (Phase 5): nur solange der Hash fehlt; danach gilt die Zeile als fertig geprüft.
   - Diese Phase setzt **nicht** `bestaetigt_in_lauf`: Das bedeutet „Quelle **und** Ziel im Lauf frisch gelesen" und ist allein Sache des Aufräumens (Phase 5, §5).
   - **Schlägt die Prüfung fehl** (Zieldatei fehlt, Größe weicht ab, Inhalt weicht ab, nicht lesbar), bekommt die Zeile Status `fehler` mit Grund und ein Ereignis `pruefung_fehlgeschlagen`. Die fehlerhafte Zieldatei wird **weder gelöscht noch überschrieben**, nur gemeldet. Ein erneutes `fotosort kopieren` gibt solche Zeilen wieder frei (Status `analysiert`, Zielpfad aus den gespeicherten Feldern neu berechnet, Ereignis `neu_nach_pruefung`) und legt nach den Regeln aus §5 eine frische Kopie an; ist der Name belegt, bekommt sie den Anhang `_1`.
   Für umbenannte Dateien (Status `verschoben`) gibt es keine Quelle mehr, gegen die verglichen werden könnte. Für sie wird in dieser Phase der Hash aus der Zieldatei berechnet und in den Ziel-Index geschrieben. Im Bericht werden sie getrennt ausgewiesen.
5. **Quelle aufräumen** (nur im Kopier-Modus, nur auf ausdrücklichen Befehl) – gelöscht werden ausschließlich Quelldateien mit Status `geprueft` oder `duplikat_bestaetigt` (§5). Kein anderer Status berechtigt zum Löschen.
   **Der Status ist notwendig, aber nicht hinreichend.** Vor jeder einzelnen Löschung werden **beide** Dateien im aktuellen Lauf vollständig neu gelesen: die **Zieldatei** und die **Quelldatei**. Beide Hashes werden mit dem in der Datenbank gespeicherten Quell-Hash verglichen. Das gilt für `geprueft` genauso wie für `duplikat_bestaetigt`; ein Status oder Hash aus einem früheren Lauf genügt für keinen von beiden.

   **Die Bedingung zum Löschen, als ein Satz:** Eine Quelldatei wird genau dann gelöscht, wenn ihr Status `geprueft` oder `duplikat_bestaetigt` ist **und** Quelldatei und Zieldatei in diesem Lauf beide vollständig frisch gelesen wurden (Spalte `bestaetigt_in_lauf` trägt die Nummer des laufenden Laufs, §6) **und** beide denselben Hash tragen wie der gespeicherte Quell-Hash; fehlt auch nur eine dieser Bedingungen, wird nicht gelöscht.

   **Warum die Quelle mitgelesen wird.** Würde nur die Zieldatei frisch gelesen und ihr Hash mit dem beim Kopieren gespeicherten Quell-Hash verglichen, beschrieben beide Werte denselben alten Stand. Ändert sich die Quelldatei nach dem Kopieren — durch Bearbeitung, Synchronisierung oder eine neue Fassung —, stimmen die beiden Werte weiterhin überein. Die geänderte Quelle würde gelöscht, obwohl ihr aktueller Inhalt nie im Ziel angekommen ist. Das ist ein Verlustpfad; er wird allein dadurch geschlossen, dass auch die Quelle im aktuellen Lauf frisch gelesen wird.

   Was bei Abweichungen geschieht:
   - **Quelle weicht ab** (frisch gelesener Quell-Hash ungleich gespeichertem Quell-Hash): nicht löschen. Der Status fällt auf `analysiert` zurück, denn die Datei muss neu kopiert werden; der gespeicherte Hash und `bestaetigt_in_lauf` werden geleert (der Hash wird beim nächsten Kopieren neu berechnet, §7). Die Datei erscheint im Bericht in der Liste „Quelle seit dem Kopieren geändert" (§10).
   - **Ziel weicht ab:** nicht löschen. Die Datei bekommt Status `fehler` mit Grund und erscheint im Bericht.
   - **Frischlesung fehlt** (`bestaetigt_in_lauf` gehört nicht zum laufenden Lauf und die Frischlesung lässt sich nicht nachholen): nicht löschen, im Bericht aufführen.

   Vorher Anzahl und Größe anzeigen und bestätigen lassen.

   **Gebaut (Phase 5).** Jede Löschung des Programms — hier und im Verschieben-Modus — geht durch **eine einzige Stelle** (`loeschen.quelldatei_entfernen`), die alle Bedingungen dieses Abschnitts an der frisch aus der Datenbank gelesenen Zeile selbst prüft und keinem Aufrufer vertraut. Ablauf je Datei: Quelle und Ziel im Hash-Worker vollständig lesen → `bestaetigt_in_lauf` festschreiben → Zeile erneut lesen, alle Bedingungen prüfen → entfernen → `quelle_geloescht` festschreiben.
   - **Bestätigung:** je Quelle werden Anzahl und Größe gezeigt; gelöscht wird nur nach Eingabe eines Wortes (`loeschen` bei endgültigem Löschen, `verschieben` beim Ordner `_geloescht_`, `entfernen` bei leeren Ordnern). Enter allein oder ein anderes Wort überspringt die Quelle. Ohne Terminal (Pipe, Skript) gibt es keine Bestätigung und es wird nichts gelöscht. `--quelle A` beschränkt auf eine Quelle; ohne Angabe wird je Quelle einzeln gefragt. `--dry-run` zeigt die Liste und legt keinen Lauf an.
   - **Löschweise:** Standard ist der Ordner `_geloescht_<Datum>` innerhalb der jeweiligen Quelle: Die Datei wird dorthin nicht überschreibend verschoben (gleicher relativer Pfad; belegter Name → Anhang `_1`; kann das Dateisystem kein nicht überschreibendes Umbenennen, wird kopiert, geprüft und dann entfernt). Der Nutzer löscht diesen Ordner später selbst. Nur mit `--endgueltig` wird wirklich gelöscht. Wo die Datei im Ordner `_geloescht_` liegt, steht in `schreibpfad` (§6). Der Ordner wird vom Scan, vom Aufräumen und vom Entfernen leerer Ordner nie angefasst.
   - **Nach einem Absturz** (die Datei ist weg, der Status noch nicht geschrieben): Fehlt die Quelle, wird **nichts** gelöscht. Nur wenn `bestaetigt_in_lauf` gesetzt ist **und** die Datei nachweislich im Ziel (oder unter dem Papierkorb-Pfad) mit dem gespeicherten Hash liegt, wird der Status `quelle_geloescht` nachgetragen (Ereignis `loeschung_nachgetragen`). Sonst Status `fehler` mit Grund und Ereignis `loeschung_verweigert`.
   - Eine „Quelle seit dem Kopieren geändert" hat danach eine andere Größe oder Zeit als beim Scan; `kopieren` stellt sie auf `gefunden` zurück. Der Weg zur frischen Kopie ist deshalb `scan` → `analyse` → `kopieren`; die neue Fassung bekommt neben der alten Kopie den Anhang `_1`.
6. **Leere Ordner entfernen** (eigener, optionaler Schritt) – nur wirklich leere Ordner. Reste wie `Thumbs.db`, `.DS_Store`, `desktop.ini` zählen als leer und dürfen mit entfernt werden (Liste konfigurierbar: `reste_dateien`, §9). Der angegebene Quell-Wurzelordner selbst bleibt stehen.
   Diese Reste-Dateien sind eine ausdrücklich benannte, eng begrenzte **Ausnahme** von der Löschregel aus §5: Sie stehen nie **mit echtem Dateityp** in der Datenbank und sind keine Quelldateien aus deren Bestand. (Eine Zeile haben sie durchaus — jede gefundene Datei bekommt eine, §3 — aber mit `dateityp` = `sonstiges`.) Für Quelldateien aus dem Bestand der Datenbank gilt die Statusregel unverändert und ohne Ausnahme.
   **Die Ausnahme wird durchgesetzt, nicht geglaubt.** Eine Datei gilt nur dann als Rest, wenn zusätzlich zum passenden Namen gilt: Es gibt für sie **keine Zeile in der Datenbank mit einem echten Dateityp** (Foto, RAW, Video, Sidecar, §3). Das Programm prüft das vor jeder einzelnen Löschung selbst, für jeden Namen aus der Liste. Sonst könnte ein Eintrag wie `.jpg` oder `*` in `reste_dateien` die gesamte Löschregel aushebeln. Trifft ein Name aus `reste_dateien` auf eine Datei, die mit echtem Dateityp in der Datenbank steht, wird sie **nicht** gelöscht, der Ordner gilt als nicht leer, und der Fall wird im Bericht vermerkt.
   **Gebaut (Phase 5):** `aufraeumen --leere-ordner`, nach Bestätigung mit dem Wort `entfernen`, `--dry-run` zeigt die Ordner. Ein Ordner gilt nur als leer, wenn er ausschließlich leere Unterordner und Reste-Dateien ohne echten Dateityp enthält; Verknüpfungen, jede andere Datei und ein im Quellbaum liegendes Ziel machen ihn nicht leer. Reste werden erst entfernt, wenn der Ordner sonst leer ist (Ereignis `rest_entfernt`), dann der Ordner (`leerer_ordner_entfernt`). Der Ordner `_geloescht_` bleibt.

## 5. Sicherheit

- Kopieren immer in eine temporäre Datei im Zielordner, danach atomar und nicht überschreibend umbenennen.
- **Name der temporären Datei:** der vollständige Zieldateiname plus `.part`, also `DSC01234.ARW.part` für `DSC01234.ARW`. Nicht der Stammname: Ein RAW+JPG-Paar ergäbe sonst zweimal `DSC01234.part`. Der Zielname ist im Zielordner eindeutig (Regel „Niemals überschreiben"), damit ist auch der `.part`-Name eindeutig; `DSC01234.ARW.part` und `DSC01234.JPG.part` kollidieren nicht.
- **Liegengebliebene `.part`-Dateien** aus einem abgebrochenen Lauf werden beim nächsten Start erkannt. Entfernt werden sie **nur dann, wenn keine Zeile in der Datenbank sie beansprucht** — also kein Kopiervorgang gerade in genau diese Datei schreibt oder sie fortsetzen will. Beanspruchte `.part`-Dateien bleiben stehen und werden vom zugehörigen Kopiervorgang neu geschrieben.
- **Niemals überschreiben.** Existiert der Zielname schon:
  - gleicher Hash → Duplikat, wird nicht erneut kopiert. Gelöscht werden darf die Quelldatei deswegen noch nicht; dafür braucht sie den Status `duplikat_bestaetigt` (siehe unten).
  - anderer Inhalt → neuer Name mit Anhang `_1`, `_2` …; zusammengehörige Dateien bekommen denselben Anhang.
  - **Wo der Anhang steht:** hinter dem Stammnamen der **Hauptdatei** der Gruppe, damit die Sidecars weiter zu ihr passen (§3, drei Formen): `DSC01234.ARW` → `DSC01234_1.ARW`, `DSC01234.xmp` → `DSC01234_1.xmp`, `DSC01234.ARW.xmp` → `DSC01234_1.ARW.xmp`, `C0001M01.XML` → `C0001_1M01.XML` (Hauptdatei `C0001.MP4`).
  - Der Anhang wird **nach** der Duplikat-Entscheidung bestimmt: Ist ein Mitglied der Gruppe inhaltsgleich mit der Datei unter seinem Zielnamen, wird es zum Duplikat und zählt nicht mehr; der Anhang gilt dann für die übrigen Mitglieder. So bekommt ein RAW+JPG-Paar, das schon im Ziel liegt und nur um ein neues Sidecar ergänzt wird, keinen unnötigen Anhang.
- **Gleicher Inhalt unter anderem Namen** (über den Ziel-Index gefunden, quellintern oder über mehrere Quellen): ebenfalls Duplikat, nur eine Kopie. Das gilt für Fotos, RAW und Videos. **Sidecars sind davon ausgenommen:** Leere oder gleichlautende XMP-Dateien gleichen sich oft, und jedes Sidecar gehört zu seiner eigenen Hauptdatei — es wird kopiert, sofern nicht unter seinem eigenen Zielnamen dieselbe Datei liegt.
- **Umbenennen darf niemals überschreiben.** `os.rename` bzw. `Path.rename` ersetzt unter POSIX eine vorhandene Zieldatei stillschweigend; genau das ist ein Verlustpfad und muss ausgeschlossen werden. Überall, wo umbenannt wird — beim Verschieben auf demselben Laufwerk (§4 Phase 3) und beim abschließenden Umbenennen der `.part`-Datei auf den endgültigen Namen — wird ein nicht überschreibendes Verfahren benutzt: unter Linux `os.link` plus `os.unlink` (oder `renameat2` mit `RENAME_NOREPLACE`), unter Windows `MoveFileEx` **ohne** `MOVEFILE_REPLACE_EXISTING`. Ist der Zielname belegt, schlägt der Vorgang fehl und die Regel „Niemals überschreiben" greift.
- **Wenn das Dateisystem kein nicht überschreibendes Umbenennen kann.** Auf exFAT und FAT32 — dem üblichen Format externer Platten — gibt es keine harten Verknüpfungen, `os.link` schlägt fehl, und `renameat2` mit `RENAME_NOREPLACE` wird dort ebenfalls nicht angenommen. Das Programm stellt das einmal je Ziel-Dateisystem fest und verhält sich dann so:
  - **Das Verschieben auf demselben Laufwerk entfällt** (§4 Phase 3). Es wird auf **Kopieren, Prüfen und Löschen** zurückgefallen: kopieren, Zieldatei frisch lesen und den Hash vergleichen, und erst danach die Quelle nach den Regeln dieses Abschnitts löschen. Das ist langsamer, aber sicher.
  - **Das Kopieren verzichtet auf die `.part`-Datei**, weil auch deren abschließendes Umbenennen nicht überschreibungsfrei möglich wäre. Stattdessen wird die Zieldatei direkt unter ihrem endgültigen Namen **exklusiv angelegt** (`O_EXCL`; das Anlegen schlägt fehl, wenn der Name schon belegt ist, und ist damit auch auf exFAT und FAT32 nicht überschreibend). Ist der Name belegt, greift wieder „Niemals überschreiben".

    **Unter dem endgültigen Zielnamen wird nie etwas gelöscht, nur weil ein Status fehlt.** Bricht der Lauf mitten im Kopieren ab, bleibt eine unvollständige Zieldatei stehen. Sie am fehlenden Status `kopiert` zu erkennen wäre falsch und ein Verlustpfad: Der Status ist nicht dauerhaft, er fällt an mehreren Stellen zurück — bei geänderter Quelle auf `analysiert` (§5), beim zweiten Scan auf `gefunden` (§6), und nach `fotosort wiederherstellen` auf den Stand der letzten Sicherung. In jedem dieser Fälle läge unter dem berechneten Zielnamen ein **fertiges Archivbild**, dessen Zeile gerade nicht auf `kopiert` steht. Dasselbe gilt, wenn Monate später eine andere Datei mit gleichem Namen, Datum und gleicher Kamera denselben Zielpfad bekommt.

    Stattdessen wird der **Anspruch vor dem Schreiben festgehalten**: Die Zeile bekommt ihren `zielpfad` (den berechneten Namen), den `schreibpfad` (die Datei, in die tatsächlich geschrieben wird — mit Anhang, falls der berechnete Name belegt ist), die Nummer des laufenden Laufs und den Status `kopieren_laeuft` (§6). **Reihenfolge im Rückfall:** Die Zieldatei wird zuerst mit `O_EXCL` exklusiv angelegt und **danach** der Anspruch festgeschrieben. Hätte unter dem Namen schon etwas gelegen, wäre das Anlegen gescheitert — eine Datei unter einem beanspruchten `schreibpfad` kann also nur vom Programm selbst stammen. Eine vorhandene Datei unter dem endgültigen Zielnamen wird **nur dann** entfernt, wenn alle Bedingungen zugleich gelten: Es gibt eine Zeile mit genau diesem `schreibpfad`, ihr Status ist `kopieren_laeuft`, der zugehörige Lauf ist nicht der laufende (er wurde also abgebrochen), und die Datei ist kleiner als die Quelle. In jedem anderen Fall bleibt die Datei unangetastet und es greift „Niemals überschreiben" mit dem Anhang `_1`, `_2` … Der Anhang steht im Rückfall damit **vor** der Duplikat-Entscheidung fest; entpuppt sich ein Mitglied als Duplikat, behalten die übrigen ihren Anhang trotzdem — im `O_EXCL`-Zweig lässt sich das nicht vermeiden.

    Im `.part`-Zweig gibt es dieses Problem nicht: Dort wird nur eine `.part`-Datei entfernt, und auch nur, wenn keine Zeile sie beansprucht (siehe oben). Ist die Datei unter dem `schreibpfad` genauso groß wie die Quelle, werden beide frisch gelesen; stimmen die Hashes überein, war die Kopie fertig und wird als `kopiert` übernommen (Ereignis `kopie_nachtraeglich_bestaetigt`), sonst greift „Niemals überschreiben" mit Anhang. Das gilt in beiden Zweigen; im `.part`-Zweig wird der `schreibpfad` dafür unmittelbar **vor** dem abschließenden Umbenennen auf den endgültigen Namen gesetzt, damit ein Absturz zwischen Umbenennen und Status `kopiert` keine verwaiste zweite Kopie hinterlässt. Eine unvollständige Datei unter einem endgültigen Namen kann im `.part`-Zweig nicht vom Programm stammen und bleibt unangetastet.

    **Wie liegengebliebene Dateien gefunden werden.** Das Programm durchsucht nicht das ganze Ziel. Beim Start nimmt es sich die Zeilen mit Status `kopieren_laeuft` aus einem anderen Lauf vor (§6, `kopiert_in_lauf`) und sieht unter deren `zielpfad` (`.part`-Datei) und `schreibpfad` nach. Eine `.part`-Datei, die **keine** Zeile beansprucht, fällt erst auf, wenn ein Kopiervorgang denselben `.part`-Namen anlegen will; sie wird dann nach derselben Regel entfernt und die Kopie wiederholt.
  - **Ein einfaches Umbenennen, das eine vorhandene Datei überschreiben könnte, ist nie erlaubt** — auch nicht als letzter Ausweg, auch nicht „nur dieses eine Mal", auch nicht nach einer vorherigen Existenzprüfung.

  Dass der Rückfall gegriffen hat, steht mit Anzahl im Bericht (§10).
- Duplikate innerhalb der Quelle (gleicher Hash): nur eine Kopie ins Ziel, alle im Bericht auflisten.
- Änderungsdatum der Dateien bleibt beim Kopieren erhalten.
- **Status `duplikat_bestaetigt`:** Eine Quelldatei bekommt ihn nur, wenn die inhaltsgleiche Zieldatei **im aktuellen Lauf** vollständig neu gelesen wurde und ihr Hash mit dem Quell-Hash übereinstimmt. Ein Hash aus einem früheren Lauf oder aus dem Ziel-Index genügt dafür nicht.
- **Der Ziel-Index rechtfertigt niemals eine Löschung.** Er dient nur dazu, Kandidaten für Duplikate schnell zu finden und zu entscheiden, ob kopiert werden muss. Vor jeder Löschung werden Quelldatei und Zieldatei frisch gelesen und verglichen — ohne Ausnahme und ohne Abschaltmöglichkeit.
- **Der Status ist notwendig, nicht hinreichend.** Die Frischlesung im aktuellen Lauf gilt für **beide** löschberechtigenden Status: auch bei `geprueft` wird erneut vollständig gelesen und verglichen, nicht nur bei `duplikat_bestaetigt`. Die Datenbank hält je Datei fest, in welchem Lauf zuletzt frisch gelesen und verglichen wurde (Spalte `bestaetigt_in_lauf`, §6). Gehört dieser Eintrag nicht zum aktuellen Lauf, wird nicht gelöscht.
- **Vor dem Löschen wird auch die Quelle frisch gelesen, nicht nur das Ziel.** Die Zieldatei allein zu prüfen genügt nicht: Verglichen würde der frisch gelesene Ziel-Hash mit dem beim Kopieren gespeicherten Quell-Hash — beide beschreiben denselben alten Stand. Ändert sich die Quelldatei nach dem Kopieren (Bearbeitung, Synchronisierung, neue Fassung), stimmen die beiden Werte weiterhin überein. Die geänderte Quelle würde gelöscht, obwohl ihr aktueller Inhalt nie im Ziel angekommen ist. Deshalb wird vor jeder Löschung **auch die Quelldatei im aktuellen Lauf vollständig neu gelesen** und ihr Hash mit dem gespeicherten Quell-Hash verglichen.
- **Die Bedingung zum Löschen, als ein Satz:** Eine Quelldatei wird genau dann gelöscht, wenn ihr Status `geprueft` oder `duplikat_bestaetigt` ist **und** Quelldatei und Zieldatei in diesem Lauf beide vollständig frisch gelesen wurden (Spalte `bestaetigt_in_lauf` trägt die Nummer des laufenden Laufs, §6) **und** beide denselben Hash tragen wie der gespeicherte Quell-Hash; fehlt auch nur eine dieser Bedingungen, wird nicht gelöscht. Dieser Satz ist der Maßstab, an dem sich der Code messen lassen muss.
- **Weicht die Quelle ab,** wird nicht gelöscht: Der Status fällt auf `analysiert` zurück, weil die Datei neu kopiert werden muss; der gespeicherte Quell-Hash und `bestaetigt_in_lauf` werden geleert. Der Hash wird beim nächsten Kopieren neu berechnet (§7). Liegt unter dem berechneten Zielnamen schon die alte Fassung, greift „Niemals überschreiben": Die neue Fassung bekommt den Anhang `_1`, `_2` … Die Datei erscheint im Bericht in der Liste „Quelle seit dem Kopieren geändert" (§10).
- **Weicht das Ziel ab,** wird ebenfalls nicht gelöscht: Die Datei bekommt Status `fehler` mit Grund und erscheint im Bericht.
- Löschen nur nach bestandener Hash-Prüfung, nie auf Basis von Name oder Größe allein. Aus dem Bestand der Datenbank gelöscht werden dürfen **Quelldateien** ausschließlich aus den Status `geprueft` und `duplikat_bestaetigt`.
- **Eng begrenzte Ausnahmen von dieser Statusregel.** Sie gilt für Quelldateien aus dem Bestand der Datenbank, also für Dateien mit einem echten Dateityp (§3). Ausdrücklich davon ausgenommen sind zwei Arten von Dateien, die nie mit echtem Dateityp in der Datenbank stehen:
  - die Reste-Dateien aus §4 Phase 6 (`Thumbs.db`, `.DS_Store`, `desktop.ini`; Liste konfigurierbar: `reste_dateien`, §9),
  - liegengebliebene `.part`-Dateien aus einem abgebrochenen Kopiervorgang (und nur, wenn keine Zeile in der Datenbank sie beansprucht, siehe oben).

  Weitere Ausnahmen gibt es nicht.
- **Die Reste-Ausnahme wird durchgesetzt, nicht geglaubt.** `reste_dateien` ist eine Namensliste des Nutzers, kein Freibrief. Eine Datei gilt nur dann als Rest, wenn das Programm selbst feststellt, dass es für sie **keine Zeile in der Datenbank mit einem echten Dateityp** (Foto, RAW, Video, Sidecar, §3) gibt. Diese Prüfung läuft vor jeder einzelnen Löschung und lässt sich nicht abschalten. Ohne sie könnte ein Eintrag wie `.jpg` oder `*` in `reste_dateien` die gesamte Löschregel aushebeln.
- Option `byte_vergleich_vor_loeschen` (Standard: aus): vergleicht vor dem Löschen Quelle und Ziel zusätzlich Byte für Byte. Beide Dateien werden vor jeder Löschung ohnehin vollständig gelesen (siehe oben); die Option kostet also keinen zusätzlichen Lesevorgang, sondern nur den Vergleich selbst: Statt nur die beiden Hashes gegeneinander zu halten, werden die Inhalte blockweise verglichen. Sie sichert gegen den theoretischen Fall ab, dass zwei verschiedene Inhalte denselben BLAKE3-Hash ergeben. Warum der Standard trotzdem „aus" ist, steht mit Begründung in `docs/architektur.md` §4.6.
- **Lange Pfade unter Windows werden umgangen, nicht nur gemeldet:** Pfade werden intern mit dem Präfix `\\?\` (bei Netzpfaden `\\?\UNC\`) angesprochen, damit die 260-Zeichen-Grenze nicht greift. Der Fehlergrund „Pfad zu lang" bleibt bestehen, greift aber nur noch, wenn es trotzdem scheitert.
- Ein `--dry-run` für jede Phase, die etwas verändert.
- **Quelle und Ziel dürfen sich nicht beliebig verschachteln.** Beide Pfade werden mit `Path.resolve()` aufgelöst, Verknüpfungen also mit aufgelöst. Danach gilt: Quelle gleich Ziel → Abbruch; Ziel innerhalb der Quelle → der Zielordner wird vom Scan ausgeschlossen, mit Meldung; Quelle innerhalb des Ziels → Abbruch. Während des Durchlaufs wird der aufgelöste Pfad jedes Ordners gegen das aufgelöste Ziel geprüft, damit auch eine Verknüpfung aus der Quelle ins Ziel erkannt wird, die ein Textvergleich der Pfade übersähe (§4 Phase 1).
- **Ordner-Verknüpfungen werden standardmäßig nicht verfolgt** (`verknuepfungen_folgen` = `false`, §9). Sonst ließe ein Ring aus Verknüpfungen den Scan endlos laufen, und dieselbe Datei erschiene unter zwei Pfaden zweimal in der Datenbank. Sie werden gezählt und im Bericht aufgeführt (§4 Phase 1, §10).
- Vor dem Übertragen prüfen, ob im Ziel genug Platz ist.
- Einzelne fehlerhafte Dateien (nicht lesbar, Pfad zu lang, Rechteproblem) brechen den Lauf nicht ab, sondern bekommen Status `fehler` mit Grund und erscheinen im Bericht.

## 6. Fortschritt speichern (Absturzsicherheit)

- Eine **SQLite-Datenbank** pro Archiv speichert den ganzen Fortschritt: jede Quelldatei, den Ziel-Index und jeden Lauf. Die Datenbankdatei heißt **`fotosort.db`** und liegt im Archiv-Ordner (siehe „Ort der Datenbank").
- Ablauf der Status: `gefunden → analysiert → kopieren_laeuft → kopiert → geprueft → quelle_geloescht`, dazu `verschoben`, `duplikat`, `duplikat_bestaetigt`, `uebersprungen`, `fehler`.
- **Die in der Datenbank gespeicherten Statuswerte lauten genau so, ohne Umlaute:** `gefunden`, `analysiert`, `kopieren_laeuft`, `kopiert`, `geprueft`, `verschoben`, `duplikat`, `duplikat_bestaetigt`, `quelle_geloescht`, `uebersprungen`, `fehler`. Andere Schreibweisen gibt es nicht. Grund: An diesen Zeichenketten hängt die Löschberechtigung; eine zweite Schreibweise mit Umlaut wäre eine stille Fehlerquelle. Fließtext und Ausgaben dürfen weiter „geprüft" schreiben; wo der gespeicherte Wert gemeint ist, steht in dieser SPEC die umlautfreie Form in Codeschrift.
  - `kopieren_laeuft`: Der Zielpfad ist beansprucht, die Datei wird gerade geschrieben. Gehört der Status zu einem Lauf, der nicht mehr läuft, war es ein Abbruch — nur dann darf die angefangene Zieldatei entfernt werden (§5). Er berechtigt nie zum Löschen einer Quelldatei.
  - `verschoben`: durch Umbenennen auf demselben Laufwerk ins Ziel gebracht; Existenz und Größe geprüft (§4 Phase 3). Der Hash wird in der Prüf-Phase aus der Zieldatei nachgetragen.
  - `duplikat`: im Ziel liegt vermutlich dieselbe Datei, im aktuellen Lauf aber noch nicht nachgewiesen.
  - `duplikat_bestaetigt`: Zieldatei im aktuellen Lauf frisch gelesen, Hash stimmt mit dem der Quelle überein (§5).
  - Zum Löschen berechtigen ausschließlich `geprueft` und `duplikat_bestaetigt`, und auch dann nur zusammen mit der Frischlesung von Quelle und Ziel im aktuellen Lauf (§4 Phase 5, §5).
- Statuswechsel werden in Blöcken geschrieben (z. B. alle 500 Dateien oder alle 2 Sekunden), damit die Datenbank nicht bremst.
- Nach Absturz, Stromausfall oder Abbruch mit Strg+C: Neustart setzt genau dort fort. Nichts wird doppelt gemacht, nichts vergessen.

### Was ein Lauf ist

- **Ein Lauf ist ein Programmstart eines verändernden Befehls.** `scan`, `analyse`, `kopieren`, `pruefen`, `aufraeumen`, `ziel-index`, `wiederherstellen` und `start` legen beim Start in der Tabelle `laeufe` eine Zeile an; beim Beenden wird dort das Ende eingetragen. `status`, `config` und `bericht` lesen nur und legen **keinen** Lauf an — sonst würde `status` sich selbst als „letzten Lauf" nennen. Ein neuer Start ist ein neuer Lauf, auch wenn er nur dieselbe Phase fortsetzt. Ein Lauf endet mit dem Programm, auch bei Absturz oder Abbruch (die Zeile behält dann ein leeres Ende; ein geordneter Abbruch mit Strg+C trägt das Ende ein und vermerkt das Ereignis `abgebrochen`).
- Die Spalte `bestaetigt_in_lauf` einer Datei speichert die **Nummer des Laufs**, in dem Quelldatei und Zieldatei zuletzt frisch gelesen und ihre Hashes verglichen wurden.
- Die Regel gilt für `geprueft` und `duplikat_bestaetigt` **gleichermaßen**: Steht in `bestaetigt_in_lauf` nicht die Nummer des laufenden Laufs, wird vor dem Löschen erneut frisch gelesen und verglichen — Quelle **und** Ziel (§4 Phase 5, §5). Lässt sich dabei nicht beides bestätigen, wird nicht gelöscht.

### Tabellen und Spalten

Fünf Tabellen: `quellen`, `dateien`, `ziel_index`, `laeufe`, `lauf_ereignisse`. Die Datenbank trägt eine Schema-Version (`PRAGMA user_version`); eine Datei mit älterer Version wird mit verständlicher Meldung abgelehnt, nicht stillschweigend weiterbenutzt.

**`quellen`** — eine Zeile je Quellwurzel eines Archivs (§4 Phase 1, §8):

- `wurzel` — aufgelöster Pfad des Quell-Wurzelordners; eindeutig.
- `hinzugefuegt_in_lauf` — Lauf, in dem die Quelle aufgenommen wurde.
- `zuletzt_gescannt_in_lauf` — Lauf, in dem sie zuletzt durchlaufen wurde.
- `erreichbar` — 0 oder 1, Stand des letzten Scans. Eine nicht erreichbare Quelle (Platte nicht eingesteckt, Netz nicht eingebunden) bleibt bekannt.
- `laufwerk` — Kennung des physischen Laufwerks, nach der Quellen beim Scan gruppiert werden (§4 Phase 1).

**`dateien`** — eine Zeile je Quelldatei; der Quellpfad ist eindeutig (Schlüssel):

- `quellpfad` — absoluter, aufgelöster Pfad der Quelldatei; eindeutig.
- `quellwurzel` — die Quelle aus der Tabelle `quellen`, zu der diese Datei gehört. Daraus ergibt sich der relative Pfad für die Ausschlussmuster (§9), und danach werden Zusammenfassung und Bericht je Quelle aufgeteilt (§10).
- `groesse` — Größe der Quelldatei in Byte beim letzten Scan.
- `mtime` — Änderungsdatum der Quelldatei beim letzten Scan; zusammen mit `groesse` die Grundlage der Änderungserkennung („Zweiter Scan").
- `dateityp` — `foto`, `raw`, `video`, `sidecar` oder `sonstiges` (§3). Nur die ersten vier gelten als echter Dateityp; `sonstiges` steht für jede Datei außerhalb der Typenlisten und geht mit Status `uebersprungen` einher.
- `hash` — BLAKE3 der Quelldatei, beim Kopieren mitberechnet (§7) oder beim Prüfen eines Duplikat-Verdachts eigens ermittelt; leer, solange die Datei noch nicht gelesen wurde.
- `kamera` — Ordnername der Kamera nach Anwendung der Alias-Tabelle (§3).
- `kamera_modell` — der rohe Modellname aus den Metadaten (`Model`, ersatzweise `Make Model`), bevor die Alias-Tabelle griff. Daraus entsteht die Liste „gefundene Kameramodelle mit Anzahl" (§4 Phase 2), mit der der Nutzer fehlende Aliase nachträgt.
- `aufnahme_zeit` — Aufnahmezeitpunkt als Ortszeit, aus dem die Ordner gebildet werden. Ohne bekannte Uhrzeit (Datum aus dem Dateinamen oder ein Metadaten-Wert ohne Zeit) steht nur das Datum (`2026-01-02`); daran erkennt eine spätere Neuberechnung des Zielpfads, dass die Tagesgrenze nicht anzuwenden ist (§3).
- `datum_quelle` — welche der sechs Datumsquellen aus §3 gewonnen hat (1 bis 6). Daraus ergibt sich auch die Kennzeichnung „Zeitzone angenommen" für den Bericht: genau dann, wenn `datum_quelle` = 3.
- `datum_sicher` — 0 oder 1; unsicher (0) ist ausschließlich das Datum aus Quelle 6 (§3).
- `datum_hinweis` — leer, `zeitzone_angenommen` (Quelle 3, §3) oder `dateiname_ohne_uhrzeit` (Quelle 5 ohne Uhrzeit, Tagesgrenze nicht angewendet, §3). Daraus kommen die beiden Zählungen in §10 auch nach einem Neustart aus der Datenbank.
- `gruppe` — Kennung der zusammengehörigen Dateien (RAW + JPG + Sidecars, §3). Alle Dateien einer Gruppe bekommen denselben Zielordner und denselben Namensanhang.
- `zielpfad` — berechneter oder tatsächlicher Zielpfad, einschließlich des Anhangs `_1`, `_2` … bei Namenskonflikten; leer, solange nicht berechnet.
- `status` — einer der oben genannten Statuswerte.
- `fehlergrund` — Klartext bei Status `fehler` oder `uebersprungen`; sonst leer.
- `bestaetigt_in_lauf` — Nummer des Laufs, in dem Quelle und Ziel zuletzt frisch gelesen und verglichen wurden; leer, wenn das nie geschah.
- `gefunden_in_lauf` — Nummer des Laufs, in dem diese Zeile angelegt wurde.
- `schreibpfad` — solange der Status `kopieren_laeuft` ist: die Datei, in die der Lauf tatsächlich schreibt (die `.part`-Datei, im Rückfall der endgültige Name mit Anhang; unmittelbar vor dem Umbenennen der endgültige Name). Danach leer. Nur unter diesem Pfad darf das Aufräumen nach einem Absturz etwas entfernen (§5). Beim Aufräumen in den Ordner `_geloescht_` (§4 Phase 5) steht hier, wohin die Quelldatei verschoben wurde; bei endgültigem Löschen bleibt die Spalte leer.
- `kopiert_in_lauf` — Nummer des Laufs, der den Zielpfad beansprucht hat (Status `kopieren_laeuft`) bzw. die Datei kopiert hat. Daran erkennt der nächste Start, ob eine liegengebliebene `.part`-Datei oder eine angefangene Zieldatei aus einem **abgebrochenen** Lauf stammt (§5): Ihr Lauf ist nicht der laufende.
- `zuletzt_gesehen_in_lauf` — Nummer des letzten Laufs, in dem der Quellpfad beim Scan noch vorhanden war. Daran wird „Quelle nicht mehr vorhanden" erkannt.

Die Metadaten stehen in **eigenen Spalten** (`kamera`, `aufnahme_zeit`, `datum_quelle`, `datum_sicher`), nicht in einem JSON-Feld: Nach ihnen wird gefiltert und sortiert, und das soll die Datenbank tun.

**`ziel_index`** — eine Zeile je Datei im Ziel; der Zielpfad ist eindeutig (Schlüssel):

- `zielpfad` — absoluter Pfad der Datei im Ziel; eindeutig.
- `groesse` — Größe in Byte beim letzten Blick ins Ziel.
- `mtime` — Änderungsdatum beim letzten Blick ins Ziel; zusammen mit `groesse` entscheidet es, ob neu gehasht werden muss.
- `hash` — BLAKE3 der Zieldatei.
- `zuletzt_gelesen_in_lauf` — Nummer des Laufs, in dem die Zieldatei zuletzt vollständig gelesen und gehasht wurde.

**`laeufe`** — eine Zeile je Programmstart:

- `nummer` — fortlaufende Lauf-Nummer; Schlüssel und der Wert, der in `bestaetigt_in_lauf` steht.
- `befehl` — welcher Befehl gestartet wurde (§8), mit seinen Schaltern.
- `start` — Zeitpunkt des Starts.
- `ende` — Zeitpunkt des Endes; leer, solange der Lauf läuft oder wenn er abgestürzt ist.
- `zusammenfassung` — Zahlen des Laufs (Dateien, Bytes, Sekunden) für „Dauer und Durchsatz je Phase" im Bericht (§10); leer bei Abbruch.

**`lauf_ereignisse`** — eine Zeile je Ereignis, das zu **keiner** Datei in `dateien` gehört und trotzdem in den Bericht muss:

- `lauf_nummer` — zu welchem Lauf das Ereignis gehört.
- `art` — Kurzkennung. Bisher vergeben: `ausgeschlossen` (durch `ausschlussmuster` übersprungener Pfad), `verknuepfung_nicht_verfolgt`, `zeigt_ins_ziel`, `ordner_nicht_lesbar`, `quelle_veraendert` (§6 zweiter Scan), `quelle_nicht_erreichbar` (§4 Phase 1), `quelle_abgelehnt` (Überschneidung, §4 Phase 1), `abgebrochen` (geordneter Abbruch), `zielordner_mehrdeutig` (§3), `rueckfall_kopieren` (Dateisystem kann kein nicht überschreibendes Umbenennen), `duplikat` (nicht kopiert; `text` nennt die Partnerdatei im Ziel), `namenskonflikt` (mit Anhang abgelegt; `text` nennt den endgültigen Zielpfad), `part_aufgeraeumt`, `angefangene_zieldatei_entfernt` (nur im Rückfall, §5), `kopie_nachtraeglich_bestaetigt` (fertige Kopie aus einem abgebrochenen Lauf, §5), `quelle_nicht_mehr_vorhanden` (§6 zweiter Scan, je Pfad), `pruefung_fehlgeschlagen` (§4 Phase 4; `text` nennt Zieldatei und Grund), `neu_nach_pruefung` (nach fehlgeschlagener Prüfung wieder zum Kopieren freigegeben), `quelle_geloescht` (endgültig), `quelle_in_geloescht_ordner` (`text` nennt den neuen Pfad), `quelle_seit_kopieren_geaendert` (§5, nicht gelöscht), `loeschung_verweigert` (`text` nennt den Grund), `loeschung_nachgetragen` (§4 Phase 5, Absturz), `rest_entfernt`, `rest_nicht_entfernt`, `leerer_ordner_entfernt`. Neue Arten werden hier ergänzt.
- `pfad` — betroffener Pfad, falls es einen gibt; sonst leer.
- `anzahl` — für reine Zähler; sonst 1.
- `text` — Klartext für den Bericht; sonst leer.

Ohne diese Tabelle hätten mehrere in §10 verlangte Berichtslisten keinen Ort: Ausgeschlossene Pfade und nicht verfolgte Verknüpfungen kommen gar nicht erst in `dateien`, und ein Zähler wie „so oft wurde auf Kopieren zurückgefallen" gehört zu keiner einzelnen Datei. Der Befehl `bericht` liest aus `dateien` und aus dieser Tabelle; er ist damit auch nach einem Neustart noch vollständig und muss nichts aus dem laufenden Prozess im Speicher halten.

### Zweiter Scan (Fortsetzen)

Der Scan ist fortsetzbar. Für jeden gefundenen Quellpfad gilt:

- **Pfad noch nicht bekannt** → neue Zeile mit Status `gefunden`.
- **Pfad bekannt, `groesse` und `mtime` unverändert** → die Zeile bleibt, wie sie ist. Status, Hash und Zielpfad werden nicht angerührt; nur `zuletzt_gesehen_in_lauf` wird auf den laufenden Lauf gesetzt. Deshalb kopiert ein zweiter Lauf nichts doppelt.
- **Pfad bekannt, `groesse` oder `mtime` verändert** → der Status fällt auf `gefunden` zurück; `hash`, `zielpfad` und `bestaetigt_in_lauf` werden geleert. Die Datei erscheint im Bericht als „Quelle verändert, wird neu eingeordnet" (§10).
- **Bekannter Quellpfad nicht mehr vorhanden** → die Zeile **bleibt** in der Datenbank und erscheint im Bericht als „Quelle nicht mehr vorhanden" (§10). Erkannt wird das daran, dass `zuletzt_gesehen_in_lauf` nach dem Scan nicht die Nummer des laufenden Laufs trägt. **Ausgewertet wird das nur für die Zeilen, deren `quellwurzel` die gerade gescannte Wurzel ist** — sonst gälten bei mehreren Quellwurzeln (§8) nach jedem Scan alle Dateien der übrigen Wurzeln als verschwunden. Dateien mit Status `quelle_geloescht` oder `verschoben` fehlen erwartungsgemäß und stehen nicht in dieser Liste.
- **Es wird nie eine Zeile gelöscht.** Die Datenbank ist das Gedächtnis des Archivs; eine gelöschte Zeile wäre eine verlorene Spur.

### Ort der Datenbank

- Die Datenbank liegt **immer lokal**, nie auf einem Netzlaufwerk.
- Der **Archiv-Ordner** ist der Ordner, der die Datenbank und die Konfiguration eines Archivs enthält. Sein Name ist die Archiv-ID:
  - Windows: `%LOCALAPPDATA%\fotosortierer\<archiv-id>\`
  - Linux: `${XDG_DATA_HOME:-~/.local/share}/fotosortierer/<archiv-id>/`
  - Docker: derselbe Pfad wie unter Linux. Er wird im Container als Volume eingebunden, damit die Datenbank einen Neustart des Containers übersteht.
- Darin liegen die Datenbank `fotosort.db` und die Konfiguration `config.toml` (siehe unten). Im laufenden Betrieb kommen die Hilfsdateien `fotosort.db-wal` und `fotosort.db-shm` dazu, die SQLite selbst anlegt und verwaltet, sowie die Sperrdatei `fotosort.sperre`: Sie verhindert, dass zwei gleichzeitige Läufe einander die Datenbank wegsperren und beide scheitern. Die Sperre hält das Betriebssystem; stürzt das Programm ab, gibt es sie von selbst frei — eine liegengebliebene Datei blockiert nichts.
- Der Ort ist überschreibbar: über die Umgebungsvariable `FOTOSORT_DATENBANK` und über den Konfigurationswert `datenbank_ort` (§9). **Vorrang:** Umgebungsvariable, dann Konfigurationswert, zuletzt der Standardpfad des Betriebssystems.
- Der Konfigurationswert `datenbank_ort` wirkt nur aus einer mit `--config <pfad>` angegebenen Datei. Steht er in der `config.toml` im Archiv-Ordner selbst, ist der Ordner bereits gefunden; der Wert wird dann gemeldet und ignoriert. Anders ginge es nicht: Die Konfiguration liegt im Archiv-Ordner, sie kann ihn nicht selbst verschieben.
- **Als Netz gelten diese Dateisystemtypen** (Linux, Typ des Einhängepunkts): `cifs`, `smb3`, `nfs`, `nfs4`, `fuse.sshfs`, `9p`, `virtiofs`. Unter Windows: UNC-Pfade sowie Laufwerksbuchstaben, für die `GetDriveType` `DRIVE_REMOTE` liefert (auch für verbundene Laufwerksbuchstaben aufgelöst). `9p` und `virtiofs` gehören dazu, weil Docker Desktop und WSL2 Windows-Pfade so einbinden; die Dateisperren sind dort ebenso unzuverlässig wie über SMB. Dieselbe Liste gilt für die Prüfung „gleiches Laufwerk" (§4 Phase 3).
- Erkennt das Programm, dass der Datenbankpfad auf einem Netz-Dateisystem liegt, bricht es mit einer verständlichen Meldung ab.

### Archiv-ID

- Die Archiv-ID verbindet den Zielordner mit der zugehörigen lokalen Datenbank, damit ein späterer Lauf die richtige Datenbank wiederfindet. Sie ist zugleich der Name des Archiv-Ordners.
- **Form:** eine UUID4, kleingeschrieben, ohne Bindestriche — also genau 32 Zeichen aus `0-9` und `a-f`.
- **Ort:** `<Ziel>/.fotosortierer/archiv-id.txt`, UTF-8 ohne BOM, die ID als einzige Zeile (ein abschließender Zeilenumbruch ist erlaubt).
- **Erzeugt** wird sie beim ersten Scan eines Ziels, wenn die Datei noch nicht existiert.
- **Ist die Datei vorhanden, aber ihr Inhalt keine gültige 32-stellige Hex-ID**, bricht das Programm mit einer verständlichen Meldung ab und nennt Datei und Inhalt. Es erzeugt in diesem Fall **niemals** eine neue ID: Eine neue ID bedeutete eine neue, leere Datenbank; das Programm hielte das Ziel für leer und kopierte alles erneut.

### Konfigurationsdatei

- `config.toml` liegt im Archiv-Ordner neben der Datenbank: `<Archiv-Ordner>/config.toml`.
- Sie wird **beim ersten Scan mit Kommentaren erzeugt**. Welche Werte darin stehen und welche Standardwerte sie haben, steht vollständig in §9.
- **Eine vorhandene Datei wird nie überschrieben und nie umgeschrieben.** Fehlende Werte werden beim Lesen im Speicher mit den Standardwerten ergänzt, ohne die Datei anzufassen. Unbekannte Werte bleiben stehen und werden einmal je Lauf gemeldet — so bleibt ein Tippfehler im Schlüsselnamen sichtbar, statt still zu wirken.
- Mit `--config <pfad>` lässt sich eine andere Datei angeben.
- Weil die Konfiguration im Archiv liegt, kann **jedes Archiv eigene Kamera-Aliase haben**. Das ist gewollt: Ein Archiv mit Analog-Scans braucht andere Aliase als eines mit Kamerabildern.
- **Die Konfiguration wandert mit dem Archiv.** Bei jeder Sicherung der Datenbank (siehe unten) wird auch die `config.toml` nach `<Ziel>/.fotosortierer/config.toml` kopiert. Der lokale Archiv-Ordner ist für den Nutzer schwer zu finden; die mühsam gepflegten Kamera-Aliase sollen nicht an einem Rechner hängen.
- **Erster Start auf einem neuen Rechner:** Gibt es lokal noch keine `config.toml`, liegt aber eine im Ziel unter `.fotosortierer/`, wird **diese übernommen** statt eine neue mit Standardwerten anzulegen. So bringt ein Archiv seine Einstellungen auf jeden Rechner mit, an dem es geöffnet wird. Liegt auch im Ziel keine, wird eine neue mit Kommentaren und Standardwerten erzeugt.
- Die lokale Datei bleibt die, in der gearbeitet wird. Die Kopie im Ziel ist eine Sicherung, kein zweiter Ort zum Bearbeiten: Sie wird bei der nächsten Sicherung überschrieben. Wer im Ziel bearbeitet, verliert die Änderung beim nächsten Lauf.
- **`fotosort config`** (§8) zeigt den Pfad der geltenden Konfiguration an und öffnet sie im Standard-Editor des Systems. Damit muss niemand `%LOCALAPPDATA%` oder `~/.local/share` von Hand suchen.

### Sicherungskopie der Datenbank

- Im Zielordner liegt unter `.fotosortierer/` nur: die Archiv-ID (`archiv-id.txt`), die Berichte (§10), die Sicherungskopie der Datenbank und die Kopie der `config.toml`.
- **Nach jeder abgeschlossenen Phase** wird die Datenbank über die **SQLite-Backup-Funktion** ins Ziel gesichert. Es wird nie direkt in einer Datenbank auf dem Netzlaufwerk gearbeitet.
- Geschrieben wird zuerst nach `<Ziel>/.fotosortierer/fotosort.db.sicherung.neu`. Ist das fertig, wird die bisherige `fotosort.db.sicherung` nach `fotosort.db.sicherung.vorher` umbenannt und danach `fotosort.db.sicherung.neu` atomar auf `fotosort.db.sicherung` umbenannt.
- Es gibt damit **genau zwei Stände**: `fotosort.db.sicherung` (der letzte) und `fotosort.db.sicherung.vorher` (der davor). Weitere Versionierung gibt es nicht.
- Diese drei Namen sind die einzige Stelle, an der ein Umbenennen eine vorhandene Datei ersetzen darf. Es sind die eigenen Sicherungsstände des Programms, keine Bild- oder Videodateien; die Regel „Umbenennen darf nie überschreiben" aus §5 gilt für Mediendateien.
- **Zusammen mit der Datenbank wird die `config.toml` gesichert**: Sie wird bei demselben Anlass nach `<Ziel>/.fotosortierer/config.toml` kopiert (zuerst als `config.toml.neu`, dann atomar umbenannt). Anders als bei der Datenbank gibt es davon nur einen Stand — die Konfiguration ist klein und ändert sich selten.
- `fotosort wiederherstellen` (§8) holt die lokale Datenbank aus `fotosort.db.sicherung` zurück und, falls lokal keine vorhanden ist, auch die `config.toml`.
- **Fehlende lokale Datenbank:** Liest das Programm beim Start die Archiv-ID im Ziel, findet aber keine zugehörige lokale Datenbank, während im Ziel unter `.fotosortierer/` eine Sicherungskopie liegt, bricht es mit einer verständlichen Meldung ab und weist auf `fotosort wiederherstellen` hin (§8). Es legt in diesem Fall **niemals stillschweigend eine leere Datenbank an**: Das Programm hielte das Ziel sonst für leer und würde alles erneut kopieren. Liegt auch keine Sicherungskopie im Ziel, wird ebenfalls abgebrochen; dann hilft nur der vollständige Neuaufbau des Ziel-Index (`fotosort ziel-index --neu-aufbauen`, §8).

### Ziel-Index

- Die Datenbank merkt sich auch, was im Ziel liegt (Tabelle `ziel_index`: Pfad, Größe, Änderungsdatum, Hash). Bei späteren Läufen wird das Ziel nur auf Änderungen geprüft (Größe + Änderungsdatum), nicht komplett neu gehasht. Der Befehl `fotosort ziel-index --neu-aufbauen` (§8) baut den Index vollständig neu auf.
- Der Index darf nur entscheiden, ob **kopiert** wird. Er darf **niemals allein eine Löschung erlauben**; er dient dort nur dazu, Kandidaten für Duplikate schnell zu finden. Vor jeder Löschung gilt §5: Quelldatei und Zieldatei werden im aktuellen Lauf frisch gelesen und verglichen.

## 7. Geschwindigkeit

Ehrliche Einordnung: Der Prozessor ist selten der Engpass, meistens ist es die Festplatte oder das Netzwerk. Deshalb getrennte, einstellbare Parallelität:

- **Metadaten:** ExifTool nicht pro Datei starten. Mehrere dauerhaft laufende ExifTool-Prozesse (`-stay_open`), jeweils mit Stapeln von Dateien, JSON-Ausgabe, nur die benötigten Felder, `-fast2`. Anzahl Prozesse: Standard = Anzahl Kerne.
- **Hashing:** durchgehend **BLAKE3** im ganzen Projekt (schnell und kryptografisch), parallel, in großen Blöcken (≥ 1 MiB) lesen. Der Quell-Hash wird **während des Kopierens** mitberechnet, damit die Quelle nur einmal gelesen wird.
- **Kopieren:** eigene, kleine Worker-Zahl. Standard: 2–4 bei Festplatte/NAS, 8+ bei SSD. Zu viele gleichzeitige Kopien auf eine Festplatte machen es langsamer. Option `--profil hdd|ssd|netzwerk` plus manuelle Werte.
- Kleine Dateien (Sidecars) zuerst nicht bevorzugen; Reihenfolge nach Quellordner, damit die Platte sequentiell lesen kann.
- Am Ende jeder Phase: Durchsatz (Dateien/s, MB/s) ausgeben, damit man die Einstellungen vergleichen kann.

## 8. Bedienung

**Kern + Kommandozeile zuerst**, Weboberfläche danach als dünne Schicht über demselben Kern.

**Jeder Befehl braucht `--ziel`.** Einzige Ausnahme ist `--help`. Über das Ziel findet das Programm die Archiv-ID und darüber die lokale Datenbank (§6). Ersatzweise darf das Ziel in der Umgebungsvariablen `FOTOSORT_ZIEL` stehen; die Angabe auf der Kommandozeile hat Vorrang. Fehlt beides, bricht der Befehl mit einer verständlichen Meldung ab.

**Nur `scan` nimmt `--quelle` entgegen, und zwar mehrfach:** `fotosort scan --quelle A --quelle B`. Jede genannte Quelle wird in die Tabelle `quellen` (§6) aufgenommen, wenn sie neu ist, und durchlaufen. **`scan` mit `--quelle` durchläuft nur die genannten Quellen** — so lässt sich eine Quelle später ergänzen, ohne dass die bereits erfassten neu gescannt werden. **`scan` ohne `--quelle` durchläuft alle bekannten Quellen.** Beim allerersten Scan eines Archivs ist `--quelle` Pflicht. Die folgenden Befehle brauchen keine Quelle mehr; `start` geht die Phasen ab dem Scan durch und nimmt `--quelle` wie `scan`.

`--ziel-anlegen` legt einen noch nicht vorhandenen Zielordner wirklich an. Ohne den Schalter bricht `scan` bei fehlendem Ziel ab: Ein Tippfehler im Pfad oder ein gerade nicht eingebundenes Netzlaufwerk ergäbe sonst ein zweites, leeres Archiv mit neuer Archiv-ID, und das echte Archiv gälte danach als unbekannt (§6).

**Ein Archiv hat mehrere Quellen** (§4 Phase 1). Das ist der Normalfall: Das Chaos liegt selten in einem einzigen Ordner, sondern auf verschiedenen Platten, in verschiedenen Ordnern und auf Netzlaufwerken. Zwei Folgen davon sind festzuhalten: Die Ausschlussmuster (§9) werden je Datei gegen den Pfad relativ zu **ihrer** `quellwurzel` geprüft, nicht gegen eine globale Wurzel. Und „Quelle nicht mehr vorhanden" (§6) wird nach einem Scan nur für die Zeilen ausgewertet, deren `quellwurzel` die gerade gescannte Wurzel ist — sonst gälten nach jedem Scan alle Dateien der anderen Wurzeln als verschwunden.

Zusätzlich gibt es bei jedem Befehl den Schalter `--config <pfad>` für eine andere Konfigurationsdatei (§6).

Kommandozeile (Beispiel, `<Ziel>` steht für `\\truenas\Daten\Lightroom\Medien`):

```
fotosort scan               --quelle D:\Chaos --quelle E:\Karte --ziel <Ziel> [--ziel-anlegen]
fotosort scan               --ziel <Ziel>                       (alle bekannten Quellen)
fotosort analyse            --ziel <Ziel>
fotosort kopieren           --ziel <Ziel> [--verschieben] [--dry-run]
                            [--profil hdd|ssd|netzwerk] [--kopier-worker N] [--hash-worker N]
fotosort pruefen            --ziel <Ziel> [--profil hdd|ssd|netzwerk] [--hash-worker N]
fotosort aufraeumen         --ziel <Ziel> [--quelle A] [--leere-ordner] [--dry-run] [--endgueltig]
                            [--profil hdd|ssd|netzwerk] [--hash-worker N]
fotosort status             --ziel <Ziel>
fotosort bericht            --ziel <Ziel>
fotosort ziel-index --neu-aufbauen --ziel <Ziel>
fotosort wiederherstellen   --ziel <Ziel>
fotosort config             --ziel <Ziel> [--nur-pfad]
fotosort start              --quelle D:\Chaos --ziel <Ziel>
```

`fotosort ziel-index --neu-aufbauen` liest alle Dateien im Zielordner neu, berechnet ihre Hashes und baut die Tabelle `ziel_index` vollständig neu auf (§6). Er wird gebraucht, wenn die lokale Datenbank und die Sicherungskopie beide fehlen, oder wenn im Ziel von Hand etwas verändert wurde. Er löscht nichts und verschiebt nichts. Er ist zugleich der einzige Befehl, der eine fehlende lokale Datenbank neu anlegen darf — nicht stillschweigend, sondern weil er ausdrücklich dafür aufgerufen wurde; er füllt sie mit dem, was tatsächlich im Ziel liegt (§6).

`fotosort wiederherstellen` holt die lokale Datenbank aus der Sicherungskopie `fotosort.db.sicherung` im Zielordner zurück (§6).

`fotosort kopieren` prüft vor dem ersten Schreiben: Reste eines abgebrochenen Laufs (§5), freier Platz im Ziel gegen die Summe der anstehenden Dateien (zu wenig → Abbruch, nichts kopiert), erreichbare Quellen (eine nicht erreichbare wird gemeldet und übersprungen, ihre Dateien bleiben `analysiert`). `--dry-run` zählt nur, schreibt nichts und legt keinen Lauf an. `--profil`, `--kopier-worker` und `--hash-worker` überstimmen die Werte aus `config.toml` (§9) für diesen Lauf. Die Anzeige während des Laufs zeigt Dateien und Datenmenge (erledigt/gesamt), MB/s und die geschätzte Restzeit, höchstens zweimal je Sekunde; am Ende steht der Durchsatz (§7).

`fotosort config` zeigt den vollständigen Pfad der geltenden `config.toml` an und öffnet sie anschließend im Standard-Editor des Systems (Windows: `os.startfile`; Linux: `xdg-open`; ist kein Editor erreichbar, bleibt es bei der Pfadausgabe mit einem Hinweis). Mit `--nur-pfad` wird nur der Pfad ausgegeben und nichts geöffnet — so lässt er sich in eigenen Skripten weiterverwenden. Der Befehl ändert nichts.

Findet ein anderer Befehl im Ziel eine Archiv-ID, aber keine zugehörige lokale Datenbank, bricht er ab und nennt genau diesen Befehl. Es wird in diesem Fall keine leere Datenbank angelegt (§6).

`fotosort status` zeigt die Anzahl der Dateien je Status und die **aktuelle Phase**. Als aktuelle Phase gilt die Phase, die zu dem **niedrigsten Status gehört, in dem noch Dateien stehen** — nach der Reihenfolge `gefunden → analysiert → kopieren_laeuft → kopiert → geprueft → quelle_geloescht`. Stehen also noch Zeilen auf `gefunden`, ist die Analyse offen; steht die niedrigste Zeile auf `analysiert`, ist das Kopieren offen, und so weiter. Die Status `duplikat`, `duplikat_bestaetigt`, `verschoben`, `uebersprungen` und `fehler` zählen dabei nicht mit: Sie sind Abzweigungen, keine Stufen. Dazu wird der letzte Lauf aus der Tabelle `laeufe` genannt (Nummer, Befehl, Start, und ob er beendet wurde). Es braucht dafür keine eigene Spalte — die Phase ergibt sich aus den Zählern.

Dazu ein geführter Modus `fotosort start`, der die Phasen nacheinander durchgeht und zwischen den Schritten fragt.

**Aufräumen je Quelle** (Phase 5): `aufraeumen` und `aufraeumen --leere-ordner` wirken mit `--quelle A` nur auf diese Quelle; ohne Angabe wird je Quelle einzeln gefragt. Jeder Quell-Wurzelordner selbst bleibt stehen.

**Bedienung wie eine normale App** (Vormerk für Phase 7, jetzt nicht gebaut): Unter Windows startet das Programm per Doppelklick und zeigt die Oberfläche in einem **eigenen Fenster** (z. B. `pywebview`), nicht nur als Browser-Tab; Quelle und Ziel werden über den **normalen Windows-Ordnerdialog** gewählt. Auf dem Server läuft **dieselbe Oberfläche im Browser**, mit einem einfachen Ordner-Browser statt des Systemdialogs. Die Regeln unten gelten für beide.

**Weboberfläche** (spätere Phase, lokal im Browser, später im Container auf dem Server):

- Zeigt **nur Zusammenfassungen**: Zähler, Fortschrittsbalken, Durchsatz, Restzeit, Fehlerliste. Niemals alle Dateien auf einmal in die Seite laden.
- Listen (Fehler, Duplikate, Dateien ohne Datum) nur seitenweise, serverseitig geblättert.
- Fortschritt höchstens 1–2× pro Sekunde aktualisieren (Polling oder SSE), nicht ein Ereignis pro Datei.
- Die Arbeit läuft in einem eigenen Prozess. Browser schließen oder Seite neu laden darf den Lauf nicht beeinflussen.
- Knöpfe für die Phasen, Auswahl Kopieren/Verschieben, Pause/Fortsetzen, Alias-Tabelle bearbeiten.

## 9. Konfiguration

Die `config.toml` liegt im Archiv-Ordner neben der Datenbank (`<Archiv-Ordner>/config.toml`, §6) und wird beim ersten Scan mit Kommentaren erzeugt. Eine vorhandene Datei wird nie überschrieben; fehlende Werte werden mit den Standardwerten ergänzt, unbekannte Werte bleiben stehen und werden einmal gemeldet (§6).

Die folgende Liste ist **vollständig** und ist zugleich die Vorlage, aus der die kommentierte `config.toml` erzeugt wird: jeder Wert mit seinem Schlüsselnamen, einer Kurzbeschreibung und seinem Standardwert.

### `[ordner]`

- `vorlage` — Ordner-Vorlage für Dateien mit Datum (§3). Standard: `"{jahr}/{jahr}-{monat} {monatsname}/{jahr}-{monat}-{tag}/{kamera}"`
- `vorlage_ohne_datum` — Ordner-Vorlage für Dateien ohne verwertbares Datum (§3). Standard: `"_Ohne_Datum/{kamera}"`

### `[datum]`

- `heimat_zeitzone` — Zeitzone, in die Video-Zeiten ohne Offset aus UTC umgerechnet werden (§3, Quelle 3). Standard: `"Europe/Berlin"`
- `tagesgrenze` — Uhrzeit, ab der ein neuer Tagesordner beginnt; `"04:00"` zählt Aufnahmen bis 04:00 noch zum Vortag (§3). Standard: `"00:00"`
- `unsicheres_datum` — was mit einem unsicheren Datum geschieht (nur Quelle 6, §3). Erlaubt: `"ohne_datum"` (nach `vorlage_ohne_datum`) oder `"mtime"` (nach Änderungsdatum einsortieren). Standard: `"ohne_datum"`

### `[kamera]`

- `unbekannt` — Ordnername, wenn kein Kameramodell gefunden wurde (§3). Standard: `"Unbekannte_Kamera"`
- `aliase` — Untertabelle `[kamera.aliase]`, Modellname → Ordnername (§3). Der Nutzer ergänzt sie nach dem Scan. **Standard — genau diese Zeilen werden in die erzeugte `config.toml` geschrieben, nicht mehr und nicht weniger:**

  ```toml
  [kamera.aliase]
  "ILCE-7CM2" = "A7C2"
  "ILCE-7C"   = "A7C"
  # Scanner zählen als Analog-Material
  "Noritsu Koki QSS-32_33"      = "Analog"
  "Noritsu Koki EZ Controller"  = "Analog"
  "SP-3000"                     = "Analog"
  "Frontier SP-3000"            = "Analog"
  "Frontier SP-500"             = "Analog"
  "EPSON Perfection V600"       = "Analog"
  "EPSON Perfection V800"       = "Analog"
  "EPSON Perfection V850"       = "Analog"
  "PLUSTEK OpticFilm 8200i"     = "Analog"
  "PLUSTEK OpticFilm 120"       = "Analog"
  ```

  Diese Liste ist bewusst kurz und trifft nicht jeden Scanner. Sie ist ein Startbestand, kein Anspruch auf Vollständigkeit: Nach dem Scan zeigt das Programm alle gefundenen Modelle mit Anzahl (§3), und der Nutzer trägt fehlende Zuordnungen selbst nach. Weil eine vorhandene `config.toml` nie umgeschrieben wird (§6), wächst diese Liste nur durch den Nutzer.

### `[dateitypen]`

- `foto` — Endungen, die als Foto gelten (§3). Standard: `["jpg", "jpeg", "heic", "hif", "png", "tif", "tiff", "webp"]`
- `raw` — Endungen, die als RAW gelten (§3). Standard: `["arw", "cr2", "cr3", "nef", "dng", "raf", "orf", "rw2", "srw"]`
- `video` — Endungen, die als Video gelten (§3). Standard: `["mp4", "mov", "mts", "m2ts", "avi", "mkv"]`
- `sidecar` — Endungen, die als Sidecar gelten (§3); eigener Dateityp, nie „übersprungen nach Typ". Standard: `["xmp", "dop", "pp3", "thm", "aae", "xml"]`
- `sidecar_zusatzmuster` — Glob-Muster für die dritte Sidecar-Form, den Zusatz zwischen Stammname und Endung (§3, `C0001M01.XML` zu `C0001.MP4`). Standard: `["M[0-9][0-9]"]`, also `M01` bis `M99`

### `[quelle]`

- `ausschlussmuster` — Glob-Muster für Pfade in der Quelle, die der Scan überspringt (§4 Phase 1). Verglichen wird gegen den Pfad **relativ zur Quellwurzel**, mit Schrägstrich `/` als Trenner, **Groß- und Kleinschreibung wird ignoriert**; Beispiel: `"*/Papierkorb/*"` — ein mit `*/` beginnendes Muster wird zusätzlich ohne diesen Anfang geprüft, damit es auch einen Papierkorb-Ordner direkt in der Quellwurzel trifft (dort lautet der relative Pfad schlicht `Papierkorb/…`). Geprüft werden Datei- und Ordnerpfade; trifft ein Muster auf einen Ordner zu, wird er samt Inhalt übersprungen. Ausgeschlossene Pfade kommen nicht in die Datenbank und werden im Bericht gezählt. Standard: `[]` (leere Liste)
- `verknuepfungen_folgen` — ob der Scan Ordner-Verknüpfungen (Symlinks, Junctions) verfolgt (§4 Phase 1). Standard: `false`

### `[sicherheit]`

- `byte_vergleich_vor_loeschen` — zusätzlich zum Hash-Vergleich vor dem Löschen Byte für Byte vergleichen (§5). Standard: `false`

### `[datenbank]`

- `datenbank_ort` — Ordner, unter dem die Archiv-Ordner angelegt werden; leer bedeutet Standardpfad des Betriebssystems (§6). Vorrang: `FOTOSORT_DATENBANK` vor `datenbank_ort` vor Standardpfad. Wirkt nur aus einer mit `--config` angegebenen Datei (§6). Nie ein Netzlaufwerk. Standard: `""`

### `[aufraeumen]`

- `reste_dateien` — Dateinamen, die beim Entfernen leerer Ordner als „zählt als leer" gelten (§4 Phase 6). Ein Name allein genügt nicht: Steht die Datei mit echtem Dateityp in der Datenbank, wird sie nicht gelöscht (§5). Standard: `["Thumbs.db", ".DS_Store", "desktop.ini"]`

### `[leistung]`

- `profil` — grobe Voreinstellung für die Worker-Zahlen (§7). Erlaubt: `"hdd"`, `"ssd"`, `"netzwerk"`. Standard: `"hdd"`
- `metadaten_prozesse` — Anzahl dauerhaft laufender ExifTool-Prozesse (§7). `0` bedeutet automatisch (Anzahl Kerne). Standard: `0`
- `kopier_worker` — Anzahl gleichzeitiger Kopiervorgänge (§7). `0` bedeutet automatisch nach Profil (`hdd` 2, `netzwerk` 4, `ssd` 8). Standard: `0`
- `hash_worker` — Anzahl gleichzeitiger Hash-Berechnungen (§7). `0` bedeutet automatisch (Anzahl Kerne). Standard: `0`
- `exiftool_pfad` — Pfad zum ExifTool-Programm; leer bedeutet über `PATH` suchen (§2). Vorrang: `FOTOSORT_EXIFTOOL` vor `exiftool_pfad` vor `PATH`. Standard: `""`

Alle Angaben mit `0` für „automatisch" werden beim Start als tatsächlich benutzte Zahl ausgegeben, damit nachvollziehbar bleibt, womit gearbeitet wurde.

## 10. Bericht

Nach jedem Lauf ein Bericht als Textdatei und CSV im Ordner `.fotosortierer/berichte/`: Anzahl gefunden / kopiert / verschoben / geprüft / Duplikate / ohne Datum / Fehler — **je Quelle und gesamt** —, Dauer und Durchsatz je Phase, Liste aller Fehler mit Grund, Liste aller Umbenennungen wegen Namenskonflikt. Nicht erreichbare und abgelehnte Quellen (§4 Phase 1) werden benannt.

Die Dateien heißen `bericht_<Zeit>_lauf<N>.txt` (lesbar), `…_dateien.csv` (eine Zeile je Datei, alle Spalten der Tabelle `dateien`) und `…_ereignisse.csv` (eine Zeile je Ereignis). CSV mit Semikolon als Trenner und UTF-8 mit Kennzeichen, damit Excel unter Windows die Datei direkt richtig öffnet. Jeder verändernde Befehl schreibt den Bericht nach seinem Lauf zusammen mit der Sicherungskopie (§6); `fotosort bericht` schreibt ihn jederzeit auf Verlangen, legt keinen Lauf an und gibt den Text auch auf der Konsole aus. Der Bericht beschreibt immer das ganze Archiv (alle Läufe), nicht nur den letzten.

Dazu gehören:

- Dateien, deren Zeitzone angenommen wurde („Zeitzone angenommen", §3), als eigene Liste.
- Anzahl der Dateien, bei denen das Datum aus dem Dateinamen ohne Uhrzeit stammt und die Tagesgrenze deshalb nicht angewendet wurde (§3).
- Dateien, die per Umbenennen verschoben wurden (Status `verschoben`, §4), getrennt ausgewiesen.
- **„Quelle seit dem Kopieren geändert"** (§4 Phase 5, §5): Quelldateien, die vor dem Löschen frisch gelesen wurden und deren Hash nicht mehr zum gespeicherten Quell-Hash passt. Sie wurden **nicht gelöscht**, stehen wieder auf Status `analysiert` und müssen neu kopiert werden. Die Liste nennt jeden Pfad einzeln. Sie ist die wichtigste Liste des Berichts: Jeder Eintrag ist ein Bild, das ohne die Prüfung verloren gewesen wäre.
- **„Quelle verändert, wird neu eingeordnet"** (§6, zweiter Scan): Dateien, deren Größe oder Änderungsdatum sich seit dem letzten Scan geändert hat und die deshalb wieder auf Status `gefunden` stehen.
- **„Quelle nicht mehr vorhanden"** (§6): bekannte Quellpfade, die der Scan nicht mehr gefunden hat und die nicht durch das Programm selbst verschwunden sind.
- Dateien, deren Löschung verweigert wurde, weil die Frischlesung im aktuellen Lauf fehlte oder das Ziel abwich (§4 Phase 5), mit Grund.
- Nicht verfolgte Ordner-Verknüpfungen und nach `ausschlussmuster` übersprungene Pfade, mit Anzahl (§4 Phase 1).
- Sidecars ohne Hauptdatei (Status `uebersprungen`, §3).
- Reste-Dateien, die nicht entfernt wurden, weil sie mit echtem Dateityp in der Datenbank stehen (§4 Phase 6, §5).
- Anzahl der Fälle, in denen auf Kopieren statt Umbenennen zurückgefallen wurde, weil das Dateisystem kein nicht überschreibendes Umbenennen kann (§5).
- Quelldateien, die übersprungen wurden, weil ihr aufgelöster Pfad ins Ziel zeigt (Grund „zeigt ins Ziel", §4 Phase 1).

Der Bericht liest aus der Tabelle `dateien` und aus `lauf_ereignisse` (§6). Alles, was er nennt, steht damit in der Datenbank und überlebt einen Neustart; nichts davon wird nur im Speicher des laufenden Prozesses gehalten.

## 11. Tests

- `pytest`. Ein Skript erzeugt einen künstlichen Testbaum (kleine Dummy-Bilder mit gesetzten EXIF-Daten, Duplikate, Namenskonflikte, RAW+JPG-Paare, Sidecars, Dateien ohne Datum, kaputte Daten, tiefe und lange Pfade, Umlaute und Leerzeichen). Der Erzeuger braucht ExifTool und bricht ohne es ab (§2).
- Der Testbaum enthält außerdem diese Fälle, weil ohne sie ganze Regeln dieser SPEC ungeprüft blieben:
  - ein **Video mit Zeitzonen-Offset** (QuickTime `CreationDate`, §3 Quelle 2) und ein **Video ohne Zeitzonen-Offset** (`CreateDate`, §3 Quelle 3), letzteres so gewählt, dass die Umrechnung von UTC in die Heimat-Zeitzone den Tag wechselt;
  - das **Sony-Paar** `C0001.MP4` plus `C0001M01.XML` (dritte Sidecar-Form, §3);
  - **beide einfachen Sidecar-Schreibweisen** zur selben Hauptdatei: `DSC01234.xmp` (Stammname) und `DSC01234.ARW.xmp` (vollständiger Dateiname), §3 Formen 1 und 2;
  - ein **im Ziel bereits belegter Zielname** mit anderem Inhalt, damit das nicht überschreibende Umbenennen und der Anhang `_1` geprüft werden können (§4 Phase 3, §5);
  - eine Datei, deren **Quelle sich nach dem Kopieren ändert** (für den Pflicht-Test unten);
  - ein Ordner, auf den nur eine **Verknüpfung** zeigt, und ein Pfad, der von einem `ausschlussmuster` getroffen wird (§4 Phase 1).
- **Wie die Binärdateien des Testbaums entstehen.** Ohne zusätzliche Bibliothek, allein mit der Standardbibliothek und ExifTool:
  - **JPEG**: ein fest im Skript hinterlegtes, gültiges 1×1-Pixel-JPEG von rund 160 Byte.
  - **RAW (`.ARW` und andere)**: eine minimale, gültige TIFF-Struktur, im Skript aus `struct` zusammengesetzt (rund 110 Byte). ARW ist TIFF-basiert; ExifTool schreibt darin `DateTimeOriginal` und `Model` wie in einer echten Datei.
  - **MP4 und MOV**: eine minimale, gültige Box-Struktur (`ftyp` plus `moov`/`mvhd`), ebenfalls mit `struct` erzeugt (rund 140 Byte). Die Aufnahmezeit steht als Sekunden seit dem 1.1.1904 im `mvhd`-Kasten und wird von ExifTool als `CreateDate` gelesen. Für das Video **mit** Offset schreibt ExifTool anschließend `QuickTime:CreationDate` mit `-api QuickTimeUTC=1`.
  - **Sidecars** (`.xmp`, `.XML`, `.aae`) sind reine Textdateien und werden direkt geschrieben.

  Alle Metadaten setzt danach ExifTool; deshalb bricht der Erzeuger ohne ExifTool ab. Es werden **keine Beispieldateien im Repository abgelegt** — der Testbaum entsteht vollständig aus Code und ist damit versionierbar und nachvollziehbar.
- **Was erst ab Phase 2 entsteht.** Der Fall „im Ziel bereits belegter Zielname" setzt voraus, dass der Erzeuger den Zielpfad ausrechnen kann, also Datum, Kamera und Ordner-Vorlage anwendet. Diese Logik entsteht erst in Phase 2. **In Phase 1 erzeugt das Skript nur den Quellbaum**; den vorbelegten Zielbaum legt es ab Phase 2 an, dann aus derselben Berechnung, die auch das Programm benutzt. Ein fest eingetragener Zielpfad wäre falsch, sobald jemand die Ordner-Vorlage oder die Tagesgrenze ändert.
- Pflicht-Tests: Absturz mitten im Kopieren → Fortsetzen ergibt dasselbe Ergebnis; zweiter Lauf mit denselben Dateien kopiert nichts doppelt; Löschen verweigert ungeprüfte Dateien; bestehender Tagesordner mit Zusatz wird wiederverwendet.
- Weitere Pflicht-Tests:
  - Alle drei Sidecar-Formen werden zugeordnet: `DSC01234.xmp`, `DSC01234.ARW.xmp` und die Sony-Form `C0001M01.XML` zu `C0001.MP4` (§3).
  - Umbenennen auf einen bereits belegten Zielnamen überschreibt nichts: Die vorhandene Zieldatei bleibt unverändert, und die Quelldatei ist danach noch da (§4 Phase 3, §5).
  - Löschen wird verweigert, wenn der Status stimmt (`geprueft` oder `duplikat_bestaetigt`), die Frischlesung im aktuellen Lauf aber fehlt (§4 Phase 5, §5).
  - „Gleiches Laufwerk" wird für Netzpfade verneint: Bei einem Netzpfad auf einer der beiden Seiten wird kopiert, nicht umbenannt (§4 Phase 3).
  - Ein Video ohne Zeitzonen-Offset landet nach der Umrechnung im richtigen Tagesordner und **nicht** in `_Ohne_Datum` (§3).
  - **Geänderte Quelle wird nicht gelöscht** (§4 Phase 5, §5). Ablauf: Datei kopieren und prüfen (Status `geprueft`), dann den Inhalt der Quelldatei ändern, dann aufräumen lassen. Erwartung: Die Quelldatei ist danach **noch da** und trägt ihren neuen Inhalt, die Zieldatei ist unverändert, der Status steht auf `analysiert`, und die Datei erscheint im Bericht unter „Quelle seit dem Kopieren geändert". Dieser Test sichert den einzigen Verlustpfad ab, den ein reiner Ziel-Vergleich offen ließe; ohne ihn darf nicht gelöscht werden.
  - Löschen wird verweigert, wenn die **Zieldatei** abweicht: Die Quelldatei bleibt stehen, die Datei bekommt Status `fehler` (§4 Phase 5).
  - Eine Datei, die in `reste_dateien` steht, aber mit echtem Dateityp in der Datenbank, wird beim Entfernen leerer Ordner **nicht** gelöscht (§4 Phase 6, §5).
  - Zweiter Scan: unveränderte Datei behält ihren Status; veränderte Datei fällt auf `gefunden` zurück; verschwundene Datei behält ihre Zeile (§6).
  - Eine kaputte `archiv-id.txt` führt zum Abbruch und **nicht** zu einer neuen Archiv-ID (§6).
- **Nie mit echten Fotos testen**, solange Löschen/Verschieben nicht durch die Tests abgesichert ist.

## 12. Nicht Teil des Projekts

Bilder ansehen oder bewerten, Bildinhalte erkennen, Gesichter, systematisches Umbenennen von Dateien (etwa nach Datum oder Kamera), Bearbeiten von Metadaten, Lightroom-Katalog anpassen.

Einzige Ausnahme beim Umbenennen ist der Anhang `_1`, `_2` … bei Namenskonflikten (§5). Er bleibt bestehen und wird im Bericht aufgelistet.
