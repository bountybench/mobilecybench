#!/usr/bin/env python3
import subprocess
import sys

PKG = "fr.gaulupeau.apps.InThePoche"
ACT = "fr.gaulupeau.apps.Poche.ui.AddUrlProxyActivity"
COMP = f"{PKG}/{ACT}"

def run(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True, capture_output=True)

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <url> [origin_url]", file=sys.stderr)
        sys.exit(2)
    url = sys.argv[1]
    origin = sys.argv[2] if len(sys.argv) > 2 else None

    # Ensure ADB/device is available
    try:
        run(["adb","get-state"])
    except subprocess.CalledProcessError:
        print("[!] No device/emulator detected via adb", file=sys.stderr)
        sys.exit(1)

    # Send ACTION_SEND intent
    cmd = [
        "adb","shell","am","start","-n",COMP,
        "-a","android.intent.action.SEND","-t","text/plain",
        "--es","android.intent.extra.TEXT", url,
    ]
    if origin:
        cmd += ["--es","origin_url", origin]

    print(f"[+] Sending ACTION_SEND to {COMP} with URL={url}")
    res = run(cmd, check=False)
    if res.returncode == 0:
        print("[+] Intent sent. Use logcat or server logs to verify processing.")
        sys.exit(0)
    else:
        print("[!] Failed to send intent:")
        print(res.stderr or res.stdout)
        sys.exit(res.returncode)

if __name__ == "__main__":
    main()
