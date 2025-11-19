# Multi-Agent Security Testing System

A LangChain-based multi-agent system for automated Android app security testing.

## Architecture

```
┌────────────────────────────────────────────────────┐
│         Coordinator Agent (GPT-5)                  │
│  • Parses semgrep JSON output                     │
│  • Triages findings by severity                   │
│  • Categorizes by vulnerability type              │
│  • Assigns tasks to specialist agents             │
│  • Aggregates final report                        │
└─────────────────┬──────────────────────────────────┘
                  │
       ┌──────────┴──────────┬─────────────┐
       │                     │             │
       ▼                     ▼             ▼
┌─────────────┐    ┌─────────────┐   ┌─────────────┐
│SQL Injection│    │Path Traversal│  │Command Exec │
│   Agent     │    │    Agent     │  │   Agent     │
│  (GPT-4)    │    │   (GPT-4)    │  │  (GPT-4)    │
└─────────────┘    └──────────────┘  └─────────────┘
       │                     │              │
       └──────────┬──────────┴──────────────┘
                  ▼
      Individual Investigation Reports
                  │
                  ▼
        ┌──────────────────┐
        │  Final Report    │
        │  • Verified vulns│
        │  • Evidence      │
        │  • False +       │
        └──────────────────┘
```

## Key Features

1. **Specialized Agents**: Each vulnerability type has a dedicated specialist agent
2. **Actual Testing**: Agents execute real exploitation attempts with evidence
3. **False Positive Filtering**: Only verified vulnerabilities are reported
4. **Parallel Investigation**: Multiple specialists work simultaneously
5. **Evidence-Based**: Every finding requires concrete proof

## Specialist Agents

| Agent Type | Handles | Key Tests |
|------------|---------|-----------|
| SQL Injection | Database attacks | Query injection, UNION, error-based |
| Path Traversal | File system attacks | ../, content providers, file reads |
| Command Injection | OS command execution | Shell metacharacters, RCE |
| Intent Injection | Android intent attacks | Malicious extras, component launching |
| Exported Component | Android surface attack | Unexported activity access |
| XSS | Cross-site scripting | WebView attacks |
| XXE | XML external entities | XML parser attacks |
| SSRF | Server-side request forgery | Internal endpoint access |
| Auth Bypass | Authentication issues | Credential bypass |

## Usage

### Basic Usage

```bash
python agent/multiagent_runner.py \
  --semgrep-results /path/to/semgrep_results.json \
  --app-dir /path/to/app/codebase \
  --output multiagent_report.json
```

### With Custom Models

```bash
python agent/multiagent_runner.py \
  --semgrep-results semgrep_results.json \
  --app-dir apps/owncloud-android/codebase \
  --coordinator-model gpt-5 \
  --specialist-model gpt-4 \
  --output owncloud_assessment.json
```

### Full Example

```bash
# 1. Run semgrep on the codebase
cd apps/owncloud-android/codebase
semgrep --config auto --json -o semgrep_results.json .

# 2. Run multi-agent assessment
cd ../../..
python agent/multiagent_runner.py \
  --semgrep-results apps/owncloud-android/codebase/semgrep_results.json \
  --app-dir apps/owncloud-android/codebase \
  --mcp-server http://localhost:8000 \
  --output owncloud_multiagent_report.json \
  --log-level DEBUG

# 3. View results
cat owncloud_multiagent_report.json | jq .
```

## Integration with Existing System

To integrate with your existing `custom_agent.py`:

```python
from multiagent_system import MultiAgentSecuritySystem

# In your agent loop, after running semgrep:
system = MultiAgentSecuritySystem(
    coordinator_model="gpt-5",
    specialist_model="gpt-4",
    mcp_tools=mcp_tools  # Your existing MCP tools
)

report = system.run_security_assessment(
    semgrep_json_path="semgrep_results.json",
    context={
        "package_name": "com.owncloud.android",
        "server_url": "owncloud_server:8080"
    }
)

# Process report
for vuln in report["verified_vulnerabilities"]:
    print(f"[{vuln['severity']}] {vuln['type']}: {vuln['description']}")
```

## Report Format

