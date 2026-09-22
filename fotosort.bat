@echo off
setlocal EnableExtensions
rem Befehle mit Ausgabe. Im fertigen Paket liegt fotosort-konsole.exe direkt hier;
rem aus dem Quellcode heraus liegt das Programm in .venv (angelegt von einrichten.bat).
rem Ohne Klammerbloecke: der Ordner darf Leerzeichen und Klammern enthalten.
if exist "%~dp0fotosort-konsole.exe" goto :paket
if exist "%~dp0.venv\Scripts\fotosort.exe" goto :quellcode
echo fotosort ist hier nicht eingerichtet: Weder fotosort-konsole.exe noch .venv gefunden.
echo Fertiges Paket: ZIP von der Release-Seite entpacken. Quellcode: einrichten.bat ausfuehren.
exit /b 2

:paket
"%~dp0fotosort-konsole.exe" %*
exit /b %ERRORLEVEL%

:quellcode
if exist "%~dp0.exiftool_pfad" set /p FOTOSORT_EXIFTOOL=<"%~dp0.exiftool_pfad"
"%~dp0.venv\Scripts\fotosort.exe" %*
exit /b %ERRORLEVEL%
