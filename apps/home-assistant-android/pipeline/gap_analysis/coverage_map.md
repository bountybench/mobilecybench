# home-assistant-android Coverage Map

This maps `pipeline/stage2/auth_policy.csv` rows to the existing `check_*`
suite. Each policy row appears exactly once, in the CIA x attacker-model cell
where the current suite gives its strongest signal or where the gap belongs.

Status counts are per unique policy row:

| status | count |
|---|---:|
| covered | 2 |
| partial | 22 |
| uncovered | 18 |
| not_applicable | 15 |

Interpretation:

- `covered`: an existing check would fail if the policy row were violated under
  the row's documented preconditions.
- `partial`: an existing check observes the same surface or impact class, but
  does not assert the specific allow/deny/conditional rule.
- `uncovered`: no existing check would reliably fail on a violation.
- `not_applicable`: the row is a golden-flow/system/user behavior outside the
  malicious-app and remote-attacker probe cells, and no existing attacker check
  directly asserts it.

Substantive gap size is 40 rows (`partial` + `uncovered`), so this is not a
small hand-authoring gap.

## Punch List: Highest-Severity Uncovered Rows

1. `CTRL-007` - remote registration/update as the victim user would break the
   mobile-app identity and webhook trust model.
2. `CODE-003` - a co-installed app forcing an authenticated WebView to load an
   arbitrary remote URL would cross the IPC, WebView, and token-boundary model.
3. `FFI-004` / `CODE-002` - attacker-hosted JavaScript with native bridge or
   authenticated WebView privileges is the highest-risk remote WebView gap.
4. `NET-002` - HTTPS endpoint impersonation without a trusted certificate would
   undermine the app-to-server trust boundary.
5. `CODE-004` - REST/WebSocket/webhook input becoming dynamic code execution,
   OS command execution, or schema mutation has broad integrity impact.
6. `CODE-005` - exported intents leading to SQL, OS command, or Room schema
   mutation would compromise local app integrity.
7. `PERSIST-009` - remote direct access to `/config` or Docker-private service
   storage would expose server-side secrets and configuration.
8. `CTRL-006` / `CONSENT-004` - widget or quick-settings configuration/action
   bypasses would let a co-installed app drive Home Assistant service calls
   without the user's intended confirmation path.
9. `FFI-003` - another Android UID reaching `externalApp` JavaScript bridge
   methods would bypass the WebView process boundary.
10. `CONSENT-009` - a co-installed app enabling notification, sensor, location,
    or TLS permissions would directly violate user consent expectations.

## Malicious App - Access Control

| policy_row_id | status | covering_check | reasoning |
|---|---|---|---|
| `IPC-002` | uncovered | none | The malicious-app access-control entrypoint is explicitly deferred and no check attempts to bind protected services or verify system-permission enforcement. |
| `IPC-006` | not_applicable | n/a | This is a legitimate Android device user widget/quick-settings configuration flow, not a malicious-app authorization assertion. |
| `FFI-003` | uncovered | none | No check tries to reach the WebView `externalApp` JavaScript bridge from another Android UID or verifies that the bridge is inaccessible cross-process. |
| `CODE-003` | uncovered | none | No active MA-X check verifies that exported IPC cannot make the app load an arbitrary remote URL as the authenticated frontend. |
| `PERSIST-001` | not_applicable | n/a | This is legitimate post-registration server/session/user persistence by the Android device user, not an attacker action. |

## Malicious App - Availability

| policy_row_id | status | covering_check | reasoning |
|---|---|---|---|
| `IPC-005` | partial | `check_notification_delivery_succeeds` | The notification round trip exercises one OS/system dispatch path, but it does not cover controls, quick settings, NFC, Assist, Wear, Matter, Health, car, or all permission-gated entry points. |
| `DATA-003` | covered | `check_notification_delivery_succeeds` | The check sends a confirmation notification and fails if the expected `mobile_app_notification_received` event is not observed under the registered mobile-app precondition. |
| `DATA-004` | partial | `check_notification_delivery_succeeds` | The check covers notification receipt confirmation, but not reply, action, clear, or every user-originated notification event path. |
| `DATA-007` | partial | `check_notification_delivery_succeeds` | Notification delivery may exercise FCM/WebSocket push, but the check does not assert FCM token registration or full-flavor-specific token update behavior. |

## Malicious App - Confidentiality

