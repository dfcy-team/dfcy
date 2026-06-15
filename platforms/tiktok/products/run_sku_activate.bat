@echo off
cd /d "%~dp0"
pip install requests -q 2>\\.\r\nul
python run_sku_activate.py %*
echo.
pause
