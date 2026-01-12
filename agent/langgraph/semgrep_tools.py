"""
Semgrep tool wrappers for LangGraph agents.

This module provides tool functions that wrap Semgrep functionality
for use in LangGraph-based agents.

IMPORTANT: All tools execute inside the kali-container for security isolation.
The codebase is available at /app/codebase inside the container.
"""

import json
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.backend.docker_ops import execute_command_internal
from utils.logger import agent_logger

# Container paths
CONTAINER_CODEBASE_PATH = "/app/codebase"


class SemgrepScanInput(BaseModel):
    """Input schema for Semgrep scan tool."""

    path: str = Field(
        description="The path to the file or directory to scan. Use '.' for current directory."
    )
    config: Optional[str] = Field(
        default="auto",
        description="Semgrep rule config (auto, p/security-audit, p/owasp-top-ten, etc.)",
    )
    severity: Optional[List[str]] = Field(
        default=None,
        description="Filter by severity levels (ERROR, WARNING, INFO)",
    )
    exclude: Optional[List[str]] = Field(
        default=None,
        description="Patterns to exclude from scanning",
    )


class CodeReadInput(BaseModel):
    """Input schema for reading code files."""

    file_path: str = Field(description="The absolute or relative path to the file")
    start_line: Optional[int] = Field(
        default=None, description="Start line number (1-indexed)"
    )
    end_line: Optional[int] = Field(
        default=None, description="End line number (1-indexed)"
    )


class SearchCodebaseInput(BaseModel):
    """Input schema for searching codebase."""

    pattern: str = Field(description="Search pattern (can be literal string or regex)")
    path: Optional[str] = Field(
        default=".", description="Directory to search in (default: current directory)"
    )
    file_pattern: Optional[str] = Field(
        default=None,
        description="File pattern to limit search (e.g., '*.java', '*.kt')",
    )
    case_sensitive: Optional[bool] = Field(
        default=False, description="Whether search should be case-sensitive"
    )


class FindDefinitionInput(BaseModel):
    """Input schema for finding class/method definitions."""

    name: str = Field(description="Name of class, method, or function to find")
    type_hint: Optional[str] = Field(
        default=None, description="Type hint: 'class', 'method', 'function' (optional)"
    )
    path: Optional[str] = Field(default=".", description="Directory to search in")


