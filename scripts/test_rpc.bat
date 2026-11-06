@echo off
rem Dev helper: try token_holders on different free RPC endpoints. Output: scripts\rpc_test_log.txt
setlocal
cd /d "%~dp0.."
set "LOG=scripts\rpc_test_log.txt"
set "PY=python"
where python >nul 2>nul || set "PY=py"
> "%LOG%" echo === rpc test %DATE% %TIME% ===
for %%U in (https://solana-rpc.publicnode.com https://api.mainnet-beta.solana.com) do (
  >>"%LOG%" echo.
  >>"%LOG%" echo ##### RPC %%U #####
  >>"%LOG%" echo --- PYUSD ---
  %PY% scripts\try_tool.py token_holders 2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo %%U >>"%LOG%" 2>&1
  >>"%LOG%" echo --- BONK ---
  %PY% scripts\try_tool.py token_holders DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 %%U >>"%LOG%" 2>&1
  >>"%LOG%" echo --- USDC ---
  %PY% scripts\try_tool.py token_holders EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v %%U >>"%LOG%" 2>&1
)
>>"%LOG%" echo === DONE ===
echo Finished. Results saved to %LOG%
pause
