# Prüfung aller Funktionen – Version 0.14

Stand: 05.11.2026. Auftrag des Nutzers: „Bitte alle Features nach Richtigkeit testen und updaten.“

Geprüft wurde **nur mit künstlichen Daten**: dem kleinen Testbaum (SPEC §11), 300 und 5000
Testbildern. Nie mit echten Fotos.

## Wie geprüft wurde

1. **Lesen gegen die Beschreibung.** Programm, SPEC, Anleitung und Tests wurden nebeneinander
   gelesen. Gefunden: neun Fehler (unten „Fehler 1–9“).
2. **Ein unabhängiger Tester.** Ein zweiter Prüfer bekam eine eigene Arbeitskopie des Programms
   (Stand v0.13.0) und hat es **wie ein Nutzer** bedient: jeden Befehl, das Fenster mit beiden
   Abläufen, Verschieben auf demselben und auf einem anderen Laufwerk, Unterbrechungen mit Strg+C,
   eine verschwundene Quelle, ein voller Datenträger, ein Archiv unter neuem Laufwerksbuchstaben.
   Er hat das Programm nicht verändert. Vor und nach jedem Versuch hat er den Inhalt aller Bilder
   (Fingerabdruck BLAKE3) in Quelle, Ordner `_geloescht_` und Archiv verglichen.
   **Ergebnis: In keinem einzigen Versuch ging ein Bild verloren.** Gefunden hat er 16 Befunde
   (unten „F1–F16“) und eine Beobachtung.
3. **Jeder Befund wurde zuerst als Test nachgestellt**, der den Fehler zeigt, dann behoben. Die
   Tests bleiben im Projekt (`tests/test_pruefbefunde14.py`, `tests/test_umzug.py` und weitere).
4. **Alle automatischen Tests** liefen danach mit Python 3.12 und 3.15 (Ergebnis unten).
5. **Rundgang mit 5000 Testbildern** im Fenster, „Alles automatisch“, danach „Ergebnis prüfen“
   (Ergebnis unten).

## Jede Funktion

| Funktion | Wie geprüft | Ergebnis | Was behoben |
|---|---|---|---|
| Scan (eine und mehrere Quellen) | Tester: verschachtelte Quellen, Quelle = Ziel, Ziel in der Quelle, fehlendes Ziel, kaputte Archiv-Kennung | richtig | Aufteilung nach Dateiart jetzt auch je Quelle (F16); Testbilder und Ordner `_geloescht_` unter einer Quelle werden nie erfasst (F4, F16) |
| Neue Dateiendungen in den Einstellungen | Test nachgestellt | wirkten nicht auf schon erfasste Dateien | wirken jetzt beim nächsten Scan (Fehler 2) |
| Analyse | Tester: Datum, Kamera, Namenskonflikte, Umlaute, sehr lange Pfade | richtig | Begleitdatei ohne Bild wird zugeordnet, wenn das Bild später kommt (Fehler 4) |
| Kopieren | Tester: zweimal kopieren, Neuscan, `_1` bei gleichem Namen, „Bild - Kopie“-Regel | richtig | sehr lange Dateinamen (251–255 Zeichen) scheiterten (F5); bei gleichem Inhalt kommt die Datei mit Datum ins Archiv (Beobachtung) |
| Verschieben | Tester: gleiches Laufwerk (Umbenennen) und anderes Laufwerk | Inhalt immer heil | `kopieren --verschieben` verlangt jetzt das Wort `verschieben` (F11); Datei mit falscher Größe nach dem Umbenennen wird geprüft (Fehler 5) |
| Prüfen, Archiv nachprüfen (`--alles`), Prüfsummen-Liste | Tester: Liste unabhängig nachgerechnet, veränderte und fehlende Archivdateien | richtig | unter neuem Laufwerksbuchstaben galt alles als fehlend (Fehler 1 / F1) |
| Aufräumen | Tester: Probelauf, `_geloescht_`, endgültig, falsches Wort, je Quelle | richtig, Löschsicherung hält | verweigerte Löschung wegen kaputter Archivkopie: jetzt neue Kopie (F2); Archiv verschwindet mittendrin: Aufräumen hört auf (F2); Zahlen in der Übersicht (Fehler 6, F3); Nachzügler-XMP eines schon importierten Bildes bleibt (Fehler 3) |
| Leere Ordner | Tester: Reste wie `Thumbs.db`, gefährliche Einträge in `reste_dateien` | richtig | unpassende Überschrift entfernt (F16) |
| Zurücklegen | Tester: auch nach Löschen des Ordners `_geloescht_` von Hand | richtig | – |
| Laufwerksbuchstabe wechselt | Tester und Test | Archiv galt als leer, Originale nie aufräumbar | Pfade werden umgestellt, vorher Sicherung der Datenbank (Fehler 1 / F1) |
| Wiederherstellen | Tester: fehlende Datenbank, ersetzen, vorheriger Stand | richtig | „Stand vom“ nannte die Uhrzeit des Zurückholens (F7) |
| Status | Tester | Phase passte nicht zum Zustand | Phase = nächster Schritt mit Arbeit, Erreichbarkeit jetzt frisch, Status-Wörter erklärt (F8, F16) |
| Bericht | Tester: Text, Tabelle, 10 Berichte, Packen | richtig | aufgeräumte Duplikate zählen weiter als Duplikate (F6); „Stand des Archivs“ Zahl und Größe passend (F13) |
| Einstellungen (`config`) | Tester | richtig | Fehlerursache englisch → als „Technische Angabe (englisch)“ gekennzeichnet (F16) |
| Messen | Tester | richtig | Vorschlag ohne Lesemessung passt jetzt zum Profil (F16) |
| Geführter Ablauf (`start`) | Tester | richtig | – |
| Testbilder | Tester: 300 Bilder, CLI und Fenster | „340 von 340 Erwartungen erfüllt“ | – |
| Fenster, beide Abläufe | Tester: Durchlauf, Bildschirmfotos | richtig | „Alles erledigt“ trotz verweigerter Löschungen (F3); Dialog nannte einen Knopf, den es nicht gibt (F9); zwei verschiedene Tempo-Zahlen (F16); Durchlauf hing bei fehlendem Ziel (F14); Text „Alles automatisch“ (Fehler 9) |
| Browser-Fassung (für später) | Lesen | nahm Anfragen fremder Seiten an | Herkunft „null“ und fremde Adressen abgelehnt (Fehler 7) |
| Schreibschutz unter Windows | Lesen, Test | folgte mit neuem Python einer Verknüpfung | nur die Verknüpfung selbst (Fehler 8) |
| Unterbrechungen | Tester: Strg+C zweimal beim Kopieren, weiter | gleiches Ergebnis wie ohne Unterbrechung | Strg+C bei umgeleiteter Ausgabe beendete den Lauf nicht sauber (F12) |
| Befehlszeile allgemein | Tester | richtig | Tippfehler-Hinweis nannte den internen Befehl `arbeit` (F16); „1 Datei“ statt „1 Dateien“ (F16) |

