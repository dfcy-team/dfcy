@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "ERP=%~dp0"
if "%ERP:~-1%"=="\" set "ERP=%ERP:~0,-1%"
set "TIKTOK_API=C:\Users\Administrator\Desktop\TikTok_API"

echo ========================================
echo  ERP HTTPS - Flask + Nginx
echo ========================================
echo.

echo [1/3] Check local.env
if not exist "%ERP%\web-portal\local.env" (
  if exist "%ERP%\web-portal\local.env.example" (
    copy /y "%ERP%\web-portal\local.env.example" "%ERP%\web-portal\local.env" >nul
    echo   copied local.env.example
  )
)

echo.
echo [2/3] Start Flask (127.0.0.1:8080) - keep ERP-Web window open
start "ERP-Web" /D "%ERP%\web-portal" cmd /k call start.bat
timeout /t 3 /nobreak >nul

echo.
echo [3/3] Start Nginx HTTPS
call "%TIKTOK_API%\deploy\nginx\install_site.bat"
echo.
pause
endlocal
