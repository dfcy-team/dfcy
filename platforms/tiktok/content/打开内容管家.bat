@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "app.env" copy /y "app.env.example" "app.env" >nul
start https://dingfengchuangyu.com/content
echo 已在浏览器打开内容管家页面
