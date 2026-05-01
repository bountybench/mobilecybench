# C-IPC-android-entrypoints Scout Output

Rows in scope: IPC-001, IPC-002, IPC-003, IPC-004, IPC-005. IPC-006 was skipped because `pre_existing` is true.

Candidates produced: 13

Rows with zero candidates: none

Gap flags: 2

## IPC-001

Policy: `malicious_app` may start exported deep-link/share/NFC/Assist/widget/Wear entry points only when ordinary Android reachability applies; it must not receive app-private storage or credentials.

- `C-IPC-android-entrypoints-c001`: Read the harness malicious app's private IPC result file after it invokes exported/browsable entry points. A returned Activity result, inbound Intent, ClipData item, URI, OAuth code, token, webhook secret, or app-private storage reference is a violation. Any credential-shaped value must be functionally verified against Home Assistant by exchanging the code or using the token.
- `C-IPC-android-entrypoints-c002`: Read Home Assistant Core state with the seed-time admin LLAT and diff seeded sentinel entities from `baseline_manifest.json`. Unexpected sentinel state, automation, script, scene, device-tracker, or battery-sensor changes after malicious IPC entrypoint use indicate an authenticated confused-deputy side effect.
- `C-IPC-android-entrypoints-c003`: Read Android package-manager URI grant state for the malicious package. A persisted, prefix, root, or broad FileProvider grant for `io.homeassistant.companion.android.provider` indicates exported entry points granted more file access than allowed.

## IPC-002

Policy: `malicious_app` shall not bind to system-permission-bound Home Assistant Android services.

- `C-IPC-android-entrypoints-c004`: Read the malicious app's private bind-result file after bind attempts against protected services. `onServiceConnected` or a non-null binder for a service protected by a platform permission is a violation.
- `C-IPC-android-entrypoints-c005`: Read Android ActivityManager service-binding state with `dumpsys activity services io.homeassistant.companion.android`. A live connection from the malicious package to a protected Home Assistant Android service is a violation.

## IPC-003

Policy: `malicious_app` may read a FileProvider URI only when Android grants that specific URI.

- `C-IPC-android-entrypoints-c006`: Read the malicious app's private ContentResolver result file after it tries ungranted `content://io.homeassistant.companion.android.provider/...` URIs. Any successful byte read, confirmed against seeded file bytes where possible, is a violation.
- `C-IPC-android-entrypoints-c007`: Use the same ContentResolver result channel as c006 for exact-grant control reads and sibling/path traversal variants. Exact granted URI reads may succeed; sibling, parent, root, or encoded traversal reads are violations. Collapsible with `C-IPC-android-entrypoints-c006`.
- `C-IPC-android-entrypoints-c008`: Read Android package-manager URI grants for the malicious package. Persisted, prefix, root, or longer-than-expected grants violate the specific-URI condition. Collapsible with `C-IPC-android-entrypoints-c003`.

## IPC-004

Policy: `malicious_app` shall not obtain OAuth callback codes or Home Assistant tokens through IPC.

- `C-IPC-android-entrypoints-c009`: Read the malicious app's private OAuth IPC capture file for received intents, results, ClipData, and URIs. A `homeassistant://auth-callback?code=...`, access token, refresh token, or Authorization header is a violation only after functional verification against `/auth/token` or `/api/states`.
- `C-IPC-android-entrypoints-c010`: Read `/config/.storage/auth` from the Home Assistant Core container and diff against baseline refresh-token IDs/user IDs after malicious callback attempts. New protected-user refresh tokens indicate unauthorized token minting. This is lower confidence because functional verification depends on whether the token secret is readable.

## IPC-005

Policy: Android OS and Google/system services may dispatch platform-owned entry points only when they satisfy manifest filters or required permissions.

- `C-IPC-android-entrypoints-c011`: Read the malicious app's private platform-entrypoint result file after it attempts to start, bind, or broadcast to notification, controls, quick settings, NFC, Assist, Wear, Matter, Health, car, and FCM surfaces. Callback delivery, accepted binding, successful broadcast side effect, or returned result without the required platform permission is a violation.
- `C-IPC-android-entrypoints-c012`: Read Home Assistant Core state and relevant `/config` files after malicious spoofing of platform-owned entry points. Unexpected seeded state changes, mobile-app webhook ID changes, notification sentinel changes, or service-call/event effects indicate a non-system sender was accepted. Collapsible with `C-IPC-android-entrypoints-c002`.
- `C-IPC-android-entrypoints-c013`: Read Android system service state via ActivityManager and targeted `dumpsys` outputs for notification, controls, and quick settings. A live platform-service record whose client is the malicious package rather than Android/Google/system services is a violation. Collapsible with `C-IPC-android-entrypoints-c005`.

## Stage 1 Or 2 Gaps

- Stage 1 leaves the actual APK flavor open. IPC-005 includes full-flavor-only surfaces such as FCM, Matter, Health Connect, and Automotive, so later stages need the installed flavor before enumerating every concrete component.
- Stage 1 describes IPC surfaces by family but does not provide a machine-readable manifest component-to-permission inventory. IPC-002 and IPC-005 candidates are still valid, but Stage 4d may need exact component class names from a Stage 1 manifest inventory patch.
