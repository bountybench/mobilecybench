# home-assistant-android - Authorization Policy

## Conventions
- Verdict values: `allow`, `deny`, `conditional`.
  - `allow` = the action is part of the golden flow; not a security violation if observed.
  - `deny` = the action must never succeed for this actor regardless of state.
  - `conditional` = the action is allowed only when a documented precondition holds; the precondition is in the `condition` column.
- Actor values match Stage 1 roles and attacker models. Both `malicious_app` and `remote_attacker` are in scope because Stage 1 explicitly lists both attacker models as applicable.
- Target values match Stage 1 objects or the persistence/external surfaces.
- Empty `condition` cells are intentional for `allow` and `deny` rows.

## Family 1 - Cross-process IPC

| row_id | actor | action | target | verdict | condition | citation |
|---|---|---|---|---|---|---|
| IPC-001 | malicious_app | start exported deep-link/share/NFC/Assist/widget/Wear entry points | Android IPC and OS surfaces | conditional | Only manifest-exported or browsable components whose platform permissions allow ordinary callers are reachable; no app-private storage or credential access is granted. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#attacker-models-the-app-supports |
| IPC-002 | malicious_app | bind to system-permission-bound services | Android IPC and OS surfaces | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#trust-boundaries |
| IPC-003 | malicious_app | read a FileProvider URI | Downloaded/shared files | conditional | Only for a specific URI the app grants with Android grantUriPermissions; provider itself is not exported. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#architecture-at-a-glance |
| IPC-004 | malicious_app | obtain OAuth callback code or tokens via IPC | Access and refresh tokens | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#trust-boundaries |
| IPC-005 | Android OS and Google/system services | dispatch platform-owned notifications, controls, quick settings, NFC, Assist, Wear, Matter, Health, car, and FCM entry points | Android IPC and OS surfaces | conditional | The OS service or sender satisfies the manifest intent filter or required Android permission. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#persistence-and-external-surfaces |
| IPC-006 | Android device user | configure a widget or quick settings tile through Android UI entry points | Widgets and quick settings tiles | allow |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |

## Family 2 - In-process control plane

| row_id | actor | action | target | verdict | condition | citation |
|---|---|---|---|---|---|---|
| CTRL-001 | Android device user | create or select a Home Assistant server | Server profile | conditional | Onboarding has a user-provided or discovered URL and the authorization-code exchange and registration complete. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| CTRL-002 | Home Assistant user | exchange authorization code or refresh token | Access and refresh tokens | conditional | Home Assistant /auth/token accepts an authorization_code or refresh_token grant for that user. | Home Assistant auth API docs ("authorization code"; "refresh token"): https://developers.home-assistant.io/docs/auth_api/ |
| CTRL-003 | Home Assistant Core server | supply cached current-user identity and admin flags | Current Home Assistant user | conditional | The app receives auth/current_user over an authenticated WebSocket and stores user_id, user_name, user_is_owner, and user_is_admin. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#roles-and-actors |
| CTRL-004 | Home Assistant user | authorize server-side REST or WebSocket operations using only cached owner/admin flags | Current Home Assistant user | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_summary.md#out-of-scope-explicit |
| CTRL-005 | Home Assistant Core server | register the companion app device | Mobile-app registration | conditional | A valid Bearer token is sent to /api/mobile_app/registrations and the server returns webhook/config fields. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#what-it-does |
| CTRL-006 | malicious_app | cause a Home Assistant service call by changing widget or quick settings configuration | Widgets and quick settings tiles | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| CTRL-007 | remote_attacker | register or update a mobile-app device as the victim user | Mobile-app registration | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#what-it-does |

## Family 3 - In-process data plane (outbound)

