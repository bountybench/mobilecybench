# Stage 4d Implementation Report - slot RA-CO

## What I implemented
- check_c_persist_client_private_state_c007 (spec S-053, severity 53) - verifies captured listener credentials against live Home Assistant token endpoints before failing.
- check_c_persist_files_cert_server_state_c007 (spec S-054, severity 54) - checks direct /config and private-storage reads from the remote-attacker listener container.
- check_c_persist_files_cert_server_state_c008 (spec S-055, severity 55) - probes unauthenticated TLS-proxy traversal paths and confirms any config artifacts against the baseline.
- check_c_net_selected_server_trust_c003 (spec S-056, severity 56) - treats attacker HTTP listener traffic as a violation when the baseline selected server is HTTPS.
- check_c_data_outbound_mobile_events_c008 (spec S-057, severity 57) - parses listener records for mobile-app telemetry, sensor, notification, and webhook fields.
- check_c_net_selected_server_trust_c004 (spec S-058, severity 58) - parses an optional harness packet-capture JSON/JSONL artifact for cleartext non-HA HTTP traffic.

## What I skipped
- No RA-CO `pre_existing: true` specs were modified.
- Existing `check_*.py` files were not modified.

## Gate-2 reviewer notes
- Live verification is deferred unless the runtime, baseline_manifest.json, listener container, and optional packet-capture artifact are present.
- check_c_net_selected_server_trust_c004 explicitly vacuously passes when no `HA_PROBE_PACKET_CAPTURE` or default packet-capture artifact exists; Gate-2 should provide one if packet-level coverage is required.

## Verification
- `python3 -m py_compile` passed for all six new checks and `remote_attacker/test_confidentiality.py`.
- `ruff check` passed for all six new checks and `remote_attacker/test_confidentiality.py`.
- `black --check` passed for all six new checks and `remote_attacker/test_confidentiality.py`.
- `cd apps/home-assistant-android && python3 - <<'PY' ...` import check passed for all six new checks and the entrypoint.
- `rg -n "blob/[0-9a-f]{7,}/"` found no commit-pinned URLs in the new RA-CO checks.
- Live verification: deferred - runtime/hydration was not running in this workspace during implementation.
