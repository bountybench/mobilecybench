"""
Shared Knowledge Store for parallel agent coordination.

Simple, in-memory store for:
- Vulnerability findings from different agents (Semgrep, MobSF, Frida)
- Code index (app structure, components, entry points)
- Sinks and sources (for taint analysis)
- Runtime verification results

Design: Thread-safe, minimal, no database.
Later: Can upgrade to SQLite/Redis if caching is needed.
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Symbol:
    """Code symbol from tree-sitter (class, method, field)."""

    name: str
    type: str  # "class", "method", "field", "interface"
    file_path: str
    line_start: int
    line_end: int
    parent: Optional[str] = None  # Parent class/interface name
    modifiers: List[str] = field(default_factory=list)  # public, private, static, etc.
    parameters: List[str] = field(default_factory=list)  # For methods
    return_type: Optional[str] = None  # For methods/fields


@dataclass
class Vulnerability:
    """Vulnerability finding from any source."""

    id: str
    source: str  # "semgrep", "semgrep-custom", "mobsf", "frida", "manual"
    severity: str  # "critical", "high", "medium", "low"
    category: str  # "sqli", "xss", "rce", "auth-bypass", "path-traversal", etc.
    title: str
    description: str

    # Location
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None

    # Exploitability assessment
    exploitability: str = "unknown"  # "remote", "local", "none", "unknown"
    attack_vector: Optional[str] = None
    cve_worthy: bool = False  # Agent determines this

    # Verification
    verification_status: str = "unverified"  # "unverified", "verified", "false_positive"
    verified_by: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class CodeIndex:
    """App code structure (manifest + tree-sitter)."""

    package_name: str

    # Manifest-level (Android components)
    activities: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    receivers: List[str] = field(default_factory=list)
    providers: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)
    exported_components: List[str] = field(default_factory=list)

    # Code-level (tree-sitter)
    classes: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # class_name -> Symbol dict
    methods: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # method_name -> [Symbol dicts]
    fields: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # field_name -> [Symbol dicts]

    # Sensitive APIs flagged
    sensitive_apis: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata
    indexed_at: str = ""
    cache_file: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self, filepath: str) -> None:
        """Save CodeIndex to JSON file."""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict (dataclasses.asdict handles nested structures)
        data = asdict(self)

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

    @staticmethod
    def from_json(filepath: str) -> "CodeIndex":
        """Load CodeIndex from JSON file."""
        with open(filepath, "r") as f:
            data = json.load(f)

        return CodeIndex(**data)


@dataclass
class TaintAnalysis:
    """Sinks and sources for taint analysis."""

    sources: List[Dict[str, Any]] = field(default_factory=list)
    sinks: List[Dict[str, Any]] = field(default_factory=list)
    flows: List[Dict[str, Any]] = field(default_factory=list)


class SharedKnowledgeStore:
    """
    Thread-safe in-memory knowledge store for parallel agents.

    Usage:
        # Create shared store
        store = SharedKnowledgeStore(app_package="com.example.app")

        # Agent 1: Static analysis
        vuln = Vulnerability(id="v1", source="semgrep", ...)
        store.add_vulnerability(vuln)

        # Agent 2: Frida verification
        vulns = store.get_vulnerabilities(severity="high")
        store.update_verification_status("v1", "verified", "frida_agent")

        # Get summary
        summary = store.get_summary()
    """

    def __init__(self, app_package: str):
        self.app_package = app_package
        self._lock = threading.RLock()

        self._vulnerabilities: Dict[str, Vulnerability] = {}
        self._code_index: Optional[CodeIndex] = None
        self._taint_analysis: Optional[TaintAnalysis] = None
        self._metadata: Dict[str, Any] = {
            "created_at": datetime.now(),
            "app_package": app_package,
        }

    def add_vulnerability(self, vuln: Vulnerability) -> None:
        """Add vulnerability (thread-safe)."""
        with self._lock:
            self._vulnerabilities[vuln.id] = vuln

    def get_vulnerabilities(
        self,
        source: Optional[str] = None,
        severity: Optional[str] = None,
        verified_only: bool = False,
    ) -> List[Vulnerability]:
        """Get vulnerabilities with optional filtering."""
        with self._lock:
            vulns = list(self._vulnerabilities.values())

        if source:
            vulns = [v for v in vulns if v.source == source]
        if severity:
            vulns = [v for v in vulns if v.severity == severity]
        if verified_only:
            vulns = [v for v in vulns if v.verification_status == "verified"]

        return vulns

    def update_verification_status(
        self, vuln_id: str, status: str, verified_by: str
    ) -> bool:
        """Update vulnerability verification status."""
        with self._lock:
            if vuln_id in self._vulnerabilities:
                self._vulnerabilities[vuln_id].verification_status = status
                self._vulnerabilities[vuln_id].verified_by = verified_by
                return True
            return False

    def set_code_index(self, code_index: CodeIndex) -> None:
        """Set code index."""
        with self._lock:
            self._code_index = code_index

    def get_code_index(self) -> Optional[CodeIndex]:
        """Get code index."""
        with self._lock:
            return self._code_index

    def set_taint_analysis(self, taint: TaintAnalysis) -> None:
        """Set taint analysis results."""
        with self._lock:
            self._taint_analysis = taint

    def get_taint_analysis(self) -> Optional[TaintAnalysis]:
        """Get taint analysis results."""
        with self._lock:
            return self._taint_analysis

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata."""
        with self._lock:
            self._metadata[key] = value

    def get_metadata(self, key: str) -> Any:
        """Get metadata."""
        with self._lock:
            return self._metadata.get(key)

    def get_summary(self) -> Dict[str, Any]:
        """Get knowledge summary."""
        with self._lock:
            vulns = list(self._vulnerabilities.values())
            return {
                "app_package": self.app_package,
                "total_vulnerabilities": len(vulns),
                "verified_vulnerabilities": len(
                    [v for v in vulns if v.verification_status == "verified"]
                ),
                "by_severity": {
                    "critical": len([v for v in vulns if v.severity == "critical"]),
                    "high": len([v for v in vulns if v.severity == "high"]),
                    "medium": len([v for v in vulns if v.severity == "medium"]),
                    "low": len([v for v in vulns if v.severity == "low"]),
                },
                "by_source": {
                    source: len([v for v in vulns if v.source == source])
                    for source in set(v.source for v in vulns)
                }
                if vulns
                else {},
                "has_code_index": self._code_index is not None,
                "has_taint_analysis": self._taint_analysis is not None,
            }

    def clear(self) -> None:
        """Clear all knowledge."""
        with self._lock:
            self._vulnerabilities.clear()
            self._code_index = None
            self._taint_analysis = None
