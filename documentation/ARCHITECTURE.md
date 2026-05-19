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

**ModelProvider** (`agent/custom/model_providers/`) - Abstracts LLM API details: model routing, tokens, caching, response normalization, and conversation history.

## Runtime Architecture

The agent runs on a single Docker network — `agent_net`, declared `internal: true`. The kernel drops every packet whose destination isn't on this network, so the agent has **no** default route to the host or the internet. Two dual-homed sidecars carry the only outbound traffic:

```
                                       ┌──────────────────────┐
                                       │       Internet       │
                                       │ (allowlisted FQDNs   │
                                       │  in restricted mode) │
                                       └──────────▲───────────┘
                                                  │ Squid CONNECT
   ╔══════ agent_net (internal: true) ════════════╪═══════════════════════╗
   ║  kernel deny-all egress; agent's ONLY network                        ║
   ║                                              │                       ║
   ║                                   ┌──────────┴─────────────┐         ║
   ║                                   │  egress-proxy (Squid)  │         ║
   ║                                   │  FQDN allowlist        │         ║
   ║                                   └──────────▲─────────────┘         ║
   ║                                              │ HTTPS_PROXY=          ║
   ║                                              │ http://egress-proxy   ║
   ║                                              │           :3128       ║
   ║                                   ┌──────────┴─────────────┐         ║
   ║                                   │         agent          │         ║
   ║                                   │ (custom or external    │         ║
   ║                                   │  BYO image)            │         ║
   ║                                   └──┬─────────────────┬───┘         ║
   ║                                      │ ADB             │ HTTPS       ║
   ║                                      │ tcp:adb-proxy   │ direct      ║
   ║                                      │       :5037     │ (NO_PROXY)  ║
   ║                                      ▼                 ▼             ║
   ║                            ┌──────────────────┐  ┌──────────────────┐║
   ║                            │   adb-proxy      │  │  app tls_proxy   │║
   ║                            │ filter L7;       │  │  (frontend)      │║
   ║                            │ blocks root:/su  │  └──────────────────┘║
   ║                            └─────────┬────────┘                      ║
   ╚══════════════════════════════════════╪═══════════════════════════════╝
                                          │ via bridge +
                                          │ host.docker.internal
                                          │ (set on the sidecar; NOT the agent)
                                          ▼
   ┌──────────────────┐         ┌─────────────────────┐         ┌────────────────────┐
   │ host adbd :5037  │         │  shared_net         │         │ <app>_private_net  │
   │ (native; or      │         │ - tls_proxy (also)  │         │  backend / mariadb │
   │  emulator-       │         │ - emulator-         │         │  / redis / …       │
   │  container       │         │   container         │         │ (agent: NO L3 path)│
   │  publishes)      │         │   (CONTAINER mode)  │         │                    │
   └──────────────────┘         └─────────────────────┘         └────────────────────┘
```

### Network membership

The agent reaches a peer only if both share a network. Each container is on exactly the networks listed below.

| Container                       | `agent_net` | `bridge` (default) | `shared_net` | `<app>_private_net` |
|---------------------------------|:-:|:-:|:-:|:-:|
| agent                           | ✓ |   |   |   |
| egress-proxy (Squid)            | ✓ | ✓ |   |   |
| adb-proxy                       | ✓ | ✓ |   |   |
| app `tls_proxy` (frontend)      | ✓ |   | ✓ | ✓ |
| app backend / DB / redis        |   |   |   | ✓ |
| `emulator-container` (CONTAINER mode) |   |   | ✓ |   |

Defined in `agent/firewall/proxy.py` (`AGENT_NET`, `EXTERNAL_BRIDGE`), `agent/runtime/container.py:_start_adb_proxy` (adb-proxy dual-homing), and each migrated app's `apps/<app>/docker-compose.yml` (`tls_proxy.networks: [shared_net, agent_net, private_net]`).

### Modes (single topology, conf swap inside the image)

`network_mode` is a required `RunnerConfig` field (`models/config.py`):

| Mode         | Squid allowlist                                              |
|--------------|--------------------------------------------------------------|
| `restricted` | Exact-FQDN allowlist (LLM APIs + apt/pip mirrors)            |
| `permissive` | Any public host (`http_access allow all CONNECT`)            |

