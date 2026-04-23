@echo off
title QuantForge
cd /d "%~dp0"

echo.
echo  ==========================================
echo   QuantForge - Starting...
echo  ==========================================
echo.

REM ── Kill existing processes on port 8000 and 5173 ──────────────────────────
taskkill /F /FI "WINDOWTITLE eq QuantForge Backend" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq QuantForge Frontend" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    echo  [*] Stopping old backend (PID %%a)...
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173 " ^| findstr "LISTENING" 2^>nul') do (
    echo  [*] Stopping old frontend (PID %%a)...
    taskkill /F /PID %%a >nul 2>&1
)

REM ── Start backend ──────────────────────────────────────────────────────────
echo  [1/2] Starting backend (port 8000)...
if not exist logs mkdir logs
start "QuantForge Backend" /min cmd /k "cd /d %~dp0 && python -m uvicorn quantforge.api.app:app --host 0.0.0.0 --port 8000 2>&1 | tee logs\server.log"

REM ── Wait for backend to be ready ───────────────────────────────────────────
set /a tries=0
:wait_backend
timeout /t 1 /nobreak >nul
set /a tries+=1
curl -s http://localhost:8000/api/system/health >nul 2>&1
if %errorlevel%==0 goto backend_ready
if %tries% lss 15 goto wait_backend
echo  [!] Backend did not start in time, check logs\server.log
goto open_browser

:backend_ready
echo  [OK] Backend is ready.

REM ── Start frontend ─────────────────────────────────────────────────────────
echo  [2/2] Starting frontend (port 5173)...
start "QuantForge Frontend" /min cmd /k "cd /d %~dp0\web && npm run dev"

REM ── Wait for frontend ──────────────────────────────────────────────────────
set /a tries=0
:wait_frontend
timeout /t 1 /nobreak >nul
set /a tries+=1
curl -s http://localhost:5173 >nul 2>&1
if %errorlevel%==0 goto frontend_ready
if %tries% lss 20 goto wait_frontend
echo  [!] Frontend did not start in time.
goto open_browser

:frontend_ready
echo  [OK] Frontend is ready.

:open_browser
echo.
echo  ==========================================
echo   Opening http://localhost:5173
echo  ==========================================
echo.
timeout /t 1 /nobreak >nul
start http://localhost:5173

exit
