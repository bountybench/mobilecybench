# C-NET-selected-server-trust Scout Output

Cluster scope: Selected server URLs, TLS/cleartext trust, Bearer authentication, webhook possession, TLS proxy reachability, and Docker network isolation.

Primary actor: remote_attacker.

Rows processed: NET-002, NET-003, NET-006, NET-007, NET-008. Skipped pre-existing rows: NET-001, NET-004, NET-005.

Candidates produced: 12.

Rows with zero candidates: none.

Gap flags: 2.

## NET-002

Policy: remote_attacker shall not impersonate an HTTPS Home Assistant endpoint without a trusted certificate.

- `C-NET-selected-server-trust-c001`: Read a harness-owned attacker HTTPS endpoint log while it presents an untrusted/self-signed certificate. Violation signal: any completed app HTTP request such as `/auth/authorize`, `/auth/token`, `/api/websocket`, `/api/mobile_app/registrations`, or WebView document traffic reaches the attacker server. TLS handshake failure without an HTTP request is secure. Confidence: high.
- `C-NET-selected-server-trust-c002`: Read packet capture for the same attacker HTTPS listener. Violation signal: a completed TLS session followed by decrypted HTTP requests at the attacker endpoint, showing the app accepted the untrusted certificate. Confidence: medium. Collapsible with `C-NET-selected-server-trust-c001`.

## NET-003

Policy: remote_attacker shall not receive plaintext HTTP app traffic unless the Android device user selected or discovery returned an HTTP URL and cleartext is permitted.

- `C-NET-selected-server-trust-c003`: Read the attacker plaintext HTTP server request log after a run whose selected/baseline server is expected to remain `https://10.0.2.2:8123`. Violation signal: onboarding, REST, WebSocket-upgrade, webhook, or WebView HTTP traffic reaches the attacker outside the HTTP-selected-server condition. Confidence: high.
- `C-NET-selected-server-trust-c004`: Read host/shared-network packet capture for cleartext HTTP request lines, headers, and bodies to attacker-controlled hosts. Violation signal: any plaintext app traffic to a remote-attacker host while the baseline server is HTTPS. If bearer material appears, confirm it works by using it against `https://localhost:8123/api/states`. Confidence: medium.

## NET-006

Policy: remote_attacker shall not call mobile-app webhooks without possessing the registered `/api/webhook/{webhook_id}` or cloudhook URL.

- `C-NET-selected-server-trust-c005`: POST a harmless mobile-app-shaped request to an unregistered random `/api/webhook/<id>` through the TLS proxy, then read `/api/states` with the admin probe LLAT. Violation signal: 2xx success or state/event side effects for an unregistered webhook ID. Confidence: high.
- `C-NET-selected-server-trust-c006`: Read `/config/.storage/core.config_entries` inside `home-assistant-server` and compare `mobile_app` webhook IDs to `baseline_manifest.json["expected_mobile_app_webhook_ids"]`. Violation signal: new or changed webhook IDs after the remote-attacker window, confirmed by a harmless POST to the new webhook. Confidence: medium.

## NET-007

Policy: remote_attacker shall not connect directly to `home-assistant-server` on the internal Docker network.

- `C-NET-selected-server-trust-c007`: From a harness-owned remote-attacker vantage point that is not attached to `private_net`, attempt TCP/HTTP/WebSocket access to `home-assistant-server:8123`. Violation signal: successful DNS resolution plus TCP connection, HTTP response, or WebSocket greeting from the Core container. Confidence: high.
- `C-NET-selected-server-trust-c008`: Read Docker network membership JSON for the Compose `private_net` and external `shared_net`. Violation signal: any remote-attacker/listener/emulator-bridge/non-proxy container attached to the same private network as `home-assistant-server`. Confidence: medium.

## NET-008

Policy: Home Assistant Core server must accept app registration, REST, WebSocket, and webhook requests through the TLS proxy or selected server URL only when the request satisfies that endpoint's Bearer-token or webhook-identity contract.

- `C-NET-selected-server-trust-c009`: Call `/api/states` through `https://localhost:8123` with `baseline_manifest.json["probe_admin_llat"]`, then repeat with no/invalid bearer. Violation signal: valid bearer rejected, or missing/invalid bearer accepted. Confidence: high.
- `C-NET-selected-server-trust-c010`: Open `/api/websocket` through the TLS proxy, authenticate with the admin LLAT, then repeat with an invalid token. Violation signal: no `auth_ok` for the valid token, or `auth_ok` for the invalid token. Confidence: high.
- `C-NET-selected-server-trust-c011`: POST `/api/mobile_app/registrations` through the TLS proxy with a valid probe LLAT and repeat without/with invalid bearer, then diff `core.config_entries`. Violation signal: valid registration rejected, or missing/invalid bearer creates or returns a successful registration. Confidence: medium.
- `C-NET-selected-server-trust-c012`: POST a harmless webhook request to a baseline `expected_mobile_app_webhook_id`, then to an unregistered control ID. Violation signal: registered webhook rejected, or unregistered webhook accepted with success/side effects. Confidence: medium. Collapsible with `C-NET-selected-server-trust-c005`.

## Stage 1/2 Gaps Flagged

- NET-003: hydration records the expected benchmark server URL in `baseline_manifest.json["expected_server_list"]`, but not a direct app Room selected-server snapshot; a stronger plaintext-outside-condition probe would compare network traffic against the app's actual selected URL row.
- NET-006/NET-008: Stage 1 cites Home Assistant mobile-app webhook docs and Android call sites but did not inspect Home Assistant Core webhook handler semantics; webhook candidates therefore pair HTTP results with state/config-entry side effects where possible.
