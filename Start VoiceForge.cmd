@echo off
cd /d "%~dp0"
wscript.exe "%~dp0Start VoiceForge Hidden.vbs"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8000
exit /b 0