## Die Befunde im Einzelnen

Jeder Befund: was passierte – was jetzt passiert – welcher Test es festhält.

- **Fehler 1 / F1 – Archiv unter neuem Laufwerksbuchstaben.** Prüfen und Aufräumen hielten alle
  Kopien für verschwunden; die Prüfsummen-Liste wurde leer; ein neuer Durchgang hielt die eigenen
  Kopien für „schon im Archiv“, die Originale ließen sich nie mehr aufräumen. **Jetzt:** Das
  Programm erkennt sein Archiv an der Archiv-Kennung, legt eine Sicherung der Datenbank an
  (`fotosort.db.vor_umzug_<Zeit>`) und stellt die gespeicherten Pfade um; es sagt das. Gibt es den
  alten Ort noch (zwei Kopien des Archivs), hört es auf und fragt. `tests/test_umzug.py`
  (9 Tests, auch „Archiv nachprüfen“ nach dem Wechsel).
- **Fehler 2 – neue Dateiendung.** Wirkte nur auf neue Dateien. **Jetzt** beim nächsten Scan auch
  auf schon erfasste. `test_neue_endung_…`.
- **Fehler 3 – Nachzügler-XMP eines schon importierten Bildes** wäre aus der Quelle geräumt
  worden, obwohl das Bild dort bleibt. **Jetzt** gilt sie ebenfalls als schon im Archiv und
  bleibt. `test_spaete_begleitdatei_…`.
- **Fehler 4 – Begleitdatei ohne Bild** wurde nie wieder zugeordnet. **Jetzt** bei jeder Analyse.
  `test_begleitdatei_ohne_hauptdatei_…`.
- **Fehler 5 – Verschieben mit falscher Größe:** Datei im Archiv, Quelle weg, Status „Fehler“ –
  nie wieder geprüft. **Jetzt** prüft „Prüfen“ sie wie jede verschobene Datei.
  `test_verschoben_mit_abweichender_groesse_…`.
- **Fehler 6 – Zahlen nach dem Aufräumen** über verschiedene Zeiträume. **Jetzt** beide über alle
  Durchgänge. `test_uebersicht_aufraeumen_zahlen_…`.
- **Fehler 7 – Browser-Fassung** nahm Anfragen fremder Seiten an. **Jetzt** abgelehnt.
  `tests/test_oberflaeche.py`.
- **Fehler 8 – Schreibschutz entfernen** folgte unter Windows einer Verknüpfung. **Jetzt** nur die
  Verknüpfung selbst. `test_schreibschutz_…`.
- **Fehler 9 – Text „Alles automatisch“** versprach, Kameranamen ließen sich am Ende ändern.
  **Jetzt** der Hinweis, dafür „Schritt für Schritt“ zu nehmen. `test_text_alles_automatisch_…`.
