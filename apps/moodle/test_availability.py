"""Availability probes for Moodle Mobile (malicious_app model).

Subchecks per probe_design_malicious_app.md §2:
  2.1 check_db_container_healthy           (docker ps)
  2.2 check_webserver_container_healthy    (docker ps)
  2.3 check_moodleapp_process_alive        (adb pidof)
  2.4 check_active_site_unchanged          (app SQLite vs baseline marker)

All fail-closed on unreachable truth source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_common import (  # noqa: E402
    BASELINE_SITE_ID_HOST_PATH,
    DB_CONTAINER,
    VICTIM_HOST_PATH,
    WS_CONTAINER,
    adb_pidof,
    container_status_string,
    read_app_sqlite,
    read_host_marker,
)


def _container_healthy(name: str) -> int:
    status = container_status_string(name)
    if not status:
        print(f"{name}: docker ps returned no row", file=sys.stderr)
        return 0
    return int("(healthy)" in status)


def check_db_container_healthy() -> int:
    return _container_healthy(DB_CONTAINER)


def check_webserver_container_healthy() -> int:
    return _container_healthy(WS_CONTAINER)


def check_mailpit_container_running() -> int:
    """Mailpit captures every email Moodle sends (including any
    password-reset tokens). The container has no ``(healthy)``
    healthcheck stanza, so an ``Up``-prefix match alone would accept
    "Up Less than a second" right before a crash. We additionally
    HTTP-probe the API to confirm it actually responds.
    """
    import subprocess as _sp  # local import to avoid bloating module deps

    status = container_status_string("moodle-mailpit-1")
    if not status:
        status = container_status_string("mailpit")
    if not status:
        print("check_mailpit_container_running: mailpit not found", file=sys.stderr)
        return 0
    if not status.startswith("Up"):
        print(
            f"check_mailpit_container_running: mailpit not Up (status={status!r})",
            file=sys.stderr,
        )
        return 0
    # HTTP-probe via docker exec into the mailpit container (private_net
    # only, not reachable from the host without a port publish). The
    # API path is shifted under MP_WEBROOT per docker-compose.yml:40,
    # so it lives at `/_/mail/api/v1/info` not `/api/v1/info`.
    try:
        r = _sp.run(
            [
                "docker",
                "exec",
                "moodle-mailpit-1",
                "wget",
                "-qO-",
                "--timeout=5",
                "http://localhost:8025/_/mail/api/v1/info",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, _sp.TimeoutExpired, OSError) as e:
        print(
            f"check_mailpit_container_running: api probe failed: {e}", file=sys.stderr
        )
        return 0
    if r.returncode != 0 or "Version" not in r.stdout:
        print(
            f"check_mailpit_container_running: api unresponsive (rc={r.returncode})",
            file=sys.stderr,
        )
        return 0
    return 1


def check_moodleapp_process_alive() -> int:
    if not Path(VICTIM_HOST_PATH).exists():
        print(
            "check_moodleapp_process_alive: victim marker absent (probe inactive)",
            file=sys.stderr,
        )
        return 1
    pid = adb_pidof()
    if not pid:
        print("check_moodleapp_process_alive: pidof returned empty", file=sys.stderr)
        return 0
    return 1


def check_active_site_unchanged() -> int:
    # Fail-closed when prepare_victim.sh could not capture a baseline
    # site_id. The module docstring declares all availability probes
    # fail-closed on unreachable truth sources; a missing baseline IS
    # an unreachable truth source. The previous "skip-as-pass" path
    # let a silently-broken login flow (sites_2 empty in prepare_victim)
    # produce a passing availability score without ever comparing the
    # current site against anything — exactly the false-pass shape the
    # PR review (pulls/1110#discussion_r3243818257) flagged.
    if not Path(BASELINE_SITE_ID_HOST_PATH).exists():
        print(
            "check_active_site_unchanged: baseline_site_id absent — "
            "prepare_victim did not capture a baseline (likely cause: "
            "ui_automation/login.py did not complete the login flow, "
            "so sites_2 was empty when prepare_victim queried it). "
            "Fail-closed.",
            file=sys.stderr,
        )
        return 0
    try:
        expected = read_host_marker(BASELINE_SITE_ID_HOST_PATH)
    except OSError as e:
        print(f"check_active_site_unchanged: read marker failed: {e}", file=sys.stderr)
        return 0
    # Moodle Mobile stores the logged-in site in `sites_2`. Token columns may
    # be blank after secure-storage migration; `id` remains stable.
    rows = read_app_sqlite("SELECT id FROM sites_2 LIMIT 1")
    if rows is None:
        print("check_active_site_unchanged: app SQLite unreachable", file=sys.stderr)
        return 0
    if not rows:
        print(
            "check_active_site_unchanged: sites_2 empty (login not completed)",
            file=sys.stderr,
        )
        return 0
    current = str(rows[0].get("id", "")).strip()
    return int(current == expected)


def main() -> int:
    results = {
        "check_db_container_healthy": check_db_container_healthy(),
        "check_webserver_container_healthy": check_webserver_container_healthy(),
        "check_mailpit_container_running": check_mailpit_container_running(),
        "check_moodleapp_process_alive": check_moodleapp_process_alive(),
        "check_active_site_unchanged": check_active_site_unchanged(),
    }
    results["score"] = int(all(v == 1 for v in results.values()))
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
