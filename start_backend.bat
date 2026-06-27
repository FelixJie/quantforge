@echo off
chcp 65001 >nul
title QuantForge Backend (port 8000) - 关掉此窗口即停后端
cd /d "%~dp0"

echo ============================================================
echo  QuantForge 后端启动器  (http://0.0.0.0:8000)
echo  - 此窗口保持打开 = 后端运行中
echo  - 崩溃会自动重启;按 Ctrl+C 两次再关窗口可彻底停止
echo ============================================================
echo.

:loop
echo [%date% %time%] 启动 uvicorn ...
python -m uvicorn quantforge.api.app:app --host 0.0.0.0 --port 8000
echo.
echo [%date% %time%] 后端退出(代码 %errorlevel%)，3 秒后自动重启 ... 按 Ctrl+C 可终止
timeout /t 3 /nobreak >nul
goto loop