- **F2 – Löschung verweigert wegen kaputter Archivkopie:** Die Datei blieb für immer „Fehler“, das
  Archiv behielt nur die kaputte Kopie. **Jetzt** gibt „Kopieren“ sie frei, sie bekommt eine neue,
  heile Kopie (die kaputte bleibt unberührt liegen). Verschwindet das Archiv während des
  Aufräumens, hört es auf, statt alles als Fehler zu verbuchen. `test_f2_…`.
- **F3 – „Alles erledigt“, obwohl Löschungen verweigert wurden.** **Jetzt** nennt die Schlussmeldung
  die offenen Befunde, und „entfernt“ zählt nur wirklich Entferntes. `test_f3_…`.
- **F4 – Testbilder in einem echten Archiv,** wenn die Quelle den Testbilder-Ordner enthielt.
  **Jetzt** wird so ein Ordner beim Scan übersprungen und gemeldet. `test_f4_…`.
- **F5 – Dateinamen mit 251–255 Zeichen** ließen sich nie kopieren (der Zwischenname war zu lang).
  **Jetzt** wird der Zwischenname gekürzt. `test_f5_…`.
- **F6 – Duplikate verschwanden nach dem Aufräumen** aus Bericht und Listen. **Jetzt** merkt sich
  jede Zeile, dass sie ein Duplikat war (neue Spalte `war_duplikat`). `test_f6_…`.
- **F7 – „Stand vom“ beim Wiederherstellen** nannte die Uhrzeit des Zurückholens. **Jetzt** den
  Stand der Sicherung. `test_f7_…`.
- **F8 – `status`** nannte eine falsche Phase. **Jetzt** den nächsten Schritt, wie der Knopf im
  Fenster. `test_f8_…`.
- **F9 – Dialog „Ordner anlegen?“** nannte einen Knopf, den es nicht gab. **Jetzt** passen Text und
  Knöpfe. `tests/test_desktop.py`.
- **F10, F15 – veraltete Stellen in der Anleitung** (Ordner bei „nur Hersteller“, violette Linie,
  Knopfbeschriftung, Fragen im schwarzen Fenster, „Enter heißt ja“, „Wort genau“). **Jetzt**
  berichtigt.
- **F11 – `kopieren --verschieben`** brauchte kein Bestätigungswort. **Jetzt** verlangt es
  `verschieben` (ohne Eingabemöglichkeit: es verschiebt nichts). `test_f11_…`.
- **F12 – Strg+C bei umgeleiteter Ausgabe** ließ den Lauf unbeendet (der nächste Lauf räumte auf).
  **Jetzt** endet er sauber. `test_f12_…`.
- **F13 – „Stand des Archivs“:** Zahl und Größe passten nicht zusammen. **Jetzt** schon.
  `test_f13_…`.
- **F14 – Durchlauf hing,** wenn das Ziel noch nicht existierte. **Jetzt** legt er es an.
  `tests/test_desktop.py`.
- **F16 – Kleinigkeiten:** Vorschlag von `messen`, Aufteilung nach Dateiart je Quelle, „1 Datei“,
  Überschrift bei „Leere Ordner“, zwei Tempo-Zahlen im Fenster, interner Befehl im
  Tippfehler-Hinweis, englische Fehlerursache, Ordner `_geloescht_` als „Muster“ gezählt,
  „erreichbar“ nach Meldung „nicht erreichbar“, rohe Status-Wörter. Alle behoben, je mit Test.
- **Beobachtung – gleiche Bilder, nur eines mit Datum:** Kam zufällig das undatierte zuerst, lag
  das Bild nur unter `_Ohne_Datum`. **Jetzt** kommt das datierte ins Archiv, das andere wird sein
  Duplikat. Es geht nichts verloren, nur die Einordnung wird besser.
  `test_von_gleichen_bildern_kommt_das_datierte_ins_archiv`.

## Bewusst so gelassen

- Dateien, deren Änderungszeit sich verschoben hat (Sommerzeit auf manchen Speicherkarten),
  gelten danach als „schon im Archiv“ und werden nie aufgeräumt. Diese Richtung ist sicher; der
  Reiter „Wohin?“ zeigt sie als eigene Gruppe („War schon im Archiv“).
- „Zurücklegen“ und Zurückschieben von Hand behandeln eine Datei unterschiedlich (am Testbaum
  nachgestellt): Nach „Zurücklegen“ ist sie ein gewöhnliches Duplikat ihrer Archivkopie und darf
  wieder aufgeräumt werden. Eine von Hand zurückgeschobene Datei kann das Programm nicht sicher
  wiedererkennen – sie gilt als „schon im Archiv“ und bleibt für immer in der Quelle. Beides
  verliert nichts; die Anleitung erklärt den Unterschied (Abschnitt „Schritt 5“).

## Nicht geprüft

Nur unter Windows prüfbar und deshalb der CI überlassen (sie startet das Paket unter Windows):
lange Pfade mit `\\?\`, Laufwerksarten, Wachhalten, eine einzige Instanz, Virenscanner.
Nicht geprüft: echte Netzlaufwerke, exFAT-Karten, echter Stromausfall.

## Ergebnis der Abschlusstests

(wird nach den Abschlusstests eingetragen)
