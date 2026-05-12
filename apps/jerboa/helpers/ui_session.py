#!/usr/bin/env python3
from __future__ import annotations

import os
import time
import traceback

import adbutils
import uiautomator2 as u2

JERBOA_RELEASE_PACKAGE = "com.jerboa"
JERBOA_DEBUG_PACKAGE = "com.jerboa.debug"


def configure_adb(log) -> None:
    """Point adbutils at a remote ADB server when the harness provides one."""
    socket = os.environ.get("ADB_SERVER_SOCKET", "")
    if socket and "tcp:" in socket:
        host, port = socket.replace("tcp:", "").split(":")
        log(f"Configuring ADB for remote server: {host}:{port}")
        adbutils.adb = adbutils.AdbClient(host=host, port=int(port))


def connect_u2(log, *, max_retries: int = 3, retry_delay: int = 30):
    """Connect to uiautomator2 using the same retry discipline as runtime login."""
    devices = adbutils.adb.device_list()
    if not devices:
        raise RuntimeError("No devices found")
    device_serial = devices[0].serial
    log(f"Found device: {device_serial}")

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                log(f"Retry {attempt + 1}/{max_retries} (waiting {retry_delay}s)...")
                time.sleep(retry_delay)
            d = u2.connect(device_serial)
            log("Connected via uiautomator2")
            return d, device_serial
        except Exception as exc:
            last_error = exc
            log(f"Attempt {attempt + 1} failed: {exc}")

    raise RuntimeError(
        f"Failed to connect after {max_retries} attempts"
    ) from last_error


def verify_or_recover_u2(d, device_serial: str, log):
    """Verify uiautomator2 is usable; attempt the same recovery path on failure."""
    try:
        info = d.info
        log(
            f"Device: {info.get('productName', 'unknown')} "
            f"SDK{info.get('sdkInt', 'unknown')}"
        )
        log(
            f"Window size: {d.window_size()}, "
            f"App: {d.app_current().get('package', 'unknown')}"
        )
        return d
    except Exception as exc:
        log(f"Device check failed: {exc}\n{traceback.format_exc()}")
        log("Attempting uiautomator2 server restart...")
        try:
            d.shell("am start -n com.github.uiautomator/.MainActivity")
            time.sleep(2)
            d.shell(
                "am start -n "
                "com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner"
            )
            time.sleep(2)
            d = u2.connect(device_serial)
            log(f"Recovered: {d.info.get('productName', 'unknown')}")
            return d
        except Exception as recovery_error:
            log(f"Recovery failed: {recovery_error}")
            return None


def register_anr_watchers(d, log) -> None:
    """Best-effort ANR dialog dismissal used by Jerboa UI automation."""
    try:
        d.watcher.when("Wait").click()
        d.watcher.when("OK").click()
        d.watcher.start()
        log("ANR watcher registered")
    except Exception as exc:
        log(f"Warning: Could not register watcher: {exc}")


def get_release_package(d) -> str:
    """Return the release package and enforce the release-only benchmark contract."""
    packages = d.shell("pm list packages").output
    if f"package:{JERBOA_RELEASE_PACKAGE}" not in packages:
        raise RuntimeError("Jerboa release package not installed")
    if f"package:{JERBOA_DEBUG_PACKAGE}" in packages:
        raise RuntimeError(
            "Jerboa debug package present; release-only contract violated"
        )
    return JERBOA_RELEASE_PACKAGE
