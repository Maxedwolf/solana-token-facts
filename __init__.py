"""solana-token-facts: read-only Solana token facts for Hermes Agent.

register(ctx) runs once when Hermes starts. It must stay FAST and must NOT
touch the network (plugin doctor blocks sockets while it runs). It only reads
config and wires schemas to handlers.
"""

import logging

from . import rpc, schemas, tools

logger = logging.getLogger(__name__)

TOOLSET = "solana_token_facts"


def register(ctx):
    # 1. Read the user's RPC URL from plugins.entries.solana-token-facts.settings.rpc_url
    url = rpc.DEFAULT_RPC_URL
    try:
        url = ctx.get_config("rpc_url", default=rpc.DEFAULT_RPC_URL) or rpc.DEFAULT_RPC_URL
    except Exception as exc:  # never let config problems kill the plugin
        logger.warning("solana-token-facts: could not read rpc_url (%s); using default", exc)

    if not rpc.configure(url):
        logger.warning("solana-token-facts: rpc_url must be https:// (or http://localhost); using default")

    # How far back token_origin may page through history (1 page = 1,000 transactions).
    try:
        tools.set_origin_max_pages(ctx.get_config("origin_max_pages", default=tools.DEFAULT_ORIGIN_PAGES))
    except Exception as exc:
        logger.warning("solana-token-facts: could not read origin_max_pages (%s); using default", exc)

    # 2. Wire each schema (what the model reads) to its handler (what runs).
    ctx.register_tool(
        name="token_authorities",
        toolset=TOOLSET,
        schema=schemas.TOKEN_AUTHORITIES,
        handler=tools.token_authorities,
    )
    ctx.register_tool(
        name="token_origin",
        toolset=TOOLSET,
        schema=schemas.TOKEN_ORIGIN,
        handler=tools.token_origin,
    )
    ctx.register_tool(
        name="token_holders",
        toolset=TOOLSET,
        schema=schemas.TOKEN_HOLDERS,
        handler=tools.token_holders,
    )
