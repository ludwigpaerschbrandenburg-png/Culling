@echo off
rem Oeffnet die Oberflaeche: ein normales Windows-Fenster mit Knoepfen und Ordnerauswahl.
rem Im fertigen Paket startet das mitgelieferte, signierte Python (python\pythonw.exe,
rem ohne Konsole) - kein eigenes Programm, das ein Virenscanner erst pruefen muesste.
rem Absichtlich ohne Klammerbloecke - der Ordner darf Leerzeichen und Klammern enthalten,
rem etwa "...\Downloads\fotosort-windows (1)\fotosort".
if exist "%~dp0python\pythonw.exe" goto :paket
rem Aus dem Quellcode heraus (einrichten.bat): dasselbe Fenster ueber fotosort.bat.
call "%~dp0fotosort.bat" fenster %*
if errorlevel 1 pause
goto :eof
:paket
start "" "%~dp0python\pythonw.exe" -X utf8 "%~dp0lib\fotosort_start.py" fenster %*