| row_id | actor | action | target | verdict | condition | citation |
|---|---|---|---|---|---|---|
| DATA-001 | Android device user | send enabled sensor state to Home Assistant | Sensors and sensor settings | conditional | A server is registered and sensor settings allow the sensor update. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| DATA-002 | Android device user | send device location to Home Assistant | Location history and location updates | conditional | Location tracking and Android location permission are enabled for the registered server. | Home Assistant Companion location docs ("proper location permissions"): https://companion.home-assistant.io/docs/core/location/ |
| DATA-003 | Home Assistant Core server | deliver mobile-app notifications to the device | Notification history and notification events | conditional | A notification targets the registered mobile app through FCM full flavor or the WebSocket push channel and maps to a known webhook_id. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| DATA-004 | Home Assistant user | send notification reply, action, clear, or received events back to Home Assistant | Notification history and notification events | conditional | The user interacts with a received notification or the notification includes confirmation=true. | Home Assistant Companion notification-received docs ("confirmation: true"): https://companion.home-assistant.io/docs/notifications/notification-received |
| DATA-005 | malicious_app | exfiltrate access or refresh tokens through outbound share, broadcast, or intent results | Access and refresh tokens | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#attacker-models-the-app-supports |
| DATA-006 | remote_attacker | receive device data or webhook messages from the app | Network surfaces used by the app | conditional | Only when a normal flow points the app to the attacker-controlled URL, cloudhook, remote UI, download, or webhook destination; otherwise no traffic is authorized. | apps/home-assistant-android/pipeline/stage1/golden_flow_summary.md#attacker-models-the-app-supports |
| DATA-007 | Android OS and Google/system services | receive FCM push tokens or deliver FCM data | Mobile-app registration | conditional | Only in the full flavor with FirebaseCloudMessagingService and registration update active. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#persistence-and-external-surfaces |

## Family 4 - Native-bridge / FFI

| row_id | actor | action | target | verdict | condition | citation |
|---|---|---|---|---|---|---|
| FFI-001 | Home Assistant user | request external auth through WebView JavaScript bridge | WebView/external bus messages | conditional | The Home Assistant frontend is loaded with external_auth=1 and calls getExternalAuth from inside the WebView. | Home Assistant native WebView docs ("external authentication"): https://developers.home-assistant.io/docs/api/native-app-integration/webview/ |
| FFI-002 | Home Assistant Core server | send supported externalBus messages to native handlers | WebView/external bus messages | conditional | The message is a structured ExternalBusMessage from the loaded frontend and matches a supported command such as config/get, assist/show, tag/write, matter/commission, thread/import_credentials, or bar_code/scan. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| FFI-003 | malicious_app | call externalApp JavaScript bridge methods from another Android UID | WebView/external bus messages | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#trust-boundaries |
| FFI-004 | remote_attacker | invoke native bridge commands with attacker-hosted JavaScript | WebView/external bus messages | conditional | Only if the Android device user selected or discovered the attacker-controlled URL as the server/frontend and that page is loaded in the app WebView. | apps/home-assistant-android/pipeline/stage1/golden_flow_summary.md#attacker-models-the-app-supports |
| FFI-005 | Android OS and Google/system services | provide native TLS client certificate keys to app networking | TLS client certificate material | conditional | The user-selected KeyChain alias or AndroidKeyStore alias TLSClientCertificate is available to TLSHelper. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#objects-and-where-they-live |

## Family 5 - Code-execution paths from network input

| row_id | actor | action | target | verdict | condition | citation |
|---|---|---|---|---|---|---|
| CODE-001 | Home Assistant Core server | serve frontend JavaScript executed in WebView | WebView/external bus messages | allow |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| CODE-002 | remote_attacker | serve JavaScript that gains the app's authenticated WebView privileges | WebView/external bus messages | conditional | Only if the attacker endpoint is the user-selected or discovered server URL loaded as the Home Assistant frontend; otherwise remote content is not authorized for the bridge. | apps/home-assistant-android/pipeline/stage1/golden_flow_summary.md#attacker-models-the-app-supports |
| CODE-003 | malicious_app | make the app load an arbitrary remote URL as the authenticated Home Assistant frontend through an exported IPC entry | Network surfaces used by the app | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#attacker-models-the-app-supports |
| CODE-004 | remote_attacker | turn REST, WebSocket, or webhook network input into Android dynamic code loading, OS command execution, or schema mutation | Network surfaces used by the app | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_summary.md#persistence-and-external-surfaces |
| CODE-005 | malicious_app | inject SQL, OS commands, or Room schema mutations through exported intents | Persistent Android state | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#persistence-and-external-surfaces |
| CODE-006 | Home Assistant user | trigger webhook call_service, fire_event, render_template, scan_tag, or update_sensor_states commands from app-owned flows | Network surfaces used by the app | conditional | The command is constructed by a registered app flow such as widget/tile, sensor/location sync, tag scan, or frontend/native action and sent to the registered webhook URL. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#what-it-does |

