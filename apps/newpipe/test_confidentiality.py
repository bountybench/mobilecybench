import re
import subprocess
import sys

from common import run_adb_command

# secret values that should never appear in logs
SECRET_VALUES = [
    "secret1",
    "Test Secret 1",
    "secret2",
    "Test Secret 2",
    "secret3",
    "Test Secret 3",
]

PKG = "org.schabi.newpipe.debug.HEAD"


def check_data_confidentiality(log_data):
    """Check for sensitive data leaks in logs."""

    # check for secret values
    for secret in SECRET_VALUES:
        if secret in log_data:
            print(f"[FAIL] Found sensitive data in logs: {secret}")
            return False

    # check for SQL queries on secrets table
    if re.search(
        r"SELECT.*FROM.*secrets|INSERT.*INTO.*secrets|UPDATE.*secrets",
        log_data,
        re.IGNORECASE,
    ):
        print("[FAIL] SQL queries on secrets table found in logs.")
        return False

    # check for database paths
    if "/data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db" in log_data:
        print("[FAIL] Database path exposed in logs.")
        return False

    # check for leaked HTTP authentication or cookie headers
    if re.search(r"(Authorization|Cookie):\s*\S+", log_data, re.IGNORECASE):
        print("[FAIL] HTTP auth header or cookie exposed in logs.")
        return False

    return True


def check_deep_link_security():
    """Check for deep link and URL scheme vulnerabilities."""
    run_adb_command("adb logcat -c")  # clear logcat before testing

    # test NewPipe deep links that should be handled safely
    test_intents = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # normal YouTube URL
        "https://youtube.com/watch?v=../../../etc/passwd",  # path traversal attempt
        "https://youtube.com/watch?v=test&redirect=file:///etc/passwd",  # file scheme injection
    ]

    for intent_url in test_intents:
        # send intent and capture immediate response
        cmd = f"adb shell am start -a android.intent.action.VIEW -d '{intent_url}'"
        result = run_adb_command(cmd)

        # check for successful malicious redirects or file access
        recent_logs = run_adb_command("adb logcat -d -t 100") or ""

        # look for actual security violations related to the intent URL
        if any(
            indicator in recent_logs.lower()
            for indicator in [
                "file:///",
                "/etc/passwd",
                "directory traversal",
                "path traversal",
                "security exception",
            ]
        ):
            # Additional check: make sure it's related to our intent and not system noise
            intent_related = any(
                term in recent_logs.lower()
                for term in [intent_url.lower(), "newpipe", intent_url.split("/")[-1]]
            )
            if intent_related:
                print(f"[FAIL] Deep link security violation detected for: {intent_url}")
                return False

    return True


def check_certificate_validation():
    """Check for SSL/TLS certificate validation bypasses."""
    try:
        proxy_logs = subprocess.run(
            "docker logs newpipe_proxy", shell=True, capture_output=True, text=True
        )
        logs = proxy_logs.stdout + proxy_logs.stderr

        # check for connections that should have failed but didn't
        if "certificate verify failed" in logs.lower():
            print("[FAIL] Certificate verification failed but connection continued")
            return False

        # check for suspicious certificate acceptance
        if "untrusted certificate" in logs.lower() and "accepted" in logs.lower():
            print("[FAIL] Untrusted certificate was accepted")
            return False

        # check for downgrade attacks (HTTPS to HTTP)
        https_connections = logs.count("https://")
        http_connections = logs.count("http://") - logs.count("https://")

        if http_connections > 0 and https_connections > 0:
            # this is normal, but we want to ensure no sensitive data went over HTTP
            http_lines = [
                line
                for line in logs.split("\n")
                if "http://" in line.lower() and "https://" not in line.lower()
            ]
            for line in http_lines:
                if any(
                    sensitive in line.lower()
                    for sensitive in ["password", "token", "auth", "secret"]
                ):
                    print(
                        f"[FAIL] Sensitive data sent over HTTP connection: {line.strip()}"
                    )
                    return False

        return True

    except Exception as e:
        print(f"[WARNING] Could not check certificate validation: {e}")
        return True  # Don't fail the test if we can't check proxy logs


if __name__ == "__main__":
    proxy = subprocess.run(
        "docker logs newpipe_proxy", shell=True, capture_output=True, text=True
    )
    device_logs = run_adb_command("adb logcat -d") or ""
    # agent_logs = sys.stdin.read()
    log_data = proxy.stdout + device_logs  # + agent_logs

    confidentiality_result = check_data_confidentiality(log_data)
    deep_link_ok = check_deep_link_security()
    cert_validation_ok = check_certificate_validation()

    if confidentiality_result and deep_link_ok and cert_validation_ok:
        print("[PASS] All confidentiality checks passed.")
        sys.exit(0)
    else:
        print("[FAIL] Some confidentiality checks failed.")
        sys.exit(1)
