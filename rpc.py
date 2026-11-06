"""Tiny Solana JSON-RPC client. Python standard library only (no dependencies).

Features:
  - short in-memory cache (same question within 30s = no new request)
  - retry with backoff on HTTP 429 (rate limit), 5xx and network blips
  - thread-safe (Hermes can run tool calls in parallel threads)
  - never exposes the full RPC URL in outputs (it may contain an API key)
"""

import itertools
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"

_TIMEOUT_S = 15
_MAX_ATTEMPTS = 4          # 1 try + 3 retries
_FIRST_BACKOFF_S = 0.5     # then 1s, 2s ...
_MAX_WAIT_S = 5.0          # never sleep longer than this between tries
_CACHE_TTL_S = 30.0
_CACHE_MAX = 256
_USER_AGENT = "solana-token-facts/0.1 (+https://github.com/Maxedwolf/solana-token-facts)"

_rpc_url = DEFAULT_RPC_URL
_cache = {}                # key -> (expires_at, result)
_lock = threading.Lock()
_ids = itertools.count(1)  # JSON-RPC request ids


class RpcError(Exception):
    """Raised inside this plugin only; tool handlers turn it into JSON."""

    def __init__(self, kind, message, code=None):
        super().__init__(message)
        self.kind = kind    # short machine-readable label, e.g. "rate_limited"
        self.code = code    # HTTP status or JSON-RPC error code, if any


def _is_allowed_url(url):
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    if p.scheme == "https" and p.hostname:
        return True
    return p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1")


def configure(url):
    """Set the RPC URL. Returns False (and keeps the default) if the URL is not allowed."""
    global _rpc_url
    if _is_allowed_url(url):
        _rpc_url = url.strip()
        return True
    _rpc_url = DEFAULT_RPC_URL
    return False


# A private RPC URL usually contains an API key, so it is a Hermes *secret*
# (config_schema type: secret -> stored in Hermes' .env, read with get_secret),
# never a plain config.yaml setting. It wins over rpc_url when set.
SECRET_ENV = "SOLANA_TOKEN_FACTS_RPC_URL"


def _secret_url():
    try:
        from agent.secret_scope import get_secret   # inside Hermes: honours the active profile
        val = get_secret(SECRET_ENV, None)
    except ImportError:                             # standalone (dev scripts): plain environment
        import os
        val = os.environ.get(SECRET_ENV)
    except Exception:
        val = None
    return val.strip() if isinstance(val, str) and _is_allowed_url(val) else None


def current_url():
    return _secret_url() or _rpc_url


def endpoint_host():
    """Host only, safe to show the model/user (no path, no ?api-key=...)."""
    return urlparse(current_url()).hostname


def call(method, params, use_cache=True):
    """Call one JSON-RPC method and return its "result". Raises RpcError."""
    url = current_url()
    key = json.dumps([url, method, params], sort_keys=True)

    if use_cache:
        with _lock:
            hit = _cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]

    result = _post(url, method, params)

    if use_cache:
        with _lock:
            if len(_cache) >= _CACHE_MAX:
                now = time.monotonic()
                for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
                    del _cache[k]
                if len(_cache) >= _CACHE_MAX:
                    del _cache[next(iter(_cache))]  # dicts keep insertion order: oldest first
            _cache[key] = (time.monotonic() + _CACHE_TTL_S, result)
    return result


def _retry_after_seconds(http_error):
    try:
        return float(http_error.headers.get("Retry-After"))
    except (TypeError, ValueError, AttributeError):
        return None


def _post(url, method, params):
    body = json.dumps(
        {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params}
    ).encode("utf-8")
    backoff = _FIRST_BACKOFF_S

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        last_try = attempt == _MAX_ATTEMPTS
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

        # HTTPError must be caught BEFORE URLError: it is a subclass of it.
        except urllib.error.HTTPError as e:
            retryable = e.code == 429 or 500 <= e.code < 600
            if retryable and not last_try:
                time.sleep(min(_retry_after_seconds(e) or backoff, _MAX_WAIT_S))
                backoff *= 2
                continue
            kind = "rate_limited" if e.code == 429 else "http_error"
            raise RpcError(kind, f"RPC returned HTTP {e.code}", e.code) from None

        except (urllib.error.URLError, OSError) as e:  # DNS, refused, timeout, TLS
            if not last_try:
                time.sleep(backoff)
                backoff *= 2
                continue
            reason = getattr(e, "reason", e)
            raise RpcError("network_error", f"Could not reach RPC: {reason}") from None

        except (ValueError, UnicodeDecodeError):
            raise RpcError("bad_response", "RPC reply was not valid JSON") from None

        if not isinstance(payload, dict):
            raise RpcError("bad_response", "RPC reply had an unexpected shape")

        err = payload.get("error")
        if err:
            code = err.get("code") if isinstance(err, dict) else None
            msg = err.get("message") if isinstance(err, dict) else str(err)
            # Some providers report rate limits inside the JSON body instead of HTTP 429.
            if code in (429, -32429) and not last_try:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise RpcError("rpc_error", f"RPC error: {msg}", code)

        return payload.get("result")

    raise RpcError("network_error", "RPC call failed after retries")  # not normally reached
