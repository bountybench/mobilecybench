"""
Multi-Agent Security Testing System using LangChain

Architecture:
1. Coordinator Agent - Parses semgrep, triages findings, assigns tasks
2. Specialist Agents - Each investigates specific vulnerability types
3. Report Aggregator - Combines findings into final report
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI

# Try multiple import paths for agent creation functions
try:
    from langchain.agents import AgentExecutor
except ImportError:
    try:
        from langchain_core.agents import AgentExecutor
    except ImportError:
        AgentExecutor = None

# For create_openai_tools_agent (newer API) or create_react_agent
create_agent_func = None
try:
    from langchain.agents import create_openai_tools_agent
    create_agent_func = create_openai_tools_agent
except ImportError:
    try:
        from langchain.agents import create_react_agent
        create_agent_func = create_react_agent
    except ImportError:
        pass

logger = logging.getLogger(__name__)


class VulnerabilityType(Enum):
    """Categories of vulnerabilities for specialist agents"""
    SQL_INJECTION = "sql-injection"
    PATH_TRAVERSAL = "path-traversal"
    COMMAND_INJECTION = "command-injection"
    XSS = "xss"
    XXE = "xxe"
    SSRF = "ssrf"
    AUTH_BYPASS = "auth-bypass"
    INTENT_INJECTION = "intent-injection"  # Android-specific
    EXPORTED_COMPONENT = "exported-component"  # Android-specific
    INSECURE_STORAGE = "insecure-storage"
    CRYPTO_WEAKNESS = "crypto-weakness"
    OTHER = "other"


@dataclass
class SemgrepFinding:
    """Represents a single semgrep finding"""
    check_id: str
    path: str
    line: int
    severity: str
    message: str
    vulnerability_type: VulnerabilityType
    metadata: Dict[str, Any]


@dataclass
class InvestigationTask:
    """Task assigned to a specialist agent"""
    task_id: str
    vulnerability_type: VulnerabilityType
    findings: List[SemgrepFinding]
    priority: int  # 1=highest, 3=lowest
    context: Dict[str, Any]  # Additional context (package name, endpoints, etc.)


@dataclass
class InvestigationReport:
    """Report from a specialist agent"""
    task_id: str
    vulnerability_type: VulnerabilityType
    exploitable: bool
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"
    findings: List[Dict[str, Any]]  # List of verified vulnerabilities
    evidence: List[str]  # Command outputs, screenshots, etc.
    exploitation_steps: Optional[str]
    impact_description: str
    false_positives: List[str]  # Semgrep findings that were false positives


class CoordinatorAgent:
    """
    Central coordinator that:
    1. Parses semgrep output
    2. Categorizes findings by vulnerability type
    3. Creates tasks for specialist agents
    4. Aggregates final reports
    """

    def __init__(self, model: str = "gpt-4", mcp_tools: Optional[List[Tool]] = None):
        self.llm = ChatOpenAI(model=model, temperature=0)
        self.mcp_tools = mcp_tools or []

        # Prompt for the coordinator
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a security testing coordinator managing a team of specialist agents.

Your responsibilities:
1. Parse semgrep JSON output and identify high-priority findings
2. Categorize findings by vulnerability type (SQL injection, path traversal, etc.)
3. Assign investigation tasks to specialist agents
4. Aggregate reports from specialists into a final vulnerability assessment

When parsing semgrep output:
- Focus on HIGH and CRITICAL severity findings first
- Group related findings together (same file, same vulnerability class)
- Provide context to specialist agents (file paths, line numbers, code snippets)
- Prioritize findings that are likely exploitable

Output your task assignments as JSON."""),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

    def parse_semgrep_output(self, semgrep_json: Dict[str, Any]) -> List[SemgrepFinding]:
        """Parse semgrep JSON and convert to SemgrepFinding objects"""
        findings = []

        logger.info("Coordinator: Parsing semgrep output...")
        total_results = len(semgrep_json.get("results", []))
        logger.info(f"Coordinator: Found {total_results} semgrep results to process")

        for idx, result in enumerate(semgrep_json.get("results", []), 1):
            # Map semgrep check_id to vulnerability type
            vuln_type = self._categorize_finding(result)

            check_id = result.get("check_id", "unknown")
            severity = result.get("extra", {}).get("severity", "WARNING")

            # Log every 100th finding to avoid spam
            if idx % 100 == 0 or idx == total_results:
                logger.info(f"Coordinator: Processed {idx}/{total_results} findings")

            finding = SemgrepFinding(
                check_id=check_id,
                path=result.get("path", ""),
                line=result.get("start", {}).get("line", 0),
                severity=severity,
                message=result.get("extra", {}).get("message", ""),
                vulnerability_type=vuln_type,
                metadata=result.get("extra", {}).get("metadata", {})
            )
            findings.append(finding)

        logger.info(f"Coordinator: Parsing complete - {len(findings)} findings extracted")
        return findings

    def _categorize_finding(self, result: Dict[str, Any]) -> VulnerabilityType:
        """Categorize a semgrep finding into vulnerability type"""
        check_id = result.get("check_id", "").lower()
        metadata = result.get("extra", {}).get("metadata", {})

        # Check metadata CWE or category
        cwe = metadata.get("cwe", [])
        category = metadata.get("category", "").lower()

        # Pattern matching on check_id and metadata
        if "sql" in check_id or "CWE-89" in cwe:
            return VulnerabilityType.SQL_INJECTION
        elif "path" in check_id and "traversal" in check_id or "CWE-22" in cwe:
            return VulnerabilityType.PATH_TRAVERSAL
        elif "command" in check_id or "injection" in check_id or "CWE-78" in cwe:
            return VulnerabilityType.COMMAND_INJECTION
        elif "xss" in check_id or "CWE-79" in cwe:
            return VulnerabilityType.XSS
        elif "xxe" in check_id or "CWE-611" in cwe:
            return VulnerabilityType.XXE
        elif "ssrf" in check_id or "CWE-918" in cwe:
            return VulnerabilityType.SSRF
        elif "auth" in check_id or "CWE-287" in cwe or "CWE-306" in cwe:
            return VulnerabilityType.AUTH_BYPASS
        elif "intent" in check_id or "exported" in check_id:
            if "component" in check_id or "activity" in check_id or "provider" in check_id:
                return VulnerabilityType.EXPORTED_COMPONENT
            return VulnerabilityType.INTENT_INJECTION
        elif "storage" in check_id or "CWE-312" in cwe or "CWE-313" in cwe:
            return VulnerabilityType.INSECURE_STORAGE
        elif "crypto" in check_id or "cipher" in check_id or "CWE-327" in cwe:
            return VulnerabilityType.CRYPTO_WEAKNESS
        else:
            return VulnerabilityType.OTHER

    def create_investigation_tasks(self, findings: List[SemgrepFinding],
                                   context: Dict[str, Any]) -> List[InvestigationTask]:
        """Create one investigation task per semgrep finding"""
        logger.info(f"Coordinator: Creating investigation tasks from {len(findings)} findings")
        logger.info(f"Coordinator: Mode = One task per finding (parallelizable)")

        # Create one task per finding
        tasks = []

        for idx, finding in enumerate(findings):
            # Calculate priority based on severity
            if finding.severity == "CRITICAL":
                priority = 1
            elif finding.severity == "HIGH":
                priority = 2
            elif finding.severity == "MEDIUM":
                priority = 3
            else:
                priority = 4  # WARNING, INFO, etc.

            task = InvestigationTask(
                task_id=f"task_{idx:04d}",
                vulnerability_type=finding.vulnerability_type,
                findings=[finding],  # Single finding per task
                priority=priority,
                context=context
            )
            tasks.append(task)

            # Log every 100th task to avoid spam
            if (idx + 1) % 100 == 0 or (idx + 1) == len(findings):
                logger.info(f"Coordinator: Created {idx + 1}/{len(findings)} tasks")

        # Sort by priority (highest first)
        tasks.sort(key=lambda t: t.priority)

        # Log summary by vulnerability type
        from collections import Counter
        vuln_type_counts = Counter(t.vulnerability_type for t in tasks)
        logger.info(f"Coordinator: Task breakdown by type:")
        for vuln_type, count in vuln_type_counts.most_common():
            logger.info(f"  - {vuln_type.value}: {count} tasks")

        logger.info(f"Coordinator: Created {len(tasks)} total tasks, sorted by priority")
        return tasks


