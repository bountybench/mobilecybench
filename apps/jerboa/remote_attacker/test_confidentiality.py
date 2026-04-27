#!/usr/bin/env python3
"""
Probe: Jerboa — confidentiality (remote_attacker).
Isolated entry point for consolidated evaluation engine.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _load_and_run():
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    from jerboa_probe_utils import verify_confidentiality

    return verify_confidentiality()


if __name__ == "__main__":
    sys.exit(_load_and_run())
