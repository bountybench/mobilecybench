# MobileCybench Architecture

## Code Abstractions

**Workflow** (`workflows/base.py`) - Owns the lifecycle of an evaluation task. Abstract base with methods:
- `validate_arguments()`
- `setup_runtime_environment()`
- `setup_agent()`
- `run_agent()`
- `evaluate()`
- `cleanup()`

**Agent** (`agent/`) - The LLM-powered actor that performs security testing. Builds prompts, executes an agentic loop (prompt → LLM → tool calls → repeat), and uses a ModelProvider for LLM communication.

**ModelProvider** (`agent/model_providers/`) - Abstracts LLM API details: model routing, tokens, caching, response normalization, and conversation history.

## Runtime Architecture

```
                              Host Machine
  ┌───────────────────────────────────────────────────────────────────────────┐
  │                                                                           │
  │   runner.py / Workflow                                                    │
  │         │                                                                 │
  │         │ docker exec        ADB Server ───► Android Emulator             │
  │         │                        ▲           (local, or container in GCP) │
  │         │                        │                                        │
  └─────────┼────────────────────────┼────────────────────────────────────────┘
            │                        │ network (adb connect)
            ▼                        │
  ┌─────────────────────┐            │          ┌─────────────────────┐
  │   Kali Container    │────────────┘          │   App Containers    │
  │   (sandbox)         │                       │                     │
  │                     │◄───── shared_net ────►│ - Backend servers   │
  │ - Agent commands    │                       │ - Databases         │
  │   execute here      │                       │ - App dependencies  │
  │ - /app/codebase     │                       │                     │
  │   mounted           │                       │                     │
  └─────────────────────┘                       └─────────────────────┘
```

**Host Machine**
- Runs runner.py and Workflow orchestration
- Runs ADB server
- Runs Android emulator (local) or connects to emulator container (GCP only)
- Controls containers via `docker exec`

**Kali Container** (agent phase)
- Sandboxed environment where agent commands execute
- App codebase mounted at `/app/codebase`
- Connects to ADB server on host via network
- Tools execute via ToolRuntime
- Restarted before evaluation begins (only `agent_exploit` dir is preserved)

**App Containers**
- Backend servers, databases, and other app dependencies
- Connected to Kali via `shared_net` Docker network
- Examples: Nextcloud server, database containers

## Agent Environment

### Information Available

**Mounted directories in Kali container:**
- `/app/codebase` - Full app source code (read-only copy)
- `/app/agent_exploit` - Empty directory for agent to write exploits
- `/app/agent_output` - Directory for exploit results (captured secrets, exfiltrated data). Volume-mounted so verify scripts on the host can read them.
- `/app/verify_files` (exploit mode only) - Contains evaluator verification logic

**From initial prompt (see `agent/custom_agent.py`):**
- Package name
- App server container name + port (if applicable)
- Username/password from `metadata.json` (if provided)
- Directory tree of codebase

**Mode differences:**
- Discovery mode: Agent searches for unknown vulnerabilities
- Exploit mode: Agent receives vulnerability description + access to verify_files
- Detection mode: Agent searches for real vulnerabilities; evaluation replays exploit on original vs hardened APK

### Agent Capabilities

**Can do:**
- Create and execute files in the Kali sandbox
- Execute shell commands via ToolRuntime
- Interact with emulator via ADB (as `shell` user)
- Network access to app containers via `shared_net`

**Cannot do (allowlist restrictions):**
- `adb root`
- `adb backup`
- `su` / privilege escalation
- Other restricted operations defined in runner config

### ADB Shell User Permissions (Android Primer)

*Skip this section if you're familiar with Android/ADB internals.*

The agent runs ADB commands as the `shell` user, which has limited Android permissions:

**Cannot:**
- Directly access app private data (`/data/data/<package_name>/`)
- Read/write other apps' sandboxed storage

**Can:**
- Access shared storage (`/sdcard/`)
- Interact with the app via UI automation (`input` commands)
- Read and write to logcat (`adb logcat`)
- Use `am` (Activity Manager) commands:
  - `am start` - launch activities
  - `am broadcast` - send broadcast intents
  - `am force-stop` - kill an app
- Use `pm` (Package Manager) commands:
  - `pm list packages` - list installed packages
  - `pm path` - get APK path for a package
  - `pm clear` - clear app data

Some apps (like Termux) may expose files via other mechanisms, but standard apps' private directories are inaccessible to the shell user.

### Emulator State

- App is pre-installed as a **release APK** (so `run-as` is unavailable)
- App is open to main activity
- Test users are pre-seeded (credentials in metadata.json)

## GKE Deployment Architecture

For running experiments at scale, MobileCybench can be deployed on Google Kubernetes Engine (GKE). Each experiment runs as a Kubernetes Job in a privileged pod with Docker-in-Docker:

```
GKE Node (n2d-standard-8, nested virt enabled)
└── Pod (privileged, /dev/kvm hostPath)
    └── Orchestrator container (DinD)
        ├── Android emulator (container or native process)
        ├── Kali agent container
        └── App backend containers
```

Key infrastructure components:
- **Orchestrator images**: `Dockerfile.orchestrator` (full, ~31 GB) or `Dockerfile.orchestrator-slim` (no emulator, ~5-6 GB) + separate `Dockerfile.emulator` (~8-10 GB)
- **Emulator modes**: `container` (emulator as a separate Docker container inside DinD) or `native` (emulator as a process inside the orchestrator)
- **Job generation**: `infra/gke/generate_jobs.py` creates Kubernetes Job manifests for experiment matrices (apps x models x vulnerabilities)
- **Results collection**: Experiment results are uploaded to GCS and aggregated via `infra/gke/collect_results.py`

See `infra/gke/README.md` for full setup instructions, cluster configuration, and troubleshooting.
## Logging & Observability

MobileCybench uses a centralized logging system designed for both human debugging and machine analysis.

### LoggerManager (Singleton)
The `LoggerManager` (`utils/logger.py`) is a lazy singleton that owns the experiment lifecycle:
- **UUID Run IDs**: Every run is assigned a version 4 UUID (`run_id`).
- **Late-Binding Config**: The logger is initialized with `RunnerConfig` early in the `runner.py` execution, allowing configuration-driven log levels and UI filtering.
- **Thread Safety**: Uses log-record cloning to prevent side-effects during concurrent logging.

### Data Modeling (Pydantic)
All high-signal data objects use Pydantic `BaseModel` for strict typing and consistent serialization:
- `RunnerConfig`: Orchestrates the run parameters.
- `ProviderResponse`: Standardizes LLM outputs across OpenAI and LiteLLM.
- `TokenUsage`: Tracks cost and tokens per request.
- `CodexCLIResult`: Captures multi-turn interaction data.

### Forensic Artifacts
Beyond standard text logs, the system captures:
- **System State**: Full Logcat dump from the Android emulator.
- **Visual State**: PNG screenshots for every turn of the agent.
- **Repo State**: A `git_repro.patch` file containing any uncommitted changes at run-time.
- **Machine Trace**: A `conversation.jsonl` file that makes agent behavior trivially parseable for external analysis tools.
