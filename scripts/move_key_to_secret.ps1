# Dev helper (one-time): move the private RPC URL from Hermes' config.yaml (plain setting)
# into Hermes' .env as the SOLANA_TOKEN_FACTS_RPC_URL secret. The value is never printed.
$home_ = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$cfg = Join-Path $home_ "config.yaml"; $envf = Join-Path $home_ ".env"; $name = "SOLANA_TOKEN_FACTS_RPC_URL"
$text = Get-Content $cfg -Raw
$m = [regex]::Match($text, "solana-token-facts:[\s\S]*?rpc_url:\s*['""]?(https://[^\s'""]+)")
if (-not $m.Success -or $m.Groups[1].Value -notmatch "api-key") { "nothing to move (no private rpc_url in config.yaml)"; exit 0 }
$url = $m.Groups[1].Value
$lines = @(); if (Test-Path $envf) { $lines = Get-Content $envf | Where-Object { $_ -notmatch "^$name=" } }
$lines += "$name=$url"
Set-Content -Path $envf -Value $lines -Encoding utf8
hermes config set plugins.entries.solana-token-facts.settings.rpc_url "https://api.mainnet-beta.solana.com" *> $null
$url = $null
"moved: secret saved in .env as $name; config.yaml rpc_url reset to the public default"
