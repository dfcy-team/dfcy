@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
title TikTok Order Export
echo.
echo TikTok order export - edit: %~dp0导出设置.ini
echo Current shop: read ..\店铺配置\CURRENT_SHOP.txt  or use --shop TK2PH
echo.
pip install requests openpyxl tzdata -q 2>\\.\r\nul
python "%~dp0订单查询.py" %*
echo.
pause
