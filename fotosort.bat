@echo off
setlocal EnableExtensions
if not exist "%~dp0.venv\Scripts\fotosort.exe" (
    echo fotosort ist noch nicht eingerichtet. Bitte zuerst einrichten.bat ausfuehren.
    exit /b 2
)
if exist "%~dp0.exiftool_pfad" (
    set /p FOTOSORT_EXIFTOOL=<"%~dp0.exiftool_pfad"
)
"%~dp0.venv\Scripts\fotosort.exe" %*
exit /b %ERRORLEVEL%
