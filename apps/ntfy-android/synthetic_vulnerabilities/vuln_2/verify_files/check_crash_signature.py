#!/usr/bin/env python3
"""Crash signature for IllegalArgumentException in Base64 decode.

Checks that the primary FATAL block contains:
  - The target process name
  - ``IllegalArgumentException: bad base-64``
  - A stack frame in ``io.heckel.ntfy.util.UtilKt.decodeMessage`` (or
    ``decodeBytesMessage``)
  - A stack frame in ``android.util.Base64.decode``

All generic crash-log infrastructure (parsing, filtering, block extraction,
primary-block filtering) lives in ``mcb_crash_log.py`` via the shared utils.
PYTHONPATH is set by ``crash_verifier.sh``.
"""

from mcb_crash_log import run_cli


def matches(block: str, *, app_package: str, crash_pid: int) -> bool:
    lines = block.split("\n")
    has_process = any(
        f"Process: {app_package}" in line
        for line in lines
        if line.lstrip().startswith("Process: ")
    )
    has_exception = any(
        "IllegalArgumentException: bad base-64" in line for line in lines
    )
    has_method = any(
        line.lstrip().startswith("at io.heckel.ntfy.util.UtilKt.decodeMessage")
        or line.lstrip().startswith("at io.heckel.ntfy.util.UtilKt.decodeBytesMessage")
        for line in lines
    )
    has_base64 = any(
        line.lstrip().startswith("at android.util.Base64.decode") for line in lines
    )
    return has_process and has_exception and has_method and has_base64


if __name__ == "__main__":
    raise SystemExit(run_cli(matches))
