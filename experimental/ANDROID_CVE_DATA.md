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

Each CVE in `android_{year}_enriched.jsonl` has three groups of fields. **You generally don't need to read the raw JSON** — `cve_query.py` resolves everything for you. The per-source fields exist for transparency and debugging.

### Group 1: Classification (Haiku → Opus pipeline)

| Field | Description |
|-------|-------------|
| `cve_id` | The CVE identifier |
| `file_path` | Path to the raw cvelistV5 JSON |
| `original_confidence` | Haiku's initial confidence (0.0–1.0) |
| `original_reason` | Haiku's classification reasoning |
| `android` | Opus's final verdict (always `true` in the enriched file) |
| `confidence` | Opus's confidence (may differ from Haiku's) |
| `reason` | Opus's reasoning |

### Group 2: CVSS scores — three sources, same schema

Each source provides the same 11 CVSS 3.1 fields (`base_score`, `severity`, `vector`, `attack_vector`, `attack_complexity`, `privileges_required`, `user_interaction`, `scope`, `confidentiality_impact`, `integrity_impact`, `availability_impact`), prefixed by source:

| Source prefix | What it is | Coverage (2025) |
|---------------|------------|-----------------|
| `nvd_cvss31_*` | NVD Primary — NIST analysts apply consistent worst-case methodology | ~38% |
| `vendor_cvss31_*` | Vendor/CNA — first-party scoring, product-specific | ~67% |
| `adp_cvss31_*` | CISA-ADP — CISA Vulnrichment, fills NVD's backlog | ~90% |

Sources can disagree significantly (up to 5+ points). NVD tends to score higher because it assumes worst-case impact. `cve_query.py` resolves to a single score using priority **NVD → vendor → ADP**.

CVSS 4.0 fields (`nvd_cvss40_*`, `vendor_cvss40_*`) exist but have sparse coverage and are not used in queries.

### Group 3: CWE weakness types — three sources, lists

| Field | Description |
|-------|-------------|
| `nvd_cwe_ids` | CWE list from NVD Primary analysis |
| `vendor_cwe_ids` | CWE list from the vendor/CNA |
| `adp_cwe_ids` | CWE list from CISA-ADP |

Each source may assign multiple CWEs (e.g., `["CWE-352", "CWE-384"]`) and sources may disagree. `cve_query.py` resolves using the same priority: first non-empty list from **NVD → vendor → ADP**. Searching with `--cwe CWE-352` checks membership in the resolved list.

### Example: how resolution works

Raw data for CVE-2025-1812:
```
nvd_cvss31_base_score:    8.8 HIGH     ← NVD (worst-case)
vendor_cvss31_base_score: 6.3 MEDIUM   ← vendor (product-specific)
adp_cvss31_base_score:    6.3 MEDIUM   ← CISA-ADP

nvd_cwe_ids:    ["CWE-89"]              ← NVD: SQL injection
vendor_cwe_ids: ["CWE-89", "CWE-74"]    ← vendor: adds Injection (parent)
adp_cwe_ids:    ["CWE-74", "CWE-89"]    ← CISA-ADP: same, different order
```

`cve_query.py` resolves to: **Score 8.8 HIGH, CWE: CWE-89** (NVD wins on both since it has data). If NVD were missing, it would show 6.3 MEDIUM and CWE-89, CWE-74 from vendor.
