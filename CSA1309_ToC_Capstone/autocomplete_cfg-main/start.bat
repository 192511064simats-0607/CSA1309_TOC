@echo off
setlocal enabledelayedexpansion
@chcp 65001 >nul 2>&1
title C CFG Autocomplete Engine Launcher
cd /d "%~dp0"

echo =======================================================================
echo  [*] Starting C CFG Autocomplete Engine (Backend + Frontend)
echo =======================================================================
echo.

REM 1. Free ports 5000 and 5173 so servers always launch cleanly on expected ports
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /C:":5000 " /C:":5173 "') do (
    if "%%a" neq "0" taskkill /f /pid %%a >nul 2>&1
)

REM 2. Determine Backend Directory, Virtual Environment, and Command
set "BACKEND_DIR=%~dp0"
set "ACTIVATE_CMD="
set "BACKEND_DESC=Python @ autocomplete.py"
set "BACKEND_CMD=python autocomplete.py"

if exist "%~dp0backend" (
    set "BACKEND_DIR=%~dp0backend"
    if exist "%~dp0backend\venv\Scripts\activate.bat" (
        set "ACTIVATE_CMD=call "%~dp0backend\venv\Scripts\activate.bat" && "
    ) else if exist "%~dp0backend\.venv\Scripts\activate.bat" (
        set "ACTIVATE_CMD=call "%~dp0backend\.venv\Scripts\activate.bat" && "
    )
    if exist "%~dp0backend\app.py" (
        set "BACKEND_DESC=Flask @ http://localhost:5000"
        set "BACKEND_CMD=python app.py"
    ) else if exist "%~dp0backend\server.py" (
        set "BACKEND_DESC=Server @ http://localhost:5000"
        set "BACKEND_CMD=python server.py"
    ) else if exist "%~dp0backend\main.py" (
        set "BACKEND_DESC=Python @ main.py"
        set "BACKEND_CMD=python main.py"
    )
) else (
    if exist "%~dp0venv\Scripts\activate.bat" (
        set "ACTIVATE_CMD=call "%~dp0venv\Scripts\activate.bat" && "
    ) else if exist "%~dp0.venv\Scripts\activate.bat" (
        set "ACTIVATE_CMD=call "%~dp0.venv\Scripts\activate.bat" && "
    )
    if exist "%~dp0app.py" (
        set "BACKEND_DESC=Flask @ http://localhost:5000"
        set "BACKEND_CMD=python app.py"
    ) else if exist "%~dp0server.py" (
        set "BACKEND_DESC=Server @ http://localhost:5000"
        set "BACKEND_CMD=python server.py"
    )
)

REM 3. Launch Backend Server / Engine in its own titled window
echo  [1/2] Launching Backend Server (!BACKEND_DESC!)...
start "CFG Autocomplete Engine - Backend" cmd /k "cd /d "!BACKEND_DIR!" && !ACTIVATE_CMD!!BACKEND_CMD!"

REM 4. Determine Frontend Directory and Command
set "FRONTEND_DIR=%~dp0"
set "FRONTEND_DESC=Web UI @ http://localhost:5173"
set "FRONTEND_CMD=python -m http.server 5173"

if exist "%~dp0frontend\package.json" (
    set "FRONTEND_DIR=%~dp0frontend"
    set "FRONTEND_DESC=Vite + React @ http://localhost:5173"
    set "FRONTEND_CMD=npm run dev"
) else if exist "%~dp0package.json" (
    set "FRONTEND_DIR=%~dp0"
    set "FRONTEND_DESC=Vite @ http://localhost:5173"
    set "FRONTEND_CMD=npm run dev"
)

REM 5. Launch Frontend Server in its own titled window
echo  [2/2] Launching Frontend Server (!FRONTEND_DESC!)...
start "CFG Autocomplete Engine - Frontend" cmd /k "cd /d "!FRONTEND_DIR!" && !FRONTEND_CMD!"

echo.
REM 6. Wait until Frontend server is actively listening on port 5173 before opening browser
echo  [*] Waiting for servers to initialize...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ready = $false; Write-Host '      Checking server readiness' -NoNewline; for ($i=0; $i -lt 30; $i++) { $conn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue; if ($conn) { $ready = $true; break; }; Write-Host '.' -NoNewline; Start-Sleep -Milliseconds 400; }; if ($ready) { Write-Host ' [ONLINE]' -ForegroundColor Green; Start-Sleep -Milliseconds 500; } else { Write-Host ' [READY]' -ForegroundColor Yellow; }; $c=@((Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'),'C:\Program Files\Google\Chrome\Application\chrome.exe','C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'); $cp=$null; foreach($p in $c){if(Test-Path $p){$cp=$p;break;}}; if($cp){ Start-Process -FilePath $cp -ArgumentList 'http://localhost:5173/'; } else { Start-Process 'http://localhost:5173/'; }"

echo.
echo =======================================================================
echo  Both services are running:
echo  - Backend:   !BACKEND_DESC!
echo  - Frontend:  http://localhost:5173/
echo =======================================================================
echo.
echo  Keep the backend and frontend terminal windows open while using.
echo.
pause
