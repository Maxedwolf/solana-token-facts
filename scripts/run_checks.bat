@echo off
rem Dev helper: runs every Day 1 check and saves ALL output to scripts\checks_log.txt
rem Double-click it, or run it from Command Prompt. Makes real network calls (Solana RPC).
setlocal
cd /d "%~dp0.."
set "LOG=scripts\checks_log.txt"
set "PY=python"
where python >nul 2>nul || set "PY=py"

> "%LOG%" echo === run_checks %DATE% %TIME% ===
>>"%LOG%" echo [folder] %CD%
>>"%LOG%" echo.
>>"%LOG%" echo === python version (%PY%) ===
%PY% --version >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === TEST 1: USDC (classic Token program) ===
%PY% scripts\try_tool.py token_authorities EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === TEST 2: PYUSD (Token-2022) ===
%PY% scripts\try_tool.py token_authorities 2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === TEST 2b: token_holders PYUSD ===
%PY% scripts\try_tool.py token_holders 2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === TEST 2c: token_holders BONK ===
%PY% scripts\try_tool.py token_holders DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === TEST 2d: token_holders USDC (huge token, may be refused by public RPC) ===
%PY% scripts\try_tool.py token_holders EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === TEST 3: bad address ===
%PY% scripts\try_tool.py token_authorities hello >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === where hermes ===
where hermes >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === hermes --version ===
call hermes --version >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === hermes plugins doctor . --ci ===
call hermes plugins doctor . --ci >>"%LOG%" 2>&1
>>"%LOG%" echo [exit code %ERRORLEVEL%]
>>"%LOG%" echo.
>>"%LOG%" echo === hermes plugins validate . ===
call hermes plugins validate . >>"%LOG%" 2>&1
>>"%LOG%" echo [exit code %ERRORLEVEL%]
>>"%LOG%" echo.
>>"%LOG%" echo === git status ===
git status >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === DONE ===

echo.
echo All checks finished. Results saved to %LOG%
echo Go back to Claude and say "done".
pause
