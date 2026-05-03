"""Pure data models used across the probe-generation pipeline.

No I/O, no LLM calls, no subprocess invocations. All persistence and
serialization lives elsewhere — these classes round-trip through ``to_dict()``
and ``from_dict()`` for JSON storage.

Shapes follow the existing codebase conventions in
``apps/home-assistant-android/`` (canonical reference per ``DESIGN.md``):

- ``Invariant`` mirrors a "shall not" statement under a per-attacker-model
  section in ``threat_model.md``.
- ``Probe`` mirrors a single ``checks/check_*.py`` file: one channel,
  baseline-diff, anti-pattern declarations, observer-only.
- ``SyntheticVulnerability`` mirrors a directory under
  ``apps/<app>/synthetic_vulnerabilities/<id>/``.
- ``GateResult`` records the outcome of one gate run for either an invariant
  (covering all its probes) or a single probe.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

# ----- Enumerations modeled as Literal types for static analysis -----

AttackerModel = Literal["malicious_app", "remote_attacker"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
GateName = Literal[
    "dual_comparator_vulnerable",
    "dual_comparator_clean",
    "clean_baseline",
    "idle_with_victim",
    "golden_flow",
    "cross_app_baseline",
    "adversarial_decoy",
]
GateOutcome = Literal["pass", "fail", "skipped", "error"]
DecoyClass = Literal[
    "artifact_forgery",
    "log_line_injection",
    "state_mimicry",
    "api_short_circuit",
    "network_replay",
]


# ----- Top-level artifacts -----


@dataclass
class CVSSv31:
    vector: str
    base_score: float
    severity: Severity
    rationale: str = ""


@dataclass
class Invariant:
    """A declarative shall-not statement under a documented threat model.

    One invariant : N probes. The probes collectively cover ≥2 channels where
    applicable (avoiding the ``two-probes-one-channel`` anti-pattern).
    """

    invariant_id: str  # e.g. "RA-C", "MA-X", "RA-I"
    statement: str  # single falsifiable shall-not sentence
    attacker_model: AttackerModel
    cwe_ids: list[str] = field(default_factory=list)  # ["CWE-285"]
    cvss: Optional[CVSSv31] = None
    linked_historic_cves: list[str] = field(default_factory=list)
    threat_model_anchor: str = ""  # path:section, e.g. "threat_model.md#shall-not-ra-c"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Invariant":
        cvss = d.get("cvss")
        if cvss is not None:
            cvss = CVSSv31(**cvss)
        return cls(**{**d, "cvss": cvss})


@dataclass
class Probe:
    """A single check function enforcing one invariant via one channel.

    Maps 1:1 onto a ``checks/check_<name>.py`` (or
    ``remote_attacker/checks/check_<name>.py``) file.
    """

    probe_id: str  # e.g. "check_no_new_admin_refresh_tokens"
    invariant_id: str  # the invariant this probe enforces
    channel: str  # e.g. "auth-store-diff", "endpoint-reject", "process-liveness"
    attacker_model: AttackerModel
    category: Literal["access", "availability", "confidentiality", "integrity"]
    primitives_used: list[str] = field(default_factory=list)  # names from probe_lib
    anti_patterns_avoided: list[str] = field(default_factory=list)  # numbered KB keys
    diff_based: bool = True  # required by acceptance rubric
    observer_only: bool = True  # required (probe-runs-the-exploit anti-pattern)
    source_path: str = ""  # filled in once written: apps/<app>/checks/<probe_id>.py
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Probe":
        return cls(**d)


@dataclass
class SyntheticVulnerability:
    """A bug we introduce via vulnerability.patch to validate a target invariant.

    Maps onto a directory ``apps/<app>/synthetic_vulnerabilities/<vuln_id>/``.
    """

    vuln_id: str  # e.g. "vuln_0"
    target_invariant_id: str  # which invariant this validates
    title: str
    historic_cve: str  # e.g. "CVE-2025-27916"
    cwe_id: str
    cwe_name: str
    cvss_historic: CVSSv31
    cvss_synthetic: CVSSv31
    attacker_model: AttackerModel
    patch_path: str = ""  # vulnerability.patch
    exploit_path: str = ""  # exploit.sh OR exploit_apk/
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SyntheticVulnerability":
        return cls(
            **{
                **d,
                "cvss_historic": CVSSv31(**d["cvss_historic"]),
                "cvss_synthetic": CVSSv31(**d["cvss_synthetic"]),
            }
        )


# ----- Pipeline run + gates -----


@dataclass
class GateResult:
    gate: GateName
    outcome: GateOutcome
    duration_seconds: float = 0.0
    artifact_id: str = ""  # invariant_id or probe_id or vuln_id depending on context
    artifact_kind: Literal["invariant", "probe", "synthetic_vuln"] = "probe"
    detail: str = ""  # short human-readable result line
    trace_path: str = ""  # link to verbose trace under runs/<run_id>/

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DecoyAttempt:
    decoy_class: DecoyClass
    model_family: str  # "claude" / "gpt" / "gemini"
    against_artifact: str  # invariant_id or probe_id
    succeeded: bool  # True = decoy fooled the probe = FAILURE for the probe
    description: str = ""
    trace_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProbeGenRun:
    """One pipeline invocation. Produced by the runner, written as summary.json.

    All artifact decisions (accepted/rejected) are appended here so the
    ``decisions.md`` view is a deterministic render of this object.
    """

    run_id: str
    app: str
    started_at_iso: str
    ended_at_iso: str = ""
    invariants_proposed: list[Invariant] = field(default_factory=list)
    probes_proposed: list[Probe] = field(default_factory=list)
    synthetic_vulns_proposed: list[SyntheticVulnerability] = field(default_factory=list)
    invariants_accepted: list[str] = field(default_factory=list)  # invariant_ids
    probes_accepted: list[str] = field(default_factory=list)  # probe_ids
    synthetic_vulns_accepted: list[str] = field(default_factory=list)  # vuln_ids
    rejections: list[dict[str, Any]] = field(default_factory=list)
    gate_results: list[GateResult] = field(default_factory=list)
    decoy_attempts: list[DecoyAttempt] = field(default_factory=list)
    cost_usd: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "invariants_proposed": [i.to_dict() for i in self.invariants_proposed],
            "probes_proposed": [p.to_dict() for p in self.probes_proposed],
            "synthetic_vulns_proposed": [
                s.to_dict() for s in self.synthetic_vulns_proposed
            ],
            "gate_results": [g.to_dict() for g in self.gate_results],
            "decoy_attempts": [d.to_dict() for d in self.decoy_attempts],
        }
