"""Tool handlers. Rules (from the Hermes plugin guide):
  - signature: handler(args: dict, **kwargs) -> str
  - ALWAYS return a JSON string, success or error
  - NEVER raise
Facts only: if something can't be verified, it's null, never guessed.
"""

import base64
import hashlib
import json
import time
from datetime import datetime, timezone
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

# Returned with every successful result, so the agent keeps to facts even without the skill.
HOW_TO_PRESENT = (
    "State these as on-chain facts with their numbers and links. Do not call the token or the "
    "developer safe, risky, high-risk, a scam or a rug, and do not use loaded words like 'dumped'. "
    "Give no buy, sell or timing advice. End with: these are on-chain facts, not trading advice."
)

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


def _b58encode(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58_ALPHABET[r] + out
    leading_zeros = len(b) - len(b.lstrip(b"\x00"))
    return "1" * leading_zeros + out


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


def find_program_address(seeds, program_id):
    """Solana's PDA rule: hash(seeds + bump + program + marker), first result OFF the curve.
    Returns (address_str, bump). Same answer as solana-py / web3.js findProgramAddress."""
    prog = _b58decode(program_id)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join(seeds) + bytes([bump]) + prog + b"ProgramDerivedAddress").digest()
        if not is_on_curve(h):
            return _b58encode(h), bump
    return None, None


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


# ---------------------------------------------------------------- token metadata

# Metaplex Token Metadata: where most Solana tokens (incl. pump.fun) keep name, symbol and image URI.
METAPLEX_METADATA_PROGRAM_ID = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
# Signs every pump.fun mint and metadata account it creates (pump.fun's own authority).
PUMP_FUN_MINT_AUTHORITY = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"
_KNOWN_UPDATE_AUTHORITIES = {PUMP_FUN_MINT_AUTHORITY: "pump.fun"}


def _borsh_str(raw, pos):
    """Borsh string: u32 little-endian length, then UTF-8 bytes (Metaplex pads with NULs)."""
    n = int.from_bytes(raw[pos:pos + 4], "little")
    if n > 1000 or pos + 4 + n > len(raw):
        raise ValueError("bad string length")
    s = raw[pos + 4:pos + 4 + n].decode("utf-8", "replace").rstrip("\x00").strip()
    return s, pos + 4 + n


def parse_metaplex_metadata(raw):
    """Decode the start of a Metaplex metadata account.
    Layout: key u8 | update_authority 32 | mint 32 | name | symbol | uri | seller_fee u16 |
    creators Option<Vec<{address 32, verified u8, share u8}>> | primary_sale_happened u8 | is_mutable u8.
    Returns a dict, or None if the bytes don't fit that layout."""
    try:
        if len(raw) < 65 + 12 or raw[0] != 4:          # key 4 = MetadataV1
            return None
        update_authority = _b58encode(raw[1:33])
        name, pos = _borsh_str(raw, 65)
        symbol, pos = _borsh_str(raw, pos)
        uri, pos = _borsh_str(raw, pos)
        pos += 2                                         # seller_fee_basis_points
        creators = []
        if raw[pos] == 1:
            count = int.from_bytes(raw[pos + 1:pos + 5], "little")
            pos += 5
            for _ in range(min(count, 5)):
                creators.append({"address": _b58encode(raw[pos:pos + 32]), "verified": bool(raw[pos + 32])})
                pos += 34
            pos += 34 * max(0, count - 5)
        else:
            pos += 1
        is_mutable = bool(raw[pos + 1])                  # skip primary_sale_happened
        return {"update_authority": update_authority, "name": name, "symbol": symbol, "uri": uri,
                "creators": creators, "is_mutable": is_mutable}
    except (IndexError, ValueError):
        return None


