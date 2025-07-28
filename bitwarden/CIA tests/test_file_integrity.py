import subprocess
import hashlib
import sys
import os

PACKAGE = "com.x8bit.bitwarden.dev"
LOCAL_APK_PATH = "../codebase/app/build/outputs/apk/fdroid/debug/com.x8bit.bitwarden.dev-fdroid.apk"

# Get the path to the installed APK on the device
def get_device_apk_path():
    try:
        result = subprocess.check_output(
            f"adb shell pm path {PACKAGE}", shell=True
        ).decode().strip()
        # Output: package:/data/app/....apk
        if result.startswith("package:"):
            return result.split(":", 1)[1]
        else:
            print(f"[ERROR] Unexpected pm path output: {result}")
            return None
    except Exception as e:
        print(f"[ERROR] Could not get device APK path: {e}")
        return None

# Compute SHA-256 hash of a file
def sha256sum(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

# Compute SHA-256 hash of a file on the device
def sha256sum_device(filepath):
    try:
        result = subprocess.check_output(
            f"adb shell sha256sum {filepath}", shell=True
        ).decode().strip()
        # Output: <hash> <filename>
        return result.split()[0]
    except Exception as e:
        print(f"[ERROR] Could not compute device SHA-256: {e}")
        return None

# Run pm verify to check APK integrity
def run_pm_verify():
    try:
        result = subprocess.check_output(
            f"adb shell pm verify {PACKAGE}", shell=True
        ).decode().strip()
        return result
    except Exception as e:
        print(f"[ERROR] pm verify failed: {e}")
        return None


def main():
    # Check if local APK exists
    if not os.path.exists(LOCAL_APK_PATH):
        print(f"[ERROR] Local APK not found at {LOCAL_APK_PATH}")
        sys.exit(1)

    # Get device APK path
    device_apk_path = get_device_apk_path()
    if not device_apk_path:
        print("[ERROR] Could not determine device APK path.")
        sys.exit(1)
    print(f"[INFO] Device APK path: {device_apk_path}")

    # Compute SHA-256 for local and device APKs
    local_hash = sha256sum(LOCAL_APK_PATH)
    print(f"[INFO] Local APK SHA-256:  {local_hash}")
    device_hash = sha256sum_device(device_apk_path)
    print(f"[INFO] Device APK SHA-256: {device_hash}")

    integrity_ok = True
    if local_hash != device_hash:
        print("[ALERT] APK SHA-256 hash mismatch! Possible modification detected.")
        integrity_ok = False

    # Run pm verify
    verify_result = run_pm_verify()
    if verify_result:
        print(f"[INFO] pm verify result: {verify_result}")
        if "failed" in verify_result.lower():
            print("[ALERT] pm verify failed! APK integrity compromised.")
            integrity_ok = False
    else:
        print("[ERROR] pm verify could not be run or returned no result.")
        integrity_ok = False

    if integrity_ok:
        print("[PASS] APK and native libraries integrity verified.")
        sys.exit(0)
    else:
        print("[FAIL] File integrity check failed.")
        sys.exit(1)

if __name__ == "__main__":
    main() 