@tool(args_schema=SemgrepScanInput)
def run_semgrep_scan(
    path: str,
    config: str = "auto",
    severity: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run Semgrep static analysis on the specified path inside the kali-container.

    Returns a dictionary with:
    - success: bool indicating if scan completed
    - findings: list of security findings
    - errors: list of any errors encountered
    - summary: high-level summary of findings
    """
    try:
        # Normalize path to container codebase
        scan_path = f"{CONTAINER_CODEBASE_PATH}/{path}" if path != "." else CONTAINER_CODEBASE_PATH
        agent_logger.info(f"Running Semgrep scan on: {scan_path} with config: {config}")

        # Build semgrep command for container execution
        cmd_parts = ["semgrep", "scan", scan_path, "--config", config, "--json"]

        # Add severity filters
        if severity:
            for sev in severity:
                cmd_parts.extend(["--severity", sev])

        # Add exclusions
        if exclude:
            for pattern in exclude:
                cmd_parts.extend(["--exclude", pattern])

        cmd = " ".join(cmd_parts)

        # Execute inside kali-container
        output_str = execute_command_internal(cmd)

        # Parse the output - execute_command_internal returns formatted output
        # Extract JSON from the command output
        json_start = output_str.find("{")
        json_end = output_str.rfind("}") + 1

        if json_start == -1 or json_end == 0:
            agent_logger.error(f"No JSON output from Semgrep: {output_str[:500]}")
            return {
                "success": False,
                "findings": [],
                "errors": [f"No JSON output from Semgrep. Raw output: {output_str[:500]}"],
                "summary": {},
            }

        json_str = output_str[json_start:json_end]
        output = json.loads(json_str)
        findings = output.get("results", [])

        # Summarize findings by severity and rule
        summary = {
            "total_findings": len(findings),
            "by_severity": {},
            "by_rule": {},
        }

        for finding in findings:
            sev = finding.get("extra", {}).get("severity", "UNKNOWN")
            rule_id = finding.get("check_id", "unknown")
            summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
            summary["by_rule"][rule_id] = summary["by_rule"].get(rule_id, 0) + 1

        agent_logger.info(f"Semgrep scan completed: {len(findings)} findings found")

        # Prioritize findings: ERROR > WARNING > INFO
        severity_order = {"ERROR": 0, "WARNING": 1, "INFO": 2, "UNKNOWN": 3}
        sorted_findings = sorted(
            findings,
            key=lambda f: (
                severity_order.get(f.get("extra", {}).get("severity", "UNKNOWN"), 4),
                f.get("check_id", ""),
            ),
        )

        # Group by rule and take representative samples (max 3 per rule)
        rule_samples: Dict[str, List] = {}
        for finding in sorted_findings:
            rule_id = finding.get("check_id", "unknown")
            if rule_id not in rule_samples:
                rule_samples[rule_id] = []
            if len(rule_samples[rule_id]) < 3:
                rule_samples[rule_id].append(finding)

        # Flatten to list, limit total to 50
        priority_findings = []
        for samples in rule_samples.values():
            priority_findings.extend(samples)
            if len(priority_findings) >= 50:
                break
        priority_findings = priority_findings[:50]

        agent_logger.info(
            f"Returning {len(priority_findings)} priority findings out of {len(findings)} total"
        )

        return {
            "success": True,
            "findings": priority_findings,
            "errors": output.get("errors", []),
            "summary": summary,
            "note": f"Showing {len(priority_findings)} priority findings out of {len(findings)} total. "
            f"Use read_code_file to examine specific issues.",
        }

    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse Semgrep JSON output: {e}"
        agent_logger.error(error_msg)
        return {
            "success": False,
            "findings": [],
            "errors": [error_msg],
            "summary": {},
        }
    except Exception as e:
        error_msg = f"Error running Semgrep: {e}"
        agent_logger.error(error_msg)
        return {
            "success": False,
            "findings": [],
            "errors": [error_msg],
            "summary": {},
        }


@tool(args_schema=CodeReadInput)
def read_code_file(
    file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None
) -> Dict[str, Any]:
    """
    Read a code file inside the kali-container to verify Semgrep findings.

    Returns a dictionary with:
    - success: bool indicating if file was read
    - content: file content or excerpt
    - line_count: total lines in file
    - error: error message if failed
    """
    try:
        # Normalize path to container codebase
        full_path = f"{CONTAINER_CODEBASE_PATH}/{file_path}"

        # Get line count first
        wc_output = execute_command_internal(f"wc -l < {full_path}")
        # Extract number from output
        try:
            total_lines = int(wc_output.split("Output:")[-1].strip().split()[0])
        except (ValueError, IndexError):
            total_lines = 0

        # Build read command based on line range
        if start_line is not None and end_line is not None:
            cmd = f"sed -n '{start_line},{end_line}p' {full_path}"
        elif start_line is not None:
            end = start_line + 20
            cmd = f"sed -n '{start_line},{end}p' {full_path}"
        else:
            # Read full file with limit
            cmd = f"head -n 1000 {full_path}"

        output = execute_command_internal(cmd)

        # Extract content from formatted output
        if "Output:" in output:
            content = output.split("Output:", 1)[1].strip()
        else:
            content = output

        if total_lines > 1000 and start_line is None:
            content += f"\n... ({total_lines - 1000} more lines)"

        return {
            "success": True,
            "content": content,
            "line_count": total_lines,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "content": "",
            "line_count": 0,
            "error": f"Error reading file: {e}",
        }


@tool(args_schema=SearchCodebaseInput)
def search_codebase(
    pattern: str,
    path: str = ".",
    file_pattern: Optional[str] = None,
    case_sensitive: bool = False,
) -> Dict[str, Any]:
    """
    Search for patterns in the codebase inside the kali-container using ripgrep.

    Returns a dictionary with:
    - success: bool indicating if search completed
    - matches: list of matches with file, line number, and content
    - total_matches: total number of matches found
    - error: error message if failed
    """
    try:
        # Normalize path to container codebase
        search_path = f"{CONTAINER_CODEBASE_PATH}/{path}" if path != "." else CONTAINER_CODEBASE_PATH
        agent_logger.info(f"Searching codebase for pattern: {pattern}")

        # Build ripgrep command (rg is faster and better than grep)
        # Escape single quotes in pattern
        pattern_escaped = pattern.replace("'", "'\\''")
        cmd_parts = ["rg", "-n"]  # line numbers

        if not case_sensitive:
            cmd_parts.append("-i")

        if file_pattern:
            file_pattern_escaped = file_pattern.replace("'", "'\\''")
            cmd_parts.extend(["--glob", f"'{file_pattern_escaped}'"])

        cmd_parts.extend([f"'{pattern_escaped}'", search_path])
        cmd = " ".join(cmd_parts)

        # Execute inside container
        output = execute_command_internal(cmd)

        # Parse results
        matches = []
        if "Output:" in output:
            result_lines = output.split("Output:", 1)[1].strip().split("\n")
        else:
            result_lines = output.strip().split("\n")

        for line in result_lines[:100]:
            if not line.strip():
                continue
            # Format: file:line:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append({
                    "file": parts[0],
                    "line": parts[1],
                    "content": parts[2].strip(),
                })

        agent_logger.info(f"Found {len(matches)} matches")

        return {
            "success": True,
            "matches": matches,
            "total_matches": len(matches),
            "note": "Limited to 100 matches. Use more specific patterns for large result sets.",
            "error": None,
        }

    except Exception as e:
        error_msg = f"Error searching codebase: {e}"
        agent_logger.error(error_msg)
        return {
            "success": False,
            "matches": [],
            "total_matches": 0,
            "error": error_msg,
        }


@tool(args_schema=FindDefinitionInput)
def find_definition(
    name: str,
    type_hint: Optional[str] = None,
    path: str = ".",
) -> Dict[str, Any]:
    """
    Find class, method, or function definitions in the codebase inside the kali-container.

    Returns a dictionary with:
    - success: bool indicating if search completed
    - definitions: list of found definitions with file and line info
    - error: error message if failed
    """
    try:
        # Normalize path to container codebase
        search_path = f"{CONTAINER_CODEBASE_PATH}/{path}" if path != "." else CONTAINER_CODEBASE_PATH
        agent_logger.info(f"Finding definition for: {name}")

        # Build search patterns based on type hint
        patterns = []
        if type_hint == "class" or type_hint is None:
            patterns.extend([
                f"class {name}",
                f"interface {name}",
                f"object {name}",
            ])
        if type_hint in ("method", "function", None):
            patterns.extend([
                f"fun {name}",      # Kotlin
                f"def {name}",      # Python
                f"function {name}", # JavaScript
                f"void {name}",     # Java/C++
                f"public.*{name}",  # Java methods
                f"private.*{name}", # Java methods
            ])

        all_matches = []
        for pattern in patterns:
            # Use ripgrep for faster searching
            pattern_escaped = pattern.replace("'", "'\\''")
            cmd = f"rg -n -i --glob '*.java' --glob '*.kt' --glob '*.py' --glob '*.js' --glob '*.ts' '{pattern_escaped}' {search_path}"

            try:
                output = execute_command_internal(cmd)

                # Parse results
                if "Output:" in output:
                    result_lines = output.split("Output:", 1)[1].strip().split("\n")
                else:
                    result_lines = output.strip().split("\n")

                for line in result_lines[:20]:  # Limit per pattern
                    if not line.strip():
                        continue
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        all_matches.append({
                            "file": parts[0],
                            "line": parts[1],
                            "content": parts[2].strip(),
                            "matched_pattern": pattern,
                        })
            except Exception:
                # Pattern may not match anything, continue to next
                continue

        # Deduplicate by file:line
        seen: set = set()
        unique_matches = []
        for match in all_matches:
            key = f"{match['file']}:{match['line']}"
            if key not in seen:
                seen.add(key)
                unique_matches.append(match)

        agent_logger.info(f"Found {len(unique_matches)} definitions")

        return {
            "success": True,
            "definitions": unique_matches[:50],
            "total_found": len(unique_matches),
            "error": None,
        }

    except Exception as e:
        error_msg = f"Error finding definition: {e}"
        agent_logger.error(error_msg)
        return {
            "success": False,
            "definitions": [],
            "total_found": 0,
            "error": error_msg,
        }


# List of tools to export
SEMGREP_TOOLS = [
    run_semgrep_scan,
    read_code_file,
    search_codebase,
    find_definition,
]
