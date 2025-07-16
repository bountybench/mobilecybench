import sys
import subprocess
import socket

def run_command(command):
    """Run command and return success status."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except:
        return False

def check_availability():
    """Check system availability."""
    checks_passed = []
    
    # Check emulator
    if run_command("adb devices | grep device"):
        if run_command("adb shell getprop sys.boot_completed | grep 1"):
            print("Emulator is running and ready", file=sys.stderr)
            checks_passed.append(True)
        else:
            print("Emulator not ready", file=sys.stderr)
            checks_passed.append(False)
    else:
        print("No emulator connected", file=sys.stderr)
        checks_passed.append(False)
    
    # Check proxy container
    if run_command("docker ps | grep newpipe_proxy"):
        print("Proxy container is running", file=sys.stderr)
        checks_passed.append(True)
        
        # Check proxy port
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("localhost", 8082))
            sock.close()
            if result == 0:
                print("Proxy port 8082 is accessible", file=sys.stderr)
                checks_passed.append(True)
            else:
                print("Proxy port 8082 not accessible", file=sys.stderr)
                checks_passed.append(False)
        except:
            print("Could not check proxy port", file=sys.stderr)
            checks_passed.append(False)
    else:
        print("Proxy container not running", file=sys.stderr)
        checks_passed.append(False)
        checks_passed.append(False) # Also count port as failed
    
    # Check NewPipe app
    if run_command("adb shell pm list packages | grep org.schabi.newpipe.debug.newplayer"):
        print("NewPipe app is installed", file=sys.stderr)
        checks_passed.append(True)
    else:
        print("NewPipe app not installed", file=sys.stderr)
        checks_passed.append(False)
    
    # Check proxy configuration
    result = subprocess.run("adb shell settings get global http_proxy", shell=True, capture_output=True, text=True)
    if result.returncode == 0 and "10.0.2.2:8082" in result.stdout:
        print("Proxy is configured on device", file=sys.stderr)
        checks_passed.append(True)
    else:
        print("Proxy not configured on device", file=sys.stderr)
        checks_passed.append(False)
    
    # Summary
    passed = sum(checks_passed)
    total = len(checks_passed)
    
    if all(checks_passed):
        print("Availability check PASSED: All services available.", file=sys.stderr)
        return 0
    else:
        print(f"Availability check FAILED: Some services unavailable. {passed}/{total} checks passed", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(check_availability()) 