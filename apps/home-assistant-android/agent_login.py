#!/usr/bin/env python3
"""Pre-agent login: sign HA Android in as the agent's user.

Runs once on the dedicated agent-epoch emulator (see workflows/redteam.py:
_run_agent_login). The per-phase emulator restart wipes this state before
prepare_victim re-seeds the victim, so agent_login and prepare_victim
never coexist on the same epoch.

Reuses prepare_victim.run() so the onboarding flow has a single source of
truth. Overrides: agent credentials (metadata.json username/password —
the same fields workflows/base.py:_agent_credentials returns to the agent
prompt) and no_capture=True (baseline belongs to the victim epoch).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import prepare_victim

APP_DIR = Path(__file__).resolve().parent


def main() -> int:
    meta = json.loads((APP_DIR / "metadata.json").read_text())
    args = argparse.Namespace(
        username=meta["username"],
        password=meta["password"],
        server_url=meta["emulator_server"],
        no_capture=True,
    )
    try:
        prepare_victim.run(args)
    except Exception:
        import logging

        logging.exception("agent_login failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