def get_metadata(mint, mint_info=None):
    """Who can still change the token's name, symbol and image? Never raises; None if unknown.
    Token-2022 tokens can keep metadata inside the mint (tokenMetadata extension); everything
    else uses a Metaplex metadata account at PDA ["metadata", program, mint]."""
    for ext in (mint_info or {}).get("extensions") or []:
        if isinstance(ext, dict) and ext.get("extension") == "tokenMetadata":
            st = ext.get("state") or {}
            ua = st.get("updateAuthority")
            return {"standard": "token-2022 tokenMetadata", "account": mint, "name": st.get("name"),
                    "symbol": st.get("symbol"), "uri": st.get("uri"), "update_authority": ua,
                    "update_authority_label": _KNOWN_UPDATE_AUTHORITIES.get(ua),
                    "is_mutable": ua is not None, "can_change": ua is not None}
    try:
        pda, _ = find_program_address([b"metadata", _b58decode(METAPLEX_METADATA_PROGRAM_ID), _b58decode(mint)],
                                      METAPLEX_METADATA_PROGRAM_ID)
        res = rpc.call("getAccountInfo", [pda, {"encoding": "base64", "commitment": "finalized"}])
        value = (res or {}).get("value") if isinstance(res, dict) else None
        if not value or value.get("owner") != METAPLEX_METADATA_PROGRAM_ID:
            return {"standard": None, "account": pda, "name": None, "symbol": None, "uri": None,
                    "update_authority": None, "is_mutable": None, "can_change": None,
                    "note": "No Metaplex metadata account found for this mint."}
        md = parse_metaplex_metadata(base64.b64decode(value["data"][0]))
    except (rpc.RpcError, KeyError, IndexError, TypeError, ValueError):
        return None
    if md is None:
        return {"standard": "metaplex", "account": pda, "is_mutable": None, "can_change": None,
                "note": "Metadata account could not be decoded."}
    ua = md["update_authority"]
    return {"standard": "metaplex", "account": pda, "name": md["name"], "symbol": md["symbol"],
            "uri": md["uri"], "update_authority": ua, "update_authority_label": _KNOWN_UPDATE_AUTHORITIES.get(ua),
            "is_mutable": md["is_mutable"],
            # Metaplex: changes need is_mutable AND an update authority that isn't the all-zero key.
            "can_change": md["is_mutable"] and ua != "11111111111111111111111111111111"}


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

    metadata = get_metadata(mint, info)

    return {
        "ok": True,
        "mint": mint,
        "name": (metadata or {}).get("name"),
        "symbol": (metadata or {}).get("symbol"),
        "can_change_metadata": (metadata or {}).get("can_change"),
        "metadata": metadata,
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
        "how_to_present": HOW_TO_PRESENT,
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

    # Name the pump.fun bonding curve if it is a holder (it holds the not-yet-sold supply).
    labels = {}
    try:
        pump = get_pump_curve(mint)
        if pump:
            labels[pump["bonding_curve"]] = "pump.fun bonding curve (unsold supply, not a person)"
    except rpc.RpcError:
        pass

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
            "label": labels.get(addr),
            "amount": _ui_amount(w["raw"], decimals),
            "pct_of_supply": _pct(w["raw"], supply_raw),
            "token_accounts": w["token_accounts"],
        }
        for i, (addr, w) in enumerate(ranked[:top])
    ]

    def top_n(n, rows=None):
        rows = ranked if rows is None else rows
        if not rows:
            return None
        return _pct(sum(w["raw"] for _, w in rows[:n]), supply_raw)

    others = [(a, w) for a, w in ranked if a not in labels]

    return {
        "ok": True,
        "mint": mint,
        "token_program": base["token_program"],
        "decimals": decimals,
        "supply": base["supply"],
        "token_accounts_scanned": len(accounts),
        "distinct_owners_found": len(wallets),
        "concentration_pct": {"top1": top_n(1), "top5": top_n(5), "top10": top_n(10)},
        "concentration_excluding_labeled_pct": {"top1": top_n(1, others), "top5": top_n(5, others),
                                                "top10": top_n(10, others)},
        "top_holders": top_holders,
        "unresolved_accounts": unresolved,
        "owner_type_meaning": {
            "wallet": "Normal key-pair address: whoever holds the private key controls it.",
            "program_address": "Program Derived Address: no private key; a program controls it (often a liquidity pool, vault, lock or bridge).",
        },
        "note": _HOLDERS_NOTE,
        "how_to_present": HOW_TO_PRESENT,
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


# ---------------------------------------------------------------- token_origin

PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
# Launchpad programs we can name. Anything else is still listed by raw program id.
LAUNCHPADS = {
    PUMP_FUN_PROGRAM_ID: "pump.fun",
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": "Raydium LaunchLab",
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN": "Meteora Dynamic Bonding Curve",
    "MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qcqUQTrG": "Moonshot",
    "boop8hVGQGqehUK2iVEMEnMrL5RbjywRzHKBmBE7ry4": "boop.fun",
}
_SIG_PAGE = 1000          # max signatures per getSignaturesForAddress call
DEFAULT_ORIGIN_PAGES = 10  # up to 10,000 transactions scanned; overridable in settings
_origin_max_pages = DEFAULT_ORIGIN_PAGES


def set_origin_max_pages(n):
    global _origin_max_pages
    try:
        _origin_max_pages = max(1, min(100, int(n)))
    except (TypeError, ValueError):
        _origin_max_pages = DEFAULT_ORIGIN_PAGES


def _iso(ts):
    if not isinstance(ts, (int, float)):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _links(mint=None, wallet=None, tx=None):
    out = {}
    if mint:
        out["mint"] = f"https://solscan.io/token/{mint}"
    if wallet:
        out["creator_wallet"] = f"https://solscan.io/account/{wallet}"
    if tx:
        out["creation_tx"] = f"https://solscan.io/tx/{tx}"
    return out


def get_pump_curve(mint):
    """pump.fun bonding curve facts for a mint, or None if it never used pump.fun.
    Layout: 8-byte discriminator, 5 x u64 reserves/supply, complete (bool) at byte 48,
    creator (32-byte pubkey) at bytes 49-80. Raises rpc.RpcError."""
    curve, _ = find_program_address([b"bonding-curve", _b58decode(mint)], PUMP_FUN_PROGRAM_ID)
    res = rpc.call("getAccountInfo", [curve, {"encoding": "base64", "commitment": "finalized"}])
    value = (res or {}).get("value") if isinstance(res, dict) else None
    if not value or value.get("owner") != PUMP_FUN_PROGRAM_ID:
        return None
    try:
        raw = base64.b64decode(value["data"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return {"bonding_curve": curve, "graduated": None, "creator": None}
    graduated = bool(raw[48]) if len(raw) > 48 else None
    total_supply = int.from_bytes(raw[40:48], "little") if len(raw) >= 48 else None
    creator = None
    if len(raw) >= 81 and any(raw[49:81]):
        creator = _b58encode(raw[49:81])
    return {"bonding_curve": curve, "graduated": graduated, "creator_fee_recipient": creator,
            "total_supply_raw": total_supply}


def _first_transaction(address, max_pages):
    """Find an address's oldest transaction.
    Fast path: Helius getTransactionsForAddress with sortOrder "asc" (1 call, any history size).
    Fallback (other RPCs): walk getSignaturesForAddress backwards, max_pages x 1,000.
    Returns (oldest_sig_info or None, pages_used, total_seen or None, reached_start). Raises rpc.RpcError."""
    try:
        r = rpc.call("getTransactionsForAddress",
                     [address, {"transactionDetails": "signatures", "sortOrder": "asc", "limit": 1}])
        data = (r or {}).get("data") if isinstance(r, dict) else None
        if isinstance(data, list):
            return (data[0] if data else None), 1, None, True
    except rpc.RpcError as e:
        if e.kind in ("network_error", "rate_limited"):
            raise
        # method not supported by this RPC provider -> use the portable fallback below
    before, oldest, seen = None, None, 0
    for page in range(1, max_pages + 1):
        opts = {"limit": _SIG_PAGE, "commitment": "finalized"}
        if before:
            opts["before"] = before
        batch = rpc.call("getSignaturesForAddress", [address, opts]) or []
        if not isinstance(batch, list):
            raise rpc.RpcError("bad_response", "Unexpected getSignaturesForAddress reply.")
        if batch:
            oldest = batch[-1]
            before = oldest.get("signature")
            seen += len(batch)
        if len(batch) < _SIG_PAGE:
            return oldest, page, seen, True
    return oldest, max_pages, seen, False


def get_transaction(sig):
    """getTransaction that accepts every transaction format (legacy, v0 and the newer v1).
    Asks for v1 support first; if an older RPC rejects that parameter, retries with v0."""
    opts = {"encoding": "jsonParsed", "commitment": "finalized"}
    try:
        return rpc.call("getTransaction", [sig, dict(opts, maxSupportedTransactionVersion=1)])
    except rpc.RpcError as e:
        if e.kind != "rpc_error":
            raise
        return rpc.call("getTransaction", [sig, dict(opts, maxSupportedTransactionVersion=0)])


def _programs_in(tx):
    """Every program id invoked in a jsonParsed transaction (outer + inner instructions)."""
    progs = []
    msg = ((tx or {}).get("transaction") or {}).get("message") or {}
    groups = [msg.get("instructions") or []]
    for inner in ((tx or {}).get("meta") or {}).get("innerInstructions") or []:
        groups.append(inner.get("instructions") or [])
    for group in groups:
        for ix in group:
            pid = ix.get("programId") if isinstance(ix, dict) else None
            if pid and pid not in progs:
                progs.append(pid)
    return progs


def _creates_mint(tx, mint):
    """True if this transaction contains initializeMint/initializeMint2 for this mint."""
    msg = ((tx or {}).get("transaction") or {}).get("message") or {}
    groups = [msg.get("instructions") or []]
    for inner in ((tx or {}).get("meta") or {}).get("innerInstructions") or []:
        groups.append(inner.get("instructions") or [])
    for group in groups:
        for ix in group:
            parsed = ix.get("parsed") if isinstance(ix, dict) else None
            if (isinstance(parsed, dict) and str(parsed.get("type", "")).startswith("initializeMint")
                    and (parsed.get("info") or {}).get("mint") == mint):
                return True
    return False


def get_origin(mint):
    """Plain-dict version, reused later by dev_launches and the /token command."""
    base = get_authorities(mint)
    if not base.get("ok"):
        return base
    mint = base["mint"]
    methods = ["getAccountInfo", "getSignaturesForAddress", "getTransaction"]

    try:
        pump = get_pump_curve(mint)
    except rpc.RpcError:
        pump = None                                   # optional extra; never fatal

    try:
        oldest, pages, seen, reached = _first_transaction(mint, _origin_max_pages)
    except rpc.RpcError as e:
        return _fail(mint, e.kind, str(e), method="getSignaturesForAddress")

    result = {
        "ok": True,
        "mint": mint,
        "history_scanned": {"transactions": seen, "pages": pages, "reached_first_transaction": reached},
        "created_at": None,
        "created_unix": None,
        "age_days": None,
        "created_slot": None,
        "creation_signature": None,
        "creator_wallet": None,
        "creator_basis": None,
        "fee_payer": None,
        "creation_tx_confirmed": None,
        "launchpad": None,
        "programs_invoked": [],
        "pump_fun": pump,
        "links": _links(mint=mint),
        "how_to_present": HOW_TO_PRESENT,
        "source": {"rpc_methods": methods, "commitment": "finalized", "rpc_host": rpc.endpoint_host()},
    }

    if not reached:
        result["note"] = (
            f"This token has more than {seen} transactions, so its first transaction was not reached "
            "(scan limit is a setting: origin_max_pages; a Helius RPC URL finds it in one call). "
            "Creation time and creator are unknown."
        )
        if pump:
            # A pump.fun bonding curve exists for this mint, so it launched on pump.fun.
            result["launchpad"] = {"name": "pump.fun", "program_id": PUMP_FUN_PROGRAM_ID}
        return result
    if oldest is None:
        result["note"] = "No transactions found for this mint."
        return result

    sig = oldest.get("signature")
    try:
        tx = get_transaction(sig)
    except rpc.RpcError as e:
        return _fail(mint, e.kind, str(e), method="getTransaction")
    if not isinstance(tx, dict):
        return _fail(mint, "bad_response", "Creation transaction could not be loaded.", method="getTransaction")

    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    fee_payer = None
    if keys:
        k0 = keys[0]
        fee_payer = k0.get("pubkey") if isinstance(k0, dict) else k0
    programs = _programs_in(tx)
    pad = next((p for p in programs if p in LAUNCHPADS), None)
    block_time = tx.get("blockTime", oldest.get("blockTime"))

    result.update({
        "created_at": _iso(block_time),
        "created_unix": block_time if isinstance(block_time, (int, float)) else None,
        "age_days": round((time.time() - block_time) / 86400, 2) if isinstance(block_time, (int, float)) else None,
        "created_slot": tx.get("slot", oldest.get("slot")),
        "creation_signature": sig,
        "creator_wallet": fee_payer,
        "creator_basis": "fee payer (first signer) of the token's first transaction",
        "creation_tx_confirmed": _creates_mint(tx, mint),
        "launchpad": {"name": LAUNCHPADS[pad], "program_id": pad} if pad else None,
        "programs_invoked": programs,
        "links": _links(mint=mint, wallet=fee_payer, tx=sig),
    })
    result["fee_payer"] = fee_payer
    signers = [k.get("pubkey") for k in keys if isinstance(k, dict) and k.get("signer")]
    result["signers"] = signers
    # pump.fun stores a separate 'creator' that receives creator fees. It can be a wallet that
    # never signs anything, so it is reported separately and NOT treated as the launcher.
    if pump and pump.get("creator_fee_recipient") and pump["creator_fee_recipient"] != fee_payer:
        result["pump_fun"]["note"] = ("The creator-fee recipient differs from the wallet that signed the launch. "
                                      "creator_wallet is the signer.")
    return result


def token_origin(args, **kwargs):
    try:
        args = args if isinstance(args, dict) else {}
        return _to_json(get_origin(args.get("mint")))
    except Exception as e:  # last-resort safety net: handlers must never raise
        return _to_json({
            "ok": False,
            "error": {"kind": "internal_error", "message": f"{type(e).__name__}: {e}"},
        })


# ---------------------------------------------------------------- recent_graduations

# Every pump.fun graduation (migration of liquidity to PumpSwap) is signed by this account,
# so its transaction history is a list of graduations.
PUMP_MIGRATION_ACCOUNT = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
_WSOL = "So11111111111111111111111111111111111111112"


def _is_migration(tx):
    logs = (tx.get("meta") or {}).get("logMessages") or []
    return PUMP_FUN_PROGRAM_ID in _programs_in(tx) and any("Instruction: Migrate" in l for l in logs)


def get_recent_graduations(limit=10):
    """Most recent pump.fun tokens that graduated to PumpSwap (newest first)."""
    try:
        limit = max(1, min(25, int(limit)))
    except (TypeError, ValueError):
        limit = 10
    out, token, scanned = [], None, 0
    for _ in range(3):                                   # at most 3 x 50 transactions
        cfg = {"transactionDetails": "full", "encoding": "jsonParsed", "sortOrder": "desc", "limit": 50,
               "maxSupportedTransactionVersion": 1, "filters": {"status": "succeeded"}}
        if token:
            cfg["paginationToken"] = token
        try:
            r = rpc.call("getTransactionsForAddress", [PUMP_MIGRATION_ACCOUNT, cfg], use_cache=False)
        except rpc.RpcError as e:
            msg = str(e)
            if e.kind == "rpc_error":
                msg += " recent_graduations needs an RPC that supports getTransactionsForAddress (e.g. a Helius URL)."
            return {"ok": False, "error": {"kind": e.kind, "message": msg}}
        data = (r or {}).get("data") or [] if isinstance(r, dict) else []
        scanned += len(data)
        for tx in data:
            if not _is_migration(tx):
                continue
            mints = []
            for b in (tx.get("meta") or {}).get("postTokenBalances") or []:
                m = b.get("mint")
                if m and m != _WSOL and m not in mints:
                    mints.append(m)
            for m in mints:
                if any(g["mint"] == m for g in out):
                    continue
                # Keep only real graduates: a pump.fun bonding curve that is complete.
                # (Filters out the pool's LP token and anything else in the same transaction.)
                try:
                    curve = get_pump_curve(m)
                except rpc.RpcError:
                    curve = None
                if not curve or curve.get("graduated") is not True:
                    continue
                sig = ((tx.get("transaction") or {}).get("signatures") or [None])[0]
                out.append({"mint": m, "graduated_at": _iso(tx.get("blockTime")), "signature": sig,
                            "links": {"mint": f"https://solscan.io/token/{m}", "tx": f"https://solscan.io/tx/{sig}"}})
            if len(out) >= limit:
                break
        token = (r or {}).get("paginationToken") if isinstance(r, dict) else None
        if len(out) >= limit or not token:
            break
    return {
        "ok": True,
        "graduations": out[:limit],
        "count": len(out[:limit]),
        "scanned_transactions": scanned,
        "next_step": "Use dev_launches(mint=...) or save_dev_report(mint=...) on any of these to check the dev's full history.",
        "source": {"rpc_methods": ["getTransactionsForAddress"], "account": PUMP_MIGRATION_ACCOUNT,
                   "commitment": "finalized", "rpc_host": rpc.endpoint_host()},
    }


def recent_graduations(args, **kwargs):
    try:
        args = args if isinstance(args, dict) else {}
        return _to_json(get_recent_graduations(args.get("limit", 10)))
    except Exception as e:  # last-resort safety net: handlers must never raise
        return _to_json({"ok": False, "error": {"kind": "internal_error", "message": f"{type(e).__name__}: {e}"}})


# ---------------------------------------------------------------- dev_launches

DEFAULT_DEV_MAX_LAUNCHES = 5      # how many past launches to report (user setting)
DEFAULT_DEV_MAX_PAGES = 5         # pages of 100 full transactions to scan (user setting)
_DEV_PAGE = 100
_dev_max_launches = DEFAULT_DEV_MAX_LAUNCHES
_dev_max_pages = DEFAULT_DEV_MAX_PAGES


def set_dev_limits(max_launches=None, max_pages=None):
    global _dev_max_launches, _dev_max_pages
    try:
        _dev_max_launches = max(1, min(1000, int(max_launches)))
    except (TypeError, ValueError):
        _dev_max_launches = DEFAULT_DEV_MAX_LAUNCHES
    try:
        _dev_max_pages = max(1, min(500, int(max_pages)))
    except (TypeError, ValueError):
        _dev_max_pages = DEFAULT_DEV_MAX_PAGES


def _fee_payer(tx):
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    if not keys:
        return None
    return keys[0].get("pubkey") if isinstance(keys[0], dict) else keys[0]


def _minted_in(tx):
    """Mints initialised in this transaction (initializeMint / initializeMint2)."""
    found = []
    msg = (tx.get("transaction") or {}).get("message") or {}
    groups = [msg.get("instructions") or []]
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        groups.append(inner.get("instructions") or [])
    for group in groups:
        for ix in group:
            p = ix.get("parsed") if isinstance(ix, dict) else None
            if isinstance(p, dict) and str(p.get("type", "")).startswith("initializeMint"):
                m = (p.get("info") or {}).get("mint")
                if m and m not in found:
                    found.append(m)
    return found


def _dev_balance(tx, side, owner, mint):
    """Raw token amount `owner` held of `mint` before ('pre') or after ('post') this tx; None if absent."""
    total, seen = 0, False
    for b in (tx.get("meta") or {}).get(f"{side}TokenBalances") or []:
        if b.get("owner") == owner and b.get("mint") == mint:
            try:
                total += int((b.get("uiTokenAmount") or {}).get("amount"))
                seen = True
            except (TypeError, ValueError):
                pass
    return total if seen else None


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else round((xs[mid - 1] + xs[mid]) / 2, 2)


def get_dev_launches(wallet=None, mint=None, max_launches=None):
    """Plain-dict version, reused by the dev report and /token command."""
    want = _dev_max_launches
    if max_launches is not None:
        try:
            want = max(1, min(_dev_max_launches, int(max_launches)))
        except (TypeError, ValueError):
            pass

    # 1. Who is the dev? Either given directly, or the signer that created `mint`.
    found_via = None
    if not wallet and mint:
        origin = get_origin(mint)
        if not origin.get("ok"):
            return origin
        wallet = origin.get("creator_wallet")
        found_via = {"mint": origin["mint"], "created_at": origin.get("created_at")}
        if not wallet:
            return _fail(origin["mint"], "creator_unknown", "Could not determine who created this token.",
                         method="getTransactionsForAddress")
    wallet = wallet.strip() if isinstance(wallet, str) else ""
    if not is_valid_pubkey(wallet):
        return _fail(None, "invalid_wallet", "Not a valid Solana wallet address (base58, 32 bytes).",
                     method="getTransactionsForAddress")

    # 2. Scan the dev's history, newest first, 100 full transactions per page.
    txs, token, pages, launches = [], None, 0, []
    for pages in range(1, _dev_max_pages + 1):
        cfg = {"transactionDetails": "full", "encoding": "jsonParsed", "sortOrder": "desc",
               "limit": _DEV_PAGE, "maxSupportedTransactionVersion": 1, "filters": {"status": "succeeded"}}
        if token:
            cfg["paginationToken"] = token
        try:
            r = rpc.call("getTransactionsForAddress", [wallet, cfg])
        except rpc.RpcError as e:
            msg = str(e)
            if e.kind == "rpc_error":
                msg += " dev_launches needs an RPC that supports getTransactionsForAddress (e.g. a Helius URL in rpc_url)."
            return _fail(None, e.kind, msg, method="getTransactionsForAddress")
        data = (r or {}).get("data") or [] if isinstance(r, dict) else []
        txs.extend(data)
        for tx in data:
            if _fee_payer(tx) == wallet:
                for m in _minted_in(tx):
                    launches.append({"mint": m, "time": tx.get("blockTime"),
                                     "signature": ((tx.get("transaction") or {}).get("signatures") or [None])[0],
                                     "programs": _programs_in(tx)})
        token = (r or {}).get("paginationToken") if isinstance(r, dict) else None
        if len(launches) >= want or not token:
            break
    reached_end = not token
    launches = launches[:want]

    # 3. For each launch: graduated? how much did the dev buy, and when (if ever) did they sell out?
    ordered = sorted(txs, key=lambda t: (t.get("slot") or 0, t.get("transactionIndex") or 0))
    out = []
    for L in launches:
        m, t0 = L["mint"], L["time"]
        pad = next((p for p in L["programs"] if p in LAUNCHPADS), None)
        try:
            pump = get_pump_curve(m) if pad == PUMP_FUN_PROGRAM_ID else None
        except rpc.RpcError:
            pump = None
        supply = (pump or {}).get("total_supply_raw")
        first_hold, peak, sold_at, last = None, 0, None, None
        for tx in ordered:
            if (tx.get("blockTime") or 0) < (t0 or 0):
                continue
            pre, post = _dev_balance(tx, "pre", wallet, m), _dev_balance(tx, "post", wallet, m)
            if post is None and pre is None:
                continue
            post = post or 0
            if first_hold is None and post > 0:
                first_hold = post
            peak = max(peak, post)
            if (pre or 0) > 0 and post == 0 and sold_at is None:
                sold_at = tx.get("blockTime")
            last = post
        out.append({
            "mint": m,
            "created_at": _iso(t0),
            "launchpad": LAUNCHPADS.get(pad) if pad else None,
            "graduated": (pump or {}).get("graduated"),
            "dev_initial_buy_pct": _pct(first_hold, supply) if first_hold and supply else None,
            "dev_sold_out": (sold_at is not None) if first_hold else None,
            "minutes_to_sell_out": round((sold_at - t0) / 60, 1) if sold_at and t0 else None,
            "dev_last_known_balance_pct": _pct(last, supply) if last is not None and supply else None,
            "links": {"mint": f"https://solscan.io/token/{m}"},
        })

    # 4. Plain-language facts, no advice.
    n = len(out)
    grads = sum(1 for x in out if x["graduated"] is True)
    sold = [x for x in out if x["dev_sold_out"] is True]
    mins = [x["minutes_to_sell_out"] for x in sold if x["minutes_to_sell_out"] is not None]
    oldest = min((t.get("blockTime") for t in txs if t.get("blockTime")), default=None)
    if n == 0:
        pattern = (f"No token launches found in this wallet's last {len(txs)} transactions"
                   + (" (its whole history)." if reached_end else ". Older launches may exist beyond the scan limit."))
    else:
        pattern = f"{n} launch(es) checked: {grads} graduated, {n - grads} did not."
        if sold:
            pattern += f" The dev sold their whole position in {len(sold)} of {n}"
            pattern += f", median {_median(mins)} min after launch." if mins else "."
    return {
        "ok": True,
        "dev_wallet": wallet,
        "found_via": found_via,
        "summary": {
            "launches_checked": n,
            "graduated": grads,
            "not_graduated": n - grads,
            "dev_sold_out": len(sold),
            "median_minutes_to_sell_out": _median(mins),
            "pattern": pattern,
        },
        "launches": out,
        "history_scanned": {"transactions": len(txs), "pages": pages, "reached_wallet_start": reached_end,
                            "oldest_scanned": _iso(oldest)},
        "limits": {"max_launches": want, "max_pages": _dev_max_pages,
                   "note": "Raise dev_max_launches / dev_max_pages in settings for deeper history (costs more RPC credits)."},
        "links": {"dev_wallet": f"https://solscan.io/account/{wallet}"},
        "disclaimer": "Facts from on-chain data only, not trading advice. You can feed these facts into your own analysis tools or strategies.",
        "how_to_present": HOW_TO_PRESENT,
        "source": {"rpc_methods": ["getTransactionsForAddress", "getAccountInfo"], "commitment": "finalized",
                   "rpc_host": rpc.endpoint_host()},
    }


def dev_launches(args, **kwargs):
    try:
        args = args if isinstance(args, dict) else {}
        return _to_json(get_dev_launches(args.get("wallet"), args.get("mint"), args.get("max_launches")))
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


# ---------------------------------------------------------------- shared: balance and SOL-transfer readers

_SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"


def _token_deltas(tx, mint):
    """{owner: post - pre} raw amounts of `mint` for every owner whose balance changed in this tx."""
    bal = {}
    meta = tx.get("meta") or {}
    for side, sign in (("pre", -1), ("post", 1)):
        for b in meta.get(f"{side}TokenBalances") or []:
            if b.get("mint") != mint or not b.get("owner"):
                continue
            try:
                amt = int((b.get("uiTokenAmount") or {}).get("amount"))
            except (TypeError, ValueError):
                continue
            bal[b["owner"]] = bal.get(b["owner"], 0) + sign * amt
    return {o: d for o, d in bal.items() if d != 0}


def _sol_transfers(tx):
    """Every System Program SOL movement in a jsonParsed tx: [(source, destination, lamports)]."""
    out = []
    msg = (tx.get("transaction") or {}).get("message") or {}
    groups = [msg.get("instructions") or []]
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        groups.append(inner.get("instructions") or [])
    for group in groups:
        for ix in group:
            if not isinstance(ix, dict) or ix.get("programId") != _SYSTEM_PROGRAM_ID:
                continue
            p = ix.get("parsed")
            if not isinstance(p, dict):
                continue
            info, kind = p.get("info") or {}, p.get("type")
            if kind in ("transfer", "transferWithSeed"):
                src, dst = info.get("source"), info.get("destination")
            elif kind in ("createAccount", "createAccountWithSeed"):
                src, dst = info.get("source"), info.get("newAccount")
            else:
                continue
            try:
                lamports = int(info.get("lamports"))
            except (TypeError, ValueError):
                continue
            if src and dst and lamports > 0:
                out.append((src, dst, lamports))
    return out


def _sig(tx):
    return ((tx.get("transaction") or {}).get("signatures") or [None])[0]


def _sol(lamports):
    return float(round(Decimal(lamports) / Decimal(10**9), 4))


def _is_wallet(address):
    try:
        return is_on_curve(_b58decode(address))
    except (KeyError, ValueError):
        return False


def _gtfa(address, sort="asc", limit=100, token=None):
    """One page of Helius getTransactionsForAddress with full jsonParsed transactions. Raises rpc.RpcError."""
    cfg = {"transactionDetails": "full", "encoding": "jsonParsed", "sortOrder": sort, "limit": limit,
           "maxSupportedTransactionVersion": 1, "filters": {"status": "succeeded"}}
    if token:
        cfg["paginationToken"] = token
    r = rpc.call("getTransactionsForAddress", [address, cfg])
    if not isinstance(r, dict):
        return [], None
    return (r.get("data") or []), r.get("paginationToken")


def _needs_helius(e, tool):
    msg = str(e)
    if e.kind == "rpc_error":
        msg += f" {tool} needs an RPC that supports getTransactionsForAddress (e.g. a Helius URL)."
    return msg


def _token_balance_now(owner, mint):
    """Current raw balance of `mint` across all of owner's token accounts, or None if unknown."""
    try:
        r = rpc.call("getTokenAccountsByOwner", [owner, {"mint": mint},
                                                 {"encoding": "jsonParsed", "commitment": "finalized"}])
    except rpc.RpcError:
        return None
    total = 0
    accounts = (r.get("value") or []) if isinstance(r, dict) else []
    for acc in accounts:
        try:
            total += int(acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
        except (KeyError, TypeError, ValueError):
            pass
    return total


# ---------------------------------------------------------------- launch_buyers

_MAX_BUYER_LOOKUPS = 20


def get_launch_buyers(mint, slots_after=0):
    """Wallets that bought in the token's creation block (slot), optionally a few blocks after."""
    try:
        slots_after = max(0, min(5, int(slots_after or 0)))
    except (TypeError, ValueError):
        slots_after = 0
    origin = get_origin(mint)
    if not origin.get("ok"):
        return origin
    mint = origin["mint"]
    slot0, creator = origin.get("created_slot"), origin.get("creator_wallet")
    if slot0 is None:
        return _fail(mint, "creation_unknown", origin.get("note") or "Creation block could not be found.",
                     method="getTransactionsForAddress")
    last_slot = slot0 + slots_after
    supply = ((origin.get("pump_fun") or {}).get("total_supply_raw")
              or int(get_authorities(mint).get("supply_raw") or 0) or None)

    buyers, token, scanned, complete = {}, None, 0, False
    try:
        for _ in range(3):                                # at most 300 of the token's first transactions
            data, token = _gtfa(mint, "asc", 100, token)
            for tx in data:
                if (tx.get("slot") or 0) > last_slot:
                    complete = True
                    break
                scanned += 1
                for owner, delta in _token_deltas(tx, mint).items():
                    if delta <= 0 or not _is_wallet(owner):   # program addresses = curve/pool, not buyers
                        continue
                    b = buyers.setdefault(owner, {"wallet": owner, "is_creator": owner == creator,
                                                  "bought_raw": 0, "slot": tx.get("slot"), "first_tx": _sig(tx)})
                    b["bought_raw"] += delta
            if complete or not token:
                complete = True
                break
    except rpc.RpcError as e:
        return _fail(mint, e.kind, _needs_helius(e, "launch_buyers"), method="getTransactionsForAddress")

    rows = sorted(buyers.values(), key=lambda b: -b["bought_raw"])
    for i, b in enumerate(rows):
        b["bought_pct"] = _pct(b["bought_raw"], supply) if supply else None
        b["slot_offset"] = (b["slot"] - slot0) if b.get("slot") is not None else None
        if i < _MAX_BUYER_LOOKUPS:
            now = _token_balance_now(b["wallet"], mint)
            b["holds_now_pct"] = _pct(now, supply) if now is not None and supply else None
        else:
            b["holds_now_pct"] = None
        b["links"] = {"wallet": f"https://solscan.io/account/{b['wallet']}",
                      "tx": f"https://solscan.io/tx/{b['first_tx']}"}
        b["bought_raw"] = str(b["bought_raw"])

    others = [b for b in rows if not b["is_creator"]]
    dev = next((b for b in rows if b["is_creator"]), None)
    others_pct = round(sum(b["bought_pct"] or 0 for b in others), 4) if supply else None
    still = [b for b in others if (b.get("holds_now_pct") or 0) > 0]
    still_pct = round(sum(b["holds_now_pct"] for b in still), 4) if supply else None
    where = "the creation block" if slots_after == 0 else f"the creation block and the {slots_after} block(s) after it"
    pattern = f"{len(others)} wallet(s) other than the creator bought in {where}"
    pattern += f", {round(others_pct, 2)}% of supply together." if others and others_pct is not None else "."
    if dev and dev.get("bought_pct") is not None:
        pattern += f" The creator bought {round(dev['bought_pct'], 2)}%."
    if others:
        pattern += f" {len(still)} of them still hold tokens now"
        pattern += f" ({round(still_pct, 2)}% of supply)." if still and still_pct is not None else "."
    return {
        "ok": True,
        "mint": mint,
        "creation_slot": slot0,
        "window_slots": [slot0, last_slot],
        "created_at": origin.get("created_at"),
        "creator_wallet": creator,
        "summary": {"other_buyers": len(others), "other_buyers_pct": others_pct,
                    "creator_bought_pct": (dev or {}).get("bought_pct"),
                    "still_holding": len(still), "still_holding_pct": still_pct, "pattern": pattern},
        "buyers": rows,
        "transactions_scanned": scanned,
        "complete": complete,
        "notes": [
            "A buyer is any key-pair wallet whose balance of this token went up in a transaction in the window. "
            "Program addresses (bonding curve, pools) are excluded.",
            "Buying in the same block as creation is only possible if the transaction was sent at the same moment "
            "as the launch; that is a fact about timing, not proof of who controls the wallets.",
            f"holds_now_pct is checked for the {_MAX_BUYER_LOOKUPS} largest buyers.",
        ],
        "how_to_present": HOW_TO_PRESENT,
        "source": {"rpc_methods": ["getTransactionsForAddress", "getTokenAccountsByOwner", "getAccountInfo"],
                   "commitment": "finalized", "rpc_host": rpc.endpoint_host()},
    }


def launch_buyers(args, **kwargs):
    try:
        args = args if isinstance(args, dict) else {}
        return _to_json(get_launch_buyers(args.get("mint"), args.get("slots_after", 0)))
    except Exception as e:  # last-resort safety net: handlers must never raise
        return _to_json({"ok": False, "error": {"kind": "internal_error", "message": f"{type(e).__name__}: {e}"}})


# ---------------------------------------------------------------- dev_funding

_DUST_LAMPORTS = 10_000_000         # < 0.01 SOL: spam, airdrops, rebates and address poisoning, not funding


def _span(minutes):
    """12.3 -> '12.3 min', 300 -> '5.0 hours', 5000 -> '3.5 days'."""
    if minutes is None:
        return None
    if minutes < 120:
        return f"{round(minutes, 1)} min"
    if minutes < 2880:
        return f"{round(minutes / 60, 1)} hours"
    return f"{round(minutes / 1440, 1)} days"


def _incoming(txs, wallet):
    """Non-dust SOL transfers into `wallet`, in the order of `txs`."""
    out = []
    for tx in txs:
        for src, dst, lamports in _sol_transfers(tx):
            if dst == wallet and src != wallet and lamports >= _DUST_LAMPORTS:
                out.append({"from": src, "sol": _sol(lamports), "time": tx.get("blockTime"), "tx": _sig(tx)})
    return out


def _funding_fact(f, launch_time):
    mins = round((launch_time - f["time"]) / 60, 1) if launch_time and f.get("time") else None
    return {"from": f["from"], "sol": f["sol"], "at": _iso(f["time"]), "tx": f["tx"],
            "from_is_wallet": _is_wallet(f["from"]), "minutes_before_launch": mins,
            "before_launch": _span(mins),
            "links": {"from": f"https://solscan.io/account/{f['from']}", "tx": f"https://solscan.io/tx/{f['tx']}"}}


def _fanout(funder):
    """How many different wallets `funder` sent SOL to in its last 100 transactions."""
    try:
        f_txs, _ = _gtfa(funder, "desc", 100)
    except rpc.RpcError:
        return None
    recipients, sent = set(), 0
    for tx in f_txs:
        for src, dst, lamports in _sol_transfers(tx):
            if src == funder and dst != funder and lamports >= _DUST_LAMPORTS:
                recipients.add(dst)
                sent += 1
    times = [t.get("blockTime") for t in f_txs if t.get("blockTime")]
    return {
        "address": funder,
        "is_wallet": _is_wallet(funder),
        "recent_transactions_scanned": len(f_txs),
        "scanned_period_hours": round((max(times) - min(times)) / 3600, 2) if len(times) > 1 else None,
        "scanned_from": _iso(min(times)) if times else None,
        "sol_transfers_out": sent,
        "distinct_wallets_funded": len(recipients),
        "note": ("Counts cover only the funder's most recent transactions. A funder that sends SOL to very "
                 "many wallets per hour is often an exchange or payment service; that is context, not a label."),
    }


def get_dev_funding(wallet=None, mint=None):
    """Who funded the dev wallet: its first-ever SOL, the last SOL before the launch, and the funder's fan-out."""
    launch_time = launch_slot = found_via = None
    if not wallet and mint:
        origin = get_origin(mint)
        if not origin.get("ok"):
            return origin
        wallet = origin.get("creator_wallet")
        launch_time, launch_slot = origin.get("created_unix"), origin.get("created_slot")
        found_via = {"mint": origin["mint"], "created_at": origin.get("created_at")}
        if not wallet:
            return _fail(origin["mint"], "creator_unknown", "Could not determine who created this token.",
                         method="getTransactionsForAddress")
    wallet = wallet.strip() if isinstance(wallet, str) else ""
    if not is_valid_pubkey(wallet):
        return _fail(None, "invalid_wallet", "Not a valid Solana wallet address (base58, 32 bytes).",
                     method="getTransactionsForAddress")

    try:
        first_txs, _ = _gtfa(wallet, "asc", 50)                       # the wallet's oldest transactions
        before = []
        if launch_slot is not None:                                   # newest transactions before the launch
            cfg = {"transactionDetails": "full", "encoding": "jsonParsed", "sortOrder": "desc", "limit": 50,
                   "maxSupportedTransactionVersion": 1,
                   "filters": {"status": "succeeded", "slot": {"lt": launch_slot}}}
            r = rpc.call("getTransactionsForAddress", [wallet, cfg])
            before = (r.get("data") or []) if isinstance(r, dict) else []
    except rpc.RpcError as e:
        return _fail(None, e.kind, _needs_helius(e, "dev_funding"), method="getTransactionsForAddress")

    first_in = _incoming(first_txs, wallet)
    last_in = _incoming(before, wallet)                               # newest first
    result = {
        "ok": True,
        "dev_wallet": wallet,
        "found_via": found_via,
        "wallet_first_activity": _iso(first_txs[0].get("blockTime")) if first_txs else None,
        "first_funding": _funding_fact(first_in[0], launch_time) if first_in else None,
        "last_funding_before_launch": _funding_fact(last_in[0], launch_time) if last_in else None,
        "early_funders": [],
        "funder": None,
        "links": {"dev_wallet": f"https://solscan.io/account/{wallet}"},
        "how_to_present": HOW_TO_PRESENT,
        "source": {"rpc_methods": ["getTransactionsForAddress"], "commitment": "finalized",
                   "rpc_host": rpc.endpoint_host()},
    }
    totals = {}
    for i in first_in:
        totals[i["from"]] = round(totals.get(i["from"], 0) + i["sol"], 4)
    result["early_funders"] = [{"from": k, "sol_total": v} for k, v in list(totals.items())[:5]]

    key = result["last_funding_before_launch"] or result["first_funding"]
    if not key:
        result["summary"] = {"pattern": f"No incoming SOL transfer (0.01 SOL or more) found in the scanned history "
                                        f"of this wallet ({len(first_txs)} oldest transactions checked)."}
        return result
    result["funder"] = _fanout(key["from"])

    def who(a):
        return f"{a[:4]}...{a[-4:]}"
    parts = []
    lf, ff = result["last_funding_before_launch"], result["first_funding"]
    if lf:
        parts.append(f"Before this launch, the dev wallet last received SOL from {who(lf['from'])} "
                     f"({lf['sol']} SOL, {lf['before_launch']} before launch).")
    if ff and (not lf or ff["tx"] != lf["tx"]):
        parts.append(f"Its first SOL ever came from {who(ff['from'])} ({ff['sol']} SOL"
                     + (f", {ff['before_launch']} before launch)." if ff["before_launch"] else f", on {ff['at']})."))
    fu = result["funder"]
    if fu and fu["recent_transactions_scanned"]:
        parts.append(f"In its last {fu['recent_transactions_scanned']} transactions"
                     + (f" (about {_span(fu['scanned_period_hours'] * 60)})" if fu["scanned_period_hours"] is not None else "")
                     + f", {who(fu['address'])} sent SOL to {fu['distinct_wallets_funded']} different wallets.")
    result["summary"] = {"pattern": " ".join(parts)}
    return result


def dev_funding(args, **kwargs):
    try:
        args = args if isinstance(args, dict) else {}
        return _to_json(get_dev_funding(args.get("wallet"), args.get("mint")))
    except Exception as e:  # last-resort safety net: handlers must never raise
        return _to_json({"ok": False, "error": {"kind": "internal_error", "message": f"{type(e).__name__}: {e}"}})
