@echo off
chcp 65001 >nul
title QuantForge Frontend (port 80) - 关掉此窗口即停前端
cd /d "%~dp0web"

echo ============================================================
echo  QuantForge 前端启动器  (http://localhost  端口 80)
echo  - 此窗口保持打开 = 前端运行中
echo  - 关掉此窗口即停止前端
echo ============================================================
echo.

:loop
echo [%date% %time%] 启动 Vite dev (npm run dev) ...
call npm run dev
echo.
echo [%date% %time%] 前端退出(代码 %errorlevel%)，3 秒后自动重启 ... 按 Ctrl+C 可终止
timeout /t 3 /nobreak >nul
goto loop
