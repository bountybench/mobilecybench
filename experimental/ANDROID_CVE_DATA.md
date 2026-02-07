# Android CVE Dataset (2025)

381 potential android CVEs

## How This Dataset Was Created

1. **Source**: All 42,043 published CVEs from 2025 (cvelistV5 repository)

2. **Initial classification (Haiku)**: Each CVE was classified as android/non-android using Claude Haiku. Definition: an Android vulnerability exists in an Android app's code (NOT Android OS, kernel, server-side, iOS, or browser). This identified 574 potential Android app CVEs.

3. **Re-evaluation (Opus 4.5)**: The 574 candidates were re-evaluated with Claude Opus 4.5, which rejected 193 as false positives (mostly Android OS/framework and Samsung device firmware vulnerabilities that Haiku misclassified).

4. **Enrichment**: The remaining 381 CVEs were enriched with CVSS and CWE data from NVD API and vendor sources.

**Disclaimer**: Created using LLM classification. There may still be errors. **If you associate a CVE with your synthetic vulnerability, you should manually verify** that the CVE is actually an Android app vulnerability and that the CWE/CVSS data matches your use case.

## Purpose

When creating synthetic vulnerabilities, use this dataset to find real CVEs that match your synthetic's characteristics. This helps ground your work in real-world vulnerability patterns.

## Quick Start
Querying uses AND logic - meant for finding the closest CVE to a candidate synthetic vulnerability

```bash
# Show dataset stats
./cve_query.py stats

# List all CWEs
./cve_query.py cwes

# Find CVEs by CWE
./cve_query.py find --cwe CWE-89

# Find CVEs by multiple criteria
./cve_query.py find --cwe CWE-862 --av NETWORK --pr NONE

# Get a specific CVE
./cve_query.py get CVE-2025-0476

# Get with raw JSON
./cve_query.py get CVE-2025-0476 --json
```

## Matching Your Synthetic Vulnerability

When you create a synthetic vulnerability, identify these characteristics and find matching CVEs:

| Category | Your Synthetic | CLI Flag |
|----------|----------------|----------|
| **CWE** | What type of vulnerability? | `--cwe CWE-89` |
| **Attack Vector** | How is it exploited? | `--av NETWORK` |
| **Privileges Required** | Auth needed? | `--pr NONE` |
| **User Interaction** | User action needed? | `--ui NONE` |
| **Confidentiality** | Data exposed? | `--ci HIGH` |
| **Integrity** | Data modified? | `--ii HIGH` |
| **Availability** | Service disrupted? | `--ai LOW` |

### CVSS Values Reference

**Attack Vector (AV):**
- `NETWORK` — Exploitable over the internet
- `ADJACENT_NETWORK` — Requires same network segment
- `LOCAL` — Requires local access to device
- `PHYSICAL` — Requires physical access

**Privileges Required (PR):**
- `NONE` — No authentication needed
- `LOW` — Basic user privileges
- `HIGH` — Admin/root privileges

**User Interaction (UI):**
- `NONE` — No user action required
- `REQUIRED` — User must click/open something

**Impact (C/I/A):**
- `NONE` — No impact
- `LOW` — Limited impact
- `HIGH` — Total compromise

## Data Schema

Each CVE in `android_2025_enriched.jsonl`:

```json
{
  "cve_id": "CVE-2025-0476",
  "reason": "Mattermost Mobile Apps vulnerability...",
  "confidence": 0.85,

  // CWE (use whichever is available)
  "nvd_cwe_id": null,
  "vendor_cwe_id": "CWE-1287",

  // NVD CVSS 3.1 (may be null if NVD hasn't scored)
  "nvd_cvss31_base_score": 4.3,
  "nvd_cvss31_severity": "MEDIUM",
  "nvd_cvss31_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:L",
  "nvd_cvss31_attack_vector": "NETWORK",
  "nvd_cvss31_attack_complexity": "LOW",
  "nvd_cvss31_privileges_required": "LOW",
  "nvd_cvss31_user_interaction": "NONE",
  "nvd_cvss31_scope": "UNCHANGED",
  "nvd_cvss31_confidentiality_impact": "NONE",
  "nvd_cvss31_integrity_impact": "NONE",
  "nvd_cvss31_availability_impact": "LOW",

  // Vendor CVSS 3.1 (usually has better coverage)
  "vendor_cvss31_base_score": 4.3,
  "vendor_cvss31_severity": "MEDIUM",
  "vendor_cvss31_attack_vector": "NETWORK",
  // ... same fields as NVD

  // CVSS 4.0 (sparse coverage, ~22%)
  "nvd_cvss40_base_score": null,
  "vendor_cvss40_base_score": null
}
```
