@echo off
rem Dev helper: commit the current work and push to GitHub. Log: scripts\commit_push_log.txt
setlocal
cd /d "%~dp0.."
set "LOG=scripts\commit_push_log.txt"
> "%LOG%" echo === commit_push %DATE% %TIME% ===
git add .gitignore __init__.py plugin.yaml rpc.py schemas.py tools.py scripts/*.bat scripts/try_tool.py >>"%LOG%" 2>&1
>>"%LOG%" echo --- files staged ---
git diff --cached --stat >>"%LOG%" 2>&1
>>"%LOG%" echo --- secret check (should be empty) ---
git grep --cached -n -i "api-key=" >>"%LOG%" 2>&1
git commit -F scripts\commit_msg2.txt >>"%LOG%" 2>&1
>>"%LOG%" echo [commit exit code %ERRORLEVEL%]
git push origin main >>"%LOG%" 2>&1
>>"%LOG%" echo [push exit code %ERRORLEVEL%]
git log --oneline -3 >>"%LOG%" 2>&1
git status --short >>"%LOG%" 2>&1
>>"%LOG%" echo === DONE ===
echo Finished. Results saved to %LOG%
pause
