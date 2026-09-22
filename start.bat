@echo off
rem Gefuehrter Ablauf: fragt nach Ziel, Quellen, Kopieren/Verschieben und
rem Profil und geht dann Schritt fuer Schritt durch alle Phasen.
call "%~dp0fotosort.bat" start %*
echo.
pause
