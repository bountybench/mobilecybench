#!/usr/bin/env python3
"""
Simple script to get Prosody debug log and load it into memory
"""

import subprocess

def get_debug_log():
    """Get debug log from Prosody container"""
    try:
        result = subprocess.run([
            'docker', 'exec', 'conversations-prosody', 
            'cat', '/var/log/prosody/debug.log'
        ], capture_output=True, text=True, check=True)
        
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        return ""

def main():
    print("Getting debug log...")
    log_content = get_debug_log()
    
    print(f"Log has {len(log_content.splitlines())} lines")
    print("\nFirst 10 lines:")
    for i, line in enumerate(log_content.splitlines()[:10]):
        print(f"{i+1}: {line}")
    
    # TODO: Look for signs that impersonations have happened

if __name__ == "__main__":
    main()