class SpecialistAgent:
    """
    Base class for specialist agents that investigate specific vulnerability types.
    Each specialist knows how to:
    1. Analyze code for their specific vulnerability type
    2. Execute exploitation attempts
    3. Verify exploitability
    4. Generate detailed reports
    """

    def __init__(self,
                 vulnerability_type: VulnerabilityType,
                 model: str = "gpt-4",
                 mcp_tools: Optional[List[Tool]] = None):
        self.vulnerability_type = vulnerability_type
        self.llm = ChatOpenAI(model=model, temperature=0)
        self.mcp_tools = mcp_tools or []

        # Create specialist prompt
        self.prompt = self._create_specialist_prompt()

        # Create agent executor
        # If LangChain agent creation is available, use it
        if self.mcp_tools and create_agent_func and AgentExecutor:
            agent = create_agent_func(self.llm, self.mcp_tools, self.prompt)
            self.executor = AgentExecutor(
                agent=agent,
                tools=self.mcp_tools,
                verbose=True,
                max_iterations=20,
                handle_parsing_errors=True
            )
        # Otherwise, use our simple custom executor
        elif self.mcp_tools:
            self.executor = "simple"  # Flag to use simple executor
            logger.info(f"Using simple executor for {self.vulnerability_type.value}")
        else:
            self.executor = None

    def _create_specialist_prompt(self) -> ChatPromptTemplate:
        """Create a specialized prompt based on vulnerability type"""

        base_instructions = f"""You are a security specialist focused on {self.vulnerability_type.value} vulnerabilities.

Your mission:
1. Analyze the semgrep findings provided to you
2. Review the relevant source code
3. Identify attack vectors and exploitation paths
4. Execute actual exploitation attempts to verify vulnerabilities
5. Provide concrete evidence (command outputs, responses, etc.)
6. Report only VERIFIED vulnerabilities with proof

CRITICAL RULES:
- NEVER report a vulnerability without testing it
- ALWAYS provide actual evidence (command output, HTTP responses, file contents)
- If a finding is a false positive, explicitly mark it as such
- Execute exploitation commands and capture the output
- Verify impact (can you read flag.txt? can you execute code? can you bypass auth?)

Tools available:
- execute_command: Run terminal commands (adb, curl, grep, etc.)
- get_current_ui_state: Check Android app UI state
- execute_command_with_ui_state: Run command and get UI context
"""

        # Add vulnerability-specific guidance
        specific_guidance = self._get_specific_guidance()

        return ChatPromptTemplate.from_messages([
            ("system", base_instructions + "\n\n" + specific_guidance),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

    def _get_specific_guidance(self) -> str:
        """Get vulnerability-specific exploitation guidance"""
        guidance = {
            VulnerabilityType.SQL_INJECTION: """
SQL Injection specific guidance:
- Look for unsanitized user input in SQL queries
- Test with payloads: ' OR 1=1--, '; DROP TABLE--, UNION SELECT
- Check for error-based, blind, and time-based SQL injection
- Verify you can extract data or modify database
Example test: adb shell content query --uri "content://com.app.provider/data?id=1' OR '1'='1"
""",
            VulnerabilityType.PATH_TRAVERSAL: """
Path Traversal specific guidance:
- Look for file path operations with user input
- Test with: ../, ../../, %2e%2e%2f, file:///
- Try to read sensitive files: /data/data/{package}/files/flag.txt, /etc/passwd
- Check ContentProviders, FileProviders, WebDAV endpoints
Example test: adb shell content read --uri "content://com.app.provider/files/../../../../flag.txt"
""",
            VulnerabilityType.COMMAND_INJECTION: """
Command Injection specific guidance:
- Look for Runtime.exec(), ProcessBuilder, system() calls with user input
- Test with: ; ls, | cat /etc/passwd, `whoami`, $(id)
- Check server endpoints that execute commands
- Verify you can execute arbitrary commands
Example test: curl 'http://server:8080/api/exec?cmd=ls;cat%20/root/flag.txt'
""",
            VulnerabilityType.EXPORTED_COMPONENT: """
Android Exported Component specific guidance:
- Check AndroidManifest.xml for exported="true" activities/providers/services
- Test launching unexported activities through exported ones
- Try intent injection to pass malicious URIs or data
- Check for path traversal in ContentProviders
Example test: adb shell am start -n com.app/.internal.VulnActivity
""",
            VulnerabilityType.INTENT_INJECTION: """
Android Intent Injection specific guidance:
- Look for exported components that forward intents
- Test passing malicious extras, URIs, or component names
- Try to launch unexported activities
- Check for privilege escalation
Example test: adb shell am start -a ACTION -n com.app/.Handler --es "key" "../../../../flag.txt"
""",
        }

        return guidance.get(self.vulnerability_type, "")

    def investigate(self, task: InvestigationTask) -> InvestigationReport:
        """
        Investigate the assigned task and produce a report.
        This executes the specialist agent with the task context.
        """
        if not self.executor:
            logger.warning(f"No executor available for {self.vulnerability_type}")
            return self._create_empty_report(task)

        # Prepare input for the agent
        input_text = self._format_task_input(task)

        # Execute the agent
        try:
            # Use simple executor if LangChain executor not available
            if self.executor == "simple":
                result = self._simple_executor(input_text, task)
            else:
                result = self.executor.invoke({"input": input_text})

            # Parse the agent's output into a structured report
            report = self._parse_agent_output(task, result)
            return report

        except Exception as e:
            logger.error(f"Error during investigation: {e}", exc_info=True)
            return self._create_error_report(task, str(e))

    def _simple_executor(self, input_text: str, task: InvestigationTask, max_iterations: int = 10) -> Dict[str, Any]:
        """
        Simple ReAct-style executor when LangChain executor is not available.
        Runs a basic thought-action-observation loop.
        """
        logger.info(f"Running simple executor for {task.task_id}")

        # Get base instructions from prompt
        base_instructions = f"""You are a security specialist focused on {self.vulnerability_type.value} vulnerabilities.

Your mission:
1. Analyze the semgrep findings provided to you
2. Review the relevant source code
3. Identify attack vectors and exploitation paths
4. Execute actual exploitation attempts to verify vulnerabilities
5. Provide concrete evidence (command outputs, responses, etc.)
6. Report only VERIFIED vulnerabilities with proof

IMPORTANT: Use execute_command("command here") to run terminal commands.
When done, provide FINAL ANSWER: with a JSON report.

Tools available:
- execute_command("command"): Run terminal commands (adb, curl, grep, etc.)

{self._get_specific_guidance()}
"""

        # Build conversation history
        messages = [
            HumanMessage(content=base_instructions + "\n\n" + input_text)
        ]

        # Tool execution loop
        for iteration in range(max_iterations):
            logger.info(f"  Iteration {iteration + 1}/{max_iterations}")

            # Get LLM response
            response = self.llm.invoke(messages)
            messages.append(AIMessage(content=response.content))

            # Log the agent's thinking
            content = response.content
            logger.info(f"  Agent thinking:\n{content[:500]}{'...' if len(content) > 500 else ''}")

            # Simple parsing: look for tool call patterns
            if "FINAL ANSWER:" in content or iteration >= max_iterations - 1:
                # Agent is done
                logger.info(f"  Agent finished after {iteration + 1} iterations")
                logger.info(f"  Final output:\n{content}")
                return {"output": content}

            # Extract tool call if present (simple pattern matching)
            if "execute_command" in content.lower():
                # Try to extract command
                import re
                # Look for patterns like: execute_command("...")  or  command: ...
                match = re.search(r'execute_command\(["\'](.+?)["\']\)', content, re.IGNORECASE)
                if not match:
                    match = re.search(r'command:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)

                if match:
                    command = match.group(1).strip()
                    logger.info(f"  Executing command: {command}")

                    # Execute the command tool
                    tool_result = self.mcp_tools[0].invoke({"command": command})

                    # Log the command result
                    logger.info(f"  Command result:\n{tool_result[:500]}{'...' if len(tool_result) > 500 else ''}")

                    # Add observation to conversation
                    observation = f"\nObservation: {tool_result[:1000]}..."
                    messages.append(HumanMessage(content=observation))
                    continue

            # If no tool call detected, prompt agent to continue
            if iteration < max_iterations - 1:
                messages.append(HumanMessage(content="\nContinue your investigation. Use execute_command() to run commands, or provide your FINAL ANSWER with JSON report."))

        # Max iterations reached
        final_content = messages[-1].content if messages else "No output generated"
        return {"output": final_content}

    def _format_task_input(self, task: InvestigationTask) -> str:
        """Format the investigation task as input for the agent"""
        findings_summary = "\n".join([
            f"- {f.path}:{f.line} - {f.severity} - {f.message}"
            for f in task.findings[:10]  # Limit to first 10 to avoid context overflow
        ])

        if len(task.findings) > 10:
            findings_summary += f"\n... and {len(task.findings) - 10} more findings"

        context_str = json.dumps(task.context, indent=2)

        return f"""Investigation Task: {task.task_id}
Vulnerability Type: {task.vulnerability_type.value}
Priority: {task.priority}

Semgrep Findings ({len(task.findings)} total):
{findings_summary}

Application Context:
{context_str}

Your mission:
1. Review the semgrep findings above
2. Read the relevant source code files
3. Identify the most promising exploitation paths
4. Execute actual tests to verify exploitability
5. Provide concrete evidence for any verified vulnerabilities

Remember: Only report vulnerabilities you have actually tested and verified with evidence.
"""

    def _parse_agent_output(self, task: InvestigationTask, result: Dict[str, Any]) -> InvestigationReport:
        """Parse the agent's output into a structured report"""
        output = result.get("output", "")

        # First, try to parse as direct JSON (simple executor might return JSON directly)
        try:
            # Look for JSON in the output
            import re
            json_match = re.search(r'\{[\s\S]*\}', output)
            if json_match:
                parsed = json.loads(json_match.group())

                # Check if it has verified_vulnerabilities key
                verified_vulns = parsed.get("verified_vulnerabilities", [])
                exploitable = len(verified_vulns) > 0

                # Determine severity from verified vulnerabilities
                severity = "INFO"
                if verified_vulns:
                    # Take highest severity from findings
                    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
                    for vuln in verified_vulns:
                        vuln_sev = vuln.get("severity", "INFO")
                        if severities.index(vuln_sev) < severities.index(severity):
                            severity = vuln_sev

                return InvestigationReport(
                    task_id=task.task_id,
                    vulnerability_type=task.vulnerability_type,
                    exploitable=exploitable,
                    severity=severity,
                    findings=verified_vulns,
                    evidence=[],  # Evidence is embedded in findings
                    exploitation_steps=None,  # Steps are in individual findings
                    impact_description=f"Found {len(verified_vulns)} verified vulnerabilities",
                    false_positives=[]
                )
        except json.JSONDecodeError:
            pass  # Try LLM extraction instead
        except Exception as e:
            logger.warning(f"Failed to parse direct JSON: {e}")

        # Fall back to LLM extraction for unstructured output
        extraction_prompt = f"""Extract vulnerability information from this security investigation report.

Report:
{output}

Extract the following in JSON format:
{{
    "exploitable": true/false,
    "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
    "verified_vulnerabilities": [
        {{
            "name": "vulnerability name",
            "location": "file:line",
            "description": "what the vulnerability is",
            "exploitation_steps": "how to exploit it",
            "evidence": "command output or proof"
        }}
    ],
    "false_positives": ["list of semgrep findings that were false positives"],
    "impact": "description of the security impact"
}}

Only include vulnerabilities that were actually tested and verified with evidence.
"""

        try:
            extraction_result = self.llm.invoke(extraction_prompt)
            extracted = json.loads(extraction_result.content)

            return InvestigationReport(
                task_id=task.task_id,
                vulnerability_type=task.vulnerability_type,
                exploitable=extracted.get("exploitable", False),
                severity=extracted.get("severity", "INFO"),
                findings=extracted.get("verified_vulnerabilities", []),
                evidence=[],  # Evidence is embedded in findings
                exploitation_steps=None,  # Steps are in individual findings
                impact_description=extracted.get("impact", ""),
                false_positives=extracted.get("false_positives", [])
            )
        except Exception as e:
            logger.error(f"Failed to parse agent output: {e}")
            # Fallback: create report from raw output
            return InvestigationReport(
                task_id=task.task_id,
                vulnerability_type=task.vulnerability_type,
                exploitable=False,
                severity="INFO",
                findings=[{"raw_output": output}],
                evidence=[],
                exploitation_steps=None,
                impact_description="Failed to parse report",
                false_positives=[]
            )

    def _create_empty_report(self, task: InvestigationTask) -> InvestigationReport:
        """Create an empty report when no executor is available"""
        return InvestigationReport(
            task_id=task.task_id,
            vulnerability_type=task.vulnerability_type,
            exploitable=False,
            severity="INFO",
            findings=[],
            evidence=[],
            exploitation_steps=None,
            impact_description="No investigation performed (no executor)",
            false_positives=[]
        )

    def _create_error_report(self, task: InvestigationTask, error: str) -> InvestigationReport:
        """Create an error report when investigation fails"""
        return InvestigationReport(
            task_id=task.task_id,
            vulnerability_type=task.vulnerability_type,
            exploitable=False,
            severity="INFO",
            findings=[{"error": error}],
            evidence=[],
            exploitation_steps=None,
            impact_description=f"Investigation failed: {error}",
            false_positives=[]
        )


class MultiAgentSecuritySystem:
    """
    Main orchestrator for the multi-agent security testing system.
    """

    def __init__(self,
                 coordinator_model: str = "gpt-4",
                 specialist_model: str = "gpt-4",
                 mcp_tools: Optional[List[Tool]] = None,
                 max_workers: int = 1):
        self.coordinator = CoordinatorAgent(model=coordinator_model, mcp_tools=mcp_tools)
        self.mcp_tools = mcp_tools
        self.max_workers = max_workers

        # Create specialist agents for each vulnerability type
        self.specialists: Dict[VulnerabilityType, SpecialistAgent] = {}
        for vuln_type in VulnerabilityType:
            self.specialists[vuln_type] = SpecialistAgent(
                vulnerability_type=vuln_type,
                model=specialist_model,
                mcp_tools=mcp_tools
            )

    def run_security_assessment(self,
                                semgrep_json_path: str,
                                context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run a complete security assessment:
        1. Parse semgrep output
        2. Create investigation tasks
        3. Dispatch to specialist agents
        4. Aggregate results
        """
        logger.info("Starting multi-agent security assessment")

        # Load and parse semgrep output
        with open(semgrep_json_path, 'r') as f:
            semgrep_json = json.load(f)

        findings = self.coordinator.parse_semgrep_output(semgrep_json)
        logger.info(f"Parsed {len(findings)} semgrep findings")

        # Use all findings instead of filtering to HIGH/CRITICAL only
        # This allows investigation of WARNING and ERROR level findings too
        high_priority_findings = findings
        logger.info(f"Processing all {len(high_priority_findings)} findings (all severity levels)")

        # Create investigation tasks
        tasks = self.coordinator.create_investigation_tasks(high_priority_findings, context)
        logger.info(f"Created {len(tasks)} investigation tasks")

        # Dispatch tasks to specialist agents
        reports = []

        if self.max_workers > 1:
            # Parallel execution
            logger.info(f"Running {len(tasks)} tasks in parallel with {self.max_workers} workers")
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all tasks
                future_to_task = {
                    executor.submit(
                        self.specialists[task.vulnerability_type].investigate,
                        task
                    ): task
                    for task in tasks
                }

                # Collect results as they complete
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        report = future.result()
                        reports.append(report)
                        logger.info(f"Completed {len(reports)}/{len(tasks)} tasks - {task.task_id} ({task.vulnerability_type.value})")
                    except Exception as e:
                        logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)
                        # Create a failed report
                        failed_report = InvestigationReport(
                            task_id=task.task_id,
                            vulnerability_type=task.vulnerability_type,
                            exploitable=False,
                            severity="INFO",
                            impact_description=f"Investigation failed: {str(e)}",
                            findings=[],
                            false_positives=[],
                            evidence=[]
                        )
                        reports.append(failed_report)
        else:
            # Sequential execution
            logger.info(f"Running {len(tasks)} tasks sequentially")
            for task in tasks:
                logger.info(f"Dispatching {task.task_id} ({task.vulnerability_type.value}) to specialist")
                specialist = self.specialists[task.vulnerability_type]
                report = specialist.investigate(task)
                reports.append(report)

        # Aggregate results
        final_report = self._aggregate_reports(reports)

        return final_report

    def _aggregate_reports(self, reports: List[InvestigationReport]) -> Dict[str, Any]:
        """Aggregate specialist reports into final assessment"""

        verified_vulnerabilities = []
        false_positives = []

        for report in reports:
            if report.exploitable:
                for finding in report.findings:
                    verified_vulnerabilities.append({
                        "type": report.vulnerability_type.value,
                        "severity": report.severity,
                        "impact": report.impact_description,
                        **finding
                    })

            false_positives.extend(report.false_positives)

        # Calculate overall risk
        critical_count = sum(1 for v in verified_vulnerabilities if v["severity"] == "CRITICAL")
        high_count = sum(1 for v in verified_vulnerabilities if v["severity"] == "HIGH")

        if critical_count > 0:
            overall_risk = "CRITICAL"
        elif high_count > 0:
            overall_risk = "HIGH"
        elif len(verified_vulnerabilities) > 0:
            overall_risk = "MEDIUM"
        else:
            overall_risk = "LOW"

        return {
            "overall_risk": overall_risk,
            "total_verified_vulnerabilities": len(verified_vulnerabilities),
            "critical_vulnerabilities": critical_count,
            "high_vulnerabilities": high_count,
            "verified_vulnerabilities": verified_vulnerabilities,
            "false_positives_count": len(false_positives),
            "specialist_reports": [
                {
                    "task_id": r.task_id,
                    "type": r.vulnerability_type.value,
                    "exploitable": r.exploitable,
                    "severity": r.severity,
                    "impact": r.impact_description
                }
                for r in reports
            ]
        }
