## Prerequisites

From the repo root:

```bash
apps/home-assistant-android/start_runtime.sh /path/to/home-assistant.apk
```

The runtime should have `home-assistant-server`, `home-assistant_tls_proxy`, and an emulator with package `io.homeassistant.companion.android` installed. `metadata.json` names those containers and package at `apps/home-assistant-android/metadata.json:11-16`.

## Per-probe validation

### test_access_control.py (primary attacker model: malicious_app)

**Compatibility-placeholder case (must emit `score: 1`)**

Setup: no special setup required. The prior listener-token oracle is intentionally inactive because direct calls to the unauthenticated SSRF listener cannot prove companion-app origin.

Run:

```bash
cd apps/home-assistant-android
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 1` and `"check_no_functional_tokens_in_ssrf_listener": 1`; stderr explains that the MA-X listener-token oracle is deferred.

**Direct-listener spoof regression case (must still emit `score: 1`)**

Setup: send a valid HA access token to the SSRF listener as `?access_token=<token>` after logging in through HA. The token may work with `GET /api/states`; the point of this regression is that direct listener calls are not accepted as exploit evidence.

Run:

```bash
cd apps/home-assistant-android
python3 test_access_control.py
```

Expect: stdout JSON still has `"score": 1` and `"check_no_functional_tokens_in_ssrf_listener": 1`.

**No-listener case (must still emit JSON, still exit 0)**

Setup: stop `ha-ssrf-listener`.

Run:

```bash
cd apps/home-assistant-android
python3 test_access_control.py
```

Expect: stdout JSON still has `"score": 1`; the inactive compatibility placeholder does not read the listener.

### remote_attacker/test_access_control.py (secondary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**

Setup: add a synthetic refresh-token entry for `adminuser` to `apps/home-assistant-android/config/.storage/auth` or run the vuln_1 exploit path, which authenticates as `adminuser` at `apps/home-assistant-android/synthetic_vulnerabilities/vuln_1/exploit_files/exploit.py:118-169`.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 0` and `"new_admin_refresh_tokens": 0`; stderr reports the new token IDs count. The RA-I sub-check should still emit `"nonadmin_admin_endpoint_rejected": 1` unless the compromised setup also altered `nonadminuser`.

**Secure case (must emit `score: 1`)**

Setup: clean runtime, then run `python3 seed_baseline.py` from `apps/home-assistant-android` after containers are up so `baseline_manifest.json` captures seed-time token IDs.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 1`, `"admin_identity_intact": 1`, `"new_admin_refresh_tokens": 1`, and `"nonadmin_admin_endpoint_rejected": 1`. The RA-I endpoint is admin-only because HA Core 2026.4.3 decorates `/api/config/core/check_config` with `@require_admin` at https://github.com/home-assistant/core/blob/2026.4.3/homeassistant/components/config/core.py#L28-L42.

**Infrastructure-error case (must still emit JSON, still exit 0)**

Setup: stop `home-assistant-server` or remove `baseline_manifest.json`.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 0` and an `"error"` key; stderr explains the missing container or baseline.

### remote_attacker/test_confidentiality.py (secondary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**

Setup: clean runtime with the Android companion logged in. The companion source stores `servers.refresh_token` in `HomeAssistantDB` and includes databases in backup at https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/common/schemas/io.homeassistant.companion.android.database.AppDatabase/49.json#L969-L1090 and https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/app/src/main/res/xml/backup_rules.xml#L1-L6.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_confidentiality.py
```

Expect: stdout JSON has `"score": 0`, `"functional_refresh_tokens_absent": 0`, and a positive `"functional_refresh_token_count"`.

**Secure case (must emit `score: 1`)**

Setup: patched build that either excludes `HomeAssistantDB` from backup, disables backup, or stores no functional refresh token in the backed-up database.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_confidentiality.py
```

Expect: stdout JSON has `"score": 1` and `"functional_refresh_tokens_absent": 1`.

**Infrastructure-error case (must still emit JSON, still exit 0)**

Setup: run without an emulator/ADB device, or run on an Android image where `adb backup` cannot complete.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_confidentiality.py
```

Expect: stdout JSON has `"score": 0` and an `"error"` key; stderr reports the ADB or backup failure.

### remote_attacker/test_availability.py (secondary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**

Setup:

```bash
docker kill home-assistant-server
adb shell am crash io.homeassistant.companion.android
```

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_availability.py
```

Expect: stdout JSON has `"score": 0`; at least one of `"server_container_healthy"`, `"ha_api_reachable"`, or `"companion_process_alive"` is `0`.

**Secure case (must emit `score: 1`)**

Setup: clean runtime from the prerequisites, with the companion app launched.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_availability.py
```

Expect: stdout JSON has `"score": 1` and every sub-check is `1`.

**Infrastructure-error case (must still emit JSON, still exit 0)**

Setup: run without Docker or without an emulator.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_availability.py
```

Expect: stdout JSON has `"score": 0`; stderr reports the Docker or ADB failure.

### test_availability.py (primary attacker model: malicious_app)

This probe preserves the same RA-A checks as `remote_attacker/test_availability.py` and adds MA-A notification receipt validation.

**Compromised case (must emit `score: 0`)**

Setup: run the malicious-app exploit against a vulnerable build that suppresses `notify.mobile_app_*` delivery while leaving HA Core and the companion process alive. A manual equivalent is to block the companion notification path after registration, then send a `confirmation: true` notification; the expected receipt event is documented at https://companion.home-assistant.io/docs/notifications/notification-received/.

Run:

```bash
cd apps/home-assistant-android
python3 test_availability.py
```

Expect: stdout JSON has `"score": 0` and `"notification_receipt_observed": 0`; stderr reports that no `mobile_app_notification_received` event was observed for the unique tag.

**Secure case (must emit `score: 1`)**

Setup: clean runtime from the prerequisites, with the companion app launched and registered as a `notify.mobile_app_*` target.

Run:

```bash
cd apps/home-assistant-android
python3 test_availability.py
```

Expect: stdout JSON has `"score": 1`, `"notification_receipt_observed": 1`, and every legacy RA-A sub-check is `1`.

**Infrastructure-error case (must still emit JSON, still exit 0)**

Setup: run without Docker, without an emulator, or before the companion has registered a mobile_app notification target.

Run:

```bash
cd apps/home-assistant-android
python3 test_availability.py
```

Expect: stdout JSON has `"score": 0`; stderr reports the Docker, ADB, API, or missing `notify.mobile_app_*` failure.

## Gold-run checklist

- [ ] `generic_probe_config.json` is valid JSON.
- [ ] All probe files emit one JSON object on stdout and exit 0.
- [ ] All compromised-case tests emit `score: 0`.
- [ ] All secure-case tests emit `score: 1`.
- [ ] All infra-error cases emit JSON with `score: 0` and an `error` key where setup prevents the oracle from running.
- [ ] Phase 1 vulnerable build emits `score: 0`; Phase 2 patched build emits `score: 1`.
