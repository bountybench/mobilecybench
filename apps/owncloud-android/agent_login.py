#!/usr/bin/env python3
"""Pre-agent login: log the agent's user into ownCloud Android.

Reuses prepare_victim's OAuth flow with agent credentials from metadata.json,
skipping baseline capture (baselines belong to the victim epoch and would be
overwritten with agent state). Runs once before the agent sees the env;
the per-phase emulator restart in evaluate() isolates this from
prepare_victim's per-phase state.
"""
import argparse
import json
import os
import sys

import prepare_victim

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    with open(os.path.join(SCRIPT_DIR, "metadata.json"), encoding="utf-8") as f:
        meta = json.load(f)
    prepare_victim.run(
        argparse.Namespace(
            username=meta["username"],
            password=meta["password"],
            server_url=meta["emulator_server"],
            no_capture=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        prepare_victim.log(f"ERROR: {exc}")
        prepare_victim._dump_state_on_error()
        sys.exit(1)
