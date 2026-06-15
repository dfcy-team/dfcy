@echo off
chcp 65001 >\\.\r\nul
cd /d "%~dp0"
python run_excel_create.py %*
