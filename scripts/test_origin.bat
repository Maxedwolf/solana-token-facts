@echo off
rem Dev helper: live-test token_origin (uses the RPC URL saved in Hermes). Log: scripts\origin_log.txt
setlocal
cd /d "%~dp0.."
set "LOG=scripts\origin_log.txt"
set "PY=python"
where python >nul 2>nul || set "PY=py"
> "%LOG%" echo === test_origin %DATE% %TIME% ===
set "NEW="
for /f "usebackq delims=" %%M in (`%PY% scripts\try_tool.py recent_pump_mint 2^>nul`) do set "NEW=%%M"
>>"%LOG%" echo [recent pump.fun mint] %NEW%
>>"%LOG%" echo === origin: brand-new pump.fun token ===
%PY% scripts\try_tool.py token_origin %NEW% >>"%LOG%" 2>&1
>>"%LOG%" echo === holders: brand-new pump.fun token ===
%PY% scripts\try_tool.py token_holders %NEW% >>"%LOG%" 2>&1
>>"%LOG%" echo === origin: Fartcoin (pump.fun, graduated, very busy) ===
%PY% scripts\try_tool.py token_origin 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump >>"%LOG%" 2>&1
>>"%LOG%" echo === origin: PYUSD ===
%PY% scripts\try_tool.py token_origin 2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo >>"%LOG%" 2>&1
>>"%LOG%" echo === hermes plugins validate . ===
call hermes plugins validate . >>"%LOG%" 2>&1
>>"%LOG%" echo === hermes plugins doctor . --ci ===
call hermes plugins doctor . --ci >>"%LOG%" 2>&1
>>"%LOG%" echo === DONE ===
echo Finished. Results saved to %LOG%
pause
