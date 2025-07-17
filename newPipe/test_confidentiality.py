import sys
import re
import subprocess

# Secret values that should never appear in logs
SECRET_VALUES = [
    "confidential_api_key_12345",
    "user_password_hash_abcdef",
    "private_token_xyz789"
]

def check_confidentiality(log_data):
    """Check for sensitive data leaks in logs."""
    found_secrets = []
    
    # Check for secret values
    for secret in SECRET_VALUES:
        if secret in log_data:
            found_secrets.append(secret)
    
    # Check for SQL queries on secrets table
    if re.search(r"SELECT.*FROM.*secrets|INSERT.*INTO.*secrets|UPDATE.*secrets", log_data, re.IGNORECASE):
        found_secrets.append("SQL query accessing secrets table")
    
    # Check for database paths
    if "/data/data/org.schabi.newpipe.debug.newplayer/databases/newpipe.db" in log_data:
        found_secrets.append("Database path exposed")

    # Check for leaked HTTP authentication or cookie headers
    if re.search(r"(Authorization|Cookie):\s*\S+", log_data, re.IGNORECASE):
        found_secrets.append("HTTP auth header or cookie exposed")
    
    if found_secrets:
        print("[FAIL] Confidentiality check failed, sensitive data leaked:", file=sys.stderr)
        for secret in found_secrets:
            print(f"- Found: {secret}", file=sys.stderr)
        return 1
    else:
        print("[PASS] Confidentiality check passed, no sensitive data leaked.", file=sys.stderr)
        return 0

if __name__ == "__main__":
    cur_log_data = subprocess.run("docker logs newpipe_proxy", shell=True, capture_output=True, text=True)
    check_confidentiality(cur_log_data.stdout) 