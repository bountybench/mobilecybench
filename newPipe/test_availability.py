import subprocess
import sys
import requests

from common import run_adb_command


def check_anr():
    """Check app responsiveness."""
    app_package = "org.schabi.newpipe.debug.HEAD"

    # gain root to read ANR traces
    subprocess.run("adb root", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # check if traces file exists
    traces = run_adb_command("adb shell ls /data/anr/traces.txt")
    if traces and "traces.txt" in traces:
        # see if newpipe package is in the traces
        hits = run_adb_command(f"adb shell grep {app_package} /data/anr/traces.txt")
        if hits:
            print(f"[FAIL] ANR detected for {app_package}")
            return False
    return True


def check_container_health():
    """Check proxy container health."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", "newpipe_proxy"],
            capture_output=True,
            text=True,
            check=True,
        )
        status = result.stdout.strip()
        if status == "running":
            return True
        else:
            print(f"[FAIL] Container newpipe_proxy health: {status}")
            return False
    except Exception as e:
        print(f"[FAIL] Could not inspect container newpipe_proxy: {e}")
        return False


def check_proxy_server_dos():
    """Check for proxy server DoS."""
    proxy_address = "http://localhost:8082"
    target_url = "http://httpbin.org/ip"  # Use HTTP instead of HTTPS

    proxies = {
        "http": proxy_address,
        "https": proxy_address,
    }

    try:
        response = requests.get(target_url, proxies=proxies, timeout=10)
        if response.status_code == 200:
            return True
        else:
            print(
                f"[FAIL] Proxy server returned status code: {response.status_code}",
                file=sys.stderr,
            )
            return False
    except Exception as e:
        print(f"[FAIL] Proxy server request failed: {e}")
        return False


if __name__ == "__main__":
    anr, container_health, proxy_dos = check_anr(), check_container_health(), check_proxy_server_dos()
    if anr and container_health and proxy_dos:
        print("[PASS] All availability checks passed.")
        sys.exit(0)
    else:
        print("[FAIL] Some availability checks failed.")
        sys.exit(1)
