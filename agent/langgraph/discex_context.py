"""
DiscEx Data Structures - Minimal structured output formats.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class VulnerabilityFinding:
    """Structured vulnerability finding."""

    vuln_type: str
    severity: str = "medium"
    confidence: float = 0.5

    # Attack chain
    entry_point: str = ""
    data_flow: List[str] = field(default_factory=list)
    vulnerable_sink: str = ""

    # Evidence
    code_locations: List[Dict[str, Any]] = field(default_factory=list)

    # Exploitation
    prerequisites: List[str] = field(default_factory=list)
    attack_vector: str = ""
    payload_hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_exploit_context(self) -> str:
        """Format for Exploit Agent."""
        lines = [
            f"## Vulnerability: {self.vuln_type}",
            f"**Severity**: {self.severity.upper()} | **Confidence**: {self.confidence:.0%}",
            "",
        ]

        if self.entry_point:
            lines.append(f"**Entry Point**: {self.entry_point}")
        if self.vulnerable_sink:
            lines.append(f"**Vulnerable Sink**: {self.vulnerable_sink}")

        if self.data_flow:
            lines.append("\n**Data Flow**:")
            for i, step in enumerate(self.data_flow, 1):
                lines.append(f"  {i}. {step}")

        if self.code_locations:
            lines.append("\n**Code Evidence**:")
            for loc in self.code_locations[:5]:
                lines.append(f"  - `{loc.get('file', '?')}:{loc.get('line', '?')}` ({loc.get('role', 'evidence')})")

        if self.attack_vector:
            lines.append(f"\n**Attack Vector**: {self.attack_vector}")

        if self.payload_hints:
            lines.append("\n**Payload Hints**: " + ", ".join(self.payload_hints[:3]))

        return "\n".join(lines)


@dataclass
class ExploitationFeedback:
    """Structured feedback when exploitation is blocked."""

    status: str  # "success", "blocked", "partial", "infeasible"
    vulnerability_confirmed: bool = False

    missing_capabilities: List[str] = field(default_factory=list)
    blocking_factors: List[str] = field(default_factory=list)
    required_for_exploitation: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
