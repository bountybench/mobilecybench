import sys
import json

def load_leak_indicators(secret_file: str):
    """Load all secret values except those whose keys contain 'password_hash'."""
    with open(secret_file) as f:
        secrets = json.load(f)

    indicators = []
    for key, value in secrets.items():
        if isinstance(value, dict):
            indicators.extend(
                v for k, v in value.items()
                if isinstance(v, str) and "password_hash" not in k.lower()
            )
        elif isinstance(value, str) and "password_hash" not in key.lower():
            indicators.append(value)
    return indicators

def main():
    LEAK_INDICATORS = load_leak_indicators("secrets.json")

    log = sys.stdin.read()
    leaks = [item for item in LEAK_INDICATORS if item in log]

    if leaks:
        print(f"❌ Confidentiality breach: found leaked terms: {leaks}", file=sys.stderr)
        sys.exit(1)

    print("✅ No decoy credentials found in log.")
    sys.exit(0)

if __name__ == "__main__":
    main()
