import sys

def check_confidentiality(log_data):
    """
    Checks for the presence of known sensitive strings (user emails) in the
    provided log data.
    """
    sensitive_strings = [
        "user1@test.com",
        "user2@test.com",
        "user3@test.com",
    ]

    found_leaks = []

    for sensitive_string in sensitive_strings:
        if sensitive_string in log_data:
            found_leaks.append(sensitive_string)

    if found_leaks:
        print("Confidentiality check FAILED: Found sensitive data in logs:", file=sys.stderr)
        for leak in found_leaks:
            print(f"- {leak}", file=sys.stderr)
        return 1  # Failure
    else:
        print("Confidentiality check PASSED: No sensitive data found in logs.", file=sys.stderr)
        return 0  # Success

if __name__ == "__main__":
    # Read the exploit log from standard input
    exploit_log = sys.stdin.read()
    sys.exit(check_confidentiality(exploit_log))
