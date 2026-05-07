@echo off
echo Stopping old ComfyUI...
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul

echo Starting ComfyUI...
cd /d C:\Users\ASUS\sd-animate
call venv\Scripts\activate.bat
python C:\Users\ASUS\ComfyUI\main.py
pause
