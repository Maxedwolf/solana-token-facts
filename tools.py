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


def token_authorities(args, **kwargs):
    try:
        mint = args.get("mint") if isinstance(args, dict) else None
        return _to_json(get_authorities(mint))
    except Exception as e:  # last-resort safety net: handlers must never raise
        return _to_json({
            "ok": False,
            "error": {"kind": "internal_error", "message": f"{type(e).__name__}: {e}"},
        })
