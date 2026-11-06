"""Tool handlers. Rules (from the Hermes plugin guide):
  - signature: handler(args: dict, **kwargs) -> str
  - ALWAYS return a JSON string, success or error
  - NEVER raise
Facts only: if something can't be verified, it's null, never guessed.
"""

import json
from decimal import Decimal, InvalidOperation

from . import rpc

TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
_PROGRAM_NAMES = {TOKEN_PROGRAM_ID: "token", TOKEN_2022_PROGRAM_ID: "token-2022"}

# Token-2022 extensions that give someone a power over holders or transfers.
# The text says what the extension ALLOWS (a fact), not whether the token is "bad".
RISKY_EXTENSIONS = {
    "permanentDelegate": "A permanent delegate can transfer or burn tokens from any holder's account.",
    "transferHook": "Every transfer runs a custom program, which can block or alter transfers.",
    "transferFeeConfig": "Transfers can be charged a fee set by the fee authority.",
    "nonTransferable": "Tokens cannot be moved between wallets.",
    "defaultAccountState": "New token accounts start frozen until the freeze authority thaws them.",
    "mintCloseAuthority": "An authority can close the mint account.",
    "pausableConfig": "An authority can pause transfers, mints and burns.",
    "interestBearingConfig": "Displayed balances change over time at a rate set by an authority.",
    "scaledUiAmountConfig": "Displayed amounts are scaled by a multiplier an authority can change.",
    "confidentialTransferMint": "Balances and transfer amounts can be hidden, so they can't be checked publicly.",
}
# Extensions we recognise as informational only.
BENIGN_EXTENSIONS = {
    "metadataPointer", "tokenMetadata", "groupPointer", "tokenGroup",
    "groupMemberPointer", "tokenGroupMember", "confidentialTransferFeeConfig",
}
# For these, the power only exists if this field in the extension's state is set.
_ACTIVE_FIELD = {
    "permanentDelegate": "delegate",
    "transferHook": "programId",
    "mintCloseAuthority": "closeAuthority",
}

# ---------------------------------------------------------------- helpers

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def _b58decode(s):
    n = 0
    for ch in s:
        n = n * 58 + _B58_INDEX[ch]          # KeyError on an invalid character
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    leading_zeros = len(s) - len(s.lstrip("1"))  # each leading "1" is a zero byte
    return b"\x00" * leading_zeros + body


def is_valid_pubkey(s):
    """True if s is base58 that decodes to exactly 32 bytes (a Solana address)."""
    if not isinstance(s, str) or not 32 <= len(s) <= 44:
        return False
    try:
        return len(_b58decode(s)) == 32
    except KeyError:
        return False


