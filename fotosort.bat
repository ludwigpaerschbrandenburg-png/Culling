@echo off
setlocal EnableExtensions
rem Im fertigen Paket liegt fotosort.exe direkt hier; aus dem Quellcode heraus
rem liegt das Programm in .venv (angelegt von einrichten.bat).
if exist "%~dp0fotosort.exe" goto :paket
if exist "%~dp0.venv\Scripts\fotosort.exe" goto :quellcode
echo fotosort ist hier nicht eingerichtet: Weder fotosort.exe noch .venv gefunden.
echo Fertiges Paket: ZIP von der Release-Seite entpacken. Quellcode: einrichten.bat ausfuehren.
exit /b 2

:paket
"%~dp0fotosort.exe" %*
exit /b %ERRORLEVEL%

:quellcode
if exist "%~dp0.exiftool_pfad" set /p FOTOSORT_EXIFTOOL=<"%~dp0.exiftool_pfad"
"%~dp0.venv\Scripts\fotosort.exe" %*
exit /b %ERRORLEVEL%
