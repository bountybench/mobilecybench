"""Runtime path/import setup for remote_attacker probes.

Importing this module:
- Inserts the parent app dir into ``sys.path`` so ``from tools.vuln_utils import ...``
  resolves the same way it does for the malicious_app probes that live one level up.
- Loads ``.env`` from the parent app dir, since probes may run with cwd
  pointing at this remote_attacker directory.
- Exposes ``BASELINE_PATH`` as an absolute path to ``baseline_manifest.json``
  in the parent app dir, overridable via ``BASELINE_FILE``.
"""

import os
import sys

_RA_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(_RA_DIR)

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(APP_DIR, ".env"))

# .env values like BASELINE_FILE and REQUESTS_CA_BUNDLE are written relative to
# the app dir, but probes run with cwd at this remote_attacker subdir. Resolve
# any relative entries against APP_DIR so the values work regardless of cwd.
_env_baseline = os.getenv("BASELINE_FILE", "baseline_manifest.json")
BASELINE_PATH = (
    _env_baseline
    if os.path.isabs(_env_baseline)
    else os.path.normpath(os.path.join(APP_DIR, _env_baseline))
)

_ca = os.getenv("REQUESTS_CA_BUNDLE")
if _ca and not os.path.isabs(_ca):
    os.environ["REQUESTS_CA_BUNDLE"] = os.path.normpath(os.path.join(APP_DIR, _ca))
