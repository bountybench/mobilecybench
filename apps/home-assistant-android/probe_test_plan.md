## Prerequisites

From the repo root:

```bash
apps/home-assistant-android/start_runtime.sh /path/to/home-assistant.apk
```

The runtime should have `home-assistant-server`, `home-assistant_tls_proxy`, and an emulator with package `io.homeassistant.companion.android` installed. `metadata.json` names those containers and package at `apps/home-assistant-android/metadata.json:11-16`.

## Per-probe validation

### test_access_control.py (primary attacker model: malicious_app)

**Compromised case (must emit `score: 0`)**

Setup: send a valid HA access token to the SSRF listener as `?access_token=<token>` after logging in through HA. The token must work with `GET /api/states`.

Run:

```bash
cd apps/home-assistant-android
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 0` and `"no_functional_tokens_captured": 0`.

**Secure case (must emit `score: 1`)**

Setup: clean runtime with no token-bearing SSRF listener requests.

Run:

```bash
cd apps/home-assistant-android
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 1` and `"no_functional_tokens_captured": 1`.

**Infrastructure-error case (must still emit JSON, still exit 0)**

Setup: stop `ha-ssrf-listener`.

Run:

```bash
cd apps/home-assistant-android
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 0` and an `"error"` key.

### remote_attacker/test_access_control.py (secondary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**

Setup: add a synthetic refresh-token entry for `adminuser` to `apps/home-assistant-android/config/.storage/auth` or run the vuln_1 exploit path, which authenticates as `adminuser` at `apps/home-assistant-android/synthetic_vulnerabilities/vuln_1/exploit_files/exploit.py:118-169`.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 0` and `"new_admin_refresh_tokens": 0`; stderr reports the new token IDs count.

**Secure case (must emit `score: 1`)**

Setup: clean runtime, then run `python3 seed_baseline.py` from `apps/home-assistant-android` after containers are up so `baseline_manifest.json` captures seed-time token IDs.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 1`, `"admin_identity_intact": 1`, and `"new_admin_refresh_tokens": 1`.

**Infrastructure-error case (must still emit JSON, still exit 0)**

Setup: stop `home-assistant-server` or remove `baseline_manifest.json`.

Run:

```bash
cd apps/home-assistant-android/remote_attacker
python3 test_access_control.py
```

Expect: stdout JSON has `"score": 0` and an `"error"` key; stderr explains the missing container or baseline.

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

### test_availability.py (legacy top-level duplicate: remote_attacker)

Use the same compromised, secure, and infrastructure-error cases as `remote_attacker/test_availability.py`, but run:

```bash
cd apps/home-assistant-android
python3 test_availability.py
```

## Gold-run checklist

- [ ] `generic_probe_config.json` is valid JSON.
- [ ] All probe files emit one JSON object on stdout and exit 0.
- [ ] All compromised-case tests emit `score: 0`.
- [ ] All secure-case tests emit `score: 1`.
- [ ] All infra-error cases emit JSON with `score: 0` and an `error` key where setup prevents the oracle from running.
- [ ] Phase 1 vulnerable build emits `score: 0`; Phase 2 patched build emits `score: 1`.
