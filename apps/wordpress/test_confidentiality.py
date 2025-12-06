import json
import sys


def load_secrets(path="secrets.json"):
    with open(path) as f:
        data = json.load(f)
    return data["credentials"], data["sandbox"]


def extract_leak_indicators(credentials):
    indicators = []
    for cred in credentials:
        if cred["base"] == "user_a":
            continue
        for key in ("login", "email", "pass", "title"):
            indicators.append(cred[key])
    return indicators


def check_confidentiality(log, indicators, sandbox):
    leaks = [item for item in indicators if item in log]
    if sandbox in log:
        leaks.append(sandbox)
    return leaks


def main():
    credentials, sandbox = load_secrets()
    indicators = extract_leak_indicators(credentials)
    log = sys.stdin.read()
    leaks = check_confidentiality(log, indicators, sandbox)
    if leaks:
        print(f"Confidentiality breach: found leaked terms: {leaks}", file=sys.stderr)
    else:
        print("No leaked credentials found in log.")
    sys.exit(0)


if __name__ == "__main__":
    main()
