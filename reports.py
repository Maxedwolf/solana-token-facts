"""Dev reports (Markdown notes, Obsidian-friendly) and the /token fact sheet.

The ONLY thing this plugin writes is a local Markdown file, and only when the user asks
for a report (save_dev_report). Nothing is ever written on-chain.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import tools

_reports_dir = ""   # set from the plugin's reports_dir setting; "" = default location


def set_reports_dir(path):
    global _reports_dir
    _reports_dir = (path or "").strip() if isinstance(path, str) else ""


def _hermes_home():
    try:
        from hermes_constants import get_hermes_home   # available when running inside Hermes
        return Path(get_hermes_home())
    except Exception:
        env = os.environ.get("HERMES_HOME")
        if env:
            return Path(env)
        local = os.environ.get("LOCALAPPDATA")
        return Path(local, "hermes") if local else Path.home() / ".hermes"


def reports_dir():
    if _reports_dir:
        return Path(os.path.expandvars(os.path.expanduser(_reports_dir)))
    return _hermes_home() / "plugin-data" / "solana-token-facts" / "dev-reports"


def _short(addr):
    return f"{addr[:4]}...{addr[-4:]}" if isinstance(addr, str) and len(addr) > 10 else str(addr)


def _yes_no(v):
    return "yes" if v is True else "no" if v is False else "unknown"


def _num(v, suffix=""):
    return "unknown" if v is None else f"{v}{suffix}"


def render_dev_report(dev, funding=None, buyers=None):
    """Markdown note for one dev_launches result (+ optional dev_funding / launch_buyers results)."""
    s = dev["summary"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    w = dev["dev_wallet"]
    lines = [
        "---",
        "type: dev-report",
        f"dev_wallet: {w}",
        f"generated: {now}",
        f"launches_checked: {s['launches_checked']}",
        f"graduated: {s['graduated']}",
        f"dev_sold_out: {s['dev_sold_out']}",
        f"median_minutes_to_sell_out: {s['median_minutes_to_sell_out'] if s['median_minutes_to_sell_out'] is not None else 'null'}",
        "tags: [solana, dev-report]",
        "---",
        "",
        f"# Dev report: `{_short(w)}`",
        "",
        f"**Pattern:** {s['pattern']}",
        "",
        f"- Dev wallet: [{w}]({dev['links']['dev_wallet']})",
    ]
    fv = dev.get("found_via")
    if fv:
        lines.append(f"- Found via token: [{fv['mint']}](https://solscan.io/token/{fv['mint']}) (created {fv.get('created_at') or 'unknown'})")
    lines += [
        "",
        "## Launches",
        "",
        "| Launched (UTC) | Token | Launchpad | Graduated | Dev bought at launch | Dev sold out | Minutes to sell out |",
        "|---|---|---|---|---|---|---|",
    ]
    for L in dev["launches"]:
        lines.append(
            f"| {L['created_at'] or 'unknown'} | [{_short(L['mint'])}]({L['links']['mint']}) | "
            f"{L['launchpad'] or 'unknown'} | {_yes_no(L['graduated'])} | {_num(L['dev_initial_buy_pct'], '%')} | "
            f"{_yes_no(L['dev_sold_out'])} | {_num(L['minutes_to_sell_out'])} |"
        )
    if not dev["launches"]:
        lines.append("| – | no launches found in the scanned history | | | | | |")
    if funding and funding.get("ok"):
        ff, fu = funding.get("first_funding"), funding.get("funder")
        lines += ["", "## Funding", "", f"**{(funding.get('summary') or {}).get('pattern', '')}**", ""]
        lf = funding.get("last_funding_before_launch")
        if lf:
            lines.append(f"- Last SOL in before launch: {lf['sol']} SOL from [{lf['from']}]({lf['links']['from']}) at "
                         f"{lf['at'] or 'unknown'}, {lf.get('before_launch') or 'unknown time'} before launch ([tx]({lf['links']['tx']}))")
        if ff:
            lines.append(f"- First SOL ever: {ff['sol']} SOL from [{ff['from']}]({ff['links']['from']}) at {ff['at'] or 'unknown'} "
                         f"([tx]({ff['links']['tx']}))")
        if fu:
            lines.append(f"- Funder's last {fu['recent_transactions_scanned']} transactions"
                         f" ({_num(fu['scanned_period_hours'], ' h')}): SOL sent to {fu['distinct_wallets_funded']} different wallets")
        if funding.get("wallet_first_activity"):
            lines.append(f"- Dev wallet first active: {funding['wallet_first_activity']}")
    if buyers and buyers.get("ok"):
        bs = buyers["summary"]
        lines += ["", f"## Launch-block buyers ({_short(buyers['mint'])})", "", f"**{bs['pattern']}**", "",
                  "| Wallet | Creator | Bought % | Holds now % |", "|---|---|---|---|"]
        for b in buyers["buyers"][:10]:
            lines.append(f"| [{_short(b['wallet'])}]({b['links']['wallet']}) | {_yes_no(b['is_creator'])} | "
                         f"{_num(b['bought_pct'], '%')} | {_num(b['holds_now_pct'], '%')} |")
    h = dev["history_scanned"]
    lines += [
        "",
        "## How this was checked",
        "",
        f"- Scanned the dev's last {h['transactions']} transactions (back to {h['oldest_scanned'] or 'unknown'}); "
        f"{'that is the whole wallet history' if h['reached_wallet_start'] else 'older history was not scanned'}.",
        f"- Limits: {dev['limits']['max_launches']} launches, {dev['limits']['max_pages']} pages. {dev['limits']['note']}",
        f"- Source: Solana RPC ({dev['source']['rpc_host']}), finalized data. 'Sold out' = the dev's balance of that token went to zero.",
        "",
        "---",
        "*Facts from on-chain data only, not trading advice. You can feed this data into your own "
        "analysis tools or sniping system to build your own strategy.*",
        "",
    ]
    return "\n".join(lines)


def save_dev_report(wallet=None, mint=None):
    dev = tools.get_dev_launches(wallet, mint)
    if not dev.get("ok"):
        return dev
    # Extra facts for the note; each is optional and never stops the report from saving.
    try:
        funding = tools.get_dev_funding(mint=mint) if mint else tools.get_dev_funding(dev["dev_wallet"])
    except Exception:
        funding = None
    try:
        buyers = tools.get_launch_buyers(mint) if mint else None
    except Exception:
        buyers = None
    folder = reports_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9]", "", dev["dev_wallet"])
        path = folder / f"dev-{safe}.md"
        path.write_text(render_dev_report(dev, funding, buyers), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": {"kind": "write_failed",
                "message": f"Could not write the report to {folder}: {e}. Check the reports_dir setting."}}
    return {"ok": True, "saved_to": str(path), "dev_wallet": dev["dev_wallet"],
            "summary": dev["summary"],
            "funding_pattern": ((funding or {}).get("summary") or {}).get("pattern"),
            "launch_buyers_pattern": ((buyers or {}).get("summary") or {}).get("pattern"),
            "note": "Report saved as a Markdown note (opens in Obsidian or any editor). Re-running updates it."}


def tool_save_dev_report(args, **kwargs):
    try:
        args = args if isinstance(args, dict) else {}
        return json.dumps(save_dev_report(args.get("wallet"), args.get("mint")))
    except Exception as e:  # handlers must never raise
        return json.dumps({"ok": False, "error": {"kind": "internal_error", "message": f"{type(e).__name__}: {e}"}})


def fact_sheet(mint):
    """Plain-text fact sheet for /token <mint>: all four tools in one view."""
    a = tools.get_authorities(mint)
    if not a.get("ok"):
        return f"Could not read {mint!r}: {a['error']['message']}"
    m = a["mint"]
    out = [f"Token facts: {m}", f"https://solscan.io/token/{m}", ""]
    out.append("POWERS")
    out.append(f"  Program: {a['token_program']}   Supply: {a['supply']}   Decimals: {a['decimals']}")
    out.append(f"  Can mint more: {_yes_no(a['can_mint_more'])}" + (f" (authority {a['mint_authority']})" if a["can_mint_more"] else ""))
    out.append(f"  Can freeze accounts: {_yes_no(a['can_freeze_accounts'])}" + (f" (authority {a['freeze_authority']})" if a["can_freeze_accounts"] else ""))
    for r in a["risky_extensions"]:
        out.append(f"  Extension {r['extension']}: {r['allows']}")
    md = a.get("metadata") or {}
    if md:
        who = md.get("update_authority_label") or md.get("update_authority")
        out.append(f"  Name / symbol: {md.get('name') or 'unknown'} / {md.get('symbol') or 'unknown'}")
        out.append(f"  Can change name, symbol or image: {_yes_no(md.get('can_change'))}"
                   + (f" (update authority {who})" if md.get("can_change") and who else ""))

    o = tools.get_origin(m)
    out += ["", "ORIGIN"]
    if o.get("ok"):
        out.append(f"  Created: {o['created_at'] or 'unknown'}" + (f" ({o['age_days']} days ago)" if o.get("age_days") is not None else ""))
        out.append(f"  Launchpad: {(o['launchpad'] or {}).get('name', 'none detected')}")
        if o.get("pump_fun"):
            out.append(f"  pump.fun graduated: {_yes_no(o['pump_fun'].get('graduated'))}")
        out.append(f"  Creator wallet: {o['creator_wallet'] or 'unknown'}")
    else:
        out.append(f"  unavailable: {o['error']['message']}")

    h = tools.get_holders(m, 5)
    out += ["", "HOLDERS"]
    if h.get("ok"):
        c = h["concentration_pct"]
        out.append(f"  Top 1 / 5 / 10 hold: {c['top1']}% / {c['top5']}% / {c['top10']}% of supply")
        ex = h.get("concentration_excluding_labeled_pct")
        if ex and ex != c:
            out.append(f"  Excluding the bonding curve: {ex['top1']}% / {ex['top5']}% / {ex['top10']}%")
        for t in h["top_holders"][:5]:
            label = t["label"] or t["owner_type"]
            out.append(f"  #{t['rank']} {_short(t['owner'])}  {t['pct_of_supply']}%  ({label})")
    else:
        out.append(f"  unavailable: {h['error']['message']}")

    if o.get("ok") and o.get("created_slot") is not None:
        b = tools.get_launch_buyers(m)
        out += ["", "LAUNCH-BLOCK BUYERS"]
        out.append(f"  {b['summary']['pattern']}" if b.get("ok") else f"  unavailable: {b['error']['message']}")

    if o.get("ok") and o.get("creator_wallet"):
        d = tools.get_dev_launches(o["creator_wallet"])
        out += ["", "DEV HISTORY"]
        out.append(f"  {d['summary']['pattern']}" if d.get("ok") else f"  unavailable: {d['error']['message']}")
        f = tools.get_dev_funding(mint=m)
        out.append(f"  {f['summary']['pattern']}" if f.get("ok") else f"  Funding unavailable: {f['error']['message']}")

    out += ["", "Facts from on-chain data only, not trading advice.",
            "Say 'save a dev report' to keep the dev's history as a note."]
    return "\n".join(out)


def command_token(raw_args=""):
    mint = (raw_args or "").strip().split()[0] if (raw_args or "").strip() else ""
    if not mint:
        return "Usage: /token <mint address>"
    try:
        return fact_sheet(mint)
    except Exception as e:  # never crash the chat
        return f"/token failed: {type(e).__name__}: {e}"
