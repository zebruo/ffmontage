@echo off
rem Lance la Table de montage depuis les sources (environnement .venv du projet), sans console.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0TableDeMontage.py" %*
