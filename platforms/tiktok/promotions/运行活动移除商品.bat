@echo off
chcp 65001 >nul
cd /d "%~dp0"
python 活动移除商品.py %*
pause
