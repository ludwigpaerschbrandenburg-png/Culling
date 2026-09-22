@echo off
rem Oeffnet die Oberflaeche: ein Fenster mit Knoepfen und Ordnerauswahl.
rem Im fertigen Paket liegt fotosort-fenster.exe direkt hier (ohne Konsole).
if exist "%~dp0fotosort-fenster.exe" (
  start "" "%~dp0fotosort-fenster.exe"
  exit /b 0
)
rem Aus dem Quellcode heraus (einrichten.bat): dasselbe Fenster ueber fotosort.bat.
call "%~dp0fotosort.bat" fenster %*
if errorlevel 1 pause