```json
{
  "overall_risk": "HIGH",
  "total_verified_vulnerabilities": 3,
  "critical_vulnerabilities": 1,
  "high_vulnerabilities": 2,
  "verified_vulnerabilities": [
    {
      "type": "path-traversal",
      "severity": "CRITICAL",
      "impact": "Can read arbitrary files including flag.txt",
      "name": "ContentProvider Path Traversal",
      "location": "DocumentsStorageProvider.kt:123",
      "description": "Exported ContentProvider allows path traversal via documentId parameter",
      "exploitation_steps": "adb shell content read --uri 'content://com.app.docs/files/../../../../flag.txt'",
      "evidence": "Successfully read /data/data/com.app/files/flag.txt"
    }
  ],
  "false_positives_count": 47,
  "specialist_reports": [
    {
      "task_id": "task_001",
      "type": "path-traversal",
      "exploitable": true,
      "severity": "CRITICAL",
      "impact": "File read vulnerability"
    }
  ]
}
```

## Advantages Over Single Agent

| Aspect | Single Agent | Multi-Agent System |
|--------|--------------|-------------------|
| **Focus** | Tries to do everything | Specialists focus on one type |
| **Expertise** | Generic knowledge | Deep domain knowledge |
| **Testing** | May skip tests | Each specialist tests thoroughly |
| **False Positives** | High rate | Filtered by verification |
| **Evidence** | Sometimes missing | Always required |
| **Parallel Work** | Sequential | Simultaneous investigation |
| **Code Quality** | Prompts get very long | Modular, maintainable |

## Workflow

1. **Coordinator parses semgrep**: Loads JSON, extracts HIGH/CRITICAL findings
2. **Categorization**: Groups findings by vulnerability type
3. **Task creation**: Creates investigation tasks with priority
4. **Dispatch**: Assigns tasks to relevant specialists
5. **Investigation**: Each specialist:
   - Reviews semgrep findings
   - Reads source code
   - Executes exploitation attempts
   - Verifies with evidence
   - Reports findings or marks false positives
6. **Aggregation**: Coordinator combines all reports
7. **Final output**: JSON report with verified vulnerabilities only

## Configuration

### Environment Variables

```bash
export OPENAI_API_KEY="your-key-here"
export MCP_SERVER_URL="http://localhost:8000"
```

### Model Selection

- **Coordinator**: Recommend GPT-5 or GPT-5-Pro for complex parsing/triaging
- **Specialists**: GPT-4 is sufficient, cheaper for parallel execution

### Parallelization

Currently specialists run sequentially. To parallelize:

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [
        executor.submit(specialist.investigate, task)
        for task, specialist in task_specialist_pairs
    ]
    reports = [f.result() for f in futures]
```

## Debugging

Enable debug logging:

```bash
python agent/multiagent_runner.py \
  --log-level DEBUG \
  --semgrep-results results.json \
  --app-dir codebase
```

Check individual specialist outputs:

```python
# In multiagent_system.py, enable verbose mode
self.executor = AgentExecutor(
    agent=agent,
    tools=self.mcp_tools,
    verbose=True,  # Shows agent's thought process
    max_iterations=20
)
```

## Limitations

1. **Token costs**: Running multiple LLM agents in parallel is expensive
2. **Time**: Each specialist may take 5-15 turns to verify findings
3. **MCP integration**: Currently uses mock MCP calls, needs real integration
4. **Parallelization**: Not yet implemented, runs sequentially

## Future Enhancements

1. **Async execution**: Parallelize specialist investigations
2. **Learning**: Specialists learn from past assessments
3. **Tool creation**: Specialists can create custom exploitation tools
4. **Cross-agent communication**: Agents share discovered credentials/tokens
5. **Adaptive testing**: Adjust strategy based on intermediate results
6. **Report quality scoring**: Rate the quality of evidence provided

## Testing

Test on the ownCloud Android app:

```bash
# Make sure Docker containers are running
docker ps

# Run assessment
python agent/multiagent_runner.py \
  --semgrep-results apps/owncloud-android/codebase/semgrep_results.json \
  --app-dir apps/owncloud-android/codebase \
  --output test_report.json

# Check for Host header bypass (known finding)
jq '.verified_vulnerabilities[] | select(.type == "auth-bypass")' test_report.json
```

## Cost Estimation

For a typical Android app with 1406 semgrep findings:

- **Filtering to HIGH/CRITICAL**: ~50 findings
- **Tasks created**: ~10 (grouped by type)
- **Specialist turns per task**: ~10-15
- **Tokens per turn**: ~2000 input, ~500 output

**Estimated cost**:
- Coordinator (GPT-5): ~$0.10
- 10 specialists × 15 turns × $0.05/turn (GPT-4): ~$7.50
- **Total**: ~$8 per assessment

Compare to single agent running 30 turns: ~$0.60
**Trade-off**: 13x cost for higher accuracy and verified findings
