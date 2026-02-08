# Android CVE Dataset

Two datasets of Android app CVEs are available:

| Dataset | CVEs | Preferred? | File |
|---------|------|------------|------|
| **2025** | 381 | Yes - use first | `android_2025_enriched.jsonl` |
| **2024** | 316 | Fallback if no 2025 match | `android_2024_enriched.jsonl` |

**Use 2025 CVEs when possible.** 2024 CVEs are more likely to appear in LLM training data, which can inflate agent performance on benchmarks. Only use 2024 as a last resort if no suitable 2025 match exists.

## How These Datasets Were Created

1. **Source**: All published CVEs from cvelistV5 repository (42,043 for 2025; 37,893 for 2024)

2. **Initial classification (Haiku)**: Each CVE was classified as android/non-android using Claude Haiku. Definition: an Android vulnerability exists in an Android app's code (NOT Android OS, kernel, server-side, iOS, or browser).

3. **Re-evaluation (Opus)**: Candidates were re-evaluated with Claude Opus, which rejected false positives (mostly Android OS/framework and Samsung device firmware vulnerabilities that Haiku misclassified).

4. **Enrichment**: Remaining CVEs were enriched with CVSS and CWE data from three sources:
   - **NVD Primary** — NIST's own analysis (consistent methodology, but backlogged ~35% coverage)
   - **Vendor/CNA** — First-party data from the CVE assigner (~68% coverage)
   - **CISA-ADP** — CISA Vulnrichment program, fills gaps when NVD/vendor data is missing

   Fallback order for queries: NVD → vendor → ADP.

**Disclaimer**: Created using LLM classification. There may still be errors. **If you associate a CVE with your synthetic vulnerability, you should manually verify** that the CVE is actually an Android app vulnerability and that the CWE/CVSS data matches your use case.

## Purpose

When creating synthetic vulnerabilities, use this dataset to find real CVEs that match your synthetic's characteristics. This helps ground your work in real-world vulnerability patterns.

## Quick Start

Querying uses AND logic - meant for finding the closest CVE to a candidate synthetic vulnerability.

```bash
# Show dataset stats (2025 by default)
./cve_query.py stats

# Show 2024 stats
./cve_query.py --year 2024 stats

# List all CWEs
./cve_query.py cwes

# Find CVEs by CWE
./cve_query.py find --cwe CWE-89

# Find CVEs by multiple criteria
./cve_query.py find --cwe CWE-862 --av NETWORK --pr NONE

# Search 2024 data
./cve_query.py --year 2024 find --av NETWORK --ci HIGH

# Get a specific CVE
./cve_query.py get CVE-2025-0476

# Get from 2024 data with raw JSON
./cve_query.py --year 2024 get CVE-2024-12993 --json
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

Each CVE in `android_{year}_enriched.jsonl`:

```json
{
  "cve_id": "CVE-2025-0476",
  "reason": "Mattermost Mobile Apps vulnerability...",
  "confidence": 0.85,

  // CWEs — lists, fallback order: NVD → vendor → ADP
  "nvd_cwe_ids": [],
  "vendor_cwe_ids": ["CWE-1287"],
  "adp_cwe_ids": ["CWE-352", "CWE-384"],

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

  // CISA-ADP CVSS 3.1 (fills gaps when NVD/vendor are missing)
  "adp_cvss31_base_score": 8.8,
  "adp_cvss31_severity": "HIGH",
  "adp_cvss31_attack_vector": "NETWORK",
  // ... same fields as NVD

  // CVSS 4.0 (sparse coverage)
  "nvd_cvss40_base_score": null,
  "vendor_cvss40_base_score": null
}
```
