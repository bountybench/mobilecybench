# Probe FP refinement — one-screen checklist

Keep open while working a fired probe / suspect signal cell.

## Triage (Step 1)
- [ ] Read the failing sub-check end to end. Name the exact readout (log scan / fingerprint / row-compare / API response).
- [ ] **(a) implementation bug?** Misfires on an input it was *designed* to handle, infra perfect → REFER OUT (code fix).
- [ ] **(b) environment artifact?** Vanishes on warm baseline / fixed infra / switched GPU renderer → REFER OUT (infra + re-grade).
- [ ] **(c) over-broad attribution?** Credits attacker-OWNED state, app's-OWN output, or agent's-OWN creds → CONTINUE.
- [ ] **(d) contestable design?** Detects a real effect whose vuln-status depends on role entitlement → CONTINUE.
- [ ] Dual-listed (b+d)? → fix the DESIGN, not just infra.

## Locate (Step 2)
- [ ] Answer in one sentence: *"What role-permitted or attacker-owned action makes this fire WITHOUT the modeled impact?"*
- [ ] Identify which FP-prone readout it is: any-occurrence scan / state fingerprint / contestable expectation.

## Model the boundary (Step 3) — "credit only if [impact]"
- [ ] Pick the pattern: exfil-context corroboration / role-grant exclusion / attacker-owned exclusion / victim-issued-set membership / provenance.
- [ ] Split into STRICT (untouched) vs narrowed tier — do NOT relax the high-value checks.
- [ ] Comment WHY the window/marker set is exactly this tight (no generous loosening).

## Demonstrate (Step 4)
- [ ] Where did the false fire come from?
  - [ ] **Reproduces from saved `exploit.sh` → Mode A:** decoupled re-grade, OLD fires / NEW returns no_signal; confirm a genuine violation still fires under NEW.
  - [ ] **Fired from live recon, not the artifact → Mode B:** probe-code before/after diff; remaining protected-target checks still fire.
  - [ ] **Never fired (found by inspection) → latent:** confusion-matrix unit test (benign PASS, genuine FIRE, strict FIRE); label as preventive hardening.

## No-regression (Step 5)
- [ ] Real TP fires on a DIFFERENT CIAA family / independent callback — confirm it's unaffected.
- [ ] `pytest tests/utils/ -q` (+ the test you added) green.
- [ ] No-op / no-agent baseline still returns no_signal.

## Package (Step 6)
- [ ] Fixed BOTH MA (`apps/<app>/test_*.py`) and RA (`apps/<app>/remote_attacker/test_*.py`) copies, with `# SYNC:` comments.
- [ ] Added a confusion-matrix regression test (pure-function if possible).
- [ ] Narrative: issue → improvement → observations → results; `.github/PULL_REQUEST_TEMPLATE.md` for the PR body.

## Where to look (grep anchors)
- CIAA entrypoints: `apps/<app>/test_{confidentiality,access_control,integrity,availability}.py` (+ `remote_attacker/`).
- Shared scanner: `utils/confidentiality_utils.py:check_leak_indicators(log, exclude_keys=None)` — `exclude_keys` is the de-flatten hook.
- Per-app helpers: name VARIES (`probe_common.py` / `probe_helpers.py` / `probe_lib.py` / inline). No `checks/` dir — grep `apps/<app>/*.py`.
- Fingerprints: `apps/<app>/<app>_state_fingerprint.py:collect_state/fingerprint`.
- High-value keys: a `HIGH_VALUE_KEYS` / `_STRICT_KEYS` tuple inside the probe (references `secrets.json`).
