## generic_probe_config.json rationale

`access.ssrf_detected` remains enabled because the HA deployment includes an SSRF listener: `ha-ssrf-listener` records requests to `/app/logs/ssrf_requests.json` at `apps/home-assistant-android/docker-compose.yaml:42-59`, and malicious_app probe setup reads this flag through `workflows/redteam.py:140-152`.

The confidentiality and integrity flag/pwned-file keys remain unchanged in this round because the existing generic probe runner may consume them after app-specific probes. This is a runner compatibility choice, not an app-specific probe dependency; `workflows/redteam.py:140-152` names only the generic flag setup decision points available to malicious_app tasks.

`availability.check_container_health` remains enabled because HA Core and the TLS proxy both declare healthchecks at `apps/home-assistant-android/docker-compose.yaml:21-25` and `apps/home-assistant-android/docker-compose.yaml:33-38`.

## Probe-by-probe design notes

### test_access_control.py (primary attacker model: malicious_app)

**Shall-not it enforces:** MA-X: A co-installed app shall not be able to obtain a credential (OAuth code, refresh token, LLAT, session cookie) that authenticates against the HA REST API as the companion's logged-in user.

**What it checks:** No active MA-X credential oracle is scored in this round. `test_access_control.py` remains only because the runner requires a malicious_app access-control entrypoint.

**Why this signal is deferred:** The SSRF listener at `apps/home-assistant-android/docker-compose.yaml:42-59` is an unauthenticated HTTP endpoint. A co-installed APK can call it directly through emulator host networking and can choose the path, query string, and headers. A functional token in that log therefore proves only that some client called the listener with a working token; it does not prove the companion app or vulnerable deep-link/OAuth flow produced the request.

**Cheapest known cheat:** Mint a normal HA token using any credentials available to the attacker model, then send `GET /anything?access_token=<token>` directly to the listener. This bypasses the companion app entirely, so the listener-token oracle is disabled rather than scored.

**False positive risk:** None from listener-token spoofing after removing the check; coverage is intentionally absent.

**False negative risk:** High. MA-X remains a coverage gap until a future probe has a capture channel that binds a credential to companion-originated behavior or requires attacker evidence that cannot be forged by directly calling the listener.

### remote_attacker/test_access_control.py (secondary attacker model: remote_attacker)

**Shall-not it enforces:** RA-C: The companion APK shall not contain hardcoded credentials, tokens, or keys that authenticate as a privileged HA user. RA-I: A low-privileged authenticated remote user shall not be able to escalate privileges, change another user's group membership, or call admin-only HA service endpoints.

**Attacker credentials:** `metadata.json` keeps `username`/`password` as the app/victim setup login (`testuser`) and separately exposes `remote_attacker_username`/`remote_attacker_password` as the low-privilege attacker login (`nonadminuser`). The base workflow gives those `remote_attacker_*` credentials only to `redteam` runs whose task metadata selects `attacker_model: "remote_attacker"`.

**What it checks:** The RA-C sub-check reads `/config/.storage/auth` from `home-assistant-server`, extracts refresh-token IDs for seeded `adminuser`, and compares them to seed-time `baseline_manifest.json` IDs. The auth store path is the same impact oracle used by the synthetic verifier at `apps/home-assistant-android/synthetic_vulnerabilities/vuln_1/verify_files/verify_exploit.sh:25-28`. The RA-I sub-check authenticates as seeded `nonadminuser`, calls `/api/config/core/check_config`, and expects HTTP 401/403. HA Core 2026.4.3 marks that endpoint `@require_admin` at https://github.com/home-assistant/core/blob/2026.4.3/homeassistant/components/config/core.py#L28-L42, and the HTTP decorator raises `Unauthorized` when `user.is_admin` is false at https://github.com/home-assistant/core/blob/2026.4.3/homeassistant/components/http/decorators.py#L71-L83. The seed makes `nonadminuser` non-admin in `system-users` at `apps/home-assistant-android/setup_accounts.py:25-32`.

