@echo off
setlocal
cd /d "%~dp0.."
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% scripts\try_tool.py recent_pump_mint > scripts\debug_pump_log.txt 2>&1
exit
