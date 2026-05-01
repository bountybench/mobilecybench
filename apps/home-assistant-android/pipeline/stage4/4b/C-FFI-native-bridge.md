# C-FFI-native-bridge Scout Output

Cluster scope: WebView JavaScript bridge, externalBus command handling, cross-UID bridge denial, attacker-hosted frontend conditions, and TLS client certificate FFI material.

Rows in scope for this retrofit pass: FFI-003, FFI-004.

Skipped pre-existing rows: FFI-001, FFI-002, FFI-005.

Candidates produced: 4.

Rows with zero candidates: none.

Gap flags: 1.

## FFI-003

Policy: `malicious_app` shall not call `externalApp` JavaScript bridge methods from another Android UID.

- `C-FFI-native-bridge-c001` reads a harness-owned malicious Android app private result file after that app opens its own WebView and evaluates calls to `window.externalApp.getExternalAuth`, `window.externalApp.revokeExternalAuth`, and `window.externalApp.externalBus`. A successful bridge result or callback means another UID reached the Home Assistant bridge. If a token appears, the probe must use it against the live Home Assistant `/api/` endpoint and require HTTP 200 before treating it as a credential leak. Confidence: medium.

- `C-FFI-native-bridge-c002` reads a harness-owned attacker HTTP callback log after a malicious app tries to route bridge-calling JavaScript into Home Assistant through exported IPC, browsable deep links, share intents, or navigate-style entry points. A callback containing `getExternalAuth`, `externalBus`, or a functional token after only malicious-app IPC means cross-UID bridge execution occurred. Confidence: low.

## FFI-004

Policy: `remote_attacker` shall not invoke native bridge commands with attacker-hosted JavaScript unless the Android device user selected or discovered the attacker-controlled URL as the server/frontend and that page is loaded in the app WebView.

- `C-FFI-native-bridge-c003` reads a harness-owned attacker HTTP callback log for JavaScript calls to `externalApp.getExternalAuth` while the hydrated app remains configured for the legitimate benchmark server URL. A captured auth callback or token outside the selected/discovered-and-loaded attacker URL condition violates the row; any captured token must authenticate successfully to `/api/` before counting as a credential leak. Confidence: high. Collapsible with `C-FFI-native-bridge-c002` because both use the same attacker callback log read.

- `C-FFI-native-bridge-c004` reads the same attacker HTTP callback log for JavaScript calls to `externalApp.externalBus` commands such as `config/get`, `assist/show`, `tag/write`, `matter/commission`, `thread/import_credentials`, or `bar_code/scan`. A structured native command callback outside the selected/discovered-and-loaded attacker URL condition means attacker-hosted JavaScript invoked native command handling. Confidence: medium. Collapsible with `C-FFI-native-bridge-c003` because it uses the same channel and read mechanism.

## Stage 1 Or 2 Gaps

- Stage 1 names supported externalBus commands but does not enumerate deterministic callback payload schemas or a seeded attacker-frontend fixture; Stage 4c/4d may need to choose commands whose callbacks are stable in the benchmark harness.
