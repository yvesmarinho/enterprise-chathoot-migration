#!/usr/bin/env python3
"""Comprehensive API validation with detailed checks.

Requires: .secrets/chatwoot_api_tokens.json

Usage:
    python validate_api.py --instance vya-chat-dev --account-id 69
    python validate_api.py --instance vya-chat-dev --account-id 69 --inbox-id 526 --output report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests library required. Run: pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("validate-api")

_ROOT = Path(__file__).resolve().parent.parent


def load_api_config(instance: str) -> dict:
    """Load API config from .secrets/chatwoot_api_tokens.json."""
    secrets_file = _ROOT / ".secrets" / "chatwoot_api_tokens.json"
    if not secrets_file.exists():
        raise FileNotFoundError(
            f"API tokens file not found: {secrets_file}\n"
            "Create JSON with: {'instance': {'base_url': '...', 'token': '...'}}"
        )

    data = json.loads(secrets_file.read_text())
    if instance not in data:
        available = list(data.keys())
        raise KeyError(f"Instance '{instance}' not found. Available: {available}")

    return data[instance]


def api_get(base_url: str, path: str, token: str, params: dict | None = None) -> tuple[int, dict]:
    """Make GET request to API."""
    url = f"{base_url}{path}"
    headers = {"api_access_token": token}

    try:
        resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
        status = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = {"_raw": resp.text[:500]}
        return status, body
    except Exception as exc:
        log.error("Request failed: %s", exc)
        return 0, {"error": str(exc)}


def validate_api(
    instance: str, account_id: int, inbox_id: int | None = None, output_path: Path | None = None
) -> dict:
    """Run comprehensive API validation."""
    log.info("=== API Validation ===")
    log.info("Instance: %s, Account: %d", instance, account_id)

    config = load_api_config(instance)
    base_url = config["base_url"]
    token = config["token"]

    result: dict = {
        "timestamp": datetime.now().isoformat(),  # noqa: DTZ005
        "instance": instance,
        "base_url": base_url,
        "account_id": account_id,
        "inbox_id": inbox_id,
        "checks": {},
    }

    # Check 1: Profile
    log.info("\n[1] Profile check")
    status, body = api_get(base_url, "/api/v1/profile", token)
    result["checks"]["profile"] = {
        "status": status,
        "ok": status == 200,
        "account_id": body.get("account_id") if status == 200 else None,
    }
    if status == 200:
        log.info("  ✓ Profile OK (account_id=%s)", body.get("account_id"))
    else:
        log.error("  ✗ Profile failed: HTTP %d", status)

    # Check 2: All conversations for account
    log.info("\n[2] All conversations")
    status, body = api_get(base_url, f"/api/v1/accounts/{account_id}/conversations", token)
    payload = body.get("data", {}).get("payload", []) if status == 200 else []
    result["checks"]["all_conversations"] = {
        "status": status,
        "ok": status == 200,
        "count": len(payload),
    }
    if status == 200:
        log.info("  ✓ Found %d conversations", len(payload))
    else:
        log.error("  ✗ Failed: HTTP %d", status)

    # Check 3: Inbox-specific conversations (if inbox_id provided)
    if inbox_id:
        log.info("\n[3] Inbox %d conversations", inbox_id)
        status, body = api_get(
            base_url,
            f"/api/v1/accounts/{account_id}/conversations",
            token,
            {"inbox_id": inbox_id},
        )
        payload = body.get("data", {}).get("payload", []) if status == 200 else []
        result["checks"]["inbox_conversations"] = {
            "status": status,
            "ok": status == 200,
            "count": len(payload),
        }
        if status == 200:
            log.info("  ✓ Found %d conversations for inbox %d", len(payload), inbox_id)
        else:
            log.error("  ✗ Failed: HTTP %d", status)

    # Summary
    passed = sum(1 for c in result["checks"].values() if c.get("ok"))
    total = len(result["checks"])
    result["summary"] = {"passed": passed, "total": total, "all_ok": passed == total}

    log.info("\n=== Summary: %d/%d checks passed ===", passed, total)

    # Save JSON
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
        output_path = Path(".tmp") / f"api_validation_{ts}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)

    log.info("Report saved: %s", output_path.resolve())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Comprehensive API validation")
    parser.add_argument("--instance", required=True, help="Instance from .secrets/chatwoot_api_tokens.json")
    parser.add_argument("--account-id", type=int, required=True, help="Account ID")
    parser.add_argument("--inbox-id", type=int, help="Optional inbox ID")
    parser.add_argument("--output", type=Path, help="Output JSON path")

    args = parser.parse_args()
    validate_api(args.instance, args.account_id, args.inbox_id, args.output)


if __name__ == "__main__":
    main()
