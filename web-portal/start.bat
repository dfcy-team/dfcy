@echo off
cd /d "%~dp0"
title TikTok Web Portal

set "WEB_PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%WEB_PY%" set "WEB_PY="
if not defined WEB_PY if exist "D:\software\anaconda3\python.exe" set "WEB_PY=D:\software\anaconda3\python.exe"
if not defined WEB_PY (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    set "WEB_PY=%%i"
    goto py_ok
  )
)
if not defined WEB_PY (
  echo ERROR: Python not found.
  pause
  exit /b 1
)
:py_ok

if not exist "local.env" if exist "local.env.example" copy /y "local.env.example" "local.env" >nul

echo Installing Flask if needed...
"%WEB_PY%" -m pip install -q -r requirements.txt

echo.
echo ========================================
echo  start.bat - Flask on 127.0.0.1:8080
echo  For HTTPS run: deploy\start_https.bat
echo ========================================
echo.
echo Starting web portal...
"%WEB_PY%" app.py
pause