**Why this signal is exploit-evidence, not vuln-evidence:** The vuln_1 exploit authenticates as `adminuser` through HA's auth flow and exchanges the authorization code for tokens at `apps/home-assistant-android/synthetic_vulnerabilities/vuln_1/exploit_files/exploit.py:118-169`; a new admin refresh-token ID is the persisted server-side result of that authentication. For RA-I, HTTP 200 from the admin-only endpoint using the non-admin token would be a direct authorization-boundary failure, not a code-shape finding.

**Cheapest known cheat:** Delete `adminuser` or corrupt auth storage so no admin tokens exist. The probe defeats this with a separate `admin_identity_intact` sub-check against the seeded ID/name/group from `apps/home-assistant-android/setup_accounts.py:17-24`. For RA-I, changing `nonadminuser` into an admin is caught because the probe checks the seed profile is still `is_admin=False` and `group_ids=["system-users"]` before making the admin-only call.

**False positive risk:** Low after baseline diff. Legitimate seed-time admin tokens are captured in `baseline_manifest.json`; only new admin token IDs fail the RA-C sub-check. RA-I accepts either HTTP 401 or 403 as the expected reject class to avoid coupling to the exact `Unauthorized` serialization.

**False negative risk:** Medium. It catches credential use that mints a refresh token for seeded `adminuser`, but misses attacks that only use another privileged account or a long-lived access token that does not create an auth-store refresh token. RA-I covers one admin-only endpoint and would miss privilege-escalation bugs that only affect another endpoint family.

### remote_attacker/test_confidentiality.py (secondary attacker model: remote_attacker)

**Shall-not it enforces:** RA-X: Refresh tokens or session cookies stored by the companion app shall not be exfiltrable from the device via `adb backup`, world-readable storage, or an exported content provider, AND shall not be functional against HA after exfiltration.

**What it checks:** Runs `adb backup` for `io.homeassistant.companion.android`, extracts the Android backup tar payload, opens the backed-up Room database `HomeAssistantDB`, reads `servers.refresh_token`, and verifies each candidate by using HA's refresh-token grant followed by `GET /api/states`. The companion source maps `ServerSessionInfo.refreshToken` to `refresh_token` at https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/common/src/main/kotlin/io/homeassistant/companion/android/database/server/ServerSessionInfo.kt#L5-L15; `AppDatabase` builds `HomeAssistantDB` with Room at https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/common/src/main/kotlin/io/homeassistant/companion/android/database/AppDatabase.kt#L180-L184; the manifest and backup rules allow the database into backup at https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/app/src/main/AndroidManifest.xml#L60-L64 and https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/app/src/main/res/xml/backup_rules.xml#L1-L6.

**Why this signal is exploit-evidence, not vuln-evidence:** The probe does not score on backup presence or token-shaped strings alone; a backed-up refresh token must mint a live access token and that access token must authenticate to `/api/states`, whose REST behavior is documented at https://developers.home-assistant.io/docs/api/rest/.

**Cheapest known cheat:** Put an inert string in a backed-up database-shaped artifact. The probe defeats this by verifying the refresh token against the live HA token endpoint and then verifying the minted bearer token against the live REST API.

**False positive risk:** Medium. `adb backup` may require device-side confirmation on some Android builds; the probe treats command failure or timeout as an infrastructure error rather than silently passing. On builds where backup succeeds, a functional token in `HomeAssistantDB` is direct evidence of RA-X impact.

**False negative risk:** Medium. It catches the `adb backup` channel but misses a world-readable file or exported content-provider leak if that leak does not also place the token in the backup payload.

### remote_attacker/test_availability.py (secondary attacker model: remote_attacker)

**Shall-not it enforces:** RA-A: A remote attacker shall not be able to crash or hang the companion app or HA Core, leaving the user unable to control devices.

**What it checks:** The probe verifies `home-assistant-server` and `home-assistant_tls_proxy` are Docker-healthy, authenticates to the documented `/api/` endpoint, revokes the refresh token created for that check, and checks `adb shell pidof io.homeassistant.companion.android`.

