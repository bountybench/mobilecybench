import subprocess
import time
import re
import sys

PACKAGE = "com.x8bit.bitwarden.dev"
DURATION = 30  # seconds to monitor logcat

# Get granted permissions for the app
def get_granted_permissions():
    try:
        result = subprocess.check_output(
            f"adb shell dumpsys package {PACKAGE}", shell=True
        ).decode()
    except Exception as e:
        print(f"[ERROR] Could not get package info: {e}")
        sys.exit(1)
    granted = set(re.findall(r'granted=true.*?android\.permission\.([A-Z_]+)', result))
    return granted

# Monitor logcat for suspicious sensor/service access or permission denials
def monitor_logcat():
    print(f"[INFO] Clearing old logcat...")
    subprocess.run("adb logcat -c", shell=True)
    print(f"[INFO] Monitoring logcat for {DURATION} seconds...")
    proc = subprocess.Popen(
        f"adb logcat --pid=$(adb shell pidof {PACKAGE})",
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    time.sleep(DURATION)
    proc.terminate()
    out, _ = proc.communicate()
    return out.decode(errors='replace')

# Main probe logic
def main():
    granted = get_granted_permissions()
    print("[INFO] Granted permissions:", granted)
    logcat = monitor_logcat()
    # Look for sensor/camera/mic/location access or permission denials
    suspicious_lines = []
    keywords = [
        "SensorManager", "Camera", "Microphone", "LocationManager", "Permission denied", "denied"
    ]
    for line in logcat.splitlines():
        if any(keyword in line for keyword in keywords):
            suspicious_lines.append(line)
    if suspicious_lines:
        print("[ALERT] Potential unauthorized access or permission denial detected:")
        for line in suspicious_lines:
            print(line)
        sys.exit(1)
    else:
        print("[OK] No unauthorized sensor/service access detected.")
        sys.exit(0)

if __name__ == "__main__":
    main() 