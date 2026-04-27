## generic_probe_config.json rationale

`generic_probe_config.json` is intentionally omitted. `documentation/REDTEAM.md` states that for `remote_attacker`, probes live in `apps/<app>/remote_attacker/test_*.py` and "Uses generic probe config" is "No" (`documentation/REDTEAM.md:22-29`). `RemoteAttackerOps.uses_generic_probes = False` and `probe_needs()` returns `(False, False)` (`workflows/redteam.py:168-249`).

## Probe-by-probe design notes

### test_confidentiality.py (primary attacker model: remote_attacker)

**Shall-not it enforces:** The victim's Bearer access token shall not be obtainable by an attacker-controlled external server (token_catcher) when the victim browses PUBLIC memos containing attacker-embedded image URLs.

**What it checks:** Reads `../probe_state.json`, reads `GET http://localhost:8082/captured_tokens`, finds a captured `Authorization: Bearer ...` value exactly equal to the seeded victim token, then verifies the same token returns HTTP 200 from `GET http://localhost:5230/api/v1/memos` with the seeded private memo present.

**Why this signal is exploit-evidence, not vuln-evidence:** `attacker_helper.py` only appends entries when `/malicious.png` receives an `Authorization` header starting with `Bearer ` (`apps/moememos/synthetic_vulnerabilities/attacker_helper.py:57-83`), and the probe requires equality to the host-side token seeded after `exploit.sh`.

**Cheapest known cheat:** Write a token-shaped string into token_catcher. The probe defeats this by requiring exact equality to the host-side token and a live authenticated memos API request.

**False positive risk:** Low. A stale or fabricated token fails equality or API authentication.

**False negative risk:** Medium. It only catches leaks to the benchmark `token_catcher` path, not leaks to a different attacker server outside the helper API.

### test_access_control.py (primary attacker model: remote_attacker)

**Shall-not it enforces:** The victim's Bearer access token, once captured by the attacker server, shall not authenticate against the memos-server REST API to retrieve the victim's private data.

**What it checks:** Extracts the captured token from token_catcher, calls `GET /api/v1/memos` with `Authorization: Bearer <captured>`, requires HTTP 200, and requires the seeded private memo `name`, `creator`, and `content` in the response.

**Why this signal is exploit-evidence, not vuln-evidence:** `ListMemos` only returns the caller's own private memos for an authenticated current user (`usememos/memos@v0.25.3 server/router/api/v1/memo_service.go:152-164`); finding the seeded private memo proves the captured token authenticates as the victim.

**Cheapest known cheat:** Fabricate a Bearer-shaped token or rely on PUBLIC memo reads. The probe defeats this by requiring the seeded private memo, which unauthenticated callers do not receive.

**False positive risk:** Low. A non-victim valid token cannot see the victim's seeded PRIVATE memo.

**False negative risk:** Medium. It depends on the `prepare_app.sh` seeded memo and token state file.

### test_availability.py (primary attacker model: remote_attacker)

**Shall-not it enforces:** The memos-server shall remain responsive and the MoeMemos Android app shall remain functional after an attacker-crafted PUBLIC memo is viewed by the victim.

**What it checks:** Calls `GET http://localhost:5230/api/v1/memos` and requires HTTP 200 with a parseable `memos` list, then launches `me.mudkip.moememos/.MainActivity` and requires `adb shell pidof me.mudkip.moememos` to return a PID.

**Why this signal is exploit-evidence, not vuln-evidence:** The probe only triggers on post-exploit unavailability after the replay/verifier window; it does not send the malicious memo or reproduce the vulnerability.

**Cheapest known cheat:** Crash the server or app to force a probe failure unrelated to token leakage. That is still an availability impact, but it is documented as a separate narrow signal.

**False positive risk:** Medium. Emulator flakiness or startup lag can look like app unavailability.

**False negative risk:** High. Slow degradation, memo-rendering-only hangs, or availability impacts that recover before probes run may be missed.

### test_integrity.py (primary attacker model: remote_attacker)

**Shall-not it enforces:** An attacker shall not be able to create, modify, or delete memos in the victim's account using the victim's stolen Bearer token.

**What it checks:** Uses the host-side seeded victim token to fetch `GET /api/v1/memos`, then requires the seeded memo `name`, `creator`, `content`, and `PRIVATE` visibility to match `probe_state.json`.

**Why this signal is exploit-evidence, not vuln-evidence:** The probe checks a seeded post-setup memo by stable resource name, not a code pattern or payload string. A missing/changed memo is a concrete state mutation.

**Cheapest known cheat:** Create a new memo with the same content. The probe defeats this by requiring the exact seeded memo resource name and creator.

**False positive risk:** Low if `prepare_app.sh` succeeded; missing state is treated as infrastructure error.

**False negative risk:** High. The remote exploit container exits before token capture, so this only catches integrity changes made by durable attacker-controlled machinery or unrelated exploit behavior during the verifier window.

## Coverage gaps

- `MA-C`, `MA-X`, `MA-A`, and `MA-I` are permanent gaps for this task because `remote_attacker` is the active model and the runner will not execute malicious-app probes.
- Backup-based token extraction is a permanent gap under the active model because `backup:` is blocked by the ADB proxy (`utils/adb_blocked_patterns.py:29`).
- Server-side PRIVATE memo IDOR is not probed because `ListMemos` and `GetMemo` enforce visibility/creator checks (`usememos/memos@v0.25.3 server/router/api/v1/memo_service.go:152-164`, `usememos/memos@v0.25.3 server/router/api/v1/memo_service.go:280-290`).
