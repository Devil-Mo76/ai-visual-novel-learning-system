@echo off
chcp 65001 >nul
title AI视觉小说互动式学习系统 - 启动器
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+ 并加入 PATH。
    pause
    exit /b 1
)

echo 正在启动…（首次启动会检查依赖，稍慢属正常）
python run_app.py

pause
 