"""
Semgrep tool wrappers for LangGraph agents.

This module provides tool functions that wrap Semgrep functionality
for use in LangGraph-based agents.
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from utils.logger import agent_logger


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

    pattern: str = Field(
        description="Search pattern (can be literal string or regex)"
    )
    path: Optional[str] = Field(
        default=".",
        description="Directory to search in (default: current directory)"
    )
    file_pattern: Optional[str] = Field(
        default=None,
        description="File pattern to limit search (e.g., '*.java', '*.kt')"
    )
    case_sensitive: Optional[bool] = Field(
        default=False,
        description="Whether search should be case-sensitive"
    )


class FindDefinitionInput(BaseModel):
    """Input schema for finding class/method definitions."""

    name: str = Field(
        description="Name of class, method, or function to find"
    )
    type_hint: Optional[str] = Field(
        default=None,
        description="Type hint: 'class', 'method', 'function' (optional)"
    )
    path: Optional[str] = Field(
        default=".",
        description="Directory to search in"
    )


@tool(args_schema=SemgrepScanInput)
def run_semgrep_scan(
    path: str,
    config: str = "auto",
    severity: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run Semgrep static analysis on the specified path.

    Returns a dictionary with:
    - success: bool indicating if scan completed
    - findings: list of security findings
    - errors: list of any errors encountered
    - summary: high-level summary of findings
    """
    try:
        agent_logger.info(f"Running Semgrep scan on: {path} with config: {config}")

        # Build semgrep command
        cmd = ["semgrep", "scan", path, "--config", config, "--json"]

        # Add severity filters
        if severity:
            for sev in severity:
                cmd.extend(["--severity", sev])

        # Add exclusions
        if exclude:
            for pattern in exclude:
                cmd.extend(["--exclude", pattern])

        # Run semgrep
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        # Parse JSON output
        if result.stdout:
            output = json.loads(result.stdout)
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

            agent_logger.info(
                f"Semgrep scan completed: {len(findings)} findings found"
            )

            # Return only top priority findings to avoid overwhelming LLM
            # Prioritize: ERROR > WARNING > INFO
            # Limit to top 20 findings per severity level
            priority_findings = []

            # Sort by severity
            severity_order = {"ERROR": 0, "WARNING": 1, "INFO": 2, "UNKNOWN": 3}
            sorted_findings = sorted(
                findings,
                key=lambda f: (
                    severity_order.get(f.get("extra", {}).get("severity", "UNKNOWN"), 4),
                    f.get("check_id", ""),
                )
            )

            # Group by rule and take representative samples
            rule_samples = {}
            for finding in sorted_findings:
                rule_id = finding.get("check_id", "unknown")
                if rule_id not in rule_samples:
                    rule_samples[rule_id] = []
                # Keep max 3 examples per rule
                if len(rule_samples[rule_id]) < 3:
                    rule_samples[rule_id].append(finding)

            # Flatten back to list, limit total to 50 findings
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
                "findings": priority_findings,  # Only return prioritized subset
                "errors": output.get("errors", []),
                "summary": summary,
                "note": f"Showing {len(priority_findings)} priority findings out of {len(findings)} total. "
                        f"Use read_code_file to examine specific issues.",
            }
        else:
            # No output or error
            error_msg = result.stderr or "Unknown error running Semgrep"
            agent_logger.error(f"Semgrep scan failed: {error_msg}")
            return {
                "success": False,
                "findings": [],
                "errors": [error_msg],
                "summary": {},
            }

    except subprocess.TimeoutExpired:
        error_msg = "Semgrep scan timed out after 5 minutes"
        agent_logger.error(error_msg)
        return {
            "success": False,
            "findings": [],
            "errors": [error_msg],
            "summary": {},
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
        error_msg = f"Unexpected error running Semgrep: {e}"
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
    Read a code file to verify Semgrep findings.

    Returns a dictionary with:
    - success: bool indicating if file was read
    - content: file content or excerpt
    - line_count: total lines in file
    - error: error message if failed
    """
    try:
        path = Path(file_path)

        if not path.exists():
            return {
                "success": False,
                "content": "",
                "line_count": 0,
                "error": f"File not found: {file_path}",
            }

        # Read file
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)

        # Extract specified range
        if start_line is not None and end_line is not None:
            # Convert to 0-indexed
            start_idx = max(0, start_line - 1)
            end_idx = min(total_lines, end_line)
            content_lines = lines[start_idx:end_idx]
            content = "".join(content_lines)
        elif start_line is not None:
            start_idx = max(0, start_line - 1)
            content_lines = lines[start_idx : min(total_lines, start_idx + 20)]
            content = "".join(content_lines)
        else:
            # Return full file (limit to reasonable size)
            if total_lines > 1000:
                content = "".join(lines[:1000]) + f"\n... ({total_lines - 1000} more lines)"
            else:
                content = "".join(lines)

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
    Search for patterns in the codebase using grep.

    Returns a dictionary with:
    - success: bool indicating if search completed
    - matches: list of matches with file, line number, and content
    - total_matches: total number of matches found
    - error: error message if failed
    """
    try:
        agent_logger.info(f"Searching codebase for pattern: {pattern}")

        # Build grep command
        cmd = ["grep", "-r", "-n"]  # recursive, with line numbers

        if not case_sensitive:
            cmd.append("-i")  # case insensitive

        # Add file pattern if specified
        if file_pattern:
            cmd.extend(["--include", file_pattern])

        # Exclude common non-source directories
        cmd.extend([
            "--exclude-dir=.git",
            "--exclude-dir=node_modules",
            "--exclude-dir=build",
            "--exclude-dir=.gradle",
        ])

        cmd.extend([pattern, path])

        # Run grep
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,  # 30 second timeout
        )

        # Parse results (grep returns non-zero if no matches, which is fine)
        matches = []
        if result.stdout:
            lines = result.stdout.strip().split("\n")
            for line in lines[:100]:  # Limit to 100 matches
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

    except subprocess.TimeoutExpired:
        error_msg = "Search timed out after 30 seconds"
        agent_logger.error(error_msg)
        return {
            "success": False,
            "matches": [],
            "total_matches": 0,
            "error": error_msg,
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
    Find class, method, or function definitions in the codebase.

    Returns a dictionary with:
    - success: bool indicating if search completed
    - definitions: list of found definitions with file and line info
    - error: error message if failed
    """
    try:
        agent_logger.info(f"Finding definition for: {name}")

        # Build search patterns based on type hint
        patterns = []
        if type_hint == "class" or type_hint is None:
            # Java/Kotlin class patterns
            patterns.extend([
                f"class {name}",
                f"class {name} ",
                f"interface {name}",
                f"object {name}",
            ])
        if type_hint == "method" or type_hint == "function" or type_hint is None:
            # Method/function patterns
            patterns.extend([
                f"fun {name}",  # Kotlin
                f"def {name}",  # Python
                f"function {name}",  # JavaScript
                f"void {name}",  # Java/C++
                f"public {name}",  # Java
                f"private {name}",  # Java
            ])

        all_matches = []
        for pattern in patterns:
            cmd = ["grep", "-r", "-n", "-i", "--include=*.java", "--include=*.kt",
                   "--include=*.py", "--include=*.js", "--include=*.ts",
                   "--exclude-dir=.git", "--exclude-dir=node_modules",
                   "--exclude-dir=build", "--exclude-dir=.gradle",
                   pattern, path]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )

            if result.stdout:
                lines = result.stdout.strip().split("\n")
                for line in lines[:20]:  # Limit per pattern
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        all_matches.append({
                            "file": parts[0],
                            "line": parts[1],
                            "content": parts[2].strip(),
                            "matched_pattern": pattern,
                        })

        # Deduplicate by file:line
        seen = set()
        unique_matches = []
        for match in all_matches:
            key = f"{match['file']}:{match['line']}"
            if key not in seen:
                seen.add(key)
                unique_matches.append(match)

        agent_logger.info(f"Found {len(unique_matches)} definitions")

        return {
            "success": True,
            "definitions": unique_matches[:50],  # Limit to 50 total
            "total_found": len(unique_matches),
            "error": None,
        }

    except subprocess.TimeoutExpired:
        error_msg = "Search timed out after 30 seconds"
        agent_logger.error(error_msg)
        return {
            "success": False,
            "definitions": [],
            "total_found": 0,
            "error": error_msg,
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
