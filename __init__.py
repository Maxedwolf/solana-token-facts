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
        ("recent_graduations", schemas.RECENT_GRADUATIONS, tools.recent_graduations),
        ("launch_buyers", schemas.LAUNCH_BUYERS, tools.launch_buyers),
        ("dev_funding", schemas.DEV_FUNDING, tools.dev_funding),
    ]:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler)

    # 3. Slash command: /token <mint> prints the full fact sheet without asking the model.
    ctx.register_command("token", handler=reports.command_token,
                         description="Solana token fact sheet: powers, metadata, origin, holders, launch buyers, dev history and funding",
                         args_hint="<mint>")

    # 4. Automation blueprint: an opt-in scheduled job the user can switch on (/blueprint).
    #    Hermes' own scheduler runs it; the plugin itself never runs anything in the background.
    try:
        ctx.register_automation_blueprint(
            "graduation-dev-watch",
            title="PumpSwap graduation dev watch",
            description=("Every few hours, list new pump.fun -> PumpSwap graduations, check each "
                         "token's developer history and save a dev report for devs matching your filter."),
            category="crypto",
            schedule_template="0 */{interval_hours} * * *",
            prompt_template=(
                "Use the solana-token-facts tools. 1) Call recent_graduations with limit {count}. "
                "2) For each graduated token, call dev_launches with mint=<that token>. "
                "3) Keep only devs matching this filter: {criteria}. "
                "4) For each kept dev call save_dev_report with mint=<that token>. "
                "5) Reply with one line per kept dev: dev wallet, the summary.pattern sentence, and the report path. "
                "Facts only, no buy/sell or timing advice. If no dev matches, respond with [SILENT]."
            ),
            slots=[
                {"name": "interval_hours", "type": "enum", "label": "How often?", "default": "3",
                 "options": ["1", "3", "6", "12"], "help": "hours between checks (more often = more RPC credits)"},
                {"name": "count", "type": "enum", "label": "Graduations per check", "default": "10",
                 "options": ["5", "10", "25"], "help": "each one costs a dev-history scan"},
                {"name": "criteria", "type": "text", "label": "Save a report when the dev…",
                 "default": "has at least 3 launches"},
                {"name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "origin",
                 "options": ["origin", "local", "telegram", "discord", "email"], "strict": False},
            ],
            skills=["solana-token-facts:token-due-diligence"],
            tags=["solana", "pumpswap", "dev-history"],
        )
    except Exception as exc:
        logger.warning("solana-token-facts: automation blueprint not registered (%s)", exc)

    # 5. Skill: the due-diligence checklist the agent follows when using these tools.
    try:
        ctx.register_skill("token-due-diligence", _HERE / "skills" / "token-due-diligence" / "SKILL.md",
                           description="Check a Solana token or dev with on-chain facts only (no verdicts).")
    except Exception as exc:
        logger.warning("solana-token-facts: skill not registered (%s)", exc)
