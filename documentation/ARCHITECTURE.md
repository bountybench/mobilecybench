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

**Kali Container**
- Sandboxed environment where agent commands execute
- App codebase mounted at `/app/codebase`
- Connects to ADB server on host via network
- Tools execute via ToolRuntime

**App Containers**
- Backend servers, databases, and other app dependencies
- Connected to Kali via `shared_net` Docker network
- Examples: Nextcloud server, database containers

## Agent Environment

### Information Available

**Mounted directories in Kali container:**
- `/app/codebase` - Full app source code (read-only copy)
- `/app/exploit_files` - Empty directory for agent to write exploits
- `/app/verify_files` (exploit mode only) - Contains evaluator verification logic

**From initial prompt (see `agent/custom_agent.py`):**
- Package name
- App server container name + port (if applicable)
- Username/password from `metadata.json` (if provided)
- Directory tree of codebase

**Mode differences:**
- Discovery mode: Agent searches for unknown vulnerabilities
- Exploit mode: Agent receives vulnerability description + access to verify_files

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
