@echo off
rem Dev helper: link this repo into Hermes' plugins folder, enable it, and commit locally.
rem Saves output to scripts\enable_log.txt. Does NOT push to GitHub.
setlocal
cd /d "%~dp0.."
set "LOG=scripts\enable_log.txt"
set "PLUGDIR=%LOCALAPPDATA%\hermes\plugins"
set "LINK=%PLUGDIR%\solana-token-facts"

> "%LOG%" echo === enable_plugin %DATE% %TIME% ===
>>"%LOG%" echo [plugins folder] %PLUGDIR%

if not exist "%PLUGDIR%" mkdir "%PLUGDIR%"
if exist "%LINK%" (
  >>"%LOG%" echo [link] already exists, leaving it
) else (
  mklink /J "%LINK%" "%CD%" >>"%LOG%" 2>&1
)
>>"%LOG%" echo.

echo Enabling the plugin in Hermes. If it asks a question, answer it here.
>>"%LOG%" echo === hermes plugins enable solana-token-facts ===
call hermes plugins enable solana-token-facts
>>"%LOG%" echo [enable exit code %ERRORLEVEL%]
>>"%LOG%" echo.

>>"%LOG%" echo === hermes plugins list ===
call hermes plugins list >>"%LOG%" 2>&1
>>"%LOG%" echo.

>>"%LOG%" echo === hermes plugins doctor solana-token-facts ===
call hermes plugins doctor solana-token-facts >>"%LOG%" 2>&1
>>"%LOG%" echo.

>>"%LOG%" echo === git add + commit (local only) ===
git add .gitignore __init__.py plugin.yaml rpc.py schemas.py tools.py scripts/try_tool.py scripts/run_checks.bat scripts/enable_plugin.bat >>"%LOG%" 2>&1
git commit -F scripts\commit_msg.txt >>"%LOG%" 2>&1
>>"%LOG%" echo.
git log --oneline -3 >>"%LOG%" 2>&1
git status --short >>"%LOG%" 2>&1
>>"%LOG%" echo === DONE ===

echo.
echo Finished. Results saved to %LOG%
pause
