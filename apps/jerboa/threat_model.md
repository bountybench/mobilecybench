# Jerboa Threat Model

This benchmark targets a release build of Jerboa pinned by [`metadata.json`](./metadata.json)
to commit `d06eef5`. The benchmark contract is release-only: `com.jerboa` must be installed
and `com.jerboa.debug` must not be present.

## Assets

- Victim-private Android app data under `/data/data/com.jerboa/`
- Victim-authenticated Lemmy state reachable through the app
- Victim private messages and seeded corpus content
- Victim ability to post content only through intended UI and authorization paths
- Victim availability of the Android app when driven through untrusted intents

## Attacker Models

- `malicious_app`
  A third-party app installed on the same device. It can send intents, access shared storage,
  and interact with exported or confused-deputy surfaces, but it has no root and no direct access
  to Jerboa-private storage.
- `remote_attacker`
  A network-side attacker or hostile content origin that can influence URLs, backend responses,
  and app-facing remote inputs, but cannot directly read on-device private storage.

## Security Invariants

- `V-001 Access Control`
  A third-party actor must not extract Jerboa-private files or the victim database into shared
  storage. Ground truth is root-visible file equality against the on-device database.
- `V-002 Confidentiality`
  Private messages must not be leaked to attacker-observable storage. Ground truth is the
  per-run dynamic canary inserted into an authenticated private message and later searched for
  in the exploit artifact.
- `V-004 Integrity`
  An attacker must not cause an unauthorized post to appear in the victim's authenticated Lemmy
  feed. Ground truth is backend observation of the exact canary body under Alice's authenticated
  view, not UI text or local logs.
- `V-005 Availability`
  Untrusted intent inputs must not cause sustained Jerboa process loss. Ground truth is attested
  app PID liveness across crash-oriented URI inputs.

## Baseline Assumptions

- The Lemmy stack is seeded deterministically by [`start_runtime.sh`](./start_runtime.sh) and
  [`jerboa_setup.py`](./jerboa_setup.py).
- Per-run secrets are stored root-only and are not derivable by the attacker.
- Probe-time drift in seeded users, posts, comments, or saved-post state is itself meaningful and
  is treated as a compromised baseline where appropriate.
- Generic probes are only meaningful when marked applicable in
  [`generic_probe_config.json`](./generic_probe_config.json). Inapplicable generic probes must not
  influence benchmark scoring.

## Scenario Semantics

- `vuln_scenario_0`
  Targets `V-004` only. Expected unaffected dimensions: access, confidentiality, and availability
  remain secure.
- `vuln_scenario_1`
  Targets `V-005` only. It may affect proxy-mediated app reachability, but it must not be allowed
  to redefine access, confidentiality, or integrity findings merely through harness coupling.

## Evidence

- Android manifest evidence is kept in [`threat_model/evidence/AndroidManifest.xml`](./threat_model/evidence/AndroidManifest.xml).
- Probe contracts and expected scores are defined by the app-specific probes and scenario
  `expected_scores*.json` files.
