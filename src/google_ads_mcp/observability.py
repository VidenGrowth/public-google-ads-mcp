"""Logging setup and tool-invocation telemetry.

Emits one line per tool call with name, caller email (if authenticated),
duration, and outcome. Cloud Run captures stderr into Cloud Logging, so
these lines are queryable via the log explorer.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
import sys
import time
from typing import Callable

logger = logging.getLogger("google_ads_mcp.tools")


def setup_logging() -> None:
    """Configure the root logger for stderr output at LOG_LEVEL (default INFO).

    Log to stderr specifically because the stdio MCP transport owns stdout –
    anything written there corrupts the JSON-RPC stream to the client.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def _caller_email() -> str | None:
    """Return the authenticated caller's email (remote HTTP mode) or None.

    Under the OAuth proxy the verified Google identity is attached to the
    request's access token claims. Returns None on the local stdio transport,
    where there is no auth context.
    """
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
        if token is not None:
            return (getattr(token, "claims", None) or {}).get("email")
    except Exception:
        return None
    return None


def log_tool_call(fn: Callable) -> Callable:
    """Wrap a tool function with structured invocation logging.

    Emits one `tool_call` line on entry (key=value format) and one `tool_done`
    or `tool_error` line on exit with duration_ms. Argument values are never
    logged – only argument names – to avoid leaking customer IDs or other PII.
    """

    name = fn.__name__

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            return await _dispatch_async(fn, name, args, kwargs)

        return async_wrapper

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
        return _dispatch_sync(fn, name, args, kwargs)

    return sync_wrapper


def _format_prelude(name: str, kwargs: dict) -> str:
    email = _caller_email()
    parts = [f"tool={name}", f"user={email or '-'}"]
    if kwargs:
        parts.append(f"args={','.join(sorted(kwargs.keys()))}")
    return " ".join(parts)


def _dispatch_sync(fn, name: str, args: tuple, kwargs: dict):
    prelude = _format_prelude(name, kwargs)
    logger.info("tool_call %s", prelude)
    start = time.monotonic()
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.exception(
            "tool_error %s duration_ms=%d error=%s",
            prelude,
            duration_ms,
            type(exc).__name__,
        )
        raise
    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info("tool_done %s duration_ms=%d", prelude, duration_ms)
    return result


async def _dispatch_async(fn, name: str, args: tuple, kwargs: dict):
    prelude = _format_prelude(name, kwargs)
    logger.info("tool_call %s", prelude)
    start = time.monotonic()
    try:
        result = await fn(*args, **kwargs)
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.exception(
            "tool_error %s duration_ms=%d error=%s",
            prelude,
            duration_ms,
            type(exc).__name__,
        )
        raise
    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info("tool_done %s duration_ms=%d", prelude, duration_ms)
    return result
