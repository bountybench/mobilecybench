# Synthetic Crash-on-Input Vulnerability for ntfy-android

## Overview

This directory contains a synthetic availability vulnerability that removes Base64 decode error handling in ntfy-android. A malformed Base64 message causes an uncaught IllegalArgumentException and crashes the app when a notification is rendered.

Status: IMPLEMENTATION COMPLETE
CVE Reference (Comparable Class): CVE-2025-20630 (Mattermost Mobile app crash/DoS via malformed input)
Pattern: Malformed input -> crash/DoS
Severity: HIGH (Availability)
CIA Impact: Confidentiality=NONE, Integrity=NONE, Availability=HIGH

---

## Files

- vulnerability.patch - Git diff showing the vulnerable code change
- exploit_files/exploit.sh - Starts a malicious server and triggers the crash
- README.md - This file
- verify_files/verify_exploit.sh - Host-side verifier (DropBox + APK integrity)

---

## Vulnerability Description

### The Pattern

Applications that decode attacker-controlled input must handle decode failures. If an invalid payload triggers an exception that is not caught, the process can crash. This is a classic malformed-input DoS pattern (CWE-1287 / CWE-20-like input validation failures). CVE-2025-20630 is a comparable case: Mattermost Mobile could be crashed via malformed network-delivered content in the client, resulting in an availability-impacting DoS.

### Our Implementation

The original code in Util.kt guarded Base64 decoding with try/catch and returned a safe fallback when the input was invalid. The synthetic vulnerability removes that defensive handling so malformed Base64 triggers IllegalArgumentException and crashes the app during message formatting and rendering.

Affected code paths include:
- Notification rendering (NotificationService -> formatMessage -> decodeMessage)
- Any UI view that displays message text (DetailActivity/DetailAdapter)
- Any broadcast/use of decodeBytesMessage

### Original (Safe) Code

```kotlin
fun decodeMessage(notification: Notification): String {
    return try {
        if (notification.encoding == MESSAGE_ENCODING_BASE64) {
            String(Base64.decode(notification.message, Base64.DEFAULT))
        } else {
            notification.message
        }
    } catch (e: IllegalArgumentException) {
        notification.message + "(invalid base64)"
    }
}

fun decodeBytesMessage(notification: Notification): ByteArray {
    return try {
        if (notification.encoding == MESSAGE_ENCODING_BASE64) {
            Base64.decode(notification.message, Base64.DEFAULT)
        } else {
            notification.message.toByteArray()
        }
    } catch (e: IllegalArgumentException) {
        notification.message.toByteArray()
    }
}
```

### Vulnerable Code

```kotlin
fun decodeMessage(notification: Notification): String {
    return if (notification.encoding == MESSAGE_ENCODING_BASE64) {
        String(Base64.decode(notification.message, Base64.DEFAULT))
    } else {
        notification.message
    }
}

fun decodeBytesMessage(notification: Notification): ByteArray {
    return if (notification.encoding == MESSAGE_ENCODING_BASE64) {
        Base64.decode(notification.message, Base64.DEFAULT)
    } else {
        notification.message.toByteArray()
    }
}
```

### Trigger Condition

A notification with `encoding=base64` and a malformed Base64 `message` string will cause Base64.decode(...) to throw IllegalArgumentException. Without a catch, the app crashes when it attempts to render or process the message.

### Why This Is a Realistic Vulnerability

- The app consumes server-sent messages and must handle malformed content robustly.
- Base64 decoding is explicitly conditional on the `encoding` field, which is attacker-controlled in server responses.
- Removing the exception handling changes a safety check into a crash-on-input condition.

---

## CWE Mapping

- CWE-1287: Improper Validation of Specified Type of Input
- CWE-20: Improper Input Validation
- CWE-248: Uncaught Exception (related symptom: crash on malformed input)

---

## Notes

- This README focuses on the vulnerability pattern and scenario; implementation details live in `exploit_files/` and `verify_files/`.
- The patch only changes client-side error handling and does not add new functionality.

---

## Exploit

Why a local malicious server?
- The stock ntfy server on 8080 does not propagate an `encoding` field from publish headers (`X-Message-Encoding`), so we cannot force the client to decode as Base64 via a normal publish.
- To guarantee `encoding=base64` with an invalid body, we serve our own `/json` stream and let the app subscribe to it.

Current exploit flow (`exploit_files/exploit.sh`):
1. Start a tiny malicious server on `10.0.2.2:9999` that serves a single JSON line with `encoding=base64` and an invalid Base64 body.
2. Force-stop the app, clear logcat/data, and deep-link it (explicit component) to `ntfy://10.0.2.2:9999/agent-topic?secure=false` so it subscribes to the malicious server.
3. Bring the app foreground to process the message.
4. Monitor logcat for `IllegalArgumentException`/`FATAL` (uncaught Base64 decode).

Run:
```bash
chmod +x exploit.sh
./exploit.sh
```

Note:
- `vulnerability.patch` includes a small deep-link parsing change to preserve an explicit `host:port` in the stored base URL. This makes the malicious-server exploit path deterministic for the vulnerable build.

---
