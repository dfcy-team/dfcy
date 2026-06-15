@echo off
cd /d "%~dp0web-portal"
if not exist "local.env" if exist "local.env.example" copy /y "local.env.example" "local.env" >nul
call start.bat