def _ui_amount(raw, decimals):
    """'1000000000', 6 -> '1000'. Decimal keeps it exact (floats would round)."""
    try:
        d = Decimal(int(raw)).scaleb(-int(decimals))
    except (TypeError, ValueError, InvalidOperation):
        return None
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# Ed25519 curve check. A normal wallet address is a point ON the curve (it has a
# private key). A Program Derived Address (PDA) is deliberately OFF the curve, so
# no private key exists and only a program can move its tokens (pools, vaults, locks).
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def is_on_curve(pubkey_bytes):
    """True if these 32 bytes decode to a valid ed25519 point (i.e. a key-pair wallet)."""
    if len(pubkey_bytes) != 32:
        return False
    y = int.from_bytes(pubkey_bytes, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    y2 = y * y % _P
    x2 = (y2 - 1) * pow(_D * y2 + 1, _P - 2, _P) % _P   # x^2 = (y^2-1)/(d*y^2+1)
    if x2 == 0:
        return True
    return pow(x2, (_P - 1) // 2, _P) == 1               # Euler: is x^2 a square mod p?


def _pct(part_raw, total_raw):
    """Exact percentage, rounded to 4 decimal places. None if supply is 0/unknown."""
    try:
        total = Decimal(int(total_raw))
        if total == 0:
            return None
        return float(round(Decimal(int(part_raw)) * 100 / total, 4))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _source(method, slot=None):
    return {
        "rpc_method": method,
        "commitment": "finalized",
        "slot": slot,
        "rpc_host": rpc.endpoint_host(),
    }


def _fail(mint, kind, message, method="getAccountInfo", slot=None):
    return {
        "ok": False,
        "mint": mint,
        "error": {"kind": kind, "message": message},
        "source": _source(method, slot),
    }


def _to_json(obj):
    return json.dumps(obj)


def _authority(info, field):
    """Returns (value, is_set). Missing field -> (None, None): unknown, not 'revoked'."""
    if field not in info:
        return None, None
    value = info[field]
    return value, value is not None


# ---------------------------------------------------------------- token_authorities

def get_authorities(mint):
    """Plain-dict version, reused later by token_fact_sheet."""
    mint = mint.strip() if isinstance(mint, str) else ""
    if not is_valid_pubkey(mint):
        return _fail(mint or None, "invalid_mint", "Not a valid Solana address (base58, 32 bytes).")

    try:
        res = rpc.call("getAccountInfo", [mint, {"encoding": "jsonParsed", "commitment": "finalized"}])
    except rpc.RpcError as e:
        return _fail(mint, e.kind, str(e))

    if not isinstance(res, dict):
        return _fail(mint, "bad_response", "Unexpected getAccountInfo reply.")
    slot = (res.get("context") or {}).get("slot")
    value = res.get("value")
    if value is None:
        return _fail(mint, "account_not_found", "No finalized account exists at this address.", slot=slot)

    owner = value.get("owner")
    program = _PROGRAM_NAMES.get(owner)
    data = value.get("data")
    parsed = data.get("parsed") if isinstance(data, dict) else None
    acct_type = parsed.get("type") if isinstance(parsed, dict) else None
    if program is None or acct_type != "mint":
        return _fail(
            mint, "not_a_mint",
            f"Account exists but is not a token mint (owner program {owner}, type {acct_type}). "
            "If this is a wallet or pool address, use the token's mint address instead.",
            slot=slot,
        )

    info = parsed.get("info") or {}
    mint_auth, can_mint = _authority(info, "mintAuthority")
    freeze_auth, can_freeze = _authority(info, "freezeAuthority")
    decimals = info.get("decimals")
    supply_raw = info.get("supply")

    names, risky, unrecognized = [], [], []
    for ext in info.get("extensions") or []:
        if not isinstance(ext, dict):
            continue
        name, state = ext.get("extension"), ext.get("state")
        names.append(name)

        if name == "defaultAccountState":
            frozen = isinstance(state, dict) and state.get("accountState") == "frozen"
            if frozen:
                risky.append({"extension": name, "allows": RISKY_EXTENSIONS[name], "active": True, "state": state})
            continue

        if name in RISKY_EXTENSIONS:
            field = _ACTIVE_FIELD.get(name)
            if field is None:
                active = True
            elif not isinstance(state, dict) or field not in state:
                active = None                      # can't tell -> say so, don't guess
            else:
                active = state[field] is not None
            if active is not False:
                risky.append({"extension": name, "allows": RISKY_EXTENSIONS[name], "active": active, "state": state})
        elif name not in BENIGN_EXTENSIONS:
            unrecognized.append(name)

    return {
        "ok": True,
        "mint": mint,
        "token_program": program,
        "token_program_id": owner,
        "decimals": decimals,
        "supply_raw": supply_raw,
        "supply": _ui_amount(supply_raw, decimals),
        "is_initialized": info.get("isInitialized"),
        "mint_authority": mint_auth,
        "can_mint_more": can_mint,
        "freeze_authority": freeze_auth,
        "can_freeze_accounts": can_freeze,
        "extensions": names,
        "risky_extensions": risky,
        "unrecognized_extensions": unrecognized,
        "source": _source("getAccountInfo", slot),
    }


# ---------------------------------------------------------------- token_holders

_HOLDERS_NOTE = (
    "Based on the 20 largest token accounts, the most the RPC method returns. "
    "Wallet totals and concentration figures are therefore lower bounds."
)


def get_holders(mint, top=10):
    """Plain-dict version, reused later by token_fact_sheet."""
    try:
        top = max(1, min(20, int(top)))
    except (TypeError, ValueError):
        top = 10

    # Step 1: reuse token_authorities. It validates the address, proves it is a
    # mint, and gives supply + decimals. (Cached, so a fact sheet won't repeat it.)
    base = get_authorities(mint)
    if not base.get("ok"):
        return base
    mint, supply_raw, decimals = base["mint"], base["supply_raw"], base["decimals"]

    # Step 2: the 20 biggest TOKEN ACCOUNTS (not wallets yet).
    method = "getTokenLargestAccounts"
    try:
        res = rpc.call(method, [mint, {"commitment": "finalized"}])
    except rpc.RpcError as e:
        msg = str(e)
        if "too many accounts" in msg.lower():
            return _fail(
                mint, "too_many_holders",
                "This token has too many holder accounts for the RPC to rank (millions). "
                "Holder concentration is not available for very large tokens.",
                method=method,
            )
        if e.kind in ("rate_limited", "http_error", "rpc_error"):
            msg += (
                " Free public RPC endpoints usually block or heavily rate-limit "
                "getTokenLargestAccounts. Set the plugin's rpc_url setting to an RPC "
                "provider URL (many have free tiers) and try again."
            )
        return _fail(mint, e.kind, msg, method=method)
    if not isinstance(res, dict) or not isinstance(res.get("value"), list):
        return _fail(mint, "bad_response", "Unexpected getTokenLargestAccounts reply.", method=method)
    slot = (res.get("context") or {}).get("slot")
    accounts = [a for a in res["value"] if isinstance(a, dict) and a.get("address")]

    # Step 3: who OWNS each token account? One batched call for all of them.
    owners = {}
    if accounts:
        try:
            multi = rpc.call(
                "getMultipleAccounts",
                [[a["address"] for a in accounts], {"encoding": "jsonParsed", "commitment": "finalized"}],
            )
        except rpc.RpcError as e:
            return _fail(mint, e.kind, str(e), method="getMultipleAccounts", slot=slot)
        values = (multi or {}).get("value") if isinstance(multi, dict) else None
        for acct, val in zip(accounts, values or []):
            try:
                owners[acct["address"]] = val["data"]["parsed"]["info"]["owner"]
            except (TypeError, KeyError):
                pass                                # unknown owner -> reported, not guessed

    # Step 4: group token accounts by owner wallet and add up balances.
    wallets, unresolved = {}, []
    for a in accounts:
        try:
            amount = int(a.get("amount"))
        except (TypeError, ValueError):
            continue
        owner = owners.get(a["address"])
        if owner is None:
            unresolved.append({"token_account": a["address"], "amount": _ui_amount(amount, decimals),
                               "pct_of_supply": _pct(amount, supply_raw)})
            continue
        w = wallets.setdefault(owner, {"raw": 0, "token_accounts": []})
        w["raw"] += amount
        w["token_accounts"].append(a["address"])

    ranked = sorted(wallets.items(), key=lambda kv: kv[1]["raw"], reverse=True)

    def owner_type(addr):
        try:
            return "wallet" if is_on_curve(_b58decode(addr)) else "program_address"
        except KeyError:
            return None

    top_holders = [
        {
            "rank": i + 1,
            "owner": addr,
            "owner_type": owner_type(addr),
            "amount": _ui_amount(w["raw"], decimals),
            "pct_of_supply": _pct(w["raw"], supply_raw),
            "token_accounts": w["token_accounts"],
        }
        for i, (addr, w) in enumerate(ranked[:top])
    ]

    def top_n(n):
        if not ranked:
            return None
        return _pct(sum(w["raw"] for _, w in ranked[:n]), supply_raw)

    return {
        "ok": True,
        "mint": mint,
        "token_program": base["token_program"],
        "decimals": decimals,
        "supply": base["supply"],
        "token_accounts_scanned": len(accounts),
        "distinct_owners_found": len(wallets),
        "concentration_pct": {"top1": top_n(1), "top5": top_n(5), "top10": top_n(10)},
        "top_holders": top_holders,
        "unresolved_accounts": unresolved,
        "owner_type_meaning": {
            "wallet": "Normal key-pair address: whoever holds the private key controls it.",
            "program_address": "Program Derived Address: no private key; a program controls it (often a liquidity pool, vault, lock or bridge).",
        },
        "note": _HOLDERS_NOTE,
        "source": {
            "rpc_methods": ["getAccountInfo", "getTokenLargestAccounts", "getMultipleAccounts"],
            "commitment": "finalized",
            "slot": slot,
            "rpc_host": rpc.endpoint_host(),
        },
    }


def token_holders(args, **kwargs):
    try:
        args = args if isinstance(args, dict) else {}
        return _to_json(get_holders(args.get("mint"), args.get("top", 10)))
    except Exception as e:  # last-resort safety net: handlers must never raise
        return _to_json({
            "ok": False,
            "error": {"kind": "internal_error", "message": f"{type(e).__name__}: {e}"},
        })


def token_authorities(args, **kwargs):
    try:
        mint = args.get("mint") if isinstance(args, dict) else None
        return _to_json(get_authorities(mint))
    except Exception as e:  # last-resort safety net: handlers must never raise
        return _to_json({
            "ok": False,
            "error": {"kind": "internal_error", "message": f"{type(e).__name__}: {e}"},
        })
