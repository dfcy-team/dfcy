@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

for %%P in (python py) do (
  where %%P >nul 2>&1 && set "PY=%%P" && goto :run
)
echo [ERROR] 未找到 python，请先安装 Python 并加入 PATH
exit /b 1

:run
"%PY%" "platforms\tiktok\marketing\refresh_advertisers_scheduled.py"
exit /b %ERRORLEVEL%