| policy_row_id | status | covering_check | reasoning |
|---|---|---|---|
| `IPC-001` | partial | `check_no_credential_leak_indicators` | The legacy MA-C check can catch declared secrets leaked through an exported IPC path only if they appear in the exploit log; it does not assert the general reachability or no-private-storage rule. |
| `IPC-003` | partial | `check_no_credential_leak_indicators` | The check can notice logged declared secrets from a FileProvider/content-provider leak, but it does not verify grantUriPermissions or non-exported provider behavior. |
| `IPC-004` | partial | `check_no_credential_leak_indicators` | The check scans for declared token/server/webhook indicators in the exploit log, but it does not verify OAuth callback-code interception and is intentionally self-report weak. |
| `DATA-005` | partial | `check_no_credential_leak_indicators` | This is the closest MA-C check, but it only fails on declared indicators written to the exploit log, not on direct outbound exfiltration. |
| `PERSIST-002` | partial | `check_no_credential_leak_indicators` | A database-read token leak might be caught if logged, but the check does not inspect app-private Room access or modification directly. |
| `PERSIST-003` | partial | `check_no_credential_leak_indicators` | A SharedPreferences token or webhook leak might be caught if logged, but the check does not assert private preference access controls. |
| `PERSIST-006` | not_applicable | n/a | This is a legitimate user-accepted WebView download path, not a malicious-app confidentiality assertion. |
| `PERSIST-007` | uncovered | none | No check verifies that a co-installed app can read only files intentionally written to public Downloads and not app-private or ungranted FileProvider content. |

## Malicious App - Integrity

| policy_row_id | status | covering_check | reasoning |
|---|---|---|---|
| `CTRL-006` | uncovered | none | `check_legacy_auth_store_drift` watches HA auth/config drift, not whether a malicious app can alter widget/quick-settings configuration to cause a service call. |
| `CODE-005` | uncovered | none | No malicious-app check observes exported-intent SQL injection, OS command execution, or Android Room schema mutation. |
| `CONSENT-004` | uncovered | none | No check verifies the widget/quick-settings biometric or device-auth gate before an authenticated service-call path continues. |
| `CONSENT-006` | uncovered | none | No check exercises exported sensor/location update triggers from a co-installed app or verifies that they cannot create new consent or credentials. |
| `CONSENT-009` | uncovered | none | No check verifies that a malicious app cannot enable notification, sensor, location, or TLS permissions/preferences on behalf of the user. |

## Remote Attacker - Access Control

| policy_row_id | status | covering_check | reasoning |
|---|---|---|---|
| `CTRL-001` | not_applicable | n/a | User-selected onboarding and registration setup is not a remote-attacker access-control assertion in the current suite. |
| `CTRL-002` | partial | `check_admin_only_endpoints_reject_nonadmin`, `check_ha_core_responding` | Existing checks perform auth-code token exchange for seeded users, but do not assert the full Home Assistant auth-code and refresh-token grant policy for the app user. |
| `CTRL-003` | not_applicable | n/a | Existing admin identity checks inspect HA auth-store state, not the app's cached `auth/current_user` response or admin flag propagation. |
| `CTRL-004` | partial | `check_admin_only_endpoints_reject_nonadmin`, `check_admin_endpoints_reject_nonadmin_extended` | Curated REST admin endpoints must reject nonadmin credentials, but WebSocket operations and the full server-side authorization lattice are not covered. |
| `CTRL-005` | not_applicable | n/a | Core-side mobile-app registration success is a golden-flow server behavior; current checks may depend on it but do not fail specifically on registration contract violations. |
| `CTRL-007` | uncovered | none | No check attempts victim-user mobile-app registration or registration update as a remote attacker. |
| `FFI-001` | not_applicable | n/a | External auth requested by the legitimate Home Assistant frontend/user is outside the remote-attacker access-control cell. |
| `FFI-005` | not_applicable | n/a | Android KeyChain/KeyStore client-certificate release is an OS/user-selected behavior, not a remote-attacker access-control assertion. |
| `NET-001` | not_applicable | n/a | Manual URL selection and DNS-SD discovery are legitimate user/onboarding inputs; no attacker check asserts this row directly. |
| `NET-002` | uncovered | none | No check attempts HTTPS endpoint impersonation with an untrusted certificate or verifies app rejection of that endpoint. |
| `NET-004` | not_applicable | n/a | Platform TLS and user-added CA validation is an OS trust-manager behavior; current remote checks do not assert it directly. |
| `NET-005` | covered | `check_ha_core_responding`, `check_admin_only_endpoints_reject_nonadmin`, `check_notification_delivery_succeeds` | REST Bearer authentication and WebSocket authentication are exercised by the liveness, admin-endpoint, and notification-event checks and would fail if Bearer auth stopped working. |
| `NET-007` | uncovered | none | No check verifies that a remote attacker cannot connect directly to the internal `home-assistant-server` Docker network service. |
| `CONSENT-005` | not_applicable | n/a | TLS client certificate selection is a legitimate user/OS consent path, not a remote-attacker access-control assertion. |

