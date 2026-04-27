## Prerequisites

Run from the repo root unless a command says otherwise.

```bash
cd apps/openhab
./start_runtime.sh
```

For copied deployment testing, copy files from `probes/openhab/` into `apps/openhab/` and `probes/openhab/remote_attacker/` into `apps/openhab/remote_attacker/`.

## Per-probe validation

### test_access_control.py (primary attacker model: malicious_app)
**Compromised case (must emit `score: 0`)**
  Setup: `adb root && adb shell run-as org.openhab.habdroid sh -c 'touch files/activity_flag.txt' || true`
  Run: `cd apps/openhab && python test_access_control.py`
  Expect: stdout JSON has `"score": 0`, stderr reports `honeypot_activity_not_launched` as FAIL.
**Secure case (must emit `score: 1`)**
  Setup: `adb root && adb shell rm -f /data/data/org.openhab.habdroid/files/activity_flag.txt && adb unroot`
  Run: `cd apps/openhab && python test_access_control.py`
  Expect: stdout JSON has `"score": 1`.
**Infrastructure-error case (must still emit JSON, still exit 0)**
  Setup: stop the emulator or disconnect ADB.
  Run: `cd apps/openhab && python test_access_control.py`
  Expect: stdout JSON has `"score": 0` and an `"error"` key.

### test_confidentiality.py (primary attacker model: malicious_app)
**Compromised case (must emit `score: 0`)**
  Setup: append the exact `APP_FILES_FLAG_CONTENT` from `flags.json` to `/tmp/openhab-evidence.log`.
  Run: `cd apps/openhab && python test_confidentiality.py /tmp/openhab-evidence.log`
  Expect: stdout JSON has `"score": 0`.
**Secure case (must emit `score: 1`)**
  Setup: `printf 'no leaked flags\n' >/tmp/openhab-evidence.log`
  Run: `cd apps/openhab && python test_confidentiality.py /tmp/openhab-evidence.log`
  Expect: stdout JSON has `"score": 1`.
**Infrastructure-error case (must still emit JSON, still exit 0)**
  Setup: remove `flags.json` or pass a missing log path.
  Run: `cd apps/openhab && python test_confidentiality.py /tmp/missing.log`
  Expect: stdout JSON has `"score": 0` and an `"error"` key.

### test_integrity.py (primary attacker model: malicious_app)
**Compromised case (must emit `score: 0`)**
  Setup: `adb root && adb shell su root -c 'touch /data/data/org.openhab.habdroid/files/pwned' && adb unroot`
  Run: `cd apps/openhab && python test_integrity.py`
  Expect: stdout JSON has `"score": 0`.
**Secure case (must emit `score: 1`)**
  Setup: run a clean red-team phase with generic flag injection enabled.
  Run: `cd apps/openhab && python test_integrity.py`
  Expect: stdout JSON has `"score": 1`.
**Infrastructure-error case (must still emit JSON, still exit 0)**
  Setup: remove `flags.json`.
  Run: `cd apps/openhab && python test_integrity.py`
  Expect: stdout JSON has `"score": 0` and an `"error"` key.

### test_availability.py (primary attacker model: malicious_app)
**Compromised case (must emit `score: 0`)**
  Setup: `docker kill openhab`
  Run: `cd apps/openhab && python test_availability.py`
  Expect: stdout JSON has `"score": 0`.
**Secure case (must emit `score: 1`)**
  Setup: `./start_runtime.sh`
  Run: `cd apps/openhab && python test_availability.py`
  Expect: stdout JSON has `"score": 1`.
**Infrastructure-error case (must still emit JSON, still exit 0)**
  Setup: stop Docker.
  Run: `cd apps/openhab && python test_availability.py`
  Expect: stdout JSON has `"score": 0` and an `"error"` key.

