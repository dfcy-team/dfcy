@echo off
set "ERP=%~dp0"
set "ERP=%ERP:~0,-1%"
set "TIKTOK_API=C:\Users\Administrator\Desktop\TikTok_API"

echo [1/3] Check erp local.env
if not exist "%ERP%\web-portal\local.env" (
  if exist "%ERP%\web-portal\local.env.example" (
    copy /y "%ERP%\web-portal\local.env.example" "%ERP%\web-portal\local.env" >nul
  )
)

echo.
echo [2/3] Start Flask from erp (127.0.0.1:8080) - keep window open
start "ERP-Web" /D "%ERP%\web-portal" cmd /k call start.bat

timeout /t 3 /nobreak >nul

echo.
echo [3/3] Start Nginx (HTTPS, shared with TikTok_API)
call "%TIKTOK_API%\deploy\nginx\install_site.bat"
pause
