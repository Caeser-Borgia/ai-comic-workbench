@echo off
title AI Comi Workbench

echo ============================================
echo   AI Comi Workbench
echo ============================================
echo.

:: Step 1: Start ComfyUI if not already running
echo [1/2] Starting ComfyUI...
curl -s --connect-timeout 3 http://127.0.0.1:8188/api/queue >nul 2>&1
if %errorlevel% equ 0 (
    echo   ComfyUI is already running.
) else (
    echo   Launching ComfyUI in new window...
    cd /d C:\Users\ASUS\sd-animate
    start "ComfyUI" cmd /c "call venv\Scripts\activate.bat && python C:\Users\ASUS\ComfyUI\main.py --port 8188"
    echo   Waiting for ComfyUI to be ready...
    :waitloop
    timeout /t 3 /nobreak >nul
    curl -s --connect-timeout 3 http://127.0.0.1:8188/api/queue >nul 2>&1
    if %errorlevel% neq 0 goto waitloop
    echo   ComfyUI is ready!
)

:: Step 2: Start Web UI
echo.
echo [2/2] Starting Web UI...
echo   Opening http://localhost:8080
start http://localhost:8080
cd /d D:\project
call C:\Users\ASUS\sd-animate\venv\Scripts\activate.bat
python webui.py
pause
