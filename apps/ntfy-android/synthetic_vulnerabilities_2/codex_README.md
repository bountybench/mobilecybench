# Synthetic Vulnerability 2 - Candidates Reviewed and Rejected

This document summarizes the CVE candidates and vulnerability classes we explored for a second synthetic vulnerability in ntfy-android, and why each was rejected. The goal was to stay within the benchmark constraints (remote unauthenticated or authenticated attacker) and avoid adding obviously artificial code paths that do not reflect plausible app behavior.

Constraints enforced throughout:
- Attacker model must be remote unauthenticated or authenticated only.
- Scenario must be grounded in an existing ntfy-android flow (no new features).
- Probe must be deterministic and verifiable in CI.
- The injected bug should look like a plausible mistake in this codebase.

## Candidate A: SSRF via Notification Icon or Attachment Fetch

- Proposed CVE analog: CVE-2024-42352 (Nuxt Icon SSRF).
- Proposed injection surface: notification icon URL or attachment URL fetch path.
- Rationale: notification payloads can include an icon URL or attachment URL; the app downloads these to render notifications or previews.
- Intended probe: run a listener on the host and check whether the app makes a request to a controlled internal endpoint (for example 10.0.2.2).
- Why we rejected it:
  - This is client-side request forgery, not server-side. It does not map cleanly to CWE-918 without a policy rule that forbids local network or localhost access.
  - ntfy-android already fetches external URLs for icons and attachments as a normal feature. It is difficult to argue this is a vulnerability without a documented allowlist or same-origin requirement.
  - Verification depends on an out-of-band listener and host/emulator networking. That makes probes fragile and hard to keep isolated from the agent.
  - The scenario risks being interpreted as "expected behavior" rather than a security bug.

## Candidate B: SQL Injection in Notification Insert Path

- Proposed CVE analog: CVE-2019-5454 (Nextcloud Android SQL injection).
- Proposed injection surface: notification message insert path during ingestion.
- Rationale: incoming notifications are server-controlled; unsafe string concatenation in a DB insert could allow SQL injection.
- Intended probe: verify that a crafted message can embed local subscription metadata into a stored notification row.
- Why we rejected it:
  - ntfy-android uses Room ORM for all notification writes. Replacing the Room insert with raw SQL is an obvious deviation from established style.
  - The only way to make SQLi work was to add a new raw SQL path; that is not a plausible "mistake" in this codebase.
  - This would materially change how notification rows are created (manual SQL, manual null handling, custom converters), which is too synthetic.

## Candidate C: Broadcast Receiver Injection (Local Attacker)

- Proposed class: intent or broadcast injection (CWE-926 / CWE-863).
- Proposed surface: exported BroadcastReceiver in `io/heckel/ntfy/msg/BroadcastService.kt` handling `io.heckel.ntfy.SEND_MESSAGE`.
- Rationale: a malicious local app could send a crafted broadcast and have ntfy publish using stored credentials.
- Why we rejected it:
  - The attacker model is local (another app on device), which is out of scope for this track.
  - Even if this is a real issue, it violates the remote-only constraint for synthetic scenarios.

## Candidate D: Deep Link Auto-Subscribe (Local Attacker)

- Proposed class: deep link intent injection.
- Proposed surface: `DetailActivity` handling `ntfy://` links and auto-subscribing via `maybeSubscribeAndLoadView()`.
- Rationale: another app could trigger an intent that silently adds attacker-controlled topics.
- Why we rejected it:
  - Attacker model is local only, which does not match the benchmark constraints.
  - The behavior appears intentional for UX (deep-link subscription), so classifying it as a vulnerability would require explicit policy justification that is not present.

## Current Status

No candidate has yet met all constraints:

- remote unauthenticated or authenticated attacker only
- does not require adding a new feature or obviously artificial code path
- has a deterministic probe that can be validated in CI

We should continue searching for vulnerabilities that fit existing ntfy-android flows without forcing a new architecture or style change.
