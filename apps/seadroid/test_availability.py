import argparse
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def parse_host_port_from_url(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    if parts.port is not None:
        port = parts.port
    else:
        if parts.scheme == "https":
            port = 443
        else:
            port = 80
    return host, port


def check_tcp_connectivity(
    host: str, port: int, timeout_seconds: float
) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, f"TCP connection to {host}:{port} succeeded"
    except Exception as exc:  # ConnectionRefusedError, TimeoutError, OSError
        return False, f"TCP connection to {host}:{port} failed: {exc}"


def check_http_status(url: str, timeout_seconds: float) -> tuple[bool, str]:
    try:
        # Use GET to mimic the original curl check, and reject HTTP >= 400 like curl -f
        req = Request(
            url, method="GET", headers={"User-Agent": "availability-check/1.0"}
        )
        with urlopen(req, timeout=timeout_seconds) as resp:
            status = getattr(resp, "status", 200)
            if 200 <= status < 400:
                return True, f"HTTP {status} from {url}"
            return False, f"Unhealthy HTTP status {status} from {url}"
    except HTTPError as err:
        return False, f"HTTP error {err.code} from {url}"
    except URLError as err:
        return False, f"URL error for {url}: {err.reason}"
    except Exception as exc:
        return False, f"Request to {url} failed: {exc}"


def perform_availability_check(
    url: str,
    tcp_timeout: float,
    http_timeout: float,
    retries: int,
    backoff_seconds: float,
) -> bool:
    host, port = parse_host_port_from_url(url)

    for attempt in range(1, retries + 1):
        tcp_ok, tcp_msg = check_tcp_connectivity(host, port, tcp_timeout)
        if not tcp_ok:
            print(f"❌ {tcp_msg}")
            if attempt < retries:
                time.sleep(backoff_seconds)
            continue
        else:
            print(f"✅ {tcp_msg}")

        http_ok, http_msg = check_http_status(url, http_timeout)
        if http_ok:
            print(f"✅ {http_msg}")
            return True
        else:
            print(f"❌ {http_msg}")
            if attempt < retries:
                time.sleep(backoff_seconds)

    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Availability check for local server")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/",
        help="URL to probe (default: http://localhost:8000/)",
    )
    parser.add_argument(
        "--retries", type=int, default=3, help="Number of retry attempts (default: 3)"
    )
    parser.add_argument(
        "--tcp-timeout",
        type=float,
        default=2.0,
        help="TCP connect timeout in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=5.0,
        help="HTTP request timeout in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--backoff",
        type=float,
        default=1.0,
        help="Sleep between retries in seconds (default: 1.0)",
    )
    args = parser.parse_args()

    ok = perform_availability_check(
        url=args.url,
        tcp_timeout=args.tcp_timeout,
        http_timeout=args.http_timeout,
        retries=args.retries,
        backoff_seconds=args.backoff,
    )

    if ok:
        print("✅ Server is available and accepting connections")
        return 0
    else:
        print("❌ Server is not accepting connections")
        return 1


if __name__ == "__main__":
    sys.exit(main())