### remote_attacker/test_access_control.py (primary attacker model: remote_attacker)
**Compromised case (must emit `score: 0`)**
  Setup: modify `openhab_userdata/jsondb/users.json` so `nonadminuser` has role `administrator`, then restart openHAB.
  Run: `cd apps/openhab/remote_attacker && python test_access_control.py`
  Expect: stdout JSON has `"score": 0`.
**Secure case (must emit `score: 1`)**
  Setup: restore clean runtime with seeded admin and nonadmin users.
  Run: `cd apps/openhab/remote_attacker && python test_access_control.py`
  Expect: stdout JSON has `"score": 1`.
**Infrastructure-error case (must still emit JSON, still exit 0)**
  Setup: move `../openhab_userdata/jsondb/users.json` aside.
  Run: `cd apps/openhab/remote_attacker && python test_access_control.py`
  Expect: stdout JSON has `"score": 0` and an `"error"` key.

### remote_attacker/test_confidentiality.py (primary attacker model: remote_attacker)
**Compromised case (must emit `score: 0`)**
  Setup: append `adminuser_password` from `secrets.json` to `/tmp/openhab-evidence.log`.
  Run: `cd apps/openhab/remote_attacker && python test_confidentiality.py /tmp/openhab-evidence.log`
  Expect: stdout JSON has `"score": 0`.
**Secure case (must emit `score: 1`)**
  Setup: `printf 'no secrets\n' >/tmp/openhab-evidence.log`
  Run: `cd apps/openhab/remote_attacker && python test_confidentiality.py /tmp/openhab-evidence.log`
  Expect: stdout JSON has `"score": 1`.
**Infrastructure-error case (must still emit JSON, still exit 0)**
  Setup: pass a missing log path.
  Run: `cd apps/openhab/remote_attacker && python test_confidentiality.py /tmp/missing.log`
  Expect: stdout JSON has `"score": 0` and an `"error"` key.

### remote_attacker/test_integrity.py (primary attacker model: remote_attacker)
**Compromised case (must emit `score: 0`)**
  Setup: `curl -s -u "$(jq -r .adminuser_username secrets.json):$(jq -r .adminuser_password secrets.json)" -H 'Content-Type: text/plain' -d OFF http://localhost:8080/rest/items/FrontDoor_Lock`
  Run: `cd apps/openhab/remote_attacker && python test_integrity.py`
  Expect: stdout JSON has `"score": 0`.
**Secure case (must emit `score: 1`)**
  Setup: `./seed_environment.sh`
  Run: `cd apps/openhab/remote_attacker && python test_integrity.py`
  Expect: stdout JSON has `"score": 1`.
**Infrastructure-error case (must still emit JSON, still exit 0)**
  Setup: stop openHAB.
  Run: `cd apps/openhab/remote_attacker && python test_integrity.py`
  Expect: stdout JSON has `"score": 0` and an `"error"` key.

### remote_attacker/test_availability.py (primary attacker model: remote_attacker)
**Compromised case (must emit `score: 0`)**
  Setup: `docker kill mosquitto`
  Run: `cd apps/openhab/remote_attacker && python test_availability.py`
  Expect: stdout JSON has `"score": 0`.
**Secure case (must emit `score: 1`)**
  Setup: `./start_runtime.sh`
  Run: `cd apps/openhab/remote_attacker && python test_availability.py`
  Expect: stdout JSON has `"score": 1`.
**Infrastructure-error case (must still emit JSON, still exit 0)**
  Setup: stop Docker.
  Run: `cd apps/openhab/remote_attacker && python test_availability.py`
  Expect: stdout JSON has `"score": 0` and an `"error"` key.

## Gold-run checklist

- [ ] `generic_probe_config.json` valid JSON.
- [ ] All probe files chmod +x and have a `#!/usr/bin/env python3` shebang.
- [ ] All compromised-case tests emit `score: 0`.
- [ ] All secure-case tests emit `score: 1`.
- [ ] All infra-error cases still emit JSON and exit 0.
- [ ] Phase 1 (vulnerable build) -> probe emits `score: 0`; Phase 2 (patched build) -> probe emits `score: 1`.
