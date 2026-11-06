@echo off
rem Dev helper: live-test token_origin + token_holders on a freshly launched pump.fun token. Log: scripts\origin2_log.txt
setlocal
cd /d "%~dp0.."
set "LOG=scripts\origin2_log.txt"
set "PY=python"
where python >nul 2>nul || set "PY=py"
> "%LOG%" echo === test_origin2 %DATE% %TIME% ===
set "NEW="
for /f "usebackq delims=" %%M in (`%PY% scripts\try_tool.py recent_pump_mint`) do set "NEW=%%M"
>>"%LOG%" echo [recent pump.fun mint] %NEW%
>>"%LOG%" echo === origin: brand-new pump.fun token ===
%PY% scripts\try_tool.py token_origin %NEW% >>"%LOG%" 2>&1
>>"%LOG%" echo === holders: brand-new pump.fun token ===
%PY% scripts\try_tool.py token_holders %NEW% >>"%LOG%" 2>&1
>>"%LOG%" echo === authorities: brand-new pump.fun token ===
%PY% scripts\try_tool.py token_authorities %NEW% >>"%LOG%" 2>&1
>>"%LOG%" echo === origin: Fartcoin ===
%PY% scripts\try_tool.py token_origin 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump >>"%LOG%" 2>&1
>>"%LOG%" echo === DONE ===
echo Finished. Results saved to %LOG%
pause
