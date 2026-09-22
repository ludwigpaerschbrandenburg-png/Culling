@echo off
rem Oeffnet die Oberflaeche: ein normales Windows-Fenster mit Knoepfen und Ordnerauswahl.
rem Absichtlich ohne Klammerbloecke - der Ordner darf Leerzeichen und Klammern enthalten,
rem etwa "...\Downloads\fotosort-windows (1)\fotosort".
if exist "%~dp0fotosort.exe" goto :paket
rem Aus dem Quellcode heraus (einrichten.bat): dasselbe Fenster ueber fotosort.bat.
call "%~dp0fotosort.bat" fenster %*
if errorlevel 1 pause
goto :eof
:paket
start "" "%~dp0fotosort.exe" fenster %*
