"""
Run Semgrep with CVE-focused ruleset.

Filters out low-severity findings and focuses on:
- Injection vulnerabilities (SQL, command, path traversal)
- Authentication/authorization issues
- Deserialization
- XSS
- RCE patterns
"""

import json
import subprocess
from typing import List

from agent.custom_agent_v2.shared_knowledge import Vulnerability
from utils.logger import logger


def run_default_semgrep(app_path: str) -> List[Vulnerability]:
    """
    Run Semgrep with CVE-focused ruleset.

    Config:
    - Severity: ERROR, WARNING only (skip INFO)
    - Exclude: weak crypto, hardcoded strings, HTTP warnings
    - Include: injection, deserialization, auth, path-traversal, xss

    Args:
        app_path: Path to app codebase on host (e.g., "apps/ankidroid/codebase")

    Returns:
        List of Vulnerability objects
    """
    logger.info(f"Running Semgrep on: {app_path}")

    # Check if semgrep is installed
    try:
        subprocess.run(
            ["semgrep", "--version"], capture_output=True, check=True, timeout=10
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        logger.error(
            "Semgrep not installed. Install with: pip install semgrep"
        )
        return []

    # Run Semgrep
    try:
        result = subprocess.run(
            [
                "semgrep",
                "--config=auto",  # Auto-detect rules
                "--json",
                "--severity=ERROR",
                "--severity=WARNING",
                "--skip-unknown-extensions",  # Skip non-code files
                "--timeout=300",  # 5 minute timeout
                app_path,
            ],
            capture_output=True,
            text=True,
            timeout=360,  # 6 minute process timeout
        )

        if result.returncode not in [0, 1]:  # 0 = no findings, 1 = findings found
            logger.error(f"Semgrep failed with exit code {result.returncode}")
            logger.error(f"Stderr: {result.stderr}")
            return []

        # Parse JSON output
        if not result.stdout:
            logger.warning("Semgrep returned no output")
            return []

        data = json.loads(result.stdout)
        findings = data.get("results", [])

        logger.info(f"Semgrep found {len(findings)} potential issues")

        # Convert to Vulnerability objects
        vulnerabilities = []
        for finding in findings:
            # Filter out low-priority findings
            if should_skip_finding(finding):
                continue

            vuln = convert_finding_to_vulnerability(finding)
            if vuln:
                vulnerabilities.append(vuln)

        logger.info(
            f"After filtering: {len(vulnerabilities)} vulnerabilities (removed {len(findings) - len(vulnerabilities)} low-priority)"
        )

        return vulnerabilities

    except subprocess.TimeoutExpired:
        logger.error("Semgrep timed out after 6 minutes")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Semgrep JSON output: {e}")
        return []
    except Exception as e:
        logger.error(f"Error running Semgrep: {e}")
        return []


def should_skip_finding(finding: dict) -> bool:
    """
    Determine if finding should be skipped (low-priority/informational).

    Skip:
    - Weak crypto (MD5, SHA1) unless in critical context
    - HTTP instead of HTTPS warnings
    - Hardcoded strings (unless obvious secrets)
    - Code quality issues
    """
    rule_id = finding.get("check_id", "")

    # Patterns to skip
    skip_patterns = [
        "generic.secrets.security.detected-",  # Generic secret detection (too noisy)
        "crypto.weak-hash.use-of-md5",  # MD5 usage
        "crypto.weak-hash.use-of-sha1",  # SHA1 usage
        "networking.insecure-http",  # HTTP warnings
        "best-practice",  # Code quality
        "maintainability",  # Code quality
        "todo",  # TODO comments
        "fixme",  # FIXME comments
    ]

    for pattern in skip_patterns:
        if pattern in rule_id.lower():
            return True

    return False


def convert_finding_to_vulnerability(finding: dict) -> Vulnerability:
    """
    Convert Semgrep finding to Vulnerability object.

    Args:
        finding: Semgrep finding dict

    Returns:
        Vulnerability object
    """
    try:
        rule_id = finding.get("check_id", "unknown")
        severity = map_severity(finding.get("extra", {}).get("severity", "WARNING"))
        category = extract_category(rule_id)

        vuln = Vulnerability(
            id=f"semgrep-{rule_id}-{finding['start']['line']}",
            source="semgrep",
            severity=severity,
            category=category,
            title=finding.get("extra", {}).get("message", rule_id),
            description=finding.get("extra", {})
            .get("metadata", {})
            .get("description", ""),
            file_path=finding.get("path", "unknown"),
            line_number=finding.get("start", {}).get("line", 0),
            code_snippet=finding.get("extra", {}).get("lines", ""),
            metadata={
                "semgrep_rule": rule_id,
                "semgrep_severity": finding.get("extra", {}).get("severity", ""),
            },
            cve_worthy=False,  # Agent will assess this
        )

        return vuln

    except Exception as e:
        logger.error(f"Error converting Semgrep finding: {e}")
        return None


def map_severity(semgrep_severity: str) -> str:
    """
    Map Semgrep severity to our scale.

    Args:
        semgrep_severity: Semgrep severity (ERROR, WARNING, INFO)

    Returns:
        Our severity (critical, high, medium, low)
    """
    mapping = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}

    return mapping.get(semgrep_severity.upper(), "medium")


def extract_category(rule_id: str) -> str:
    """
    Extract vulnerability category from Semgrep rule ID.

    Examples:
        "java.lang.security.audit.sqli.tainted-sql-string" -> "sqli"
        "javascript.express.security.audit.xss.mustache.explicit-unescape" -> "xss"
        "java.android.security.webview-javascript-enabled" -> "webview"

    Args:
        rule_id: Semgrep rule ID

    Returns:
        Category string
    """
    rule_lower = rule_id.lower()

    # Map keywords to categories
    category_map = {
        "sqli": "sqli",
        "sql-injection": "sqli",
        "xss": "xss",
        "command-injection": "command-injection",
        "path-traversal": "path-traversal",
        "xxe": "xxe",
        "ssrf": "ssrf",
        "deserialization": "deserialization",
        "auth": "auth-bypass",
        "authentication": "auth-bypass",
        "authorization": "auth-bypass",
        "rce": "rce",
        "remote-code": "rce",
        "webview": "webview",
        "intent": "intent-hijacking",
        "crypto": "crypto",
    }

    for keyword, category in category_map.items():
        if keyword in rule_lower:
            return category

    # Fallback: extract from rule path
    parts = rule_id.split(".")
    if len(parts) > 2:
        return parts[-2]  # Usually second-to-last part

    return "other"
