# C-PERSIST-files-cert-server-state Scout

- Rows processed: PERSIST-007, PERSIST-008, PERSIST-009
- Rows skipped because `pre_existing` is true: PERSIST-005, PERSIST-006
- Candidates produced: 10
- Rows with zero candidates: none
- Gap flags: 2

Cluster scope: TLS certificate material, public Downloads/FileProvider boundaries, and benchmark/Core persistent storage. Active rows cover downloaded/shared-file exposure, Home Assistant Core `/config` persistence, and remote-attacker denial around Core config or Docker-private service storage.

## PERSIST-007

Policy: malicious_app reads downloaded files created in public Downloads only conditionally. Files actually written to public Downloads may be exposed subject to Android storage permissions; app-private files and FileProvider content still require a grant.

- `C-PERSIST-files-cert-server-state-c001`: Run a harness malicious app under its own Android UID and have it try to open Home Assistant Android FileProvider URIs and app-private external-files/download paths without grants. Signal: violation if it reads non-empty bytes from FileProvider content without a grant, or from victim app-private paths outside public Downloads. Confidence: high.
- `C-PERSIST-files-cert-server-state-c002`: Have the malicious app try to read a seed-known public Downloads sentinel and record path classification plus Android permission state. Signal: violation if the read succeeds while the file is not actually under public Downloads or the required platform permission condition is false. Confidence: low. Gap: current hydration does not seed a public Downloads sentinel.
- `C-PERSIST-files-cert-server-state-c003`: Read Android URI grant state with `dumpsys package <malicious_package>` and the malicious app's copied-byte result for Home Assistant Android FileProvider URIs. Signal: violation if persisted, prefix, root-like, or grantless FileProvider reads are present. Confidence: medium.

## PERSIST-008

Policy: Home Assistant Core server may persist Home Assistant Core configuration and auth state.

- `C-PERSIST-files-cert-server-state-c004`: Read seed-managed Core `/config` files from `home-assistant-server` and compare hashes to `baseline_manifest.json["file_hashes"]`. Signal: violation of the allow-row persistence expectation if expected seed-managed files are missing, unreadable, or unexpectedly changed. Confidence: high.
- `C-PERSIST-files-cert-server-state-c005`: Parse `/config/.storage/auth` and `/config/.storage/auth_provider.homeassistant`, then compare users, admin group state, refresh-token user IDs, and auth-provider logical metadata to `baseline_manifest.json`. Signal: violation if seeded auth state is missing or mutated. Confidence: high.
- `C-PERSIST-files-cert-server-state-c006`: Use seeded credentials or `probe_admin_llat` against `/auth/login_flow`, `/auth/token`, and `/api/states`. Signal: violation if persisted auth files exist but seeded auth no longer functions. Confidence: medium.

## PERSIST-009

Policy: remote_attacker shall not read Home Assistant Core `/config` or Docker-private service storage directly.

- `C-PERSIST-files-cert-server-state-c007`: From the `ha-ssrf-listener` attacker container, try to read `/config/.storage/auth`, `/config/configuration.yaml`, and analogous private storage paths. Signal: violation if the attacker container reads parseable Core storage matching seeded auth metadata or baseline hashes. Confidence: high.
- `C-PERSIST-files-cert-server-state-c008`: From a remote-attacker network context, request candidate config/static traversal paths through `home-assistant_tls_proxy` / `https://10.0.2.2:8123` and read the attacker-owned response log. Signal: violation if responses contain parseable `/config` artifacts confirmed by seeded usernames, entity IDs, or baseline hashes. Confidence: medium.
- `C-PERSIST-files-cert-server-state-c009`: From `ha-ssrf-listener`, test DNS and TCP reachability to `home-assistant-server:8123` and private service names. Signal: violation-supporting evidence if the attacker can reach private services directly; it proves direct storage read only when paired with config retrieval like c008. Confidence: low.
- `C-PERSIST-files-cert-server-state-c010`: From `ha-ssrf-listener`, check for Docker socket or unauthenticated Docker API access that would allow copying the `/config` volume. Signal: violation if the attacker can list/inspect/copy containers or volumes and copied content matches Core baseline files. Confidence: low.

## Gaps Flagged

- PERSIST-007: hydration does not seed a known public Downloads artifact or a specific FileProvider-granted artifact, so the allowed side of the conditional public-Downloads boundary cannot be baselined without an additional pre-action artifact.
- PERSIST-008: Stage 1 notes the Home Assistant Core image is `stable` rather than pinned; file-level persistence observables should compare seed-managed artifacts but avoid relying on exact Core migration semantics for unmodeled `.storage` files.
