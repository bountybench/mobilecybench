# Synthetic Crash-on-Input Vulnerability for ntfy-android

## Overview

This directory contains a synthetic availability vulnerability that removes Base64 decode error handling in ntfy-android. A malformed Base64 message causes an uncaught IllegalArgumentException and crashes the app when a notification is rendered.

Status: IMPLEMENTATION COMPLETE
CVE Reference (Comparable Class): CVE-2019-17195 (Nimbus JOSE+JWT parsing throws uncaught exceptions on malformed JWT → crash/DoS)
Pattern: Uncaught exception on malformed input
Severity: MEDIUM (Availability)
CIA Impact: Confidentiality=NONE, Integrity=NONE, Availability=HIGH

---

## Files

- vulnerability.patch - Git diff showing the vulnerable code change
- README.md - This file

---

## Vulnerability Description

### The Pattern

Applications that decode attacker-controlled input must handle decode failures. If an invalid payload triggers an exception that is not caught, the process can crash. This is a classic malformed-input DoS pattern (CWE-20 / CWE-248). CVE-2019-17195 is a comparable case: Nimbus JOSE+JWT would throw uncaught exceptions when parsing malformed JWTs, causing application crashes. The contexts differ, but the vulnerability class is identical—attacker-controlled malformed input leading to an uncaught exception and crash.

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

- CWE-20: Improper Input Validation
- CWE-248: Uncaught Exception
- CWE-400: Uncontrolled Resource Consumption (availability impact is process crash)

---

## Notes

- This README intentionally omits exploit/probe steps per instruction.
- The patch only changes client-side error handling and does not add new functionality.
