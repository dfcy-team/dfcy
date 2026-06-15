@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python switch_shop.py %*
pause