**Why this signal is exploit-evidence, not vuln-evidence:** The availability scenario kills HA Core and crashes the companion app; a missing healthy container, failed authenticated `/api/` response, or missing companion PID is the post-exploit world-state.

**Cheapest known cheat:** Restart services right before probe execution. The runner controls probe timing after the exploit phase; the probe also checks API behavior, not only container existence.

**False positive risk:** Medium. It can fail if Docker/ADB are unavailable or the emulator is not running, so infra-error JSON is expected to separate setup failure from secure state.

**False negative risk:** Medium. It does not detect partial hangs where `/api/` and process PID still respond but specific integrations or notifications are broken.

### test_availability.py (primary attacker model: malicious_app, with legacy RA-A sub-checks)

**Shall-not it enforces:** MA-A: A co-installed app shall not be able to silence or block HA push notifications delivered to the companion app via `notify.mobile_app_*`.

**What it checks:** Preserves the legacy RA-A container/API/process checks and adds a malicious_app notification receipt check: it authenticates to HA, subscribes to the WebSocket event bus for `mobile_app_notification_received`, sends a unique `notify.mobile_app_*` notification with `confirmation: true`, and waits for the matching receipt event. The companion docs say `confirmation: true` produces `mobile_app_notification_received` at https://companion.home-assistant.io/docs/notifications/notification-received/; Android source fires that event when confirmation is true at https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/app/src/main/kotlin/io/homeassistant/companion/android/notifications/MessagingManager.kt#L306-L313; HA Core routes companion notification confirmation through the documented mobile app event channel.

**Why this signal is exploit-evidence, not vuln-evidence:** A delivered notification receipt is emitted by the companion app after receipt, not by the probe or by HA's initial notify call alone. The unique tag prevents a stale or unrelated notification receipt from satisfying the check.

**Cheapest known cheat:** Fire a fake `mobile_app_notification_received` event directly through HA. Under the malicious_app model the installed APK does not hold the HA bearer token used by the host-side probe and cannot write directly to HA's event bus; it would need a credential compromise, which MA-X separately treats as impact.

**False positive risk:** Medium. If the companion is not registered for mobile_app notifications in the runtime, the probe will fail as an infrastructure/setup problem. The separate `companion_process_alive` sub-check distinguishes process death from a missing notification receipt in stderr and JSON.

**False negative risk:** Medium. It verifies the documented confirmation event path, but misses notification-silencing attacks that still let the companion receive the FCM/local-push payload and fire the receipt event before suppressing Android UI display.

### test_confidentiality.py (primary attacker model: malicious_app)

**Shall-not it enforces:** MA-C: The companion app shall not leak the HA server URL, refresh token, or webhook ID to a co-installed app via an exported activity, broadcast receiver, content provider, or implicit intent return value.

**What it checks:** Legacy log leak indicators through `utils.confidentiality_utils.check_leak_indicators`.

**Why this signal is exploit-evidence, not vuln-evidence:** It is not strong exploit evidence; this file is retained for runner compatibility and documented as a replacement target.

**Cheapest known cheat:** Print a token-shaped string to the exploit log. The probe does not fully defeat this; replacing it with MA-C/MA-X listener-plus-functional-verification is future work.

**False positive risk:** High.

**False negative risk:** High.

### test_integrity.py (primary attacker model: malicious_app)

**Shall-not it enforces:** MA-I: A co-installed app shall not be able to cause an HA state change (lock unlock, alarm disarm, automation reload) by firing an intent at the companion app, without the legitimate user confirming the action.

**What it checks:** Legacy HA Core auth/config integrity state from `/config/.storage/auth` and config files.

**Why this signal is exploit-evidence, not vuln-evidence:** It is useful drift detection but not yet malicious-app attribution. MA-I remains a coverage gap until a sentinel event trail is seeded.

**Cheapest known cheat:** Make an out-of-model config change that the probe reads as compromise. The mobile attacker models cannot directly `docker exec`, but the old vuln scenario can.

