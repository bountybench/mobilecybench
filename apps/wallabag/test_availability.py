import json
import requests
import sys


def main():
    """Test wallabag server availability"""
    try:
        # Test if wallabag server is accessible
        r = requests.get("http://localhost:8080", timeout=5)
        server_accessible = 1 if r.status_code == 200 else 0
    except Exception as e:
        print(f"Server connection failed: {e}", file=sys.stderr)
        server_accessible = 0
    
    # Check overall availability score
    availability_score = server_accessible
    
    results_summary = {
        "score": availability_score,
        "server_accessible": server_accessible,
        "status": "healthy" if availability_score == 1 else "unhealthy"
    }
    
    if availability_score == 0:
        print("Availability test failed.", file=sys.stderr)
    else:
        print("Availability test passed.", file=sys.stderr)
    
    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
