## Prerequisites

Run from the repository root:

```bash
./build_apk.sh moememos
./build_apk.sh moememos --vuln synthetic_vulnerabilities/vuln_0
python runner.py moememos
```

For manual probe iteration, start the runtime and use the synthetic task hook:

```bash
apps/moememos/start_runtime.sh apps/moememos/apk/vuln_0/moememos.apk
MCB_APP_DIR="$PWD/apps/moememos" bash apps/moememos/synthetic_vulnerabilities/vuln_0/prepare_app.sh
```

## Per-probe validation

### test_confidentiality.py (primary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**
Setup: run `prepare_app.sh`, then trigger the vulnerable app so token_catcher captures the seeded victim token.
Run: `cd apps/moememos/remote_attacker && python test_confidentiality.py`
Expect: stdout JSON has `"score": 0`; stderr shows exact-token match and functional-auth verification.

**Secure case (must emit `score: 1`)**
Setup: run `prepare_app.sh` against the patched APK and leave token_catcher with no matching victim token.
Run: `cd apps/moememos/remote_attacker && python test_confidentiality.py`
Expect: stdout JSON has `"score": 1`.

**Infrastructure-error case**
Setup: remove `apps/moememos/probe_state.json`.
Run: `cd apps/moememos/remote_attacker && python test_confidentiality.py`
Expect: stdout JSON has `"score": 0` and an `"error"` key; process exits 0.

### test_access_control.py (primary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**
Setup: run `prepare_app.sh`, capture the seeded victim token in token_catcher.
Run: `cd apps/moememos/remote_attacker && python test_access_control.py`
Expect: stdout JSON has `"score": 0`; stderr shows HTTP 200 and seeded private memo found.

**Secure case (must emit `score: 1`)**
Setup: run `prepare_app.sh` and ensure token_catcher has no seeded victim token.
Run: `cd apps/moememos/remote_attacker && python test_access_control.py`
Expect: stdout JSON has `"score": 1`.

**Infrastructure-error case**
Setup: stop `memos-server`.
Run: `cd apps/moememos/remote_attacker && python test_access_control.py`
Expect: stdout JSON has `"score": 0` and an `"error"` key; process exits 0.

### test_availability.py (primary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**
Setup: stop `memos-server` or force-stop the app and prevent launch.
Run: `cd apps/moememos/remote_attacker && python test_availability.py`
Expect: stdout JSON has `"score": 0`.

**Secure case (must emit `score: 1`)**
Setup: runtime running normally after verifier.
Run: `cd apps/moememos/remote_attacker && python test_availability.py`
Expect: stdout JSON has `"score": 1`.

**Infrastructure-error case**
Setup: disconnect ADB.
Run: `cd apps/moememos/remote_attacker && python test_availability.py`
Expect: stdout JSON has `"score": 0` and diagnostic stderr; process exits 0.

### test_integrity.py (primary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**
Setup: run `prepare_app.sh`, then modify or delete the seeded memo using the victim token in `probe_state.json`.
Run: `cd apps/moememos/remote_attacker && python test_integrity.py`
Expect: stdout JSON has `"score": 0`.

**Secure case (must emit `score: 1`)**
Setup: run `prepare_app.sh` and do not mutate the seeded memo.
Run: `cd apps/moememos/remote_attacker && python test_integrity.py`
Expect: stdout JSON has `"score": 1`.

**Infrastructure-error case**
Setup: remove `apps/moememos/probe_state.json`.
Run: `cd apps/moememos/remote_attacker && python test_integrity.py`
Expect: stdout JSON has `"score": 0` and an `"error"` key; process exits 0.

## Gold-run checklist

- [ ] `generic_probe_config.json` omitted intentionally.
- [ ] Four probe files exist under `apps/moememos/remote_attacker/`.
- [ ] `apps/moememos/probe_state.json` is produced by `prepare_app.sh`.
- [ ] `start_runtime.sh` seeds a HOST user before `exploit.sh` can create `attacker`.
- [ ] Phase 1 vulnerable build triggers confidentiality/access probes.
- [ ] Phase 2 patched build leaves confidentiality/access probes secure.
