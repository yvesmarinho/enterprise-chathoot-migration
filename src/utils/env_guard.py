"""DEV-only environment guardrail.

Exits immediately if production DEST key is detected while
``DEV_ONLY_MODE`` env var is ``'true'`` (the default).

Note: ``MIGRATION_SOURCE_KEY=chat-vya-digital`` is ALWAYS the source key
(both DEV and PROD pipelines read from the same production source DB).
Only the DEST key and MIGRATION_ENV discriminate between environments.

Usage::

    from src.utils.env_guard import assert_dev_only_env

    assert_dev_only_env()  # call before any engine creation
"""

from __future__ import annotations

import os

# Production DEST key — blocked when DEV_ONLY_MODE=true
# Note: source key (chat-vya-digital) is intentionally NOT checked here —
# both DEV and PROD pipelines read from the same production source DB.
_PROD_DEST_KEY = "synchat-vya-digital"

_BANNER = (
    "\n"
    "╔══════════════════════════════════════════════════════════════╗\n"
    "║           ⛔  DEV-ONLY GUARD — EXECUÇÃO BLOQUEADA           ║\n"
    "╚══════════════════════════════════════════════════════════════╝\n"
    "  Razão   : {reason}\n"
    "  Env ativo:\n"
    "    MIGRATION_ENV        = {migration_env!r}\n"
    "    MIGRATION_SOURCE_KEY = {source_key!r}\n"
    "    MIGRATION_DEST_KEY   = {dest_key!r}\n"
    "  → Para desbloquear, defina DEV_ONLY_MODE=false\n"
    "    (requer autorização explícita do responsável pela produção).\n"
)


def assert_dev_only_env() -> None:
    """Abort with exit code 1 if prod DEST detected and DEV_ONLY_MODE is active.

    Reads three environment variables:

    * ``DEV_ONLY_MODE`` — defaults to ``'true'``; set to ``'false'`` to unlock.
    * ``MIGRATION_ENV`` — blocked if value is ``'prod'``.
    * ``MIGRATION_DEST_KEY`` — blocked if value is ``synchat-vya-digital``.

    :raises SystemExit: exit code 1 when prod dest is detected in DEV-only mode.
    """
    dev_only = os.environ.get("DEV_ONLY_MODE", "true").strip().lower()
    if dev_only != "true":
        return  # explicit override — allow prod

    migration_env = os.environ.get("MIGRATION_ENV", "")
    source_key = os.environ.get("MIGRATION_SOURCE_KEY", "")
    dest_key = os.environ.get("MIGRATION_DEST_KEY", "")

    reason: str | None = None
    if migration_env == "prod":
        reason = "MIGRATION_ENV=prod aponta para produção."
    elif dest_key == _PROD_DEST_KEY:
        reason = f"MIGRATION_DEST_KEY={dest_key!r} é chave de produção."

    if reason:
        print(
            _BANNER.format(
                reason=reason,
                migration_env=migration_env,
                source_key=source_key,
                dest_key=dest_key,
            ),
            flush=True,
        )
        raise SystemExit(1)
