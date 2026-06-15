@echo off
chcp 65001 >\\.\r\nul
cd /d "%~dp0"
python run_sync_categories.py %*
