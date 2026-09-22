"""Ein nachgebautes ExifTool fuer Tests: antwortet wie -stay_open, bleibt aber
an jeder Datei haengen, deren Name "haengt" enthaelt. Nur fuer den Test des
Zeitlimits (tests/test_metadaten.py); liest nie eine echte Datei."""

from __future__ import annotations

import json
import sys
import time


def main() -> int:
    argumente = sys.argv[1:]
    if argumente == ["-ver"]:
        print("13.00")
        return 0
    if "-stay_open" not in argumente:
        return 0
    zeilen: list[str] = []
    for roh in sys.stdin.buffer:
        zeile = roh.decode("utf-8", "surrogateescape").rstrip("\r\n")
        if zeile.startswith("-execute"):
            nummer = zeile[len("-execute"):]
            pfade = [z for z in zeilen if not z.startswith("-")]
            if any("haengt" in p for p in pfade):
                time.sleep(3600)
            antwort = [{"SourceFile": p, "DateTimeOriginal": "2026:01:01 12:30:00", "Make": "FAKE", "Model": "Nachbau"}
                       for p in pfade]
            sys.stdout.buffer.write((json.dumps(antwort) + f"\n{{ready{nummer}}}\n").encode("utf-8", "surrogateescape"))
            sys.stdout.buffer.flush()
            zeilen = []
        elif zeile == "False" and zeilen and zeilen[-1] == "-stay_open":
            return 0
        else:
            zeilen.append(zeile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
