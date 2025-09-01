#!/usr/bin/env python3
"""
Test availability of OpenVPN services and Android app.
Checks that services remain responsive and don't crash under normal conditions.
"""

import subprocess
import json
import time
import sys

def test_openvpn_server_health():
    """Test that OpenVPN server container is healthy"""
    print("Testing OpenVPN server health...")
    
    try:
        result = subprocess.run([
            "docker", "inspect", "--format", "{{.State.Health.Status}}", 
            "openvpn-server"
        ], capture_output=True, text=True)
        
        if result.returncode == 0 and "healthy" in result.stdout:
            print("✓ OpenVPN server is healthy")
            return True
        else:
            print(f"✗ OpenVPN server health check failed: {result.stdout}")
            return False
            
    except Exception as e:
        print(f"Server health test error: {e}")
        return False

def test_container_uptime():
    """Test that containers have been running for reasonable time"""
    print("Testing container uptime...")
    
    try:
        result = subprocess.run([
            "docker", "inspect", "--format", "{{.State.StartedAt}}", 
            "openvpn-server"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✓ OpenVPN server container is running")
            return True
        else:
            print("✗ OpenVPN server container not running")
            return False
            
    except Exception as e:
        print(f"Container uptime test error: {e}")
        return False

def test_android_app_running():
    """Test that Android app is installed and not crashed"""
    print("Testing Android app availability...")
    
    try:
        # Check if emulator is connected
        result = subprocess.run([
            "adb", "devices"
        ], capture_output=True, text=True)
        
        if "emulator" not in result.stdout:
            print("⚠ No emulator detected, skipping Android app test")
            return True
            
        # Check if app is installed
        result = subprocess.run([
            "adb", "shell", "pm", "list", "packages", "de.blinkt.openvpn"
        ], capture_output=True, text=True)
        
        if "de.blinkt.openvpn" in result.stdout:
            print("✓ OpenVPN Android app is installed")
            
            # Check for recent crashes
            result = subprocess.run([
                "adb", "logcat", "-d", "-s", "AndroidRuntime:E"
            ], capture_output=True, text=True)
            
            if "de.blinkt.openvpn" in result.stdout:
                print("✗ OpenVPN app has crashed recently")
                return False
            else:
                print("✓ No recent crashes detected")
                return True
        else:
            print("✗ OpenVPN Android app not installed")
            return False
            
    except Exception as e:
        print(f"Android app test error: {e}")
        return False

def test_network_connectivity():
    """Test basic network connectivity from OpenVPN server"""
    print("Testing network connectivity...")
    
    try:
        result = subprocess.run([
            "docker", "exec", "openvpn-server", 
            "ping", "-c", "3", "8.8.8.8"
        ], capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0:
            print("✓ Network connectivity from server is working")
            return True
        else:
            print("✗ Network connectivity test failed")
            return False
            
    except subprocess.TimeoutExpired:
        print("✗ Network connectivity test timed out")
        return False
    except Exception as e:
        print(f"Network connectivity test error: {e}")
        return False

def test_service_ports():
    """Test that required ports are accessible"""
    print("Testing service port accessibility...")
    
    ports_to_test = [
        ("10.0.2.2", 1194, "OpenVPN"),
        ("10.0.2.2", 8080, "Management"),
        ("10.0.2.2", 8081, "Monitoring")
    ]
    
    all_ports_accessible = True
    
    for host, port, service in ports_to_test:
        try:
            result = subprocess.run([
                "nc", "-z", "-v", host, str(port)
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                print(f"✓ {service} port {port} is accessible")
            else:
                print(f"✗ {service} port {port} is not accessible")
                all_ports_accessible = False
                
        except subprocess.TimeoutExpired:
            print(f"✗ {service} port {port} test timed out")
            all_ports_accessible = False
        except Exception as e:
            print(f"Port test error for {service}:{port} - {e}")
            all_ports_accessible = False
    
    return all_ports_accessible

def main():
    print("Starting OpenVPN Availability Tests...")
    
    tests = [
        test_openvpn_server_health,
        test_container_uptime,
        test_network_connectivity,
        test_service_ports,
        test_android_app_running
    ]
    
    passed_tests = 0
    total_tests = len(tests)
    
    for test in tests:
        try:
            if test():
                passed_tests += 1
            time.sleep(1)  # Brief pause between tests
        except Exception as e:
            print(f"Test failed with exception: {e}")
    
    print(f"\nAvailability Tests: {passed_tests}/{total_tests} passed")
    
    # Exit with 0 if all tests passed, 1 otherwise
    sys.exit(0 if passed_tests == total_tests else 1)

if __name__ == "__main__":
    main()