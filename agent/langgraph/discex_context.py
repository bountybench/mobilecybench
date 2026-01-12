"""
DiscEx Context Builders - Prepare curated context for Discovery and Exploit agents.

This module handles:
1. Building curated security context from CodeIndex for Discovery Agent
2. Loading and formatting probe objectives for Exploit Agent
3. Classifying app types based on manifest and permissions
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.preprocessing import CodeIndex


# =============================================================================
# APP TYPE CLASSIFICATION
# =============================================================================

# Permission-based app type indicators
APP_TYPE_INDICATORS = {
    "finance": {
        "permissions": [
            "android.permission.USE_BIOMETRIC",
            "android.permission.USE_FINGERPRINT",
            "android.permission.BIND_AUTOFILL_SERVICE",
        ],
        "api_categories": ["crypto", "network", "storage"],
        "keywords": ["bank", "payment", "wallet", "finance", "money", "transfer"],
    },
    "communication": {
        "permissions": [
            "android.permission.SEND_SMS",
            "android.permission.READ_SMS",
            "android.permission.READ_CONTACTS",
            "android.permission.CALL_PHONE",
        ],
        "api_categories": ["network", "ipc"],
        "keywords": ["chat", "message", "mail", "email", "call", "sms"],
    },
    "social": {
        "permissions": [
            "android.permission.CAMERA",
            "android.permission.RECORD_AUDIO",
            "android.permission.READ_CONTACTS",
        ],
        "api_categories": ["network", "file", "webview"],
        "keywords": ["social", "share", "post", "feed", "profile"],
    },
    "media": {
        "permissions": [
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.CAMERA",
            "android.permission.RECORD_AUDIO",
        ],
        "api_categories": ["file", "storage"],
        "keywords": ["media", "photo", "video", "audio", "player", "stream"],
    },
    "productivity": {
        "permissions": [
            "android.permission.READ_CALENDAR",
            "android.permission.WRITE_CALENDAR",
            "android.permission.READ_CONTACTS",
        ],
        "api_categories": ["file", "storage", "sql"],
        "keywords": ["note", "task", "calendar", "document", "office"],
    },
    "iot_home": {
        "permissions": [
            "android.permission.BLUETOOTH",
            "android.permission.BLUETOOTH_ADMIN",
            "android.permission.ACCESS_FINE_LOCATION",
        ],
        "api_categories": ["network", "ipc"],
        "keywords": ["home", "smart", "device", "iot", "automation", "control"],
    },
}

# Dangerous permissions that expand attack surface
DANGEROUS_PERMISSIONS = [
    "android.permission.INTERNET",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.READ_CONTACTS",
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.READ_SMS",
    "android.permission.SEND_SMS",
    "android.permission.READ_CALL_LOG",
    "android.permission.SYSTEM_ALERT_WINDOW",
]


def classify_app_type(code_index: CodeIndex, package_name: str) -> str:
    """
    Classify app type based on permissions, APIs, and package name.

    Returns one of: finance, communication, social, media, productivity, iot_home, general
    """
    scores: Dict[str, int] = {app_type: 0 for app_type in APP_TYPE_INDICATORS}

    permissions = set(code_index.permissions)
    api_categories = set(api["category"] for api in code_index.sensitive_apis)
    package_lower = package_name.lower()

    for app_type, indicators in APP_TYPE_INDICATORS.items():
        # Permission matches
        for perm in indicators["permissions"]:
            if perm in permissions:
                scores[app_type] += 2

        # API category matches
        for cat in indicators["api_categories"]:
            if cat in api_categories:
                scores[app_type] += 1

        # Keyword matches in package name
        for keyword in indicators["keywords"]:
            if keyword in package_lower:
                scores[app_type] += 3

    # Return highest scoring type, or "general" if no strong match
    max_score = max(scores.values())
    if max_score >= 3:
        return max(scores, key=scores.get)
    return "general"


# =============================================================================
# DISCOVERY CONTEXT
# =============================================================================

@dataclass
class DiscoveryContext:
    """Curated security context for Discovery Agent."""

    # App identification
    package_name: str
    app_type: str

    # Attack surface
    exported_components: List[str] = field(default_factory=list)
    dangerous_permissions: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)

    # Sensitive API summary
    api_summary: Dict[str, int] = field(default_factory=dict)
    high_risk_apis: List[Dict[str, Any]] = field(default_factory=list)

    # Code structure hints
    total_classes: int = 0
    total_methods: int = 0

    def to_prompt_context(self) -> str:
        """Format context for inclusion in system prompt."""
        lines = [
            "## APPLICATION SECURITY CONTEXT",
            "",
            f"**Package**: `{self.package_name}`",
            f"**App Type**: {self.app_type.upper()} application",
            "",
        ]

        # Attack surface
        if self.exported_components:
            lines.append("### Attack Surface (Exported Components)")
            lines.append("These components are accessible to other apps and are prime targets:")
            for comp in self.exported_components[:10]:  # Limit to 10
                lines.append(f"- `{comp}`")
            if len(self.exported_components) > 10:
                lines.append(f"- ... and {len(self.exported_components) - 10} more")
            lines.append("")

        # Dangerous permissions
        if self.dangerous_permissions:
            lines.append("### Dangerous Permissions")
            lines.append("The app requests these sensitive permissions:")
            for perm in self.dangerous_permissions:
                short_perm = perm.replace("android.permission.", "")
                lines.append(f"- {short_perm}")
            lines.append("")

        # Sensitive API summary
        if self.api_summary:
            lines.append("### Sensitive API Usage Summary")
            lines.append("Categories of security-relevant APIs detected:")
            for category, count in sorted(self.api_summary.items(), key=lambda x: -x[1]):
                lines.append(f"- **{category}**: {count} occurrences")
            lines.append("")

        # High risk APIs (top 5)
        if self.high_risk_apis:
            lines.append("### High-Risk API Calls (Top Findings)")
            lines.append("These specific API usages warrant investigation:")
            for api in self.high_risk_apis[:5]:
                lines.append(f"- `{api['api_call']}` in `{api['file']}:{api['line']}` ({api['category']})")
            lines.append("")

        # Entry points
        if self.entry_points:
            lines.append("### Entry Points")
            for ep in self.entry_points[:5]:
                lines.append(f"- `{ep}`")
            lines.append("")

        return "\n".join(lines)


def build_discovery_context(code_index: CodeIndex, package_name: str) -> DiscoveryContext:
    """
    Build curated security context from CodeIndex.

    Extracts only security-relevant information to avoid overwhelming the agent.
    """
    # Classify app type
    app_type = classify_app_type(code_index, package_name)

    # Filter dangerous permissions
    dangerous = [p for p in code_index.permissions if p in DANGEROUS_PERMISSIONS]

    # Summarize sensitive APIs by category
    api_summary: Dict[str, int] = {}
    for api in code_index.sensitive_apis:
        cat = api.get("category", "unknown")
        api_summary[cat] = api_summary.get(cat, 0) + 1

    # Identify high-risk APIs (prioritize certain categories)
    high_risk_categories = ["sql", "runtime", "webview", "crypto", "file", "deeplink"]
    high_risk = [
        api for api in code_index.sensitive_apis
        if api.get("category") in high_risk_categories
    ]
    # Sort by risk category priority
    high_risk.sort(key=lambda x: high_risk_categories.index(x.get("category", "unknown"))
                   if x.get("category") in high_risk_categories else 999)

    return DiscoveryContext(
        package_name=package_name,
        app_type=app_type,
        exported_components=code_index.exported_components,
        dangerous_permissions=dangerous,
        entry_points=code_index.entry_points,
        api_summary=api_summary,
        high_risk_apis=high_risk[:10],  # Top 10
        total_classes=len(code_index.classes),
        total_methods=len(code_index.methods),
    )


# =============================================================================
# VULNERABILITY FINDING FORMAT
# =============================================================================

@dataclass
class VulnerabilityFinding:
    """Information-dense vulnerability finding for handoff to Exploit Agent."""

    # Core identification
    vuln_type: str  # e.g., "SQL Injection", "Path Traversal"
    severity: str  # "critical", "high", "medium", "low"
    confidence: float  # 0.0 - 1.0

    # Attack chain
    entry_point: str  # Where attack starts (e.g., "exported activity", "deeplink")
    data_flow: List[str] = field(default_factory=list)  # Path from entry to sink
    vulnerable_sink: str = ""  # Where vulnerability manifests

    # Evidence
    code_locations: List[Dict[str, Any]] = field(default_factory=list)
    # Each: {file, line, snippet, role: "entry"|"processing"|"sink"}

    # Prerequisites
    prerequisites: List[str] = field(default_factory=list)
    # e.g., ["network access", "user interaction", "specific intent"]

    # Exploitation hints
    attack_vector: str = ""  # How to trigger
    payload_hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_exploit_context(self) -> str:
        """Format for Exploit Agent."""
        lines = [
            f"## Vulnerability: {self.vuln_type}",
            f"**Severity**: {self.severity.upper()}",
            f"**Confidence**: {self.confidence:.0%}",
            "",
            f"### Entry Point",
            f"{self.entry_point}",
            "",
        ]

        if self.data_flow:
            lines.append("### Data Flow")
            for i, step in enumerate(self.data_flow, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        if self.vulnerable_sink:
            lines.append(f"### Vulnerable Sink")
            lines.append(f"{self.vulnerable_sink}")
            lines.append("")

        if self.code_locations:
            lines.append("### Code Evidence")
            for loc in self.code_locations:
                role = loc.get("role", "evidence")
                lines.append(f"**{role.upper()}**: `{loc['file']}:{loc['line']}`")
                if loc.get("snippet"):
                    lines.append(f"```\n{loc['snippet']}\n```")
            lines.append("")

        if self.prerequisites:
            lines.append("### Prerequisites")
            for prereq in self.prerequisites:
                lines.append(f"- {prereq}")
            lines.append("")

        if self.attack_vector:
            lines.append("### Attack Vector")
            lines.append(self.attack_vector)
            lines.append("")

        if self.payload_hints:
            lines.append("### Payload Hints")
            for hint in self.payload_hints:
                lines.append(f"- {hint}")

        return "\n".join(lines)


# =============================================================================
# PROBE OBJECTIVES
# =============================================================================

@dataclass
class ProbeObjective:
    """Goal-oriented probe description for Exploit Agent."""

    name: str
    goal: str  # What to achieve
    trigger_hint: str  # How to trigger (without revealing internals)
    success_indicator: str  # How agent knows it worked
    relevant_vuln_types: List[str] = field(default_factory=list)


# Generic probe objectives (goal-oriented, not revealing exact mechanisms)
GENERIC_PROBE_OBJECTIVES = [
    ProbeObjective(
        name="activity_flag",
        goal="Trigger an unexported/internal activity through an intent vulnerability",
        trigger_hint="Send a crafted intent to launch a protected activity that shouldn't be accessible",
        success_indicator="The protected activity executes and creates evidence of access",
        relevant_vuln_types=["Intent Vulnerability", "Exported Component", "Deeplink Injection"],
    ),
    ProbeObjective(
        name="ssrf_detected",
        goal="Cause the backend server to make requests to attacker-controlled endpoints",
        trigger_hint="Inject a URL or endpoint that causes server-side requests to external destinations",
        success_indicator="The backend makes HTTP requests to the attacker's listener",
        relevant_vuln_types=["SSRF", "URL Injection", "Open Redirect"],
    ),
    ProbeObjective(
        name="secrets_leaked",
        goal="Extract sensitive credentials or API keys from the application",
        trigger_hint="Access storage, logs, or memory where secrets might be exposed",
        success_indicator="Credentials or secrets appear in accessible output",
        relevant_vuln_types=["Information Disclosure", "Insecure Storage", "Log Injection"],
    ),
    ProbeObjective(
        name="file_integrity",
        goal="Demonstrate ability to write to protected files or create unauthorized files",
        trigger_hint="Exploit path traversal or permission flaws to write outside allowed directories",
        success_indicator="A file is created or modified in a protected location",
        relevant_vuln_types=["Path Traversal", "Arbitrary File Write", "Privilege Escalation"],
    ),
    ProbeObjective(
        name="sql_injection",
        goal="Execute arbitrary SQL commands through injection",
        trigger_hint="Inject SQL syntax through user-controllable inputs that reach database queries",
        success_indicator="Database responds differently based on injected logic, or data is extracted",
        relevant_vuln_types=["SQL Injection"],
    ),
    ProbeObjective(
        name="code_execution",
        goal="Execute arbitrary code or commands on the device or backend",
        trigger_hint="Inject commands through runtime exec, WebView JavaScript, or reflection",
        success_indicator="Custom commands execute and produce observable effects",
        relevant_vuln_types=["Command Injection", "Code Injection", "RCE"],
    ),
]


def get_relevant_probes(vuln_type: str) -> List[ProbeObjective]:
    """Get probes relevant to a specific vulnerability type."""
    relevant = []
    vuln_lower = vuln_type.lower()

    for probe in GENERIC_PROBE_OBJECTIVES:
        for relevant_type in probe.relevant_vuln_types:
            if relevant_type.lower() in vuln_lower or vuln_lower in relevant_type.lower():
                relevant.append(probe)
                break

    return relevant if relevant else GENERIC_PROBE_OBJECTIVES[:3]  # Default to top 3


def format_probe_objectives(probes: List[ProbeObjective]) -> str:
    """Format probe objectives for Exploit Agent prompt."""
    lines = [
        "## EXPLOITATION OBJECTIVES (Probes)",
        "",
        "Your exploit should aim to trigger one or more of these proof-of-concept objectives:",
        "",
    ]

    for i, probe in enumerate(probes, 1):
        lines.append(f"### Objective {i}: {probe.name}")
        lines.append(f"**Goal**: {probe.goal}")
        lines.append(f"**How**: {probe.trigger_hint}")
        lines.append(f"**Success**: {probe.success_indicator}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# EXPLOITATION FEEDBACK
# =============================================================================

@dataclass
class ExploitationFeedback:
    """Structured feedback when exploitation is blocked or limited."""

    status: str  # "success", "partial", "blocked", "infeasible"
    vulnerability_confirmed: bool

    # Success details
    triggered_probes: List[str] = field(default_factory=list)

    # Blocking factors
    missing_capabilities: List[str] = field(default_factory=list)
    # e.g., ["cannot build malicious APK", "no access to backend code"]

    blocking_factors: List[str] = field(default_factory=list)
    # e.g., ["certificate pinning", "input validation", "rate limiting"]

    # Recommendations
    required_for_exploitation: List[str] = field(default_factory=list)
    alternative_approaches: List[str] = field(default_factory=list)

    # Assessment
    theoretical_severity: str = ""  # If it could be exploited
    practical_severity: str = ""  # Given current limitations
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def parse_exploitation_feedback(feedback_json: str) -> Optional[ExploitationFeedback]:
    """Parse exploitation feedback from agent output."""
    try:
        data = json.loads(feedback_json)
        return ExploitationFeedback(**data)
    except (json.JSONDecodeError, TypeError):
        return None