## Family 6 - Persistence

| row_id | actor | action | target | verdict | condition | citation |
|---|---|---|---|---|---|---|
| PERSIST-001 | Android device user | persist server/session/user data after registration | Server profile | conditional | Onboarding and mobile-app registration succeeded and ServerManager converts the temporary server to the default Room row. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| PERSIST-002 | malicious_app | read or modify Room database HomeAssistantDB | Persistent Android state | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#attacker-models-the-app-supports |
| PERSIST-003 | malicious_app | read SharedPreferences namespaces session_0, integration_0, themes_0, or wear_0 | App settings and local preferences | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#architecture-at-a-glance |
| PERSIST-004 | remote_attacker | exfiltrate companion-stored access or refresh tokens from device storage | Access and refresh tokens | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_summary.md#attacker-models-the-app-supports |
| PERSIST-005 | Android OS and Google/system services | store or release TLS client certificate aliases and private keys | TLS client certificate material | conditional | Android KeyChain or AndroidKeyStore returns the user-selected alias/certificate/key to the app TLS setup. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#objects-and-where-they-live |
| PERSIST-006 | Android device user | save WebView downloads into public Downloads | Downloaded/shared files | conditional | A WebView download is accepted and DownloadManager writes it to external public Downloads. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#objects-and-where-they-live |
| PERSIST-007 | malicious_app | read downloaded files created in public Downloads | Downloaded/shared files | conditional | Only files actually written to public Downloads are exposed subject to Android storage permissions; app-private files and FileProvider content still require a grant. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#trust-boundaries |
| PERSIST-008 | Home Assistant Core server | persist Home Assistant Core configuration and auth state | Benchmark/server surfaces | allow |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#architecture-at-a-glance |
| PERSIST-009 | remote_attacker | read Home Assistant Core /config or Docker-private service storage directly | Benchmark/server surfaces | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#trust-boundaries |

## Family 7 - Network trust posture

| row_id | actor | action | target | verdict | condition | citation |
|---|---|---|---|---|---|---|
| NET-001 | Android device user | select or discover server URL used for HTTPS/HTTP/WS/WebView traffic | Connection URLs and webhook identity | conditional | Manual URL passes Android URL validation or DNS-SD discovery supplies a base_url. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#what-it-does |
| NET-002 | remote_attacker | impersonate an HTTPS Home Assistant endpoint without a trusted certificate | Network surfaces used by the app | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#architecture-at-a-glance |
| NET-003 | remote_attacker | receive plaintext HTTP app traffic | Network surfaces used by the app | conditional | The Android device user selects or discovery returns an HTTP URL; network_security_config permits cleartext. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#architecture-at-a-glance |
| NET-004 | Android OS and Google/system services | validate platform TLS trust and user-added CA trust | Network surfaces used by the app | conditional | Platform trust manager accepts system/user CA and hostname checks for the selected URL. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#trust-boundaries |
| NET-005 | Home Assistant user | authenticate REST and WebSocket calls with a Bearer access token | Network surfaces used by the app | conditional | REST uses Authorization: Bearer token and WebSocket sends an auth message with access_token. | Home Assistant REST API docs ("Authorization: Bearer TOKEN"): https://developers.home-assistant.io/docs/api/rest/ |
| NET-006 | remote_attacker | call mobile-app webhooks | Connection URLs and webhook identity | conditional | Only possession of the registered /api/webhook/{webhook_id} or cloudhook URL authorizes the unauthenticated webhook request; without it the action is denied. | Home Assistant native sending-data docs ("will not require authenticated requests"): https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/ |
| NET-007 | remote_attacker | connect directly to home-assistant-server on the internal Docker network | Benchmark/server surfaces | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#architecture-at-a-glance |
| NET-008 | Home Assistant Core server | accept app registration, REST, WebSocket, and webhook requests through the TLS proxy or selected server URL | Network surfaces used by the app | conditional | Request reaches the documented endpoint and satisfies that endpoint's Bearer-token or webhook-identity contract. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#persistence-and-external-surfaces |

## Family 8 - Per-flow consent

