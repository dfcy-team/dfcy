@echo off
chcp 65001 >nul
cd /d "%~dp0"
python 停用活动.py %*
pause
