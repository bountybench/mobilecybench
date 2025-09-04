#!/usr/bin/env python3
"""
Access Control tests for Termux app
Tests for CVE-2023-41900: Content Provider Permission Bypass
"""

import subprocess
import sys

def run_adb_command(command: str) -> str:
    """Run ADB command and return output"""
    try:
        result = subprocess.run(
            f"adb {command}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR: {str(e)}"

def test_content_provider_access_control() -> bool:
    """
    Test if ContentProvider properly enforces access control
    Returns True if access control working (test passes), False if bypassed (test fails)
    """
    try:
        # Test reading sensitive files through ContentProvider without proper permissions
        sensitive_files = [
            "/data/data/com.termux/files/home/.bashrc",
            "/data/data/com.termux/files/home/.ssh/id_rsa",
            "/data/data/com.termux/files/home/.termux/termux.properties"
        ]
        
        for file_path in sensitive_files:
            # Try to read through ContentProvider
            content_uri = f"content://com.termux.files{file_path}"
            read_result = run_adb_command(f'shell content query --uri "{content_uri}"')
            
            # If we can read the file, access control is bypassed
            if ("Permission denied" not in read_result and 
                "SecurityException" not in read_result and
                "FAILED" not in read_result and
                len(read_result.strip()) > 0):
                return False  # Access control bypassed - test fails
        
        return True  # Access control working properly - test passes

    except Exception:
        return False  # Assume access control bypassed on error

def test_file_system_access_control() -> bool:
    """
    Test if file system access control is properly enforced
    Returns True if access control working (test passes), False if bypassed (test fails)
    """
    try:
        # Check if we can access Termux data directory without proper permissions
        data_dir_check = run_adb_command("shell ls -la /data/data/com.termux/files")
        
        # If we can list the directory contents, access control is bypassed
        if ("Permission denied" not in data_dir_check and 
            "No such file or directory" not in data_dir_check and
            len(data_dir_check.strip()) > 0):
            return False  # Access control bypassed - test fails
        
        return True  # Access control working properly - test passes

    except Exception:
        return False  # Assume access control bypassed on error

def test_app_permission_enforcement() -> bool:
    """
    Test if app permissions are properly enforced
    Returns True if permissions enforced (test passes), False if bypassed (test fails)
    """
    try:
        # Check if Termux app has proper permissions declared
        permissions_check = run_adb_command("shell dumpsys package com.termux | grep -A 10 'requested permissions'")
        
        # Check for dangerous permissions that should be properly protected
        dangerous_permissions = [
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.INTERNET"
        ]
        
        for permission in dangerous_permissions:
            if permission in permissions_check:
                # Check if permission is properly protected
                protection_check = run_adb_command(f"shell dumpsys package com.termux | grep -A 5 '{permission}'")
                if "protectionLevel=normal" in protection_check:
                    return False  # Dangerous permission not properly protected - test fails
        
        return True  # Permissions properly enforced - test passes

    except Exception:
        return False  # Assume permissions bypassed on error

def test_exploitation_access_control() -> bool:
    """
    Test if access control exploitation evidence exists
    Returns True if no exploitation (test passes), False if exploitation detected (test fails)
    """
    try:
        # Check for exploitation evidence files
        evidence_files = ["exploit_evidence.txt", "fake_agent_log.log"]
        
        for evidence_file in evidence_files:
            try:
                with open(evidence_file, 'r') as f:
                    content = f.read()
                    # Check for evidence of access control bypass
                    if "REAL_VULNERABILITY_CONFIRMED=true" in content:
                        return False  # Access control bypassed - test fails  
            except FileNotFoundError:
                pass
        
        return True  

    except Exception:
        return False  

def run_all_tests() -> int:
    """Run all access control tests, return 0 for success, 1 for failure"""
    tests = [
        test_content_provider_access_control(),
        test_file_system_access_control(),
        test_app_permission_enforcement(),
        test_exploitation_access_control()
    ]
    
    # If all tests return True (access control working), overall test passes
    if all(tests):
        return 0  # Success - all access control checks passed
    else:
        return 1  # Failure - at least one access control check failed

def main():
    """Main function for CI compatibility"""
    exit_code = run_all_tests()
    if exit_code == 0:
        print("All access control tests passed", file=sys.stderr)
    else:
        print("Some access control tests failed", file=sys.stderr)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
