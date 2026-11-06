@echo off
rem Dev helper: re-test the fresh pump.fun token, then commit + push. Log: scripts\commit3_log.txt
setlocal
cd /d "%~dp0.."
set "LOG=scripts\commit3_log.txt"
set "PY=python"
where python >nul 2>nul || set "PY=py"
> "%LOG%" echo === commit_push3 %DATE% %TIME% ===
>>"%LOG%" echo --- origin (same fresh token) ---
%PY% scripts\try_tool.py token_origin D8aSv6iLSZJdZ5ntLdZbK4YwkzZaGzJRMSGNzoF2pump >>"%LOG%" 2>&1
>>"%LOG%" echo --- holders (same fresh token) ---
%PY% scripts\try_tool.py token_holders D8aSv6iLSZJdZ5ntLdZbK4YwkzZaGzJRMSGNzoF2pump >>"%LOG%" 2>&1
>>"%LOG%" echo --- validate ---
call hermes plugins validate . >>"%LOG%" 2>&1
>>"%LOG%" echo [validate exit code %ERRORLEVEL%]
if errorlevel 1 goto :end
git add .gitignore __init__.py plugin.yaml schemas.py tools.py scripts/*.bat scripts/try_tool.py >>"%LOG%" 2>&1
>>"%LOG%" echo --- secret check ---
git grep --cached -n -i -E "api-key=[0-9a-f]" >>"%LOG%" 2>&1
git commit -F scripts\commit_msg3.txt >>"%LOG%" 2>&1
>>"%LOG%" echo [commit exit code %ERRORLEVEL%]
git push origin main >>"%LOG%" 2>&1
>>"%LOG%" echo [push exit code %ERRORLEVEL%]
git log --oneline -4 >>"%LOG%" 2>&1
:end
>>"%LOG%" echo === DONE ===
echo Finished. Results saved to %LOG%
pause
