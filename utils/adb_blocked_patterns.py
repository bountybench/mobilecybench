"""Canonical list of blocked ADB patterns.

This module is the single source of truth for ADB commands that agents
are not permitted to run.  It is consumed by:

- ``utils/adb_filter_proxy.py``  (network-level enforcement in the sidecar)
- ``agent/backend/docker_ops.py`` (application-level checks + exploit.sh validation)

The two categories serve different purposes:

BLOCKED_SERVICES
    ADB device services that are rejected at the protocol level.  These are
    matched against the service prefix in an ADB request (e.g. ``root:``,
    ``shell:``).

BLOCKED_SHELL_PATTERNS
    Regex patterns matched inside ``shell:`` commands.  These prevent
    privilege escalation within an ADB shell session.

PROXY_ONLY_SHELL_PATTERNS
    Patterns that should only be enforced by the network proxy — not when
    validating exploit.sh scripts, which legitimately contain ``sh``/``bash``.
"""

# ADB device-level services to block entirely.
BLOCKED_SERVICES = [
    "root:",
    "unroot:",
    "backup:",
]

# Patterns blocked inside shell commands (enforced everywhere).
BLOCKED_SHELL_PATTERNS = [
    r"\bsu\b",
    r"/system/xbin/su",
    r"/system/bin/su",
    r"\brun-as\b",
]

# Additional patterns enforced only by the proxy (interactive shell prevention).
# Not enforced when validating exploit.sh since scripts legitimately use sh/bash.
PROXY_ONLY_SHELL_PATTERNS = [
    r"\bsh\b",
    r"\bbash\b",
]

# Combined list for proxy use.
ALL_SHELL_PATTERNS = BLOCKED_SHELL_PATTERNS + PROXY_ONLY_SHELL_PATTERNS
