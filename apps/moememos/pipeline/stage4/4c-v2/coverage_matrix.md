# moememos - Stage 4 Coverage Matrix

## Slot counts

| category | malicious_app | remote_attacker |
|---|---:|---:|
| access | 4 | 3 |
| availability | 2 | 1 |
| confidentiality | 2 | 5 |
| integrity | 4 | 9 |
| total | 12 | 18 |

## Empty cells

- (none). All MA-* and RA-* cells contain at least one spec. MA-AV has two specs and should be treated as comparatively thin coverage.

## Input validation notes

- Scout inputs found: 10 cluster JSON files in pipeline/stage4/4b, matching all 10 clusters from clusters.json.
- Candidates ingested: 192; invalid row_ids: 0; policy rows with no scout candidate: 0.
- Existing RA specs S-001..S-018 were copied unchanged from 4c/probe_specs.json; S-019..S-030 are the added MA specs.
- Canonical MA target files are apps/moememos/test_access_control.py, test_availability.py, test_confidentiality.py, and test_integrity.py; these files do not exist yet and are expected 4d outputs.

## Per-policy-row coverage

| row_id | status | notes |
|---|---|---|
| IPC-001 | covered | S-024 |
| IPC-002 | covered | S-024, S-025 |
| IPC-003 | covered | S-027 |
| IPC-004 | covered | S-029 |
| IPC-005 | covered | S-022 |
| IPC-006 | covered | S-023 |
| IPC-007 | covered | S-024 |
| IPC-008 | covered | S-024, S-025, S-030 |
| IPC-009 | covered | S-027 |
| IPC-010 | covered | S-022 |
| IPC-011 | covered | S-023 |
| CTL-001 | uncovered: stateless | ordinary account-add positive workflow; no attacker-controlled boundary selected for 4c-v2, and account validity is a hydration prerequisite |
| CTL-002 | uncovered: stateless | ordinary account-switch positive workflow; current_user state is consumed by MA settings probes but no separate attacker-boundary spec was selected |
| CTL-003 | uncovered: stateless | ordinary account-remove positive workflow; scout candidates were local UI lifecycle checks with lower security value than direct MA/RA boundary probes |
| CTL-004 | partially-covered | server USER create/update path is covered by S-011; Android UI create/edit/pin/archive/delete workflow was not selected as an additional MA spec |
| CTL-005 | uncovered: stateless | ordinary visibility-selection UI workflow; no attacker-controlled MA/RA channel was selected for this product-positive row |
| CTL-006 | partially-covered | server tag persistence/listing is covered by S-012; Android compose tag insertion UI was not selected as an additional MA spec |
| CTL-007 | covered | S-004, S-005, S-011 |
| CTL-008 | covered | S-009 |
| CTL-009 | covered | S-009, S-010 |
| CTL-010 | covered | S-003 |
| CTL-011 | uncovered: stateless | LocalRepository denial is an implementation posture with no hydrated local/offline memo state; Stage 3 explicitly keeps this path unpopulated |
| OUT-001 | covered | S-013, S-026 |
| OUT-002 | covered | S-001, S-013 |
| OUT-003 | covered | S-001 |
| OUT-004 | covered | S-014 |
| OUT-005 | covered | S-007 |
| OUT-006 | covered | S-001 |
| OUT-007 | covered | S-001 |
| OUT-008 | partially-covered | direct remote_attacker token-catcher candidates C-NET-server-harness-boundaries-c016/c017 share S-001's channel/read/signal; row-id was not added to S-001 because the RA spec objects are intentionally preserved unchanged |
| NBF-001 | covered | S-028 |
| NBF-002 | partially-covered | inert Markdown/code storage is covered by S-015; Android WebView/JavaScript-bridge render observation was not selected separately |
| NBF-003 | covered | S-016 |
| CEX-001 | covered | S-015 |
| CEX-002 | covered | S-017 |
| CEX-003 | covered | S-016 |
| CEX-004 | covered | S-028 |
| CEX-005 | covered | S-018 |
| PER-001 | uncovered: stateless | successful login account storage is a hydration prerequisite for settings.pb probes rather than a standalone attacker-boundary spec |
| PER-002 | uncovered: stateless | current account key storage is a hydration prerequisite for settings.pb probes rather than a standalone attacker-boundary spec |
| PER-003 | uncovered: stateless | token storage is a hydration prerequisite and the denial/read consequences are covered by S-019 and S-020 |
| PER-004 | uncovered: stateless | ordinary unsent draft persistence is a local UI state transition; malicious direct draft read/write denial is covered by S-019/S-020 |
| PER-005 | uncovered: stateless | ordinary draft-clear-on-submit flow is local product behavior; no attacker-controlled boundary spec selected |
| PER-006 | covered | S-012 |
| PER-007 | covered | S-012 |
| PER-008 | covered | S-012 |
| PER-009 | covered | S-021, S-023 |
| PER-010 | covered | S-022 |
| PER-011 | uncovered: stateless | Stage 3 explicitly leaves LocalRepository unpopulated and treats local/offline memo persistence denial as stateless |
| PER-012 | covered | S-021, S-023 |
| PER-013 | covered | S-022, S-023 |
| PER-014 | covered | S-019 |
| PER-015 | covered | S-019 |
| PER-016 | covered | S-019 |
| PER-017 | covered | S-019 |
| PER-018 | covered | S-020 |
| PER-019 | covered | S-020 |
| PER-020 | covered | S-020 |
| PER-021 | covered | S-020 |
| NET-001 | covered | S-008 |
| NET-002 | uncovered: stateless | current hydration has no HTTPS server, installed test CA, or TLS fixture for certificate-chain behavior |
| NET-003 | covered | S-001 |
| NET-004 | uncovered: stateless | host normalization input is probe-supplied UI state; the existing schemed host is consumed by hydration but no MA/RA boundary spec selected |
| NET-005 | covered | S-002 |
| NET-006 | uncovered: stateless | local compose runtime is HTTP-only with no production TLS/reverse-proxy fixture |
| NET-007 | covered | S-004, S-006 |
| NET-008 | partially-covered | remote peer credential/no-victim-state candidates C-NET-server-harness-boundaries-c018/c019/c020 collapse into S-004/S-002/S-001 style RA checks; row-id was not added because the existing RA spec objects are intentionally preserved unchanged |
| CON-001 | uncovered: stateless | login submit is an ordinary user positive flow and hydration prerequisite; no attacker-controlled boundary spec selected |
| CON-002 | covered | S-024 |
| CON-003 | covered | S-026 |
| CON-004 | covered | S-022 |
| CON-005 | covered | S-025 |
| CON-006 | uncovered: stateless | visibility selection is an ordinary user UI choice; no attacker-controlled boundary spec selected |
| CON-007 | covered | S-024, S-030 |
| CON-008 | covered | S-025 |
| CON-009 | covered | S-026 |
| CON-010 | covered | S-022, S-023 |
| CON-011 | covered | S-020 |

## Unjustified gaps

(none)

## Disputed rows

- CON-003 / CON-009: Stage 4b noted that image upload may occur when the share route opens before Send. S-026 preserves that timing boundary rather than resolving the policy ambiguity in Stage 4c.
