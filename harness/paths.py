"""Container paths defined by the BYO-agent contract.

Python-side constants so call sites don't drift across files. Shell scripts
inside agent images repeat the same string literals (Python and bash cannot
share constants); the canonical cross-language record is documentation/
BRING_YOUR_OWN_AGENT.md plus schemas/{task,result}.schema.json.
"""

TASK_JSON = "/app/task.json"
EXPLOIT_DIR = "/app/agent_exploit"
RUN_DIR = "/app/agent_run"
OUTPUT_DIR = "/app/agent_output"
APK_TEMPLATE_DIR = "/app/agent_exploit/exploit_apk"
