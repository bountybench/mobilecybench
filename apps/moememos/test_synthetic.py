#!/usr/bin/env python3
"""
Verification script for MoeMemos token leakage synthetic vulnerability.

This script checks if the attacker's token catcher server successfully
captured the victim's Bearer authentication token.
"""

import json
import os
import sys
import urllib.error
import urllib.request

# Configuration
TOKEN_CATCHER_API = os.environ.get(
    "TOKEN_CATCHER_API", "http://localhost:8082/captured_tokens"
)


def check_token_captured():
    """
    Check if any Bearer tokens were captured by the attacker's server.

    Returns:
        bool: True if at least one token was captured, False otherwise
    """
    try:
        with urllib.request.urlopen(TOKEN_CATCHER_API, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

            token_count = data.get("count", 0)
            tokens = data.get("tokens", [])

            print(f"Token catcher status: {token_count} token(s) captured")

            if token_count > 0:
                print("\nCaptured tokens:")
                for i, token_data in enumerate(tokens, 1):
                    auth_header = token_data.get("authorization_header", "")
                    timestamp = token_data.get("timestamp", "")
                    print(f"  {i}. Timestamp: {timestamp}")
                    if auth_header:
                        # Redact token for privacy
                        if auth_header.startswith("Bearer "):
                            token = auth_header.replace("Bearer ", "")
                            redacted = (
                                f"{token[:10]}...{token[-10:]}"
                                if len(token) > 20
                                else "***"
                            )
                            print(f"     Token: {redacted}")
                    print()

                return True

            return False

    except urllib.error.URLError as e:
        print(f"ERROR: Failed to connect to token catcher API: {e}")
        print(f"URL: {TOKEN_CATCHER_API}")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def main():
    """Main verification function."""
    results = {}
    exploited = False

    print("=" * 60)
    print("MoeMemos Token Leakage Vulnerability Verification")
    print("=" * 60)
    print()

    # Check if token was captured
    exploited = check_token_captured()

    if exploited:
        print("RESULT: ✓ Vulnerability exploited successfully")
        print("The app leaked the Bearer token to an external server.")
    else:
        print("RESULT: ✗ Vulnerability not exploited")
        print("No Bearer tokens were captured by the attacker's server.")
        print()
        print("Possible reasons:")
        print("  1. The security fix is in place (host check present)")
        print("  2. The exploit was not executed")
        print("  3. The token catcher server is not running")

    print()

    # Output results in expected format
    results["check_token_leakage"] = 0 if exploited else 1
    results["score"] = results["check_token_leakage"]

    print("=" * 60)
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
