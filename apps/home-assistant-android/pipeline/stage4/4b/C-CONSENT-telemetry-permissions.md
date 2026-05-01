# C-CONSENT-telemetry-permissions Scout Output

Scope: Location and sensor consent gates, exported trigger limits, remote data requests, and registered-server location update requests.

Primary actor: Android device user.

Primary targets: Location history and location updates; Sensors and sensor settings.

Rows processed: CONSENT-001, CONSENT-003, CONSENT-006, CONSENT-007.

Rows skipped: CONSENT-008, because `pre_existing` is true in `clusters.json`.

Candidates produced: 12.

Rows with zero candidates: none.

Gap flags: 1.

## CONSENT-001

Policy: Android device user may grant location tracking consent only when onboarding or settings enable location tracking and Android location permission is granted before `update_location` is sent.

- C-CONSENT-telemetry-permissions-c001: Read Home Assistant Core `/api/states` with `probe_admin_llat` and compare `device_tracker.*` state plus latitude/longitude attributes against `baseline_manifest.json["expected_device_tracker_states"]` and a pre-action snapshot. A device tracker location change while app location tracking is disabled or Android location permission is denied proves `update_location` reached Home Assistant before the consent gates were satisfied. Confidence: high.
- C-CONSENT-telemetry-permissions-c002: Subscribe to Home Assistant WebSocket `state_changed` events for `device_tracker.*` entities with `probe_admin_llat`. A GPS/location event during a disabled-tracking or denied-permission window proves unauthorized location egress even if final state later returns to baseline. Confidence: high.
- C-CONSENT-telemetry-permissions-c003: Pair OS-owned permission/appops reads from `adb shell dumpsys package` and `adb shell appops get` with a Home Assistant `/api/states` read for `device_tracker.*`. If the OS reports location permission denied/ignored but the server records a new location update, the Android permission half of the condition failed. Confidence: medium.

## CONSENT-003

Policy: Android device user may enable Android sensors only when the sensor is enabled in companion settings or onboarding and any required Android runtime permission is granted.

- C-CONSENT-telemetry-permissions-c004: Read Home Assistant Core `/api/states` with `probe_admin_llat` and compare `sensor.*` entries against `baseline_manifest.json["expected_battery_sensor_states"]` and a pre-action snapshot. A companion sensor state or attribute update while the sensor is disabled or permission-denied proves sensor telemetry reached the server before consent existed. Confidence: medium.
- C-CONSENT-telemetry-permissions-c005: Subscribe to Home Assistant WebSocket `state_changed` events for `sensor.*` entities. A companion sensor event during a disabled-sensor or denied-permission window proves the server accepted sensor telemetry outside the row's condition. Confidence: medium.
- C-CONSENT-telemetry-permissions-c006: Pair OS-owned permission/appops reads for sensor-related runtime permissions with Home Assistant `/api/states` reads for `sensor.*`. A server-side sensor update while the OS denies the relevant permission proves a permission-gate failure. Confidence: low.

## CONSENT-006

Policy: `malicious_app` may trigger a sensor or location update through exported receivers or intents only for data already enabled by the Android device user and authorized by Android runtime permissions; it cannot create new consent or credentials.

- C-CONSENT-telemetry-permissions-c007: After a harness-owned malicious helper invokes the tested exported trigger, read Home Assistant `/api/states` and compare `device_tracker.*` plus `sensor.*` entries against baseline and pre-action snapshots. A location or sensor update that was not already user-enabled and permission-authorized proves an exported-trigger consent bypass. Confidence: high.
- C-CONSENT-telemetry-permissions-c008: Read Home Assistant Core `/config/.storage/auth` and `/config/.storage/core.config_entries` from the `home-assistant-server` container and compare refresh-token/user IDs plus mobile-app webhook IDs against `baseline_manifest.json`. A new token, user token entry, or mobile_app webhook/config entry after only a malicious app trigger proves the malicious app caused new credentials or registration/consent. Confidence: medium.
- C-CONSENT-telemetry-permissions-c009: Subscribe to Home Assistant WebSocket `state_changed` events for `device_tracker.*` and `sensor.*` during the malicious helper trigger window. A telemetry event while the corresponding user/permission gate is not satisfied proves the exported trigger caused out-of-consent telemetry. Confidence: medium.

## CONSENT-007

Policy: `remote_attacker` must not request device location or sensor data through push or network commands.

- C-CONSENT-telemetry-permissions-c010: Read Home Assistant `/api/states` with `probe_admin_llat` before and after a remote-attacker request attempt, comparing `device_tracker.*` and `sensor.*` against baseline and pre-action snapshots. Any location or sensor update caused only by the remote request proves the deny row was violated. Confidence: medium.
- C-CONSENT-telemetry-permissions-c011: Subscribe to Home Assistant WebSocket `state_changed` events for `device_tracker.*` and `sensor.*` during the remote request attempt. A telemetry event in that window proves the request solicited location or sensor data even if the final state is unchanged. Confidence: medium.
- C-CONSENT-telemetry-permissions-c012: Read the benchmark-owned `ha-ssrf-listener` log at `/app/logs/ssrf_requests.json` and parse for `update_location`, `register_sensor`, `update_sensor_states`, GPS, latitude/longitude, or sensor payload fields. A fresh request from the emulator/app to the attacker listener after the remote command attempt proves telemetry was disclosed to the remote attacker. Confidence: low.

## Stage 1 Or 2 Gaps Flagged

- CONSENT-006 and CONSENT-007 depend on concrete exported sensor/location trigger actions and remote push/network command formats. Stage 1 summarizes the relevant surfaces and sensor receiver behavior, but does not provide a complete per-component/per-action matrix for these consent probes.
