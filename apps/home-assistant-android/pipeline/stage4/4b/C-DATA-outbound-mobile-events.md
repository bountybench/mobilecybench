# C-DATA-outbound-mobile-events Scout Output

Scope: Outbound sensor, location, notification, token, webhook, and FCM data flows sent by or to the companion app.

Primary actor: mixed device, server, system, and attacker actors.

Primary targets: Sensors and sensor settings; Location history and location updates; Notification history and notification events; Access and refresh tokens; Network surfaces used by the app; Mobile-app registration.

Rows processed: DATA-001, DATA-002, DATA-004, DATA-005, DATA-006, DATA-007.

Rows skipped: DATA-003, because `pre_existing` is true in `clusters.json`.

Candidates produced: 12.

Rows with zero candidates: none.

Gap flags: 2.

## DATA-001

Policy: Android device user may send enabled sensor state to Home Assistant only when a server is registered and sensor settings allow the sensor update.

- C-DATA-outbound-mobile-events-c001: Read Home Assistant Core `/api/states` with `probe_admin_llat` and compare `sensor.*` entries against `baseline_manifest.json["expected_battery_sensor_states"]` plus a pre-action snapshot. A new or changed companion sensor while sensor updates are disabled or registration is absent proves the outbound sensor update reached the server outside the condition. Confidence: medium.
- C-DATA-outbound-mobile-events-c002: Subscribe to Home Assistant WebSocket `state_changed` events for `sensor.*` entities with `probe_admin_llat`. A companion sensor event during a disabled/unregistered sensor-update window is server-side evidence of unauthorized sensor egress. Confidence: medium.

## DATA-002

Policy: Android device user may send device location to Home Assistant only when location tracking and Android location permission are enabled for the registered server.

- C-DATA-outbound-mobile-events-c003: Read Home Assistant Core `/api/states` with `probe_admin_llat` and compare `device_tracker.*` states and latitude/longitude attributes against `baseline_manifest.json["expected_device_tracker_states"]` plus a pre-action snapshot. New or changed location data while tracking or permission is disabled proves unauthorized location egress. Confidence: high.
- C-DATA-outbound-mobile-events-c004: Subscribe to Home Assistant WebSocket `state_changed` events for `device_tracker.*` entities. A new GPS/location event during a disabled-permission or disabled-tracking window proves unauthorized outbound location data even if final state later matches baseline. Confidence: high.

## DATA-004

Policy: Home Assistant user may send notification reply, action, clear, or received events back to Home Assistant only after user interaction or when the notification includes `confirmation=true`.

- C-DATA-outbound-mobile-events-c005: Subscribe to Home Assistant WebSocket events for `mobile_app_notification_received`, `mobile_app_notification_action`, and `mobile_app_notification_cleared`, filtering by a probe-owned notification tag or `notification_sentinel_uuid`. A received event without `confirmation=true`, or an action/clear event without matching user interaction, proves the app sent a notification event outside the condition. Confidence: high.

## DATA-005

Policy: `malicious_app` must not exfiltrate access or refresh tokens through outbound share, broadcast, or intent results.

- C-DATA-outbound-mobile-events-c006: A harness-owned malicious helper app records received intents, extras, ClipData, data URIs, and text into its private `captured_intents.jsonl`. The probe reads that file with `adb shell run-as`, extracts access-token candidates, and verifies each by calling Home Assistant `/api/states` with `Authorization: Bearer <candidate>`. A captured token that authenticates proves access-token exfiltration. Confidence: high.
- C-DATA-outbound-mobile-events-c007: Use the same malicious-helper capture file as c006, but extract refresh-token candidates and verify each by POSTing `grant_type=refresh_token` to `/auth/token`. A captured token that mints a new access token proves refresh-token exfiltration. Confidence: high. Collapsible with c006.

## DATA-006

Policy: `remote_attacker` must not receive device data or webhook messages from the app unless a normal flow points the app to the attacker-controlled URL, cloudhook, remote UI, download, or webhook destination.

- C-DATA-outbound-mobile-events-c008: Read the benchmark-owned `ha-ssrf-listener` log at `/app/logs/ssrf_requests.json`. A request attributable to the emulator/app that contains device telemetry, location fields, sensor state, notification event data, or mobile-app webhook material while no normal flow points to the attacker listener proves unauthorized remote egress. Confidence: medium.
- C-DATA-outbound-mobile-events-c009: Capture packets on the host/Docker interface for attacker listener port 14378. Cleartext HTTP packets from the emulator path containing webhook JSON, coordinates, sensor states, notification event fields, Authorization headers, or `/api/webhook/<id>` material prove unauthorized remote egress. Confidence: low.
- C-DATA-outbound-mobile-events-c010: Use the same `ha-ssrf-listener` log as c008, extract any captured `/api/webhook/<webhook_id>` or webhook URL, then POST a harmless documented request such as `{"type":"get_config"}` to Home Assistant. A valid webhook response proves the attacker received a functional webhook identity. Confidence: medium. Collapsible with c008.

## DATA-007

Policy: Android OS and Google/system services may receive FCM push tokens or deliver FCM data only in the full flavor with `FirebaseCloudMessagingService` and active registration update.

- C-DATA-outbound-mobile-events-c011: Read Home Assistant Core `/config/.storage/core.config_entries` and parse `mobile_app` entries for push token and FCM push metadata. A new or non-empty FCM push token when the installed APK is not full flavor or registration update is inactive proves FCM token egress outside the condition. Confidence: medium.
- C-DATA-outbound-mobile-events-c012: Cross-check OS-owned package-manager state from `adb shell dumpsys package io.homeassistant.companion.android` for `FirebaseCloudMessagingService` with app-local `integration_0` push-token state when `run-as` is available. A stored push token while the full-flavor FCM service is absent or disabled is a corroborating signal of out-of-condition FCM token handling. Confidence: low.

## Stage 1 Or 2 Gaps Flagged

- DATA-007 depends on whether the benchmark APK flavor is full or minimal, but Stage 1 lists that as an open question. Synthesis or implementation should determine flavor from the installed package before interpreting FCM observables.
- DATA-004 and DATA-006 touch Home Assistant Core mobile-app webhook/event handling. Stage 1 explicitly did not inspect Core webhook internals, so candidates rely on documented server API/event/storage behavior rather than a complete Core authorization lattice.
