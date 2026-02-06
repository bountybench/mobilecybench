#!/usr/bin/env python3
"""
Query Android CVEs by CWE and CVSS categories.

Usage:
    ./cve_query.py stats                           # Show dataset stats
    ./cve_query.py cwes                            # List all CWEs
    ./cve_query.py find --cwe CWE-89               # Find by CWE
    ./cve_query.py find --av NETWORK --pr NONE     # Find by CVSS
    ./cve_query.py find --cwe CWE-862 --av NETWORK --ci HIGH
    ./cve_query.py get CVE-2025-0476               # Get specific CVE

Options for find:
    --cwe       CWE ID (e.g., CWE-89, CWE-79)
    --av        Attack Vector: NETWORK, ADJACENT_NETWORK, LOCAL, PHYSICAL
    --pr        Privileges Required: NONE, LOW, HIGH
    --ui        User Interaction: NONE, REQUIRED
    --ci        Confidentiality Impact: NONE, LOW, HIGH
    --ii        Integrity Impact: NONE, LOW, HIGH
    --ai        Availability Impact: NONE, LOW, HIGH
    --severity  Severity: CRITICAL, HIGH, MEDIUM, LOW
    --limit     Max results (default: 10)
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DATA_FILE = Path(__file__).parent / "android_2025_enriched.jsonl"

# Maps CVSS 3.1 vector string abbreviations to full field values
_CVSS31_FIELD_MAP = {
    "AV": {"N": "NETWORK", "A": "ADJACENT_NETWORK", "L": "LOCAL", "P": "PHYSICAL"},
    "AC": {"L": "LOW", "H": "HIGH"},
    "PR": {"N": "NONE", "L": "LOW", "H": "HIGH"},
    "UI": {"N": "NONE", "R": "REQUIRED"},
    "S": {"U": "UNCHANGED", "C": "CHANGED"},
    "C": {"N": "NONE", "L": "LOW", "H": "HIGH"},
    "I": {"N": "NONE", "L": "LOW", "H": "HIGH"},
    "A": {"N": "NONE", "L": "LOW", "H": "HIGH"},
}

_CVSS31_KEY_TO_FIELD = {
    "AV": "attack_vector",
    "AC": "attack_complexity",
    "PR": "privileges_required",
    "UI": "user_interaction",
    "S": "scope",
    "C": "confidentiality_impact",
    "I": "integrity_impact",
    "A": "availability_impact",
}


def _parse_cvss31_vector(vector: str) -> dict:
    """Parse 'CVSS:3.1/AV:N/AC:L/...' into {field_name: VALUE} dict."""
    result = {}
    if not vector or not vector.startswith("CVSS:3"):
        return result
    for part in vector.split("/")[1:]:
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        if key in _CVSS31_FIELD_MAP and val in _CVSS31_FIELD_MAP[key]:
            field = _CVSS31_KEY_TO_FIELD.get(key)
            if field:
                result[field] = _CVSS31_FIELD_MAP[key][val]
    return result


@dataclass
class CVE:
    """A single CVE with CWE and CVSS data."""

    cve_id: str
    reason: str
    confidence: float
    cwe_id: Optional[str]
    nvd_cwe_id: Optional[str]
    vendor_cwe_id: Optional[str]
    base_score: Optional[float]
    severity: Optional[str]
    attack_vector: Optional[str]
    attack_complexity: Optional[str]
    privileges_required: Optional[str]
    user_interaction: Optional[str]
    scope: Optional[str]
    confidentiality_impact: Optional[str]
    integrity_impact: Optional[str]
    availability_impact: Optional[str]
    raw: dict


class CVEQuery:
    """Query Android CVEs by CWE and CVSS categories."""

    def __init__(self, data_file: Path = DATA_FILE):
        self.cves: list[CVE] = []
        self._load(data_file)

    def _load(self, data_file: Path):
        with open(data_file) as f:
            for line in f:
                raw = json.loads(line)
                cwe = raw.get("nvd_cwe_id") or raw.get("vendor_cwe_id")
                score = raw.get("nvd_cvss31_base_score") or raw.get(
                    "vendor_cvss31_base_score"
                )
                severity = raw.get("nvd_cvss31_severity") or raw.get(
                    "vendor_cvss31_severity"
                )
                av = raw.get("nvd_cvss31_attack_vector") or raw.get(
                    "vendor_cvss31_attack_vector"
                )
                ac = raw.get("nvd_cvss31_attack_complexity") or raw.get(
                    "vendor_cvss31_attack_complexity"
                )
                pr = raw.get("nvd_cvss31_privileges_required") or raw.get(
                    "vendor_cvss31_privileges_required"
                )
                ui = raw.get("nvd_cvss31_user_interaction") or raw.get(
                    "vendor_cvss31_user_interaction"
                )
                scope = raw.get("nvd_cvss31_scope") or raw.get("vendor_cvss31_scope")
                ci = raw.get("nvd_cvss31_confidentiality_impact") or raw.get(
                    "vendor_cvss31_confidentiality_impact"
                )
                ii = raw.get("nvd_cvss31_integrity_impact") or raw.get(
                    "vendor_cvss31_integrity_impact"
                )
                ai = raw.get("nvd_cvss31_availability_impact") or raw.get(
                    "vendor_cvss31_availability_impact"
                )

                # Fallback: parse vector string if derived fields are null
                if not av or not pr or not ui or not ci or not ii or not ai:
                    vector = raw.get("nvd_cvss31_vector") or raw.get(
                        "vendor_cvss31_vector"
                    )
                    if vector:
                        parsed = _parse_cvss31_vector(vector)
                        av = av or parsed.get("attack_vector")
                        ac = ac or parsed.get("attack_complexity")
                        pr = pr or parsed.get("privileges_required")
                        ui = ui or parsed.get("user_interaction")
                        scope = scope or parsed.get("scope")
                        ci = ci or parsed.get("confidentiality_impact")
                        ii = ii or parsed.get("integrity_impact")
                        ai = ai or parsed.get("availability_impact")

                self.cves.append(
                    CVE(
                        cve_id=raw.get("cve_id"),
                        reason=raw.get("reason", ""),
                        confidence=raw.get("confidence", 0),
                        cwe_id=cwe,
                        nvd_cwe_id=raw.get("nvd_cwe_id"),
                        vendor_cwe_id=raw.get("vendor_cwe_id"),
                        base_score=score,
                        severity=severity,
                        attack_vector=av,
                        attack_complexity=ac,
                        privileges_required=pr,
                        user_interaction=ui,
                        scope=scope,
                        confidentiality_impact=ci,
                        integrity_impact=ii,
                        availability_impact=ai,
                        raw=raw,
                    )
                )

    def find_matches(
        self,
        cwe: Optional[str] = None,
        attack_vector: Optional[str] = None,
        privileges_required: Optional[str] = None,
        user_interaction: Optional[str] = None,
        confidentiality_impact: Optional[str] = None,
        integrity_impact: Optional[str] = None,
        availability_impact: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> list[CVE]:
        criteria = {
            "cwe_id": cwe,
            "attack_vector": attack_vector,
            "privileges_required": privileges_required,
            "user_interaction": user_interaction,
            "confidentiality_impact": confidentiality_impact,
            "integrity_impact": integrity_impact,
            "availability_impact": availability_impact,
            "severity": severity,
        }
        criteria = {k: v for k, v in criteria.items() if v is not None}

        results = []
        for cve in self.cves:
            if all(
                getattr(cve, field, None) == value for field, value in criteria.items()
            ):
                results.append(cve)

        results.sort(key=lambda x: x.base_score or 0, reverse=True)
        return results

    def get(self, cve_id: str) -> Optional[CVE]:
        for cve in self.cves:
            if cve.cve_id == cve_id:
                return cve
        return None

    def list_cwes(self) -> dict[str, int]:
        from collections import Counter

        return dict(Counter(c.cwe_id for c in self.cves if c.cwe_id).most_common())

    def stats(self) -> dict:
        from collections import Counter

        return {
            "total_cves": len(self.cves),
            "with_cwe": sum(1 for c in self.cves if c.cwe_id),
            "with_cvss": sum(1 for c in self.cves if c.base_score),
            "severity_dist": dict(Counter(c.severity for c in self.cves if c.severity)),
            "attack_vector_dist": dict(
                Counter(c.attack_vector for c in self.cves if c.attack_vector)
            ),
        }


def print_cve(cve: CVE, verbose: bool = False):
    """Print a CVE in a readable format."""
    print(f"{cve.cve_id}")
    print(f"  CWE: {cve.cwe_id or 'N/A'}")
    print(f"  Score: {cve.base_score or 'N/A'} ({cve.severity or 'N/A'})")
    print(
        f"  AV:{cve.attack_vector or '?'} PR:{cve.privileges_required or '?'} UI:{cve.user_interaction or '?'}"
    )
    print(
        f"  C:{cve.confidentiality_impact or '?'} I:{cve.integrity_impact or '?'} A:{cve.availability_impact or '?'}"
    )
    print(f"  {cve.reason[:100]}{'...' if len(cve.reason) > 100 else ''}")
    if verbose:
        print(f"  Full reason: {cve.reason}")
    print()


def cmd_stats(args):
    q = CVEQuery()
    s = q.stats()
    print(f"Total CVEs: {s['total_cves']}")
    print(f"With CWE: {s['with_cwe']} ({100*s['with_cwe']//s['total_cves']}%)")
    print(f"With CVSS: {s['with_cvss']} ({100*s['with_cvss']//s['total_cves']}%)")
    print(f"\nSeverity: {s['severity_dist']}")
    print(f"Attack Vector: {s['attack_vector_dist']}")


def cmd_cwes(args):
    q = CVEQuery()
    cwes = q.list_cwes()
    print(f"{'CWE':<12} {'Count':>5}")
    print("-" * 20)
    for cwe, count in list(cwes.items())[: args.limit]:
        print(f"{cwe:<12} {count:>5}")


def cmd_find(args):
    q = CVEQuery()
    matches = q.find_matches(
        cwe=args.cwe,
        attack_vector=args.av,
        privileges_required=args.pr,
        user_interaction=args.ui,
        confidentiality_impact=args.ci,
        integrity_impact=args.ii,
        availability_impact=args.ai,
        severity=args.severity,
    )

    if not matches:
        print("No matches found.")
        return

    print(
        f"Found {len(matches)} matches (showing top {min(args.limit, len(matches))}):\n"
    )
    for cve in matches[: args.limit]:
        print_cve(cve, verbose=args.verbose)


def cmd_get(args):
    q = CVEQuery()
    cve = q.get(args.cve_id)
    if cve:
        print_cve(cve, verbose=True)
        if args.json:
            print("Raw JSON:")
            print(json.dumps(cve.raw, indent=2))
    else:
        print(f"CVE {args.cve_id} not found in dataset.")


def main():
    parser = argparse.ArgumentParser(
        description="Query Android CVEs by CWE and CVSS categories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./cve_query.py stats
  ./cve_query.py cwes
  ./cve_query.py find --cwe CWE-89
  ./cve_query.py find --av NETWORK --pr NONE --ci HIGH
  ./cve_query.py get CVE-2025-0476
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # stats
    subparsers.add_parser("stats", help="Show dataset statistics")

    # cwes
    p_cwes = subparsers.add_parser("cwes", help="List all CWEs with counts")
    p_cwes.add_argument("--limit", type=int, default=20, help="Max CWEs to show")

    # find
    p_find = subparsers.add_parser("find", help="Find CVEs matching criteria")
    p_find.add_argument("--cwe", help="CWE ID (e.g., CWE-89)")
    p_find.add_argument(
        "--av", help="Attack Vector: NETWORK, LOCAL, PHYSICAL, ADJACENT_NETWORK"
    )
    p_find.add_argument("--pr", help="Privileges Required: NONE, LOW, HIGH")
    p_find.add_argument("--ui", help="User Interaction: NONE, REQUIRED")
    p_find.add_argument("--ci", help="Confidentiality Impact: NONE, LOW, HIGH")
    p_find.add_argument("--ii", help="Integrity Impact: NONE, LOW, HIGH")
    p_find.add_argument("--ai", help="Availability Impact: NONE, LOW, HIGH")
    p_find.add_argument("--severity", help="Severity: CRITICAL, HIGH, MEDIUM, LOW")
    p_find.add_argument("--limit", type=int, default=10, help="Max results")
    p_find.add_argument("-v", "--verbose", action="store_true", help="Show full reason")

    # get
    p_get = subparsers.add_parser("get", help="Get a specific CVE by ID")
    p_get.add_argument("cve_id", help="CVE ID (e.g., CVE-2025-0476)")
    p_get.add_argument("--json", action="store_true", help="Show raw JSON")

    args = parser.parse_args()

    if args.command == "stats":
        cmd_stats(args)
    elif args.command == "cwes":
        cmd_cwes(args)
    elif args.command == "find":
        cmd_find(args)
    elif args.command == "get":
        cmd_get(args)


if __name__ == "__main__":
    main()
