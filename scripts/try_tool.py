"""Dev helper: run a tool handler directly, without Hermes. Makes REAL network calls.

Usage (from the repo folder, Command Prompt):
    python scripts\\try_tool.py token_authorities <mint>
    python scripts\\try_tool.py token_holders <mint> [rpc_url]
    python scripts\\try_tool.py recent_pump_mint          (prints a just-launched pump.fun mint)

RPC URL: the optional last argument, otherwise the rpc_url saved in Hermes' config
(so your API key is reused without ever being typed or printed), otherwise the public default.
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = "solana_token_facts"  # the folder name has dashes, so load it under a Python-safe name

spec = importlib.util.spec_from_file_location(
    PKG, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
)
pkg = importlib.util.module_from_spec(spec)
sys.modules[PKG] = pkg          # register first so "from . import rpc" inside works
spec.loader.exec_module(pkg)

rpc = sys.modules[PKG + ".rpc"]
tools = sys.modules[PKG + ".tools"]


def hermes_rpc_url():
    """Read plugins.entries.solana-token-facts.settings.rpc_url from Hermes' config.yaml."""
    home = os.environ.get("HERMES_HOME") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
    try:
        text = Path(home, "config.yaml").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"solana-token-facts:.*?rpc_url:\s*['\"]?(https://[^\s'\"]+)", text, re.S)
    return m.group(1) if m else None


# pump.fun's shared mint-authority address appears in every token CREATION but not in trades,
# so its history is a list of launches.
PUMP_MINT_AUTHORITY = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"


def recent_pump_mint(scan=10):
    """Find a recently launched pump.fun token (dev testing only)."""
    sigs = rpc.call("getSignaturesForAddress", [PUMP_MINT_AUTHORITY, {"limit": scan, "commitment": "finalized"}],
                    use_cache=False)
    for s in sigs or []:
        if s.get("err"):
            continue
        tx = tools.get_transaction(s["signature"])
        outer = (((tx or {}).get("transaction") or {}).get("message") or {}).get("instructions") or []
        inners = ((tx or {}).get("meta") or {}).get("innerInstructions") or []
        for group in [outer] + [i.get("instructions") or [] for i in inners]:
            for ix in group:
                p = ix.get("parsed") if isinstance(ix, dict) else None
                if isinstance(p, dict) and str(p.get("type", "")).startswith("initializeMint"):
                    return p["info"]["mint"]
    return None


if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

tool_name = sys.argv[1]
url = sys.argv[3] if len(sys.argv) > 3 else hermes_rpc_url()
if url and not rpc.configure(url):
    print("RPC URL not allowed (must be https://); using default.")
print(f"[rpc host: {rpc.endpoint_host()}]", file=sys.stderr)

if tool_name == "recent_pump_mint":
    print(recent_pump_mint() or "none found")
    sys.exit(0)

reports = sys.modules[PKG + ".reports"]
if tool_name == "recent_graduations":
    print(json.dumps(json.loads(tools.recent_graduations({"limit": int(sys.argv[2]) if len(sys.argv) > 2 else 5})), indent=2))
    sys.exit(0)
if tool_name == "token_command" and len(sys.argv) >= 3:      # what /token <mint> prints
    print(reports.command_token(sys.argv[2]))
    sys.exit(0)

handler = getattr(tools, tool_name, None) or getattr(reports, "tool_" + tool_name, None)
if handler is None or len(sys.argv) < 3:
    print(f"No tool named {tool_name!r} in tools.py, or no mint given")
    sys.exit(1)

arg = sys.argv[2]
out = handler({"wallet": arg[7:]} if arg.startswith("wallet:") else {"mint": arg})
print(json.dumps(json.loads(out), indent=2))
