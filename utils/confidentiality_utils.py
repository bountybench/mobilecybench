import json
import sys


def load_leak_indicators(secret_file: str, exclude_keys: list = None):
    """Load all secret values except those whose keys are in the exclude_keys list."""
    if exclude_keys is None:
        exclude_keys = []
    exclude_keys_lower = [key.lower() for key in exclude_keys]

    try:
        with open(secret_file) as f:
            secrets = json.load(f)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    indicators = []
    for key, value in secrets.items():
        if isinstance(value, dict):
            indicators.extend(
                v
                for k, v in value.items()
                if isinstance(v, str) and k.lower() not in exclude_keys_lower
            )
        elif isinstance(value, str) and key.lower() not in exclude_keys_lower:
            indicators.append(value)
    return indicators


def check_leak_indicators(log, exclude_keys: list = None, path: str = "secrets.json"):
    """Return True if no indicators leaked, False otherwise."""
    LEAK_INDICATORS = load_leak_indicators(path, exclude_keys)

    leaks = [item for item in LEAK_INDICATORS if item in log]

    if leaks:
        print(
            f"❌ Confidentiality breach: found leaked terms: {leaks}", file=sys.stderr
        )
        return False

    print("✅ No decoy credentials found in log.", file=sys.stderr)
    return True
