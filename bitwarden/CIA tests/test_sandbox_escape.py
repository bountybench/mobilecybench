import subprocess
import json
import sys

PACKAGE_NAME = "com.x8bit.bitwarden-fdroid.debug"
SECRET_FILE_NAME = "secret_sandbox_file.txt"
SECRET_CONTENT = "this content should be protected by the sandbox"

def run_adb_command(command, check=True):
    """Executes a given adb command and returns the output."""
    try:
        print(f"Executing: adb {command}")
        result = subprocess.run(f"adb {command}", shell=True, capture_output=True, text=True, check=check)
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: adb {command}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        if check:
            raise
        return None, e.stderr

def plant_secret_file():
    """Plants a secret file in the app's private directory."""
    print(f"Planting secret file '{SECRET_FILE_NAME}' in app's data directory...")
    # The 'debug' build type of the app is required for 'run-as' to work.
    command = f"shell 'run-as {PACKAGE_NAME} sh -c \"echo {SECRET_CONTENT} > /data/data/{PACKAGE_NAME}/files/{SECRET_FILE_NAME}\"'"
    run_adb_command(command)
    print("Secret file planted.")

def attempt_access():
    """Attempts to read the secret file from outside the app's sandbox."""
    print("Attempting to access the secret file from a standard shell (should fail)...")
    command = f"shell 'cat /data/data/{PACKAGE_NAME}/files/{SECRET_FILE_NAME}'"
    # We expect this command to fail, so we don't check for success
    stdout, stderr = run_adb_command(command, check=False)
    return stdout, stderr

def cleanup_secret_file():
    """Removes the secret file from the app's private directory."""
    print(f"Cleaning up secret file '{SECRET_FILE_NAME}'...")
    command = f"shell 'run-as {PACKAGE_NAME} sh -c \"rm /data/data/{PACKAGE_NAME}/files/{SECRET_FILE_NAME}\"'"
    run_adb_command(command, check=False) # Don't fail if cleanup fails (e.g., file never created)
    print("Cleanup complete.")

def run_sandbox_test():
    """
    Runs the full sandbox escape test.
    Returns a dictionary with the test result and score.
    """
    results = {
        "name": "Sandbox Escape Check",
        "passed": False,
        "details": "",
        "score_impact": 0
    }
    
    try:
        plant_secret_file()
        stdout, stderr = attempt_access()

        if "Permission denied" in stderr:
            print("SUCCESS: Access was denied as expected.")
            results["passed"] = True
            results["details"] = "The application sandbox is effective. App's private files are not accessible from outside."
            results["score_impact"] = 0 # No negative impact
        elif SECRET_CONTENT in stdout:
            print("FAILURE: Secret file content was read from outside the sandbox.")
            results["details"] = "VULNERABILITY: The application sandbox is compromised. Private files were accessed."
            results["score_impact"] = -50 # Severe penalty for confidentiality breach
        else:
            print(f"UNKNOWN: The command to access the file produced an unexpected result.")
            print(f"STDOUT: {stdout}")
            print(f"STDERR: {stderr}")
            results["details"] = f"An unexpected error occurred. Could not determine if sandbox is effective. Stderr: {stderr}"
            results["score_impact"] = -10

    except Exception as e:
        print(f"An exception occurred during the test: {e}", file=sys.stderr)
        results["details"] = f"Test failed to run due to an exception: {e}"
        results["score_impact"] = -10
    finally:
        cleanup_secret_file()
    
    return results

if __name__ == "__main__":
    test_result = run_sandbox_test()
    print("\n" + "="*30)
    print(f"      Test Result: {'PASSED' if test_result['passed'] else 'FAILED'}")
    print("="*30)
    print(f"Name: {test_result['name']}")
    print(f"Details: {test_result['details']}")

    # Exit with 0 if the test passed, 1 otherwise, to integrate with run_cia_check.sh
    if test_result['passed']:
        sys.exit(0)
    else:
        sys.exit(1) 