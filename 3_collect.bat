@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python -m research.collect
python -m research.parse
pause