Kernel routing (`agent_net` is `internal: true`) and rfc1918/loopback denies apply in **both** modes. Only the L7 hostname ACL toggles. The two policies are baked into the `cybench/agent-firewall:v0.1.0` image (`agent/firewall/image/squid_{restricted,permissive}.conf`); the entrypoint picks one via the `SQUID_MODE` env var (`agent/firewall/proxy.py:start`).

### Host Machine

- Runs `runner.py` and Workflow orchestration (`workflows/base.py`, `workflows/exploit.py`, `workflows/redteam.py`)
- Runs the host ADB server on `:5037`
- Runs the Android emulator as a host process (`emulator_backend: native`) or as `emulator-container` on `shared_net` (`emulator_backend: container`)
- Controls containers via `docker exec` (`agent/custom/backend/docker_ops.py`)

### Egress proxy / Squid sidecar

- Defined in `agent/firewall/proxy.py`; image source in `agent/firewall/image/` (`Dockerfile`, two confs, `allowed_domains.txt`, `entrypoint.sh`).
- Dual-homed: foot on `agent_net` (agent reaches it via `HTTPS_PROXY=http://egress-proxy:3128`), foot on Docker's default `bridge` (Squid's path to the internet).
- Image lifecycle: `_ensure_image` cascades local-cache → registry-pull (`cybench/agent-firewall:v0.1.0`) → in-tree build from `agent/firewall/image/`.
- `build_no_proxy()` composes `NO_PROXY` from `metadata.app_server` + sidecar aliases, so direct in-cluster traffic (kali → `tls_proxy`) bypasses Squid.

### ADB proxy sidecar

