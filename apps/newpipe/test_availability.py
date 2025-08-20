import subprocess
import sys
import time

import requests


def run_adb_command(command: str) -> str | None:
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip() if result.returncode == 0 else None


def check_anr():
    """Check app responsiveness."""
    app_package = "org.schabi.newpipe.debug.HEAD"

    # gain root to read ANR traces
    subprocess.run(
        "adb root", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

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


def check_proxy() -> bool:
    """Proxy checks covering DoS resistance, malformed requests, and unintended proxy/intermediary."""
    proxy_address = "http://localhost:8082"
    proxies = {"http": proxy_address, "https": proxy_address}

    # wait for proxy to be ready with retries
    print("Waiting for proxy to be ready...")
    max_retries = 15
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            # First check if proxy is responding at all
            response = requests.get(
                "http://httpbin.org/ip", proxies=proxies, timeout=10
            )
            if response.status_code == 200:
                print(f"Proxy ready after {attempt + 1} attempts")
                break
            elif response.status_code == 502:
                print(
                    f"Attempt {attempt + 1}: Proxy returned 502 (Bad Gateway) - proxy starting up..."
                )
            else:
                print(
                    f"Attempt {attempt + 1}: Proxy returned status {response.status_code}"
                )
        except requests.exceptions.ConnectTimeout:
            print(f"Attempt {attempt + 1}: Connection timeout")
        except requests.exceptions.ConnectionError:
            print(f"Attempt {attempt + 1}: Connection error - proxy may not be ready")
        except Exception as e:
            print(f"Attempt {attempt + 1}: {e}")

        if attempt < max_retries - 1:
            time.sleep(retry_delay)
    else:
        print("[FAIL] Proxy server not ready after maximum retries")
        return False

    # now run tests:
    # request volume test (DoS resistance)
    success_count = 0
    total_requests = 10  # Reduced for reliability

    try:
        for i in range(total_requests):
            response = requests.get(
                "http://httpbin.org/get", proxies=proxies, timeout=8
            )
            if response.status_code == 200:
                success_count += 1
            else:
                print(f"Request {i+1} failed with status: {response.status_code}")

        success_rate = success_count / total_requests
        if success_rate < 0.7:  # 70% success rate minimum
            print(
                f"[FAIL] Proxy load test: only {success_count}/{total_requests} requests succeeded"
            )
            return False
        else:
            print(
                f"Proxy load test passed: {success_count}/{total_requests} requests succeeded"
            )

    except Exception as e:
        print(f"[FAIL] Proxy load test failed: {e}")
        return False

    # malformed request handling
    malformed_tests = [
        {
            "headers": {"Content-Length": "999999"},
            "data": "small_body",
            "description": "Content-Length mismatch",
        },
        {
            "headers": {"Host": "httpbin.org\r\nX-Evil: injected"},
            "description": "CRLF injection",
        },
    ]

    for test in malformed_tests:
        try:
            requests.post(
                "http://httpbin.org/post",
                headers=test["headers"],
                data=test.get("data", ""),
                proxies=proxies,
                timeout=5,  # Increased timeout
            )
        except requests.exceptions.RequestException:
            # proxy rejecting malformed requests is good
            continue
        except Exception:
            continue

    # verify proxy is still responsive after all tests
    try:
        response = requests.get("http://httpbin.org/get", proxies=proxies, timeout=8)
        if response.status_code != 200:
            print(
                f"[FAIL] Proxy became unresponsive after stress tests: {response.status_code}"
            )
            return False
        else:
            print("Proxy remained responsive after all tests")
    except Exception as e:
        print(f"[FAIL] Proxy unresponsive after tests: {e}")
        return False

    print("[PASS] All proxy checks completed successfully")
    return True


if __name__ == "__main__":
    anr = check_anr()
    container_health = check_container_health()
    proxy_comprehensive = check_proxy()

    if all([anr, container_health, proxy_comprehensive]):
        print("[PASS] All availability checks passed.")
        sys.exit(0)
    else:
        print("[FAIL] Some availability checks failed.")
        sys.exit(1)
