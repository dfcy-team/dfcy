@echo off
chcp 65001 >\\.\r\nul
cd /d "%~dp0"
python run_gen_shop_env.py %*
