# solana-token-facts

**Verifiable on-chain facts about Solana tokens and the developers behind them, for [Hermes Agent](https://hermes-agent.nousresearch.com).**

Ask Hermes *"is this token safe?"* and, instead of guessing, it checks the chain: who can still
mint or freeze, who holds the supply, when and where the token was born, and what the developer
did with their last launches. Every answer is a fact with a number and a Solscan link. No
predictions, no "buy" or "sell", no trading, no wallet keys.

> Example (real result): *"Dev `A6w6…1gHG`: 5 launches in 3 days, 0 graduated. Bought 6.7% of each
> at launch and sold the whole position in all 5, median 0.3 minutes after launch."*

## What you get

| Tool | Answers | Main RPC calls |
|---|---|---|
| `token_authorities` | Can more be minted? Can holders be frozen? Can the name, symbol or image still be changed (and by whom)? Supply, Token vs Token-2022, risky extensions (permanent delegate, transfer hook, pausable, fees…) | `getAccountInfo` (mint + Metaplex metadata) |
| `token_origin` | When was it created, by which wallet, on which launchpad (pump.fun, Raydium LaunchLab, Meteora, Moonshot, boop.fun), graduated or not | `getTransactionsForAddress` (oldest first), `getTransaction` |
| `token_holders` | Top holder wallets, top 1/5/10 concentration, wallet vs program address, pump.fun bonding curve labelled | `getTokenLargestAccounts`, `getMultipleAccounts` |
| `launch_buyers` | Which wallets bought in the same block the token was created (bundles / snipers), how much of the supply, and how much they still hold | `getTransactionsForAddress` (oldest first), `getTokenAccountsByOwner` |
| `dev_funding` | Who sent the dev wallet its first SOL, how much, how many minutes before launch, and how many different wallets that funder sends SOL to | `getTransactionsForAddress` |
| `dev_launches` | A developer's recent launches: graduated?, dev's buy at launch, did the dev sell out and how many minutes after launch, plus a one-line pattern | `getTransactionsForAddress` |
| `recent_graduations` | The newest pump.fun → PumpSwap graduations | `getTransactionsForAddress` |
| `save_dev_report` | Saves a dev's track record as a Markdown note (Obsidian-ready) | same as `dev_launches` |

Also included:

- **`/token <mint>`**: a one-shot fact sheet (powers, metadata, origin, holders, launch-block buyers, dev history and funding) without asking the model.
- **Skill `solana-token-facts:token-due-diligence`**: the order of checks and the "facts, no verdicts" rules the agent follows.
- **Automation blueprint `graduation-dev-watch`** (opt-in, via `/blueprint`): every few hours, list new PumpSwap graduations, check each developer and save a report for devs that match your filter (for example "has at least 3 launches"). Hermes' own scheduler runs it; the plugin never runs anything in the background.

## Install

```bash
hermes plugins install Maxedwolf/solana-token-facts --enable
hermes gateway restart        # the gateway loads plugins at start-up
```

Once listed in the catalog: `hermes plugins install solana-token-facts`.

## Set up an RPC (2 minutes, free)

The plugin works with Solana's free public RPC for `token_authorities`. Public endpoints refuse
the heavier lookups, so for the rest add a provider URL. A free [Helius](https://www.helius.dev)
account works for every tool (`getTransactionsForAddress` is Helius-specific).

The URL contains your API key, so it is stored as a **Hermes secret**, never in `config.yaml`.
Either fill in **Private RPC URL** in the plugin's settings page (Hermes dashboard / desktop), or
add one line to Hermes' `.env` (`~/.hermes/.env`, on Windows `%LOCALAPPDATA%\hermes\.env`):

```
SOLANA_TOKEN_FACTS_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY
```

Then `hermes gateway restart`. Tool results only ever show the RPC **host**, never the key.

## Settings

All optional. Set with `hermes config set plugins.entries.solana-token-facts.settings.<name> <value>`.

| Setting | Default | What it does |
|---|---|---|
| `rpc_secret_url` (secret) | none | Private RPC URL, see above. Wins over `rpc_url`. |
| `rpc_url` | `https://api.mainnet-beta.solana.com` | Keyless RPC endpoint. |
| `dev_max_launches` | `5` | How many of a dev's recent launches to report (up to 1000). |
| `dev_max_pages` | `5` | How deep to scan a dev's history, in pages of 100 transactions (~10 Helius credits per page). |
| `origin_max_pages` | `10` | Fallback scan limit for `token_origin` on RPCs without `getTransactionsForAddress`. |
| `reports_dir` | Hermes `plugin-data/solana-token-facts/dev-reports` | Where dev reports are saved. Point it at a folder in your **Obsidian vault** and the notes appear in Obsidian. |

Example: save reports into Obsidian

```bash
hermes config set plugins.entries.solana-token-facts.settings.reports_dir "C:\Users\you\Documents\Obsidian Vault\Solana Dev Reports"
```

Deeper dev history costs more RPC credits. That is why the defaults are small: raise them if your plan allows.

## Try it

```
/token 2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo
Who controls the USDC token EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v?
What graduated to PumpSwap most recently? Check the newest one's developer and save a dev report.
Has the developer of <mint> launched tokens before?
Who bought <mint> in its launch block, and do they still hold?
Who funded the developer of <mint>?
```

## How the facts are worked out (and their limits)

- **Revoked vs unknown.** An authority that is `null` on-chain is reported as revoked (`false`). A field that cannot be read is `null` ("unknown"), never a guess.
- **Who is the dev.** The wallet that *signed* the token's creation transaction. pump.fun also stores a "creator" that receives creator fees; it can be a wallet that never signs anything, so it is reported separately as `creator_fee_recipient`.
- **Graduated.** Read from the pump.fun bonding curve account (PDA `["bonding-curve", mint]`), byte 48 = complete.
- **Dev sold out.** The dev wallet's balance of that token, from the transactions' pre/post token balances, went to zero; the minutes are counted from the launch transaction.
- **Metadata can change.** Read from the token's Metaplex metadata account (PDA `["metadata", program, mint]`): `is_mutable` and its update authority. Token-2022 tokens with built-in metadata: the `tokenMetadata` extension's update authority (`null` = locked).
- **Launch-block buyers.** Every key-pair wallet whose balance of the token rose in a transaction in the creation slot (program addresses such as the bonding curve are excluded). Same-block buying is a timing fact; it does not prove who controls those wallets.
- **Dev funding.** The dev wallet's first SOL transfer ever and the last one before the launch (transfers under 0.01 SOL are ignored as spam), then the funder's last 100 transactions: how many different wallets it sent SOL to. A funder that pays thousands of wallets is usually an exchange; the tool reports the numbers and leaves the label to you.
- **Recent graduations** come from the history of pump.fun's migration account and are verified against a completed bonding curve (this filters out the pool's LP token).
- **Limits.** `token_holders` sees the 20 largest token accounts (an RPC limit), so concentration is a lower bound; tokens with millions of holders (USDC) are refused by RPCs. `dev_launches` counts launches where the dev's wallet paid the fee, within the scanned history.

## Disclosure

- **Network:** outbound HTTPS JSON-RPC requests to your configured Solana RPC endpoint only (default `https://api.mainnet-beta.solana.com`). Nothing else is contacted. No telemetry.
- **Files:** writes Markdown notes only when `save_dev_report` is called (or by the opt-in blueprint), into `reports_dir`.
- **Credentials:** the optional private RPC URL is a Hermes secret read with `get_secret`; it is never logged or returned.
- **On-chain:** read-only. No transactions, no signing, no wallet keys, no trading.
- **Not financial advice.** Results are on-chain facts; what they mean for a trade is your decision.

## Development

No dependencies beyond the Python standard library.

```bash
python scripts/try_tool.py token_authorities <mint>      # run a tool without Hermes
python scripts/try_tool.py dev_launches wallet:<address>
python scripts/try_tool.py token_command <mint>          # what /token prints
python -m unittest discover -s tests                     # offline tests (no network)
hermes plugins validate . && hermes plugins doctor . --ci
```

Test the agent from a neutral folder with only this plugin's tools, so Hermes cannot edit the repo:

```bash
cd /tmp && hermes -t solana_token_facts -s solana-token-facts:token-due-diligence -z "Is <mint> safe?"
```

## Roadmap

- Push-based alerts for the graduation watcher (streaming instead of polling).
- Funder graph: check whether the other wallets a funder pays are also token developers.
- Dev filters across larger histories (e.g. "devs with 100+ launches and 50%+ graduated").
- More launchpads in `dev_launches`.
- A *separate*, opt-in trading plugin could use these facts as guardrails. This plugin stays read-only.

## License

MIT. Built by Maxed Wolf for the Hermes Agent Plugin Hackathon.
