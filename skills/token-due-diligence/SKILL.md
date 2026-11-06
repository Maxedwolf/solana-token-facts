---
name: token-due-diligence
description: Check a Solana token or developer using verifiable on-chain facts (powers, metadata, holders, origin, launch-block buyers, dev history, dev funding). Use when someone asks if a token is safe, a rug, who made it, or about a dev's past launches.
---

# Solana token due diligence (facts only)

Use the solana-token-facts tools to answer with **verifiable on-chain facts**. Never give a
verdict like "safe", "scam", "will pump" or a buy/sell/timing recommendation. Say what the
token's creator **can** do and what the dev **has** done, and let the user decide.

## Order of checks

1. **Powers** - `token_authorities(mint)`
   - `can_mint_more: true` -> someone can still print new supply.
   - `can_freeze_accounts: true` -> someone can freeze holders' tokens.
   - Any `risky_extensions` (permanent delegate, transfer hook, pausable...) -> quote the `allows` text.
   - `can_change_metadata: true` -> someone (the `metadata.update_authority`) can still change the name, symbol or image.
   - `false` means the power was revoked. `null` means it could not be verified: say so.
2. **Origin** - `token_origin(mint)`: created when, by which wallet, which launchpad, graduated or not.
3. **Holders** - `token_holders(mint)`: top 1/5/10 concentration.
   - `program_address` holders are usually pools, vaults or the pump.fun bonding curve, not people.
   - Totals are lower bounds (only the 20 largest token accounts are visible).
4. **Launch-block buyers** - `launch_buyers(mint)`: wallets that bought in the creation block, how much,
   and what they still hold. Quote `summary.pattern`. Never claim those wallets belong to the dev.
5. **Dev history** - `dev_launches(mint=...)` or `dev_launches(wallet=...)`:
   quote the `summary.pattern` sentence, then the per-launch facts if asked.
6. **Dev funding** - `dev_funding(mint=...)`: who sent the dev wallet its first SOL, how long before launch,
   and how many wallets that funder pays. Quote `summary.pattern`. Never say the funder is the dev.
7. **Report** - offer `save_dev_report` so the user keeps the dev's history as a Markdown note.

## How to answer

- Lead with the 3-5 facts that matter most, each with its number.
- Add Solscan links from the results so the user can verify.
- If a tool fails (rate limit, RPC refused), say which fact is missing and why; do not guess.
- End with: "These are on-chain facts, not trading advice."
