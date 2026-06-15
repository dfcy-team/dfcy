@echo off
cd /d "%~dp0"
pip install requests -q 2>\\.\r\nul
python run_listing.py --product-id 1734369244110423722 --action activate --execute
echo.
pause
