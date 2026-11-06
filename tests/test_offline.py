"""Offline tests: no network. The RPC layer is replaced by fakes.

Run from the repo root:  python -m unittest discover -s tests
"""

import base64
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = "solana_token_facts_test"  # folder name has dashes, so load it under a Python-safe name

spec = importlib.util.spec_from_file_location(PKG, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[PKG] = plugin
spec.loader.exec_module(plugin)
rpc = sys.modules[PKG + ".rpc"]
tools = sys.modules[PKG + ".tools"]
reports = sys.modules[PKG + ".reports"]

PUMP = tools.PUMP_FUN_PROGRAM_ID
MINT = "D8aSv6iLSZJdZ5ntLdZbK4YwkzZaGzJRMSGNzoF2pump"
CURVE = "9jLzz6QE5J5pnoGnVo6GXe9XAyka3ToiJqBzfwrGJqDU"      # verified with solders + live chain
WALLET = "FAe4sisG95oZ42w7buUn5qEE4TAnfTTFPiguZUHmhiF"     # ed25519 key from seed 0..31 (on curve)
DEV = WALLET
OTHER = "4mJvyuhukL3p6NeTuHC1HdYbv9Q9TURB1hgE9DUdEF8d"
REAL_CALL = rpc.call


def curve_bytes(graduated, supply=10**15, creator=b"\0" * 32):
    return b"\0" * 8 + struct.pack("<5Q", 0, 0, 0, 0, supply) + bytes([graduated]) + creator


def mint_account(owner=tools.TOKEN_PROGRAM_ID, info=None, kind="mint"):
    info = info if info is not None else {"decimals": 6, "supply": "1000000000000", "isInitialized": True,
                                          "mintAuthority": None, "freezeAuthority": None}
    return {"context": {"slot": 7}, "value": {"owner": owner, "data": {"parsed": {"type": kind, "info": info}}}}


class FakeRpc:
    """Routes rpc.call(method, params) to small handlers; records calls."""

    def __init__(self, **handlers):
        self.handlers, self.calls = handlers, []

    def __call__(self, method, params, use_cache=True):
        self.calls.append(method)
        h = self.handlers.get(method)
        if h is None:
            raise rpc.RpcError("rpc_error", f"RPC error: method {method} not faked")
        return h(params) if callable(h) else h


class Base(unittest.TestCase):
    def tearDown(self):
        rpc.call = REAL_CALL
        rpc._cache.clear()


class TestAddresses(Base):
    def test_base58_round_trip(self):
        for addr in [MINT, CURVE, WALLET, "11111111111111111111111111111111"]:
            self.assertEqual(tools._b58encode(tools._b58decode(addr)), addr)

    def test_valid_pubkey(self):
        self.assertTrue(tools.is_valid_pubkey(MINT))
        for bad in ["", "hello", "0" * 44, None, 123]:
            self.assertFalse(tools.is_valid_pubkey(bad))

    def test_pda_matches_solana(self):
        addr, bump = tools.find_program_address([b"bonding-curve", tools._b58decode(MINT)], PUMP)
        self.assertEqual((addr, bump), (CURVE, 255))

    def test_curve_check(self):
        self.assertTrue(tools.is_on_curve(tools._b58decode(WALLET)))
        self.assertFalse(tools.is_on_curve(tools._b58decode(CURVE)))


class TestAuthorities(Base):
    def test_revoked_vs_unknown(self):
        rpc.call = FakeRpc(getAccountInfo=mint_account(info={"decimals": 6, "supply": "1000500000",
                                                             "mintAuthority": None}))
        r = tools.get_authorities(MINT)
        self.assertTrue(r["ok"])
        self.assertIs(r["can_mint_more"], False)        # present and null -> revoked
        self.assertIsNone(r["can_freeze_accounts"])     # missing -> unknown, not "revoked"
        self.assertEqual(r["supply"], "1000.5")         # exact decimal maths
        self.assertIn("how_to_present", r)

    def test_risky_extensions(self):
        info = {"decimals": 9, "supply": "5", "mintAuthority": None, "freezeAuthority": None, "extensions": [
            {"extension": "permanentDelegate", "state": {"delegate": OTHER}},
            {"extension": "transferHook", "state": {"programId": None}},    # no hook program -> not active
            {"extension": "metadataPointer", "state": {}},
            {"extension": "somethingNew", "state": {}}]}
        rpc.call = FakeRpc(getAccountInfo=mint_account(tools.TOKEN_2022_PROGRAM_ID, info))
        r = tools.get_authorities(MINT)
        self.assertEqual([x["extension"] for x in r["risky_extensions"]], ["permanentDelegate"])
        self.assertEqual(r["unrecognized_extensions"], ["somethingNew"])

    def test_wallet_is_not_a_mint(self):
        rpc.call = FakeRpc(getAccountInfo={"context": {"slot": 1},
                                           "value": {"owner": "11111111111111111111111111111111", "data": ["", "base64"]}})
        self.assertEqual(tools.get_authorities(WALLET)["error"]["kind"], "not_a_mint")

    def test_rate_limit_becomes_json(self):
        def boom(params):
            raise rpc.RpcError("rate_limited", "RPC returned HTTP 429", 429)
        rpc.call = FakeRpc(getAccountInfo=boom)
        self.assertEqual(json.loads(tools.token_authorities({"mint": MINT}))["error"]["kind"], "rate_limited")


class TestHolders(Base):
    def test_groups_by_owner_and_labels_curve(self):
        accts = [WALLET[:-4] + x for x in ("aaaa", "bbbb", "cccc")]  # placeholders, only used as keys

        def multi(params):
            owners = {params[0][0]: CURVE, params[0][1]: OTHER, params[0][2]: OTHER}
            return {"value": [{"data": {"parsed": {"info": {"owner": owners[a]}}}} for a in params[0]]}

        def info(params):
            if params[1].get("encoding") == "base64":       # bonding curve lookup
                return {"value": {"owner": PUMP, "data": [base64.b64encode(curve_bytes(0)).decode(), "base64"]}}
            return mint_account(info={"decimals": 0, "supply": "100", "mintAuthority": None, "freezeAuthority": None})

        rpc.call = FakeRpc(getAccountInfo=info, getMultipleAccounts=multi,
                           getTokenLargestAccounts={"context": {"slot": 3}, "value": [
                               {"address": accts[0], "amount": "80"}, {"address": accts[1], "amount": "15"},
                               {"address": accts[2], "amount": "5"}]})
        r = tools.get_holders(MINT, 5)
        self.assertEqual(r["distinct_owners_found"], 2)
        self.assertEqual(r["concentration_pct"]["top1"], 80.0)
        self.assertEqual(r["concentration_excluding_labeled_pct"]["top1"], 20.0)
        self.assertEqual(r["top_holders"][0]["owner_type"], "program_address")
        self.assertIn("bonding curve", r["top_holders"][0]["label"])
        self.assertEqual(r["top_holders"][1]["token_accounts"], accts[1:])

    def test_huge_token(self):
        def refuse(params):
            raise rpc.RpcError("rpc_error", "RPC error: Too many accounts requested (10000000 pubkeys)")
        rpc.call = FakeRpc(getAccountInfo=mint_account(), getTokenLargestAccounts=refuse)
        self.assertEqual(tools.get_holders(MINT)["error"]["kind"], "too_many_holders")


def tx(t, slot, payer, minted=None, bal=None, logs=(), post_mints=()):
    inner = [{"instructions": [{"programId": tools.TOKEN_PROGRAM_ID,
                                "parsed": {"type": "initializeMint2", "info": {"mint": minted}}}]}] if minted else []
    pre, post = [], [{"mint": m, "owner": OTHER, "uiTokenAmount": {"amount": "1"}} for m in post_mints]
    if bal:
        m, a, b = bal
        if a is not None:
            pre.append({"owner": DEV, "mint": m, "uiTokenAmount": {"amount": str(a)}})
        if b is not None:
            post.append({"owner": DEV, "mint": m, "uiTokenAmount": {"amount": str(b)}})
    return {"blockTime": t, "slot": slot, "transactionIndex": 0,
            "transaction": {"signatures": [f"sig{slot}"], "message": {
                "accountKeys": [{"pubkey": payer, "signer": True}], "instructions": [{"programId": PUMP}]}},
            "meta": {"innerInstructions": inner, "preTokenBalances": pre, "postTokenBalances": post,
                     "logMessages": list(logs)}}


class TestDevLaunches(Base):
    def setUp(self):
        tools.set_dev_limits(3, 2)

    def tearDown(self):
        super().tearDown()
        tools.set_dev_limits(None, None)

    def test_pattern_from_history(self):
        T, m0, m1, m2 = 1_700_000_000, MINT, CURVE, OTHER   # any valid addresses work as mints here
        hist = [tx(T, 1, DEV, m0, (m0, None, 5 * 10**13)), tx(T + 120, 2, DEV, None, (m0, 5 * 10**13, 0)),
                tx(T + 1000, 3, DEV, m1, (m1, None, 3 * 10**13)),
                tx(T + 2000, 4, WALLET[:-1] + "G", m2)]       # someone else paid -> not this dev's launch
        newest_first = list(reversed(hist))
        grad_curve = tools.find_program_address([b"bonding-curve", tools._b58decode(m0)], PUMP)[0]

        def curve(params):
            raw = curve_bytes(1 if params[0] == grad_curve else 0)
            return {"value": {"owner": PUMP, "data": [base64.b64encode(raw).decode(), "base64"]}}

        rpc.call = FakeRpc(getTransactionsForAddress={"data": newest_first, "paginationToken": None},
                           getAccountInfo=curve)
        r = tools.get_dev_launches(DEV)
        s = r["summary"]
        self.assertEqual((s["launches_checked"], s["graduated"], s["dev_sold_out"]), (2, 1, 1))
        first = next(x for x in r["launches"] if x["mint"] == m0)
        self.assertEqual((first["dev_initial_buy_pct"], first["minutes_to_sell_out"]), (5.0, 2.0))
        self.assertIs(next(x for x in r["launches"] if x["mint"] == m1)["dev_sold_out"], False)
        self.assertIn("not trading advice", r["disclaimer"])

    def test_bad_wallet(self):
        self.assertEqual(tools.get_dev_launches("nope")["error"]["kind"], "invalid_wallet")


class TestGraduations(Base):
    def test_lp_token_filtered_out(self):
        lp = WALLET  # stands in for the pool's LP mint (no bonding curve)
        real = MINT

        def curve(params):
            if params[0] == CURVE:
                return {"value": {"owner": PUMP, "data": [base64.b64encode(curve_bytes(1)).decode(), "base64"]}}
            return {"value": None}

        migration = tx(1_700_000_000, 9, OTHER, logs=["Program log: Instruction: Migrate"], post_mints=(lp, real))
        trade = tx(1_700_000_001, 10, OTHER, post_mints=(OTHER,))
        rpc.call = FakeRpc(getTransactionsForAddress={"data": [trade, migration], "paginationToken": None},
                           getAccountInfo=curve)
        r = tools.get_recent_graduations(5)
        self.assertEqual([g["mint"] for g in r["graduations"]], [real])


class TestReportsAndHandlers(Base):
    def test_report_written(self):
        sample = {"ok": True, "dev_wallet": DEV, "found_via": None,
                  "summary": {"launches_checked": 0, "graduated": 0, "not_graduated": 0, "dev_sold_out": 0,
                              "median_minutes_to_sell_out": None, "pattern": "No token launches found."},
                  "launches": [], "history_scanned": {"transactions": 3, "pages": 1, "reached_wallet_start": True,
                                                      "oldest_scanned": None},
                  "limits": {"max_launches": 5, "max_pages": 5, "note": "n"},
                  "links": {"dev_wallet": "https://solscan.io/account/" + DEV},
                  "source": {"rpc_host": "example"}}
        orig = tools.get_dev_launches
        tools.get_dev_launches = lambda *a, **k: sample
        try:
            with tempfile.TemporaryDirectory() as d:
                reports.set_reports_dir(d)
                r = reports.save_dev_report(DEV)
                text = Path(r["saved_to"]).read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\ntype: dev-report"))
                self.assertIn("not trading advice", text)
        finally:
            tools.get_dev_launches = orig
            reports.set_reports_dir("")

    def test_handlers_never_raise(self):
        for h in [tools.token_authorities, tools.token_holders, tools.token_origin, tools.dev_launches,
                  reports.tool_save_dev_report]:
            out = json.loads(h("not a dict"))
            self.assertFalse(out["ok"])
        self.assertTrue(reports.command_token("").startswith("Usage"))


if __name__ == "__main__":
    unittest.main()
