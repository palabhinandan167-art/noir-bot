@echo off
title SFUDP Dashboard (Live Public URL)
cd /d "%~dp0"
echo ========================================================
echo Starting SFUDP Bot & Web Dashboard...
echo ========================================================
start "SFUDP Bot" "C:\Users\GANDU\AppData\Local\Programs\Python312\python.exe" app.py
timeout /t 3 /nobreak >nul
echo ========================================================
echo Creating Public Cloudflare HTTPS Tunnel...
echo ========================================================
.\cloudflared.exe tunnel --url http://localhost:14146
pause
