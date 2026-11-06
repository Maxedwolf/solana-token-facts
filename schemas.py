"""Tool schemas: what the model reads to decide WHEN and HOW to call each tool."""

TOKEN_AUTHORITIES = {
    "name": "token_authorities",
    "description": (
        "Read-only. Look up verifiable on-chain facts about a Solana token MINT: "
        "whether more tokens can still be minted (mint authority), whether holder "
        "accounts can be frozen (freeze authority), total supply and decimals, "
        "whether it uses the classic Token program or Token-2022, and any Token-2022 "
        "extensions that give someone extra powers (permanent delegate, transfer hook, "
        "transfer fees, pausable, and others). Use when the user asks who controls a "
        "token, whether it can be rugged by minting or freezing, or what its supply is. "
        "The input must be the token's mint address, not a wallet or pool address. "
        "Returns JSON. Anything that cannot be verified is null. "
        "Gives no price, liquidity or trading advice."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mint": {
                "type": "string",
                "description": (
                    "Base58 Solana mint address (32-44 characters), e.g. "
                    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v (USDC)."
                ),
            },
        },
        "required": ["mint"],
    },
}

TOKEN_ORIGIN = {
    "name": "token_origin",
    "description": (
        "Read-only. Find where a Solana token came from, using on-chain history: when it "
        "was created (UTC time, slot and age in days), the wallet that created it (the fee "
        "payer of its first transaction), the creation transaction, which launchpad was used "
        "(pump.fun, Raydium LaunchLab, Meteora, Moonshot, boop.fun) and, for pump.fun tokens, "
        "whether the token has graduated from its bonding curve. Includes Solscan links. Use "
        "when the user asks who made a token, when it launched, how old it is, which "
        "launchpad it came from, or for the developer's wallet. Input must be the token's mint "
        "address. Very busy tokens may have too much history to reach the first transaction; "
        "then creation fields are null and the reply says so. Returns JSON. Gives no price or "
        "trading advice."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mint": {
                "type": "string",
                "description": "Base58 Solana mint address (32-44 characters).",
            },
        },
        "required": ["mint"],
    },
}

DEV_LAUNCHES = {
    "name": "dev_launches",
    "description": (
        "Read-only. Check a Solana token developer's track record from on-chain history. "
        "Give either the dev's wallet, or a token mint (the tool then finds the wallet that "
        "launched it). Returns the dev's most recent token launches (how many is a user "
        "setting, default 5) and, for each: when it launched, which launchpad, whether it "
        "graduated (pump.fun), how much of the supply the dev bought at launch, whether the "
        "dev later sold their whole position and how many minutes after launch. Also returns "
        "a plain-language pattern summary and Solscan links. Use when the user asks about a "
        "dev's history, past launches, whether a dev has rugged before, or for a dev report. "
        "Facts only: never turn the results into a buy/sell recommendation. Requires an RPC "
        "that supports getTransactionsForAddress (Helius)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "wallet": {
                "type": "string",
                "description": "The developer's wallet address (base58). Use this OR mint.",
            },
            "mint": {
                "type": "string",
                "description": "A token mint address; the tool looks up the wallet that launched it.",
            },
            "max_launches": {
                "type": "integer",
                "description": "Optional: report at most this many recent launches (capped by the user's setting).",
                "minimum": 1,
            },
        },
    },
}

TOKEN_HOLDERS = {
    "name": "token_holders",
    "description": (
        "Read-only. Look up who holds the most of a Solana token, from on-chain data: "
        "the largest holder wallets, how much of the total supply each holds, and how "
        "concentrated the supply is (top 1, top 5, top 10 holders' combined percentage). "
        "Each holder is marked 'wallet' (a normal key-pair address) or 'program_address' "
        "(controlled by a program, often a liquidity pool, vault or lock). Use when the "
        "user asks who the biggest holders or whales are, whether supply is concentrated, "
        "or whether a few wallets could dump the token. Input must be the token's mint "
        "address. Only the 20 largest token accounts are visible, so totals are lower "
        "bounds. Returns JSON; unknown values are null. Gives no price or trading advice."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mint": {
                "type": "string",
                "description": "Base58 Solana mint address (32-44 characters).",
            },
            "top": {
                "type": "integer",
                "description": "How many top holder wallets to list, 1-20. Default 10.",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["mint"],
    },
}
