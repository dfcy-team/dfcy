@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python new_shop.py %*
pause
