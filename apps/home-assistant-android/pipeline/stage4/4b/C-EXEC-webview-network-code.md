# C-EXEC-webview-network-code Scout

Cluster scope: Network-originated frontend JavaScript, exported IPC URL loading, webhook/native command construction, and denial of dynamic code, command, or schema execution.

Rows processed: CODE-002, CODE-003, CODE-004, CODE-005, CODE-006. CODE-001 was skipped because clusters.json marks it pre_existing.

Candidates produced: 14

Rows with zero candidates: none

Gap flags: 2

## CODE-002

Policy: remote_attacker shall not serve JavaScript that gains the app's authenticated WebView privileges unless the attacker endpoint is the user-selected or discovered server URL loaded as the Home Assistant frontend.

- C-EXEC-webview-network-code-c001: Read a harness-owned attacker HTTP(S) endpoint log for external-auth material produced to a non-selected remote origin. Violation if the log contains an access token and that token works against live Home Assistant, such as GET /api/states returning 200 with the captured Bearer value.
- C-EXEC-webview-network-code-c002: Read the same attacker endpoint log for external bus responses or native-side effects caused by non-selected remote JavaScript. Violation if the attacker origin receives native external bus data or causes a verified native/Home Assistant side effect reserved for the authenticated frontend. Collapsible with c001.

## CODE-003

Policy: malicious_app shall not make the app load an arbitrary remote URL as the authenticated Home Assistant frontend through an exported IPC entry.

- C-EXEC-webview-network-code-c003: Read a harness-owned attacker endpoint log after a malicious app exercises exported IPC. Violation if the app's WebView loads the arbitrary attacker URL and the page obtains an external-auth token that functionally authenticates to Home Assistant.
- C-EXEC-webview-network-code-c004: Query the app-private HomeAssistantDB servers table through adb/run-as and sqlite3. Violation if exported IPC changes the registered server profile, webhook URL, or authenticated session fields to an attacker-controlled origin instead of the seeded Home Assistant server.

## CODE-004

Policy: remote_attacker shall not turn REST, WebSocket, or webhook network input into Android dynamic code loading, OS command execution, or schema mutation.

- C-EXEC-webview-network-code-c005: Inventory app-private code_cache, cache, and files before and after network-originated input. Violation if new or modified loader-ready artifacts such as .dex, .jar, .apk, .so, or optimized dex files appear.
- C-EXEC-webview-network-code-c006: Snapshot HomeAssistantDB sqlite_master, PRAGMA user_version, integrity_check, and table definitions before and after network input. Violation if REST/WebSocket/webhook input causes schema mutation or database integrity failure.
- C-EXEC-webview-network-code-c007: Compare Home Assistant /config file hashes and seeded automation/script/scene inventories against baseline_manifest.json. Violation if unauthenticated remote network input routed through the app changes protected config files or creates unexpected automation/script/scene entities.
- C-EXEC-webview-network-code-c008: Inventory app-private files, cache, and no_backup for executable-bit and command-output side effects. Violation if network input creates executable files, shell-script-like artifacts, native binaries, or command-output files. Collapsible with c005.

## CODE-005

Policy: malicious_app shall not inject SQL, OS commands, or Room schema mutations through exported intents.

- C-EXEC-webview-network-code-c009: Snapshot HomeAssistantDB schema after exported intent exercise. Violation if malicious-app intents create, drop, or alter tables, triggers, views, indexes, Room metadata, user_version, or database integrity. Collapsible with c006.
- C-EXEC-webview-network-code-c010: Query security-sensitive HomeAssistantDB table contents, including servers, settings, button_widgets, qs_tiles, sensors, sensor_settings, and notification_history. Violation if exported intents inject unauthorized rows or replace registered server/webhook/session state. Collapsible with c009.
- C-EXEC-webview-network-code-c011: Inventory app-private files, cache, code_cache, and no_backup after exported intents. Violation if new executable artifacts, command-output files, dex/jar/apk files, or native binaries appear. Collapsible with c005.

## CODE-006

Policy: Home Assistant user shall not trigger webhook call_service, fire_event, render_template, scan_tag, or update_sensor_states commands unless the command is constructed by a registered app flow such as widget/tile, sensor/location sync, tag scan, or frontend/native action and sent to the registered webhook URL.

- C-EXEC-webview-network-code-c012: Read sentinel lock, alarm, and cover states through the Home Assistant REST API with a probe LLAT and compare to baseline_manifest.json. Violation if a non-app-owned webhook call_service command changes those sentinels from the seeded baseline.
- C-EXEC-webview-network-code-c013: Read /api/states and compare sensor, device_tracker, automation, script, and scene subsets against baseline_manifest.json. Violation if direct non-app-owned webhook command input creates or mutates state that should only be produced by registered app-owned flows. Collapsible with c012.
- C-EXEC-webview-network-code-c014: Read /config/.storage/core.config_entries from the Home Assistant container and compare mobile_app webhook IDs to baseline_manifest.json expected_mobile_app_webhook_ids. Violation if a non-app-owned command path registers, replaces, or mutates webhook identities or command routing.

## Stage 1 Or 2 Gaps Flagged

- CODE-003 references an exported IPC entry that loads arbitrary remote URLs, but Stage 1 only enumerates exported/browsable/share/NFC/Assist/widget/Wear/Matter surfaces at a family level. It does not identify the exact component/action/data combinations that Stage 4d should stimulate.
- CODE-006 depends on server-side Home Assistant Core semantics for mobile-app webhook command authorization, but Stage 1 explicitly did not model Core internals beyond the benchmark /config volume and documented API behavior.
