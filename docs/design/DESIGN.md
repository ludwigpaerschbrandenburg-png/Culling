# fotosort – Hauptansicht (Design-Übergabe)

Dateien: `index.html` (Struktur), `app.css` (Layout), `styles.css` (Design-Tokens + Komponenten, nicht ändern).
Öffnen: `index.html` im Browser – so soll das Fenster aussehen.

## Fenster
- Ein Fenster, drei Zeilen: Titelzeile 40px · Inhalt · Statusleiste 40px. Mindestbreite 1040px.
- Dunkler Grund `--color-bg`, Fläche `--color-surface`, Text `--color-text`, ein Akzent `--color-accent` (nur als Linie/Glow, nie als Fläche).
- Schrift Inter (aus styles.css). Zahlen mit `font-variant-numeric: tabular-nums`. Pfade und Statuswörter in Monospace.
- Kein Fließtext. Nur Beschriftungen, Zahlen, Pfade.

## Bereiche (von oben)
1. **Titelzeile**: `fotosort — <Zielpfad>`, rechts Tag `Lauf <N>`.
2. **Pfade**: Quellen als `.tag-neutral`, Pfeil, Ziel als `.tag-outline`; rechts Profil (`hdd|ssd|netzwerk`) und Modus (`kopieren|verschieben`).
3. **Phasenleiste**: 5 Phasen Scan · Analyse · Kopieren · Prüfen · Aufräumen. Fertige Phasen `--color-neutral-500`, aktive `--color-accent`, kommende `--color-neutral-600`. Akzentlinie darüber, Länge = Phasenfortschritt (`.phasen-fill` width).
4. **Fortschritt** (links): 2px-Balken (`.balken-fill` width = Prozent), darunter Dateien / GB / MB/s / Restzeit, darunter aktuelle Datei (pulsiert), darunter Zähler kopiert · Duplikate · Namenskonflikte · Fehler (Zeilen mit ausblendender Regel, 0 gedämpft).
5. **Karten** (rechts, 300px): „Aufräumen · Schritt 5“ mit Bestätigungsfeld (Wort `verschieben`/`loeschen`/`entfernen`; Knopf erst aktiv, wenn das Wort exakt stimmt) und „Letzter Bericht“ (Dateiname, Öffnen / CSV).
6. **Aktionen**: primär outlined (`.btn-primary`) = nächster sinnvoller Schritt; sekundär Probelauf, Einstellungen.
7. **Statusleiste**: db lokal · Sicherung <Zeit> · Sperrhinweis.

## Zustände
- Knöpfe: `disabled`, solange die Aktion nicht erlaubt ist (z. B. Aufräumen ohne Bestätigungswort, Weiter während Kopieren läuft).
- Fehler > 0: Zahl in `--color-text` statt gedämpft; nichts wird rot geflutet.
- Fokus: 2px Akzentring (kommt aus styles.css).

## Daten → Anzeige
- Phasenleiste: aktuelle Phase aus `fotosort status`.
- Kennzahlen/Zähler: aus der Fortschrittszeile (erledigt, Datenmenge, MB/s, Restzeit) und den Phasenzählern (kopiert, Duplikate, Namenskonflikte, Fehler).
- Statuswörter exakt wie in der Datenbank (`geprueft`, `duplikat_bestaetigt`, …), umlautfrei.
