#!/usr/bin/env python3
"""Test specific API endpoints after migration.

Requires: .secrets/chatwoot_api_tokens.json with format:
{
  "vya-chat-dev": {
    "base_url": "https://vya-chat-dev.vya.digital",
    "token": "..."
  }
}

Usage:
    python test_api_endpoints.py --instance vya-chat-dev --account-id 69
    python test_api_endpoints.py --instance vya-chat-dev --account-id 69 --inbox-id 526
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed. Run: pip install requests")
    raise

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("test-api")

_ROOT = Path(__file__).resolve().parent.parent


def load_api_config(instance: str) -> dict:
    """Load API config from .secrets/chatwoot_api_tokens.json."""
    secrets_file = _ROOT / ".secrets" / "chatwoot_api_tokens.json"
    if not secrets_file.exists():
        raise FileNotFoundError(
            f"API tokens file not found: {secrets_file}\n"
            "Create it with format: {'instance-name': {'base_url': '...', 'token': '...'}}"
        )

    data = json.loads(secrets_file.read_text())
    if instance not in data:
        available = list(data.keys())
        raise KeyError(f"Instance '{instance}' not found. Available: {available}")

    return data[instance]


def test_endpoint(url: str, token: str, label: str) -> dict:
    """Test a single API endpoint."""
    headers = {"api_access_token": token}
    log.info("Testing %s: %s", label, url)

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        status = resp.status_code

        if status == 200:
            data = resp.json()
            count = len(data.get("payload", data.get("data", {}).get("payload", [])))
            log.info("  ✓ HTTP %d — %d items", status, count)
            return {"status": status, "ok": True, "count": count, "error": None}
        else:
            error = resp.text[:200]
            log.error("  ✗ HTTP %d — %s", status, error)
            return {"status": status, "ok": False, "count": 0, "error": error}

    except Exception as exc:
        log.error("  ✗ Request failed: %s", exc)
        return {"status": 0, "ok": False, "count": 0, "error": str(exc)}


def test_api(instance: str, account_id: int, inbox_id: int | None = None) -> None:
    """Run API endpoint tests."""
    config = load_api_config(instance)
    base_url = config["base_url"]
    token = config["token"]

    log.info("=== API Endpoint Tests ===")
    log.info("Instance: %s", instance)
    log.info("Base URL: %s", base_url)
    log.info("Account ID: %d", account_id)
    if inbox_id:
        log.info("Inbox ID: %d", inbox_id)

    # Define tests
    tests = [
        (f"Account profile", f"{base_url}/api/v1/profile"),
        (f"All conversations", f"{base_url}/api/v1/accounts/{account_id}/conversations"),
    ]

    if inbox_id:
        tests.append(
            (
                f"Inbox {inbox_id} conversations",
                f"{base_url}/api/v1/accounts/{account_id}/conversations?inbox_id={inbox_id}",
            )
        )

    # Run tests
    results = {}
    for label, url in tests:
        results[label] = test_endpoint(url, token, label)

    # Summary
    passed = sum(1 for r in results.values() if r["ok"])
    total = len(results)
    log.info("\n=== Summary: %d/%d tests passed ===", passed, total)
    if passed < total:
        log.error("Some tests failed. See details above.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test API endpoints after migration")
    parser.add_argument(
        "--instance",
        required=True,
        help="Instance name from .secrets/chatwoot_api_tokens.json",
    )
    parser.add_argument("--account-id", type=int, required=True, help="Account ID to test")
    parser.add_argument("--inbox-id", type=int, help="Optional inbox ID for specific tests")

    args = parser.parse_args()
    test_api(args.instance, args.account_id, args.inbox_id)


if __name__ == "__main__":
    main()
