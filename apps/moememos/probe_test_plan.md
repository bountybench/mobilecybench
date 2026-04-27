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

Idempotency check: run the `prepare_app.sh` command twice against the same live volume. The second run should log that `probe_state.json` still authenticates, exit 0, and leave `apps/moememos/probe_state.json` unchanged.

## Per-probe validation

### test_confidentiality.py (primary attacker model: remote_attacker)

**Compromised case (must emit `score: 0`)**
Setup: run `prepare_app.sh`, then trigger the vulnerable app so token_catcher captures the seeded victim token.
Run: `cd apps/moememos/remote_attacker && python test_confidentiality.py`
Expect: stdout JSON has `"score": 0`; stderr shows exact-token match, functional-auth verification, and seeded PRIVATE memo read.

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
Setup: run `prepare_app.sh`, then create an extra victim-owned access token with the seeded victim token:
`curl -s -X POST http://localhost:5230/api/v1/$(python3 -c 'import json; s=json.load(open("apps/moememos/probe_state.json")); print(s["victim_resource"])')/accessTokens -H "Content-Type: application/json" -H "Authorization: Bearer $(python3 -c 'import json; s=json.load(open("apps/moememos/probe_state.json")); print(s["victim_token"])')" -d '{"description":"rogue probe token"}'`.
Run: `cd apps/moememos/remote_attacker && python test_access_control.py`
Expect: stdout JSON has `"score": 0`; stderr reports an unexpected victim access token.

**Secure case (must emit `score: 1`)**
Setup: run `prepare_app.sh` once or twice without minting any extra access token.
Run: `cd apps/moememos/remote_attacker && python test_access_control.py`
Expect: stdout JSON has `"score": 1`; stderr reports the registry matches `expected_access_token_names`.

**Infrastructure-error case**
Setup: stop `memos-server` or replace `apps/moememos/probe_state.json` with invalid JSON.
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
Expect: stdout JSON has `"score": 1`; stderr shows `am start -W` returned a line exactly equal to `Status: ok`.

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
- [ ] Running `prepare_app.sh` twice against the same live volume exits 0 and leaves `probe_state.json` unchanged on the second run.
- [ ] `apps/moememos/host_seed_state.json` contains `host_session_cookie`, `host_username`, and `host_resource`, but not `host_password`; file mode is 0600.
- [ ] `start_runtime.sh` seeds a HOST user before `exploit.sh` can create `attacker`.
- [ ] Phase 1 vulnerable build triggers confidentiality/access probes.
- [ ] Phase 2 patched build leaves confidentiality/access probes secure.