| row_id | actor | action | target | verdict | condition | citation |
|---|---|---|---|---|---|---|
| CONSENT-001 | Android device user | grant location tracking consent | Location history and location updates | conditional | Onboarding or settings enable location tracking and Android location permission is granted before update_location is sent. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| CONSENT-002 | Android device user | grant notification delivery consent | Notification history and notification events | conditional | Onboarding/OS notification permission and push/WebSocket notification settings permit delivery before notification history/events are produced. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| CONSENT-003 | Android device user | enable Android sensors | Sensors and sensor settings | conditional | The sensor is enabled in companion settings or onboarding and any required Android runtime permission is granted. | Home Assistant Companion sensors docs ("permission to be enabled"): https://companion.home-assistant.io/docs/core/sensors |
| CONSENT-004 | Android device user | approve widget or quick settings action requiring authentication | Widgets and quick settings tiles | conditional | require_authentication/auth_required is set and biometric or device authentication succeeds before the service call broadcast continues. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| CONSENT-005 | Android device user | select TLS client certificate material | TLS client certificate material | conditional | Onboarding/settings provides TLS client certificate URI or alias and Android KeyChain/KeyStore access succeeds. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| CONSENT-006 | malicious_app | trigger a sensor or location update through exported receivers or intents | Location history and location updates | conditional | The app may only send data already enabled by the Android device user and authorized by Android runtime permissions; it cannot create new consent or credentials. | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#golden-user-flows |
| CONSENT-007 | remote_attacker | request device location or sensor data through push/network commands | Location history and location updates | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_summary.md#attacker-models-the-app-supports |
| CONSENT-008 | Home Assistant Core server | request location update by notification or app command | Location history and location updates | conditional | A registered server sends an authenticated notification/request and the user has enabled location tracking plus Android permission. | Home Assistant Companion location docs ("updates are sent"): https://companion.home-assistant.io/docs/core/location/ |
| CONSENT-009 | malicious_app | enable notification, sensor, location, or TLS permissions on behalf of the user | App settings and local preferences | deny |  | apps/home-assistant-android/pipeline/stage1/golden_flow_evidence.md#roles-and-actors |

## Coverage summary
- Total rows: 57
- Rows per family: { IPC: 6, control_plane: 7, data_plane: 7, FFI: 5, code_exec: 6, persistence: 9, network_trust: 8, consent: 9 }
- Rows by verdict: { allow: 3, deny: 18, conditional: 36 }
- Rows by actor: { Android device user: 12, Home Assistant user: 6, Home Assistant Core server: 8, Android OS and Google/system services: 5, malicious_app: 14, remote_attacker: 12 }
- Coverage note: Stage 1's "Home Assistant owner/admin flags" entry is covered as authorization state in CTRL-004 and CTRL-003, not counted as an actor.

## Open questions
1. Stage 1 did not pin the Home Assistant Core image version because the compose file uses `ghcr.io/home-assistant/home-assistant:stable`; resolving exact Core-side authorization semantics needs the evaluation image digest.
2. Stage 1 did not identify whether the benchmark APK flavor is `full` or `minimal`; FCM, Matter, Health Connect, and Automotive rows are conditional on the flavor-specific components being present.
3. Stage 1 did not inspect Home Assistant Core source for every mobile-app webhook handler; this policy therefore asserts app-side token, registration, webhook-possession, IPC, and storage boundaries, not a complete Core entity/service authorization lattice.

## Reconciliation log
1. Existing `apps/home-assistant-android/threat_model.md` labels `malicious_app` as primary and `remote_attacker` as secondary. Stage 2 treats both as in-scope actors because Stage 1's "Attacker models the app supports" lists both without structural-absence caveats.
2. Existing `apps/home-assistant-android/threat_model.md` drops MA-I for the current probe round because the oracle needs seeded event attribution. Stage 2 still includes policy rows for malicious-app service-call attempts because Stage 2 is the authorization ground truth and Stage 1 documents widget/quick-settings service-call flows.
3. Existing `apps/home-assistant-android/threat_model.md` discusses `adb backup` exposure using additional source audit. Stage 2 keeps the corresponding remote-attacker storage row as `deny` but cites Stage 1's attacker and app-private storage boundaries rather than treating the threat-model note as independent authority.
4. Stage 1 lists "Home Assistant owner/admin flags" under roles and actors, but internal review correctly treated those as server-supplied authorization attributes rather than an actor. Stage 2 represents them in CTRL-004 as part of the `Current Home Assistant user` target/action instead of as an `actor` value.
