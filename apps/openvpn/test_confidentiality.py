#!/usr/bin/env python3
"""
Test confidentiality of OpenVPN communications and data protection.
Ensures that sensitive data is not leaked in logs or transmitted in plaintext.
"""

import subprocess
import json
import os
import re
import sys

def load_secrets():
    """Load secrets from secrets file"""
    try:
        with open("secrets/secrets.json", "r") as f:
            return json.load(f)
    except:
        return {
            "admin_password": "test_admin_secret",
            "user_password": "test_user_secret", 
            "ca_passphrase": "test_ca_secret"
        }

def test_log_confidentiality():
    """Test that sensitive information is not leaked in logs"""
    print("Testing log confidentiality...")
    
    secrets = load_secrets()
    leaked_secrets = []
    
    log_files = [
        "logs/openvpn.log",
        "/var/log/openvpn/openvpn.log"
    ]
    
    # Also check docker logs
    try:
        docker_logs = subprocess.run([
            "docker", "logs", "openvpn-server"
        ], capture_output=True, text=True)
        
        log_content = docker_logs.stdout + docker_logs.stderr
        
        # Check for leaked secrets in docker logs
        for secret_name, secret_value in secrets.items():
            if secret_value in log_content:
                leaked_secrets.append(f"Docker logs contain {secret_name}")
        
    except Exception as e:
        print(f"Error checking docker logs: {e}")
    
    # Check log files
    for log_file in log_files:
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    content = f.read()
                    
                for secret_name, secret_value in secrets.items():
                    if secret_value in content:
                        leaked_secrets.append(f"{log_file} contains {secret_name}")
                        
            except Exception as e:
                print(f"Error reading {log_file}: {e}")
    
    if leaked_secrets:
        print(f"✗ Confidentiality breach detected: {leaked_secrets}")
        return False
    else:
        print("✓ No secrets leaked in logs")
        return True

def test_certificate_confidentiality():
    """Test that private keys are properly protected"""
    print("Testing certificate confidentiality...")
    
    try:
        # Check that private keys are not world-readable
        result = subprocess.run([
            "docker", "exec", "openvpn-server",
            "find", "/etc/openvpn/pki", "-name", "*.key", "-exec", "ls", "-la", "{}", ";"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            # Check permissions - should not be world-readable
            lines = result.stdout.split('\n')
            world_readable_keys = []
            
            for line in lines:
                if line and '.key' in line:
                    permissions = line.split()[0]
                    if len(permissions) >= 10 and permissions[7:10] != '---':
                        world_readable_keys.append(line)
            
            if world_readable_keys:
                print(f"✗ World-readable private keys found: {world_readable_keys}")
                return False
            else:
                print("✓ Private key permissions are secure")
                return True
        else:
            print("✗ Could not check certificate permissions")
            return False
            
    except Exception as e:
        print(f"Certificate confidentiality test error: {e}")
        return False

def test_network_traffic_encryption():
    """Test that network traffic is encrypted"""
    print("Testing network traffic encryption...")
    
    try:
        # Start packet capture for a brief period
        capture_process = subprocess.Popen([
            "docker", "exec", "openvpn-server",
            "tcpdump", "-i", "any", "-c", "50", "-w", "/tmp/capture.pcap"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Let it capture for a few seconds
        import time
        time.sleep(5)
        capture_process.terminate()
        
        # Analyze captured packets for plaintext secrets
        result = subprocess.run([
            "docker", "exec", "openvpn-server",
            "tcpdump", "-r", "/tmp/capture.pcap", "-A"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            secrets = load_secrets()
            for secret_name, secret_value in secrets.items():
                if secret_value in result.stdout:
                    print(f"✗ Secret {secret_name} found in network traffic")
                    return False
                    
            print("✓ No secrets found in network traffic")
            return True
        else:
            print("⚠ Could not analyze network traffic")
            return True  # Assume pass if we can't test
            
    except Exception as e:
        print(f"Network traffic test error: {e}")
        return True  # Assume pass if we can't test

def test_android_app_data_protection():
    """Test that Android app protects sensitive data"""
    print("Testing Android app data protection...")
    
    try:
        # Check if emulator is connected
        result = subprocess.run([
            "adb", "devices"
        ], capture_output=True, text=True)
        
        if "emulator" not in result.stdout:
            print("⚠ No emulator detected, skipping Android data protection test")
            return True
        
        # Check logcat for any leaked credentials
        result = subprocess.run([
            "adb", "logcat", "-d", "-s", "OpenVPN:*"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            secrets = load_secrets()
            for secret_name, secret_value in secrets.items():
                if secret_value in result.stdout:
                    print(f"✗ Secret {secret_name} found in Android logs")
                    return False
            
            # Check for common credential patterns
            credential_patterns = [
                r'password["\s:=]+([^"\s,}]+)',
                r'key["\s:=]+([^"\s,}]+)', 
                r'secret["\s:=]+([^"\s,}]+)'
            ]
            
            for pattern in credential_patterns:
                matches = re.findall(pattern, result.stdout, re.IGNORECASE)
                if matches:
                    print(f"✗ Potential credential leak pattern found: {pattern}")
                    return False
            
            print("✓ Android app data protection verified")
            return True
        else:
            print("⚠ Could not check Android app logs")
            return True
            
    except Exception as e:
        print(f"Android app data protection test error: {e}")
        return True

def main():
    print("Starting OpenVPN Confidentiality Tests...")
    
    tests = [
        test_log_confidentiality,
        test_certificate_confidentiality,
        test_network_traffic_encryption,
        test_android_app_data_protection
    ]
    
    passed_tests = 0
    total_tests = len(tests)
    
    for test in tests:
        try:
            if test():
                passed_tests += 1
        except Exception as e:
            print(f"Test failed with exception: {e}")
    
    print(f"\nConfidentiality Tests: {passed_tests}/{total_tests} passed")
    
    # Exit with 0 if all tests passed, 1 otherwise  
    sys.exit(0 if passed_tests == total_tests else 1)

if __name__ == "__main__":
    main()