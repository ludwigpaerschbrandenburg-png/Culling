# Bildschirmfotos der Oberfläche

Jede Ansicht des Fensters, erzeugt mit Playwright (Chromium, 1180 × 800) am künstlichen
Testbaum aus SPEC §11 — nie mit echten Fotos. Erzeugt `fotos.js` in diesem Ordner gegen
`fotosort fenster --ohne-fenster --port 47812` (Ablauf: Startseite → Scan → Analyse →
Kopieren → Prüfen → Aufräumen; der „laufende Schritt“ ist ein eingespielter Beispielstand,
weil der Testbaum zu klein ist, um ihn mitten im Kopieren zu erwischen).

| Bild | Ansicht |
|---|---|
| [01](01-startseite-leer.png) | Startseite, leer |
| [02](02-startseite-ausgefuellt.png) | Startseite mit Ziel, Quelle, Modus und Profil |
| [03](03-uebersicht-nach-scan.png) | Übersicht nach dem Scan (Phasenleiste, Zähler, Karten) |
| [04](04-uebersicht-nach-analyse-kameras.png) | Übersicht nach der Analyse mit Kamera-Tabelle (Alias tippbar) |
| [05](05-laufender-schritt-kopieren.png) | Laufender Schritt: Balken, Kennzahlen, Pause/Abbrechen |
| [06](06-laufender-schritt-pause.png) | Laufender Schritt angehalten |
| [07](07-uebersicht-nach-kopieren.png) | Übersicht nach dem Kopieren |
| [08](08-uebersicht-nach-pruefen-aufraeumen-karte.png) | Übersicht nach dem Prüfen, Aufräumen-Karte aktiv |
| [09](09-aufraeumen-bestaetigt.png) | Aufräumen: Bestätigungswort getippt, Knopf aktiv |
| [10](10-liste-duplikate.png) | Liste (Duplikate), seitenweise |
| [11](11-uebersicht-nach-aufraeumen-fertig.png) | Übersicht nach dem Aufräumen, alle Phasen erledigt |
| [12](12-dialog-ordner-anlegen.png) | Dialog „Ordner anlegen?“ |

Design-Übergabe: [`../design/DESIGN.md`](../design/DESIGN.md).