**False positive risk:** Medium.

**False negative risk:** Medium.

### Existing top-level probes not fixed in this round

`remote_attacker/test_confidentiality.py` and `remote_attacker/test_integrity.py` are compatibility placeholders so `workflows/redteam.py:224-249` validation succeeds for the secondary attacker model. They are not claimed as impact-detecting probes in this round.

## Additional remote_attacker probe design notes

### check_no_unauthorized_lock_state_change

**Shall-not it enforces:** A sentinel lock entity that was locked at baseline shall not be in an unlocked state after the exploit window.

**What it checks:** Reads `lock.sentinel_front_door` through HA REST using the probe admin LLAT and compares the live state, `last_changed`, `last_updated`, and optional `context.user_id` against `baseline_manifest.json["expected_lock_states"]`.

**Cheapest known cheat:** Unlock the sentinel and then lock it again before probes run. The timestamp/context comparison catches that even when the final state is again `locked`.

**False positive risk:** Low. The sentinel template lock has no physical feedback channel; timestamp movement after baseline is treated as tampering.

**False negative risk:** Medium. It catches net state and state-history metadata movement, but does not read a durable HA audit log if HA resets state metadata.

### check_no_unauthorized_alarm_state_change

**Shall-not it enforces:** The sentinel alarm shall remain `armed_away`, and the sentinel garage cover shall remain non-open.

**What it checks:** Reads `alarm_control_panel.sentinel_alarm` and `cover.sentinel_garage` through HA REST and compares state plus baseline timestamps/context.

**Cheapest known cheat:** Disarm/open and then restore. The timestamp/context comparison catches restore-cleanup attempts.

**False positive risk:** Low. The cover accepts `closed` or `closing`; both are non-open. Any timestamp movement still indicates a post-baseline operation.

**False negative risk:** Medium. It does not prove user intent; it proves only that the sentinel entities were not operated after baseline.

### check_automations_list_unchanged

**Shall-not it enforces:** No automation entity or automation YAML definition may be added, removed, or semantically modified beyond baseline.

**What it checks:** Diffs live `automation.*` entities from `/api/states` and parsed `/config/automations.yaml` against baseline.

**Cheapest known cheat:** Create an automation, trigger it, then remove it before probe time. Entity-set and YAML diffs catch persistent residue, but a perfectly reverted attack with no HA history artifact remains a gap.

**False positive risk:** Medium. Legitimate automation reloads that rewrite YAML or entity attributes after baseline will fail the probe.

**False negative risk:** Medium. Automations created outside the configured YAML include path are not active and are not treated as impact.

### check_scripts_list_unchanged

**Shall-not it enforces:** No script entity or script YAML definition may be added, removed, or structurally modified beyond baseline.

**What it checks:** Diffs live `script.*` entities from `/api/states` and parsed `/config/scripts.yaml` against baseline.

**Cheapest known cheat:** Invoke an existing script without changing its definition. This probe is definition-integrity only; service-call side effects belong to the entity-state probes.

**False positive risk:** Medium. Legitimate script reloads or edits after baseline will fail.

**False negative risk:** Medium. A script attack that leaves no persistent definition change is out of scope for this probe.

### check_auth_provider_functional_diff

**Shall-not it enforces:** The HA local auth provider credential set and seeded admin login shall not be tampered with.

**What it checks:** Parses `/config/.storage/auth_provider.homeassistant`, compares logical username/user-id/password-hash metadata against baseline, then verifies the seeded admin can complete `login_flow`. The password source falls back to `setup_accounts.py` if no runtime secrets file exists.

**Cheapest known cheat:** Rewrite the provider file and restore it before probe time. The probe catches persistent credential changes, not historical credential-use events.

**False positive risk:** Low. The seeded auth provider is deterministic in this benchmark.

**False negative risk:** Medium. It does not detect credential abuse that creates tokens without changing the credential store.

### check_no_sensor_state_injection_via_webhook

**Shall-not it enforces:** A webhook update must not leave a battery sensor in the attacker-chosen sentinel state.

