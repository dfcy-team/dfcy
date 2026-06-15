@echo off
chcp 65001 >nul
cd /d "%~dp0"
python 活动加商品.py %*
pause
