@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ==========================================================
echo  fotosort einrichten
echo ==========================================================
echo.
echo Dieses Skript prueft, ob Python und ExifTool da sind, legt eine
echo eigene Python-Umgebung im Unterordner .venv an und installiert
echo fotosort dort hinein. Am uebrigen Rechner aendert es nichts.
echo.
rem Keine Klammerbloecke mit Variablen: Ein Pfad mit ")" wuerde sie sprengen.

rem ---------------------------------------------------------- Python ----
set "PY="
py -3.14 -c "import sys" >nul 2>&1 && set "PY=py -3.14"
if defined PY goto :python_da
py -3.13 -c "import sys" >nul 2>&1 && set "PY=py -3.13"
if defined PY goto :python_da
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if defined PY goto :python_da
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=python"
if defined PY goto :python_da
echo FEHLT: Python 3.12 oder neuer wurde nicht gefunden.
echo.
echo So wird es installiert:
echo   1. https://www.python.org/downloads/windows/ im Browser oeffnen
echo   2. "Windows installer (64-bit)" von Python 3.12 oder neuer laden
echo   3. Beim Installieren UNBEDINGT das Haekchen
echo      "Add python.exe to PATH" setzen, dann "Install Now"
echo   4. Danach dieses Skript (einrichten.bat) noch einmal starten
goto :ende

:python_da
for /f "delims=" %%I in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%I"
echo Gefunden: Python %PYVER%

rem -------------------------------------------------------- ExifTool ----
set "EXIFTOOL="
if exist "%~dp0exiftool.exe" set "EXIFTOOL=%~dp0exiftool.exe"
if defined EXIFTOOL goto :exiftool_pruefen
if exist "C:\ExifTool\exiftool.exe" set "EXIFTOOL=C:\ExifTool\exiftool.exe"
if defined EXIFTOOL goto :exiftool_pruefen
where exiftool >nul 2>&1 && set "EXIFTOOL=exiftool"
if defined EXIFTOOL goto :exiftool_pruefen
echo FEHLT: ExifTool wurde nicht gefunden.
echo.
echo ExifTool liest das Aufnahmedatum und das Kameramodell aus den Bildern.
echo So wird es installiert:
echo   1. https://exiftool.org im Browser oeffnen
echo   2. "Windows Executable" laden (eine ZIP-Datei)
echo   3. Die ZIP-Datei entpacken; es entsteht ein Ordner mit der Datei
echo      "exiftool(-k).exe" und einem Unterordner "exiftool_files"
echo   4. Den ganzen entpackten Ordner nach C:\ExifTool verschieben
echo   5. Dort die Datei "exiftool(-k).exe" in "exiftool.exe" umbenennen
echo      (nur das "(-k)" entfernen)
echo   6. Danach dieses Skript (einrichten.bat) noch einmal starten
goto :ende

:exiftool_pruefen
set "EXVER="
for /f "delims=" %%I in ('"%EXIFTOOL%" -ver 2^>nul') do set "EXVER=%%I"
if defined EXVER goto :exiftool_da
echo FEHLER: ExifTool wurde gefunden, startet aber nicht:
echo   %EXIFTOOL%
echo Bitte die Datei noch einmal wie beschrieben entpacken und umbenennen.
goto :ende

:exiftool_da
echo Gefunden: ExifTool %EXVER%
echo   %EXIFTOOL%
if /i "%EXIFTOOL%"=="exiftool" goto :pfad_vergessen
<nul set /p "=%EXIFTOOL%" > "%~dp0.exiftool_pfad"
goto :umgebung
:pfad_vergessen
if exist "%~dp0.exiftool_pfad" del "%~dp0.exiftool_pfad"

rem -------------------------------------------------- Umgebung anlegen ----
:umgebung
if exist ".venv\Scripts\python.exe" goto :installieren
echo Lege die Python-Umgebung an, Ordner .venv ...
%PY% -m venv .venv
if errorlevel 1 goto :venv_fehler

:installieren
echo Installiere fotosort und seine Bausteine, braucht Internet, dauert etwa eine Minute ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -e .
if errorlevel 1 goto :install_fehler
".venv\Scripts\fotosort.exe" --help >nul 2>&1
if errorlevel 1 goto :start_fehler
echo.
echo FERTIG. fotosort ist eingerichtet.
echo.
echo   Gefuehrt starten:   start.bat  (Doppelklick, stellt Fragen)
echo   Einzelne Befehle:   fotosort.bat scan --quelle D:\Chaos --ziel D:\Archiv
echo   Anleitung:          LIESMICH.md
echo.
echo Bitte zuerst mit KOPIEN einiger Fotos ausprobieren, nie gleich mit den Originalen.
goto :ende

:venv_fehler
echo FEHLER: Die Umgebung konnte nicht angelegt werden.
goto :ende
:install_fehler
echo FEHLER: Die Installation ist fehlgeschlagen. Ist eine Internetverbindung da?
goto :ende
:start_fehler
echo FEHLER: fotosort laesst sich nicht starten.
goto :ende

:ende
echo.
pause
