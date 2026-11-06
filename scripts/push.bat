@echo off
rem Dev helper: push local commits to GitHub and record the result in scripts\push_log.txt
setlocal
cd /d "%~dp0.."
set "LOG=scripts\push_log.txt"
> "%LOG%" echo === push %DATE% %TIME% ===
echo Pushing to GitHub. If a sign-in window appears, sign in yourself.
git push origin main >>"%LOG%" 2>&1
>>"%LOG%" echo [push exit code %ERRORLEVEL%]
git status -sb >>"%LOG%" 2>&1
git log --oneline -3 >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === hermes --help ===
call hermes --help >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo === hermes chat --help ===
call hermes chat --help >>"%LOG%" 2>&1
>>"%LOG%" echo === DONE ===
echo Finished. Results saved to %LOG%
pause
