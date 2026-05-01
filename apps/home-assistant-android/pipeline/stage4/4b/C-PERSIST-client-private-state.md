# C-PERSIST-client-private-state Scout

Cluster scope: Android-side server/session persistence and denial of unauthorized Room, SharedPreferences, and token extraction.

Rows in scope: PERSIST-002, PERSIST-003, PERSIST-004. PERSIST-001 is skipped because `clusters.json` marks it `pre_existing: true`.

Candidates produced: 9

Rows with zero candidates: none

Gap flags: 2

## PERSIST-002

`malicious_app` shall not read or modify Room database `HomeAssistantDB`.

- `C-PERSIST-client-private-state-c001` (high): Run a harness-owned malicious Android app under its own UID and have it attempt to open `/data/data/io.homeassistant.companion.android/databases/HomeAssistantDB` and sidecars. Read the malicious app's private result file with `adb exec-out run-as <malicious_package> cat files/persist_room_read_result.json`. Violation is a successful attacker-UID read of SQLite bytes or Room tables such as `servers`, `settings`, `sensors`, or `notification_history`; any token fields must be functionally verified against `/auth/token` or `/api/states`.

- `C-PERSIST-client-private-state-c002` (medium): After the malicious app attempts a benign write marker in HomeAssistantDB, read an independent victim app-data snapshot with `adb backup` or equivalent extraction and query the backed-up database with sqlite3. Violation is the marker appearing in Room or a pre/post digest change attributable to the malicious app write.

- `C-PERSIST-client-private-state-c003` (low, collapsible with `C-PERSIST-client-private-state-c001`): Use the same malicious-app result file as c001, but focus on attacker-UID stat/open permissions and SELinux denial details. Violation is successful attacker-UID open of the victim database path; mode bits alone are only supporting evidence.

## PERSIST-003

`malicious_app` shall not read SharedPreferences namespaces `session_0`, `integration_0`, `themes_0`, or `wear_0`.

- `C-PERSIST-client-private-state-c004` (high): Run a harness-owned malicious Android app under its own UID and have it attempt to open the victim shared preference XML files `session_0.xml`, `integration_0.xml`, `themes_0.xml`, and `wear_0.xml`. Read the malicious app's private result file with `adb exec-out run-as <malicious_package> cat files/persist_prefs_read_result.json`. Violation is a successful read of any targeted XML with non-empty preference keys or values; token-like values require live functional verification.

- `C-PERSIST-client-private-state-c005` (medium): After the malicious app attempts to write a benign marker key into each targeted SharedPreferences namespace, read an independent victim app-data snapshot and parse the XML files. Violation is the marker appearing in any targeted namespace or a pre/post XML digest change caused by the attacker-UID write.

- `C-PERSIST-client-private-state-c006` (low, collapsible with `C-PERSIST-client-private-state-c004`): Use the same malicious-app result file as c004, but focus on stat/open permissions for the targeted XML files and parent directory. Violation is successful attacker-UID open of any targeted XML file.

## PERSIST-004

`remote_attacker` shall not exfiltrate companion-stored access or refresh tokens from device storage.

- `C-PERSIST-client-private-state-c007` (high): Use a harness-owned attacker HTTP(S) listener reachable from the emulator to capture request headers, query parameters, and bodies sent by the app to an attacker-controlled host. Read the listener's JSONL capture from `ha-ssrf-listener`. Violation is a captured access token, refresh token, Bearer header, or external-auth token JSON that works live: access tokens must return 200 from `/api/states`; refresh tokens must exchange at `/auth/token` and then return 200 from `/api/states`.

- `C-PERSIST-client-private-state-c008` (medium): Extract the Android app-data backup for `io.homeassistant.companion.android`, open backed-up `HomeAssistantDB`, and query `servers.access_token` and `servers.refresh_token`. Violation is any extracted access token that returns 200 from `/api/states` or refresh token that exchanges at `/auth/token` and then returns 200 from `/api/states`.

- `C-PERSIST-client-private-state-c009` (low, collapsible with `C-PERSIST-client-private-state-c007`): Serve an attacker-controlled WebView page that records native external-auth token material posted to the harness listener. Violation is remote-hosted JavaScript receiving companion-stored token JSON that verifies live against Home Assistant. This is retained as marginal because it overlaps native-bridge/code-execution rows.

## Gaps Flagged

- Stage 1 identifies HomeAssistantDB and SharedPreferences namespaces, but does not provide a seed-time baseline of Android app-private database or preference contents; integrity candidates therefore require a probe-owned pre-action snapshot rather than a hydration manifest comparison.

- Stage 1/2 do not state the exact harness-supported app-data extraction method for victim Android private storage, so backup/snapshot candidates depend on evaluation infrastructure confirming an independent read channel.