- `agent/runtime/container.py:_start_adb_proxy`. Image `python:3.11-slim`; the script `utils/adb_filter_proxy.py` is copied in.
- Dual-homed: foot on `agent_net` (the agent's only network), foot on Docker's default `bridge`. The sidecar — not the agent — gets `extra_hosts: host.docker.internal: host-gateway`, so the proxy hairpins out to the host's `adbd` on `:5037`.
- Filters ADB protocol messages and blocks dangerous operations (`root:`, `unroot:`, `backup:`, `su`, `run-as`, interactive shells); blocked patterns in `utils/adb_blocked_patterns.py`.
- The agent's `ADB_SERVER_SOCKET=tcp:adb-proxy:5037` is set in container env by `setup_agent_environment` (`agent/runtime/container.py:setup_agent_environment`).
- `su` is also disabled on the emulator via a bind mount over `/system/xbin/su` (`agent/runtime/container.py:_disable_emulator_root`).

### Agent container

- Joined to `[agent_net]` only — `agent/runtime/container.py:setup_agent_environment` passes `docker_networks=[AGENT_NET]`.
- No `extra_hosts` mapping, no host-gateway alias, no default route off `agent_net`.
- App codebase mounted at `/app/codebase` (default), or APK only at `/app/apk` when `no_codebase=true`.
- Tools execute via `ToolRuntime`. Restarted before evaluation begins (only `agent_exploit` dir is preserved).
- Two dispatch paths: `agent_mode: "custom"` runs the in-process Python loop; `agent_mode: "external"` delivers a `task.json` to a BYO Docker image satisfying the contract in [BRING_YOUR_OWN_AGENT.md](BRING_YOUR_OWN_AGENT.md). The external path is implemented in `harness/byo_agent.py:run_agent` (host-side SIGTERM/SIGKILL + artifact extraction) plus `agent/in_container/runner.py` (in-container entrypoint that streams events through a `BaseEventParser` subclass and writes `agent_run/result.json` + `conversation.jsonl` per turn). Auth tokens (listed in `agent/runtime/container.py:AUTH_ENV_PASSTHROUGH`) are forwarded uniformly to both.


## Agent Environment

### Information Available

**Mounted directories in Kali container:**
- `/app/codebase` - Full app source code (read-only copy). Mounted when `no_codebase=false` (the default), in both the agent container and the exploit-replay container. `no_codebase=true` is the only mode that guarantees no source anywhere the agent or replay reaches.
- `/app/apk` - One phase-specific APK. Mounted under `no_codebase=true` in both the agent container and the exploit-replay container so exploit.sh resolves the same path the agent had. (One APK only — never `apps/<app>/apk` wholesale.) Note that the agent always has ADB access to the running emulator and can pull the APK regardless of this mount.
- `/app/agent_exploit` - Empty directory for agent to write exploits
- `/app/agent_output` - Directory for exploit results (captured secrets, exfiltrated data). Volume-mounted so verify scripts on the host can read them.
- `/app/verify_files` (exploit mode only) - Contains evaluator verification logic

**From initial prompt (see `agent/custom/agent.py`):**
- Package name
- App server container name + port (if applicable)
- Username/password from `metadata.json` (if provided)
- Directory tree of codebase

**Mode differences:**
- Exploit mode: Agent receives vulnerability description + access to verify_files.
- Redteam two-phase: Agent searches for the vulnerability without disclosure; evaluation replays the generated exploit on original vs hardened APKs and scores via differential signals.
- Redteam probe-only (`probe_only=true`): single baseline replay against the app's `apps/<app>/apk/<app>.apk` (no patch / no verifier / no two-phase comparison); scoring is `signal`/`no_signal` based on app probes. See [REDTEAM.md#probe-only-mode](REDTEAM.md#probe-only-mode).

### Agent Capabilities

**Can do:**
- Create and execute files in the Kali sandbox
- Execute shell commands via ToolRuntime
- Interact with emulator via ADB through `adb-proxy` (as `shell` user)
- Reach the app's `tls_proxy` over HTTPS directly on `agent_net` (NO_PROXY bypasses Squid)
- Reach LLM provider APIs (and apt/pip mirrors) via Squid in `restricted` mode; any public host in `permissive` mode

**Cannot do (enforced by kernel routing + ADB proxy + emulator lockdown):**
- Reach the host directly (`host.docker.internal` is absent from `agent_net`; no route)
- Reach the host's ADB server, `emulator-container:5037`, or any peer on `shared_net` / private nets (no L3 path)
- Reach any FQDN not on the Squid allowlist in `restricted` mode (deny-by-default)
- `adb root`, `adb unroot`, `adb backup` (blocked ADB services)
- `su`, `run-as` (blocked shell commands; `su` binary also disabled via bind mount)
- Interactive shells via `adb shell sh`/`bash` (proxy-only restriction)
- Full blocked pattern list: `utils/adb_blocked_patterns.py`

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
- **Images**: `orchestrator/Dockerfile.orchestrator` (~5-6 GB, no emulator) + `orchestrator/Dockerfile.emulator` (~8-10 GB) + `infra/gke/Dockerfile.runner` (the per-job image that runs `runner.py`).
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

### Data Modeling (Pydantic + JSON Schema)
High-signal data objects use Pydantic `BaseModel` for strict typing; the BYO contract uses JSON Schema for cross-language interop:
- `RunnerConfig`: Orchestrates the run parameters; emitted as `schemas/runner_config.schema.json` for editor autocomplete.
- `ProviderResponse`: Standardizes LLM outputs across OpenAI and LiteLLM.
- `TokenUsage`: Tracks cost and tokens per request.
- `schemas/result.schema.json` / `schemas/task.schema.json`: The BYO-contract I/O — what an external agent reads from `/app/task.json` and writes to `/app/agent_run/result.json`.

### Cost provenance
Every run records `cost_source ∈ {agent, derived, derived_unpriced}` alongside `cost_usd` in `run_summary.metrics`:
- `agent`: the agent's CLI reported a number (claude-code emits `total_cost_usd`).
- `derived`: the harness computed cost from `token_totals × utils/token_pricing.json` (codex always lands here; claude-code on timeout).
- `derived_unpriced`: the model has no pricing row; `cost_usd` is `0` with an explicit "we don't know" marker.

Resolution lives in `utils/run_artifacts.py:_resolve_cost` and `utils/token_costs.py:derive_cost_from_totals`. Agent-reported values win whenever present (including a legitimate `$0`).

### Forensic Artifacts
Beyond standard text logs, the system captures:
- **System State**: Full Logcat dump from the Android emulator.
- **Repo State**: A `git_repro.patch` file containing any uncommitted changes at run-time.
- **Machine Trace**: A `conversation.jsonl` file that makes agent behavior trivially parseable for external analysis tools.
