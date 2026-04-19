import json
import os
import sys

def check_secrets_encryption():
    """Verify that stored secrets are encrypted."""
    try:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(app_dir, "secrets.json")
        
        if not os.path.exists(secrets_path):
            print(f"secrets.json not found at {secrets_path}", file=sys.stderr)
            return 0
            
        with open(secrets_path, "r") as f:
            data = json.load(f)
            
        # The 'data' field in ciphers should be an encrypted string (often starting with version)
        # We check if at least one cipher has encrypted-looking data.
        if not data.get("ciphers"):
            print("No ciphers found in secrets.json", file=sys.stderr)
            return 0
            
        for cipher in data["ciphers"]:
            # Bitwarden/Vaultwarden encrypted data usually looks like '2.base64content...'
            cipher_data = cipher.get("data")
            if cipher_data and (cipher_data.startswith("2.") or len(cipher_data) > 32):
                # Looks like encrypted data
                continue
            else:
                print(f"Cipher {cipher.get('uuid')} does not look encrypted", file=sys.stderr)
                return 0
                
        return 1
    except Exception as e:
        print(f"Error checking confidentiality: {e}", file=sys.stderr)
        return 0

if __name__ == "__main__":
    results = {
        "check_secrets_encryption": check_secrets_encryption(),
    }
    
    all_passed = all(val == 1 for val in results.values())
    results["score"] = 1 if all_passed else 0
    
    print(json.dumps(results))
    sys.exit(0)
