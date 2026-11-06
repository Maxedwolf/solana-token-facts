"""Dev helper: run a tool handler directly, without Hermes. Makes REAL network calls.

Usage (from the repo folder, Command Prompt):
    python scripts\\try_tool.py token_authorities EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
    python scripts\\try_tool.py token_authorities <mint> https://your-rpc-url
"""

import importlib.util
import json
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

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

tool_name, mint = sys.argv[1], sys.argv[2]
if len(sys.argv) > 3 and not rpc.configure(sys.argv[3]):
    print("RPC URL not allowed (must be https://); using default.")

handler = getattr(tools, tool_name, None)
if handler is None:
    print(f"No tool named {tool_name!r} in tools.py")
    sys.exit(1)

out = handler({"mint": mint})
print(json.dumps(json.loads(out), indent=2))
