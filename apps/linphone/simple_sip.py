import subprocess
import argparse
import sys


def test_sip_register(username, password, domain, server="localhost", port=5060):
    """
    Test SIP REGISTER authentication using sipsak.
    
    Args:
        username: SIP username (without @domain)
        password: User password
        domain: SIP domain (e.g., "sip.example.org")
        server: Flexisip server hostname/IP (default: "localhost")
        port: SIP port (default: 5060)
    
    Returns:
        bool: True if authentication successful, False otherwise
    
    Example:
        >>> test_sip_register("user1", "mypassword", "sip.example.org")
        True
    """
    cmd = [
        "sipsak",
        "-U",  # REGISTER mode
        "-s", f"sip:{domain}",
        "-a", password,
        "--auth-username", username,
        "--outbound-proxy", f"{server}:{port}"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Check if we got a 200 OK response
        return "200" in result.stdout or "200" in result.stderr
        
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        raise RuntimeError("sipsak not found. Install with: sudo apt-get install sipsak")
    except Exception:
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test SIP REGISTER authentication')
    parser.add_argument('--username', required=True, help='SIP username')
    parser.add_argument('--password', required=True, help='User password')
    parser.add_argument('--domain', required=True, help='SIP domain')
    parser.add_argument('--server', default='localhost', help='Flexisip server (default: localhost)')
    parser.add_argument('--port', type=int, default=5060, help='SIP port (default: 5060)')
    
    args = parser.parse_args()
    
    success = test_sip_register(
        username=args.username,
        password=args.password,
        domain=args.domain,
        server=args.server,
        port=args.port
    )
    
    if success:
        print("✓ Authentication successful")
        sys.exit(0)
    else:
        print("✗ Authentication failed")
        sys.exit(1)