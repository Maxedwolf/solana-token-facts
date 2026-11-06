"""solana-token-facts: Solana token facts for Hermes Agent (read-only on-chain).

register(ctx) runs once when Hermes starts. It must stay FAST and must NOT
touch the network (plugin doctor blocks sockets while it runs). It only reads
config and wires schemas to handlers.
"""

import logging
from pathlib import Path

from . import reports, rpc, schemas, tools

logger = logging.getLogger(__name__)

TOOLSET = "solana_token_facts"
_HERE = Path(__file__).resolve().parent


def _setting(ctx, key, default):
    try:
        return ctx.get_config(key, default=default)
    except Exception as exc:  # never let config problems kill the plugin
        logger.warning("solana-token-facts: could not read %s (%s); using default", key, exc)
        return default


def register(ctx):
    # 1. Settings (plugins.entries.solana-token-facts.settings.* in Hermes config).
    url = _setting(ctx, "rpc_url", rpc.DEFAULT_RPC_URL) or rpc.DEFAULT_RPC_URL
    if not rpc.configure(url):
        logger.warning("solana-token-facts: rpc_url must be https:// (or http://localhost); using default")
    tools.set_origin_max_pages(_setting(ctx, "origin_max_pages", tools.DEFAULT_ORIGIN_PAGES))
    tools.set_dev_limits(_setting(ctx, "dev_max_launches", tools.DEFAULT_DEV_MAX_LAUNCHES),
                         _setting(ctx, "dev_max_pages", tools.DEFAULT_DEV_MAX_PAGES))
    reports.set_reports_dir(_setting(ctx, "reports_dir", ""))

    # 2. Tools: schema (what the model reads) -> handler (what runs).
    for name, schema, handler in [
        ("token_authorities", schemas.TOKEN_AUTHORITIES, tools.token_authorities),
        ("token_origin", schemas.TOKEN_ORIGIN, tools.token_origin),
        ("token_holders", schemas.TOKEN_HOLDERS, tools.token_holders),
        ("dev_launches", schemas.DEV_LAUNCHES, tools.dev_launches),
        ("save_dev_report", schemas.SAVE_DEV_REPORT, reports.tool_save_dev_report),
    ]:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler)

    # 3. Slash command: /token <mint> prints the full fact sheet without asking the model.
    ctx.register_command("token", handler=reports.command_token,
                         description="Solana token fact sheet: powers, origin, holders, dev history",
                         args_hint="<mint>")

    # 4. Skill: the due-diligence checklist the agent follows when using these tools.
    try:
        ctx.register_skill("token-due-diligence", _HERE / "skills" / "token-due-diligence" / "SKILL.md",
                           description="Check a Solana token or dev with on-chain facts only (no verdicts).")
    except Exception as exc:
        logger.warning("solana-token-facts: skill not registered (%s)", exc)
