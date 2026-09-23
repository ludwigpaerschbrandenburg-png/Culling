@echo off
setlocal EnableExtensions
rem Befehle mit Ausgabe. Im fertigen Paket laeuft alles ueber das mitgelieferte, signierte
rem Python (python\python.exe); aus dem Quellcode heraus ueber .venv (einrichten.bat).
rem Ohne Klammerbloecke: der Ordner darf Leerzeichen und Klammern enthalten.
if exist "%~dp0python\python.exe" goto :paket
if exist "%~dp0.venv\Scripts\python.exe" goto :quellcode
echo fotosort ist hier nicht eingerichtet: Weder python\python.exe noch .venv gefunden.
echo Fertiges Paket: ZIP von der Release-Seite vollstaendig entpacken. Quellcode: einrichten.bat ausfuehren.
exit /b 2

:paket
"%~dp0python\python.exe" -X utf8 "%~dp0lib\fotosort_start.py" %*
exit /b %ERRORLEVEL%

:quellcode
if exist "%~dp0.exiftool_pfad" set /p FOTOSORT_EXIFTOOL=<"%~dp0.exiftool_pfad"
"%~dp0.venv\Scripts\python.exe" -X utf8 -m fotosort %*
exit /b %ERRORLEVEL%
