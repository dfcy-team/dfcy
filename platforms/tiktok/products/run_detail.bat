@echo off
cd /d "%~dp0"
pip install requests -q 2>\\.\r\nul
if "%~1"=="" (
  python run_query.py --detail 1734369244110423722
) else (
  python run_query.py --detail %1
)
echo.
pause
