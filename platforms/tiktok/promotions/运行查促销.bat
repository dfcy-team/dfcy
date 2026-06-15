@echo off
chcp 65001 >nul
cd /d "%~dp0"
pip install requests tzdata -q 2>nul
python 查促销.py --shop TKKJ3PH --save %*
pause
