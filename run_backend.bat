@echo off
title QuantForge Backend
cd /d "%~dp0"
if not exist logs mkdir logs

REM ── 后端守护循环：无 --reload(Windows 上不稳 + 重启空窗导致间歇 503)，
REM    进程退出即自动重拉(2s 间隔)。
REM
REM    关键：项目根的 .venv 不完整(缺 uvicorn/fastapi)。若本窗口继承了已激活
REM    的 .venv 环境，裸 `python` 会解析到 .venv 导致 "No module named uvicorn"
REM    无限重启。因此这里：
REM      1) 清掉 VIRTUAL_ENV，避免任何 venv 探测
REM      2) 写死系统 Python 全路径(已装 uvicorn/fastapi，且能 import quantforge)
REM      3) PYTHONPATH=src + 从项目根启动(相对路径 data/ 才找得到)
set "VIRTUAL_ENV="
set "PYTHONHOME="
set "PYEXE=C:\Users\auspi\AppData\Local\Programs\Python\Python314\python.exe"
set "PYTHONPATH=src"

if not exist "%PYEXE%" (
    echo  [FATAL] system python not found at %PYEXE% >> logs\server.log
    echo  [FATAL] system python not found, aborting guard.
    pause
    exit /b 1
)

:loop
echo. >> logs\server.log
echo  [%date% %time%] starting backend via %PYEXE% (no-reload)... >> logs\server.log
"%PYEXE%" -m uvicorn quantforge.api.app:app --host 0.0.0.0 --port 8000 >> logs\server.log 2>&1
echo  [%date% %time%] backend exited (code %errorlevel%), restarting in 2s... >> logs\server.log
echo  [!] backend exited, restarting in 2s...
timeout /t 2 /nobreak >nul
goto loop
