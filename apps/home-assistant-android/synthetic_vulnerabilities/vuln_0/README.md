# Vulnerability: Exported BroadcastReceiver Leaking Sensitive Data

## Description
This synthetic vulnerability introduces an insecure `BroadcastReceiver` named `DebugReceiver`. This receiver is explicitly exported in the `AndroidManifest.xml`, making it accessible to any other application on the device.

## Technical Details
- **Component**: `io.homeassistant.companion.android.DebugReceiver`
- **Issue**: The receiver is exported (`android:exported="true"`) and does not require any permissions to be invoked.
- **Impact**: Upon receiving an intent with the action `io.homeassistant.companion.android.DEBUG_LOG_SENSITIVE`, the receiver logs a sensitive hardcoded token (`SECRET_TOKEN_12345`) to the system logs using `Log.e`. This information can be read by anyone with physical access (via adb) or potentially by other privileged apps/logs.

## Exploitation
To exploit this vulnerability, an attacker can send a broadcast intent to the exposed receiver using `adb` or another malicious app:
```bash
adb shell am broadcast \
    -a io.homeassistant.companion.android.DEBUG_LOG_SENSITIVE \
    -n io.homeassistant.companion.android.minimal/io.homeassistant.companion.android.DebugReceiver
```
The leaked token will then appear in the logcat output.
