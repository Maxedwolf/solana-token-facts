@echo off
rem Dev helper: ask Hermes a real question in one-shot mode and save the answer to scripts\hermes_test_log.txt
setlocal
cd /d "%~dp0.."
set "LOG=scripts\hermes_test_log.txt"
> "%LOG%" echo === hermes one-shot test %DATE% %TIME% ===
echo Asking Hermes about the USDC and PYUSD mints...
call hermes -z "Using your tools, who controls the Solana token with mint EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v? Can more be minted, can accounts be frozen, and what is the supply? Then do the same for mint 2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo and list any risky Token-2022 extensions. Say which tool you used." >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo [exit code %ERRORLEVEL%]
>>"%LOG%" echo === DONE ===
echo Finished. Results saved to %LOG%
pause