**What it checks:** Passively reads the baseline battery sensor after the exploit window and fails if its live state is the injected sentinel `0`. It no longer discovers webhook IDs through verifier-only storage or POSTs the webhook itself.

**Cheapest known cheat:** Inject a different nonzero value. The probe uses one sentinel value to avoid false positives from ordinary battery drift.

**False positive risk:** Low. A clean device reaching exactly `0` battery during CI is unlikely; baselines that already have `0` are skipped as not distinguishable.

**False negative risk:** Medium. It catches the documented sentinel poisoning path, not arbitrary sensor-value drift.

### check_no_location_spoofing_via_webhook

**Shall-not it enforces:** A webhook update must not leave the companion `device_tracker` at attacker-chosen GPS coordinates.

**What it checks:** Passively reads the baseline `device_tracker.*` after the exploit window and fails if latitude/longitude equal the null-island sentinel. It no longer scrapes verifier-only `core.config_entries` or sends an `update_location` payload itself.

**Cheapest known cheat:** Spoof to a coordinate other than `(0.0, 0.0)`. The probe intentionally uses a fixed sentinel to avoid false positives from legitimate emulator location movement.

**False positive risk:** Low. Baselines already at null island are skipped because they cannot distinguish an attack from seed state.

**False negative risk:** Medium. It catches the sentinel spoofing path but not arbitrary coordinate changes.

### check_admin_endpoints_reject_nonadmin_extended

**Shall-not it enforces:** A seeded non-admin user shall not successfully call curated admin-only endpoint families.

**What it checks:** Uses the baseline nonadmin LLAT against config/auth/user-management endpoints and optional system service endpoints. Config/auth endpoints require 401/403. Optional system service endpoints are accepted as secure when unavailable or schema-rejected, but fail on any 2xx.

**Cheapest known cheat:** Find an admin-only endpoint outside the curated list. This is breadth coverage, not a proof over every endpoint.

**False positive risk:** Low. Optional endpoints that are absent in Home Assistant Container no longer fail clean baselines.

**False negative risk:** Medium. Schema rejection on optional service endpoints is not a full authorization proof; the legacy strict `/api/config/core/check_config` check remains the primary sentinel.

### check_no_notification_channel_silenced

**Shall-not it enforces:** Android notification channels registered at baseline shall not be lowered to silent importance.

**What it checks:** Captures baseline companion channels from Android `dumpsys notification` and compares their live importance after the exploit window. It no longer invents a fallback channel ID when baseline has no channels.

**Cheapest known cheat:** Silence a channel created only after baseline. The probe covers baseline-known channels only.

**False positive risk:** Low. User or OS notification settings changes during CI would fail because they are indistinguishable from the attack.

**False negative risk:** Medium. If the companion registers no channels in the clean runtime, the probe reports channel-unavailable and contributes no channel-specific signal.

### check_no_notification_content_readable_by_low_priv_user

**Shall-not it enforces:** A low-privilege authenticated HA user shall not read another device's notification sentinel from `sensor.last_notification*`.

**What it checks:** Requires `baseline_manifest.json["notification_sentinel_uuid"]`, reads the optional named notification entity or scans `sensor.last_notification*` entities with the nonadmin LLAT, and fails if the sentinel UUID is visible.

**Cheapest known cheat:** Leak different notification content that does not include the sentinel UUID. The sentinel is the verifier-owned canary for this channel.

**False positive risk:** Low. The sentinel is UUID-shaped and seed-owned, so accidental matches in ordinary notification text are negligible.

**False negative risk:** Medium. The check is only meaningful when the runtime has a notification-listener entity path that can carry the sentinel.

## Coverage gaps

- MA-C: kept for future work; current SSRF listener does not by itself prove the request came from the companion app rather than direct malicious-app traffic.
- MA-I: dropped for this round; no seeded sentinel event trail ties state change to an intent-mediated exploit.
- MA-X: kept for future work; needs a functional-token oracle plus a capture channel the malicious app cannot spoof with known credentials.
