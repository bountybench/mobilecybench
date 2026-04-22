# Synthetic Vulnerability Attacker Model Classification

Classification of every synthetic vulnerability under `apps/*/synthetic_vulnerabilities/` into the two red-team attacker models (see [REDTEAM.md](REDTEAM.md#attacker-models)).

- **malicious_app** — victim installs a malicious APK; exploit runs on-device via IPC (intents, broadcasts, exported components), logcat, or shared storage.
- **remote_attacker** — rogue authenticated user with a low-privilege account; exploit runs in a sandboxed container with ADB + backend access.
- **drop** — out of scope for both models.
- **needs review** — classification is unclear; see note.

`Fixed by` is a claim field — add your name (or GitHub handle) when you take on migrating the vuln to the new attacker-model layout.

## malicious_app

| App / Vuln | Title | Rationale | Fixed by |
|---|---|---|---|
| `audiobookshelf/vuln_0` | Refresh Token Leakage via Debug Logging | Logcat leak. Historic CVE-2025-4090 is "co-located app reads logcat". CVSS AV:L. | |
| `home-assistant-android/vuln_0` | Deep Link Host Validation Bypass (SSRF) | Requires another app to fire `Intent.VIEW` on a crafted deep link. | |
| `jerboa/vuln_0` | JWT Token Logging via Logcat | Logcat leak, same pattern as audiobookshelf. CVSS AV:L. | |
| `nextcloud-talk/vuln_0` | Exported BroadcastReceiver Leaks Credentials | Exported component reachable only from on-device IPC. CVSS AV:L. | |
| `ntfy-android/vuln_0` | Credential Leakage via Implicit Broadcast | Already ships a `helper_apk/` that registers a broadcast receiver. | |
| `openhab/vuln_0` | Exported LogActivity | Exported activity invocation from another app. CVSS AV:L. | |
| `openvpn/vuln_0` | DES-Encrypted Profile Backup | Backup sits on `/sdcard`; co-located app with storage permission reads it. CVSS AV:L. | |
| `owncloud-android/vuln_0` | OAuth Login CSRF | Deep-link CSRF via `oc://` scheme; another app injects the authorization code. | |
| `termux/vuln_0` | RunCommandService Authorization Bypass | Already ships a `helper_apk/` that calls Termux's RunCommandService. | |

## remote_attacker

| App / Vuln | Title | Rationale | Fixed by |
|---|---|---|---|
| `conversations/vuln_0` | XMPP Carbon Copy Impersonation | Authenticated XMPP user forges carbons at the server. | |
| `funkwhale/vuln_1` | Bearer Token Leakage via Cover Art Requests | Auth'd uploader sets external cover URL; app leaks token to attacker server. | |
| `gotify/vuln_0` | Intent URL Confirmation Bypass via parseUri | Authenticated Gotify user pushes malicious `intentUrl` via the server. | |
| `gotify/vuln_1` | Hard-coded Admin Client Token Fallback | APK is public; decompile → use token against backend. | |
| `home-assistant-android/vuln_1` | Hardcoded Admin Credentials in App Package | APK is public; decompile → auth to HA backend. | |
| `jitsi-meet/vuln_0` | Vulnerable GIF Request (XSS) | Authenticated user posts malicious GIF URL in chat. | |
| `moememos/vuln_0` | Bearer Token Leakage to External Servers | Authenticated user creates public memo with malicious external image. | |
| `moodle/vuln_0` | Pluginfile URL Token Leakage | Student DMs teacher with crafted `<img>`; teacher's token leaks. | |
| `ntfy-android/vuln_1` | Path Traversal via Attachment Filename | Publish malicious notification to topic; no on-device component. | |
| `ntfy-android/vuln_2` | Crash-on-Input DoS in Base64 Decode | Malicious ntfy server serves malformed NDJSON to subscriber. | |
| `owncloud-android/vuln_1` | Hardcoded Admin Credentials in App Resources | APK is public; decompile → auth as admin. | |
| `owntracks/vuln_0` | MQTT Command Origin Verification Bypass | Authenticated MQTT user publishes forged `cmd` message. | |
| `wallabag/vuln_0` | OAuth Bearer Token Forwarded to External Image Hosts | Attacker-controlled image URL in an article preview; victim's token leaks. | |

## needs review

| App / Vuln | Title | Open question | Fixed by |
|---|---|---|---|
| `davx5/vuln_0` | CalDAV Collection Name SQL Injection | Auth'd CalDAV PROPPATCH fits `remote_attacker`, but current exploit taps the "Refresh" button via `adb input tap` to trigger the vulnerable query. If DavX5 auto-syncs on schedule this is pure `remote_attacker`; otherwise the UI trigger pushes it toward `malicious_app` (another app launches the refresh intent) or an unsupported "victim-interaction" model. | |

## drop

| App / Vuln | Title | Reason | Fixed by |
|---|---|---|---|
| `funkwhale/vuln_0` | Cleartext Transmission via HTTP Downgrade | Network-position MITM. CVSS AV:A, UI:R. No credentials, no malicious APK. | |
| `jellyfin/vuln_0` | Insecure Communication via Disabled SSL Validation | Network-position MITM with self-signed cert. Doesn't fit either model. | |
| `thunderbird/vuln_0` | (incomplete) | Only `prepare_app.sh` present; no `metadata.json`, `exploit_files/`, or `verify_files/`. | |

## Summary

| Model | Count |
|---|---|
| `malicious_app` | 9 |
| `remote_attacker` | 13 |
| needs review | 1 |
| drop | 3 |
| **Total** | **26** |
