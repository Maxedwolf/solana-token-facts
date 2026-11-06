@echo off
rem Dev helper: save your RPC URL (from the clipboard) into Hermes, then test token_holders live.
rem The key never gets printed or logged. Log: scripts\set_rpc_log.txt
setlocal EnableExtensions
cd /d "%~dp0.."
set "LOG=scripts\set_rpc_log.txt"
set "PY=python"
where python >nul 2>nul || set "PY=py"

echo.
echo  1. In your browser, on the Helius dashboard, click the COPY button
echo     next to your MAINNET RPC URL  (https://mainnet.helius-rpc.com/?api-key=...)
echo  2. Then come back to this window and press any key.
echo.
pause

set "URL="
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "(Get-Clipboard -Raw).Trim()"`) do set "URL=%%U"

> "%LOG%" echo === set_rpc %DATE% %TIME% ===
if not defined URL (
  echo Clipboard was empty. Copy the URL and run this again.
  >>"%LOG%" echo [error] clipboard empty
  goto :end
)
echo %URL%| findstr /b /c:"https://" >nul || (
  echo That does not look like an https:// URL. Copy the RPC URL and run this again.
  >>"%LOG%" echo [error] clipboard did not start with https://
  goto :end
)
for /f "tokens=2 delims=/" %%H in ("%URL%") do set "HOST=%%H"
>>"%LOG%" echo [ok] got an https URL for host: %HOST%

call hermes config set plugins.entries.solana-token-facts.settings.rpc_url "%URL%" >nul 2>&1
>>"%LOG%" echo [hermes config set exit code %ERRORLEVEL%]  (output hidden so the key is never logged)
>>"%LOG%" echo.

echo Testing token_holders through the new RPC...
>>"%LOG%" echo === token_holders PYUSD ===
%PY% scripts\try_tool.py token_holders 2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo "%URL%" >>"%LOG%" 2>&1
>>"%LOG%" echo === token_holders BONK ===
%PY% scripts\try_tool.py token_holders DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 "%URL%" >>"%LOG%" 2>&1
>>"%LOG%" echo === token_holders USDC ===
%PY% scripts\try_tool.py token_holders EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v "%URL%" >>"%LOG%" 2>&1
>>"%LOG%" echo === DONE ===

:end
set "URL="
echo.
echo Finished. Results saved to %LOG%
pause
