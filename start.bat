@echo off
echo Starting Anime Image Generator...
cd /d D:\project
call C:\Users\ASUS\sd-animate\venv\Scripts\activate.bat
start http://localhost:8080
python webui.py
pause
