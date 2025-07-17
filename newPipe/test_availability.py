import sys
import subprocess
import socket

def run_command(command):
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None

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

        # Verify mitmproxy process inside the container
        if run_command("docker exec newpipe_proxy sh -c 'ps aux | grep -i mitmproxy | grep -v grep'"):
            print("Mitmproxy process running inside container", file=sys.stderr)
            checks_passed.append(True)
        else:
            print("Mitmproxy process not running inside container", file=sys.stderr)
            checks_passed.append(False)
    else:
        print("Proxy container not running", file=sys.stderr)
        checks_passed.append(False)
        checks_passed.append(False) # Also count port as failed
    
    # Check NewPipe app
    if run_command("adb shell pm list packages | grep org.schabi.newpipe.debug.newplayer"):
        print("NewPipe app installed", file=sys.stderr)
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
    
    passed = sum(checks_passed) / len(checks_passed)
    if passed == 1:
        print("Availability check passed: All services available.", file=sys.stderr)
        return 0
    else:
        print(f"Availability check failed: Some services unavailable. {passed} checks passed", file=sys.stderr)
        return 1

if __name__ == "__main__":
    check_availability()