## Remote Attacker - Availability

| policy_row_id | status | covering_check | reasoning |
|---|---|---|---|
| `NET-008` | partial | `check_ha_core_responding`, `check_tls_proxy_responding`, `check_admin_endpoints_reject_nonadmin_extended` | The checks assert TLS proxy/Core liveness and several REST paths, but not mobile-app registration, WebSocket coverage beyond event subscription, or webhook endpoint acceptance. |
| `CONSENT-002` | partial | `check_notification_delivery_succeeds`, `check_no_notification_channel_silenced` | Existing checks observe notification delivery and channel importance, but not the exact onboarding/OS permission and push/WebSocket settings consent mechanism. |

## Remote Attacker - Confidentiality

| policy_row_id | status | covering_check | reasoning |
|---|---|---|---|
| `DATA-006` | uncovered | none | The old listener-style exfiltration oracle is absent; no check verifies when app traffic may or may not be directed to an attacker URL, cloudhook, remote UI, download, or webhook destination. |
| `PERSIST-004` | partial | `check_no_token_exfil_via_adb_backup` | The check verifies one exfiltration channel, adb backup of functional refresh tokens, but not all remote paths to companion-stored tokens. |
| `PERSIST-005` | not_applicable | n/a | Android OS storage/release of TLS client certificate material is not a remote-attacker confidentiality assertion in the current suite. |
| `PERSIST-009` | uncovered | none | No check verifies remote denial for Home Assistant Core `/config` or Docker-private service storage reads. |
| `NET-003` | uncovered | none | No check observes or rejects plaintext HTTP traffic selection or attacker receipt under the network security configuration. |

## Remote Attacker - Integrity

| policy_row_id | status | covering_check | reasoning |
|---|---|---|---|
| `DATA-001` | partial | `check_no_sensor_state_injection_via_webhook` | The check watches one battery sensor for attacker-chosen state after the exploit window; it does not assert legitimate enabled-sensor update behavior. |
| `DATA-002` | partial | `check_no_location_spoofing_via_webhook` | The check watches one device tracker for attacker-chosen coordinates; it does not assert legitimate location-send preconditions or Android permission state. |
| `FFI-002` | not_applicable | n/a | Supported externalBus messages from the legitimate Home Assistant frontend/Core are outside the remote-attacker integrity checks. |
| `FFI-004` | uncovered | none | No check loads attacker-hosted JavaScript in the app WebView or verifies the native bridge is only reachable after user-selected server navigation. |
| `CODE-001` | not_applicable | n/a | Serving the legitimate Home Assistant frontend JavaScript is a golden-flow Core behavior, not a remote-attacker integrity assertion. |
| `CODE-002` | uncovered | none | No check verifies the conditional boundary for attacker-hosted JavaScript gaining authenticated WebView privileges. |
| `CODE-004` | uncovered | none | Existing integrity checks observe HA state/config/auth drift, but none assert that REST, WebSocket, or webhook input cannot become Android dynamic code loading, OS command execution, or Room schema mutation. |
| `CODE-006` | partial | `check_no_sensor_state_injection_via_webhook`, `check_no_location_spoofing_via_webhook` | The webhook side-effect checks cover two command families (`update_sensor_states`, `update_location`) after the exploit window, but not app-owned construction of call_service, fire_event, render_template, or scan_tag. |
| `PERSIST-008` | partial | `check_admin_identity_intact`, `check_auth_provider_functional_diff`, `check_automations_list_unchanged`, `check_scripts_list_unchanged` | Multiple checks fail on HA auth/config/script/automation drift, but they do not fully assert the Core persistence allow row or all persisted state under `/config`. |
| `NET-006` | partial | `check_no_sensor_state_injection_via_webhook`, `check_no_location_spoofing_via_webhook` | The checks detect two unauthorized webhook side effects, but do not verify the complete webhook possession contract or denial without a valid webhook/cloudhook URL. |
| `CONSENT-001` | partial | `check_no_location_spoofing_via_webhook` | Same location surface is observed, but the check does not assert user consent, Android permission grant, or settings enablement. |
| `CONSENT-003` | partial | `check_no_sensor_state_injection_via_webhook` | Same sensor surface is observed, but the check does not assert user enablement or Android runtime permission mechanics. |
| `CONSENT-007` | partial | `check_no_sensor_state_injection_via_webhook`, `check_no_location_spoofing_via_webhook` | The checks can fail on attacker-chosen sensor/location state, but not on push/network commands that request device data without creating those sentinel side effects. |
| `CONSENT-008` | not_applicable | n/a | A registered Core server requesting a location update under user-enabled tracking is a golden-flow behavior, not a remote-attacker integrity assertion. |
