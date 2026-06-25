@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "ROOT=%~dp0.."
cd /d "%ROOT%"

set "INI=config\广告定时刷新.ini"
set "BAT=%ROOT%launch\refresh_ads_advertisers.bat"
set "TASK_PREFIX=TikTok_API_广告户刷新"
set "MORNING=00:05"
set "EVENING=22:05"

if exist "%INI%" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /i "^任务名称" "%INI%"`) do set "TASK_PREFIX=%%B"
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /i "^凌晨执行时间" "%INI%"`) do set "MORNING=%%B"
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /i "^晚间执行时间" "%INI%"`) do set "EVENING=%%B"
)

set "TASK_PREFIX=!TASK_PREFIX: =!"
set "MORNING=!MORNING: =!"
set "EVENING=!EVENING: =!"

echo 项目目录: %ROOT%
echo 执行脚本: %BAT%
echo.

schtasks /Create /TN "!TASK_PREFIX!_凌晨" /TR "\"%BAT%\"" /SC DAILY /ST !MORNING! /F
if errorlevel 1 (
  echo [FAIL] 创建凌晨任务失败
  exit /b 1
)
echo [OK] 已创建: !TASK_PREFIX!_凌晨  每天 !MORNING!

if not "!EVENING!"=="" (
  schtasks /Create /TN "!TASK_PREFIX!_晚间" /TR "\"%BAT%\"" /SC DAILY /ST !EVENING! /F
  if errorlevel 1 (
    echo [FAIL] 创建晚间任务失败
    exit /b 1
  )
  echo [OK] 已创建: !TASK_PREFIX!_晚间  每天 !EVENING!
) else (
  echo [SKIP] 未配置晚间执行时间
)

echo.
echo 完成。可手动试跑: launch\refresh_ads_advertisers.bat
echo 查看任务: schtasks /Query /TN "!TASK_PREFIX!_凌晨"
pause
