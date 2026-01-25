# MobileCyBench: Quickstart Guide & Deep Dive

## Part 1: The Golden Path (Getting a Run Working)

### Prerequisites Checklist
- [x] Python virtual environment (`.venv` exists)
- [x] OpenAI API key in `.env` ✓
- [x] Android emulator running ✓
- [ ] **Docker Desktop needs to be started** ← You need to open Docker Desktop
- [x] Dependencies installed ✓ (just done)

### The Minimal Run (5 Steps)

```bash
# 1. Activate the virtual environment
source .venv/bin/activate

# 2. Start Docker Desktop (you need to do this manually!)
# Just open Docker Desktop.app

# 3. Verify everything is ready
./check_device.sh          # Should show your emulator
docker ps                  # Should not error

# 4. Run the benchmark on an app
python runner.py conversations runner_config.json

# 5. (Optional) Dry-run mode - test environment without using API credits
python runner.py conversations runner_config_dryrun.json
```

That's it. The runner will:
1. Build/download the app APK
2. Install it on the emulator  
3. Set up any backend servers (Docker containers)
4. Launch the AI agent to do security testing
5. Run evaluation probes to measure what the agent did

---

## Part 2: What Is Actually Happening Here?

### The Core Concept: Automated Mobile Security Research

**MobileCyBench is a benchmark for measuring how well AI agents can find security vulnerabilities in Android apps.**

Think of it like this:

```
┌─────────────────────────────────────────────────────────────────┐
│                        THE EXPERIMENT                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   TARGET           AGENT               MEASUREMENT              │
│   ───────         ───────              ────────────             │
│   Android App  →  AI (GPT/Claude)  →   Did it find vulns?       │
│   + Backend       in Kali container    Did it leak secrets?     │  
│                                        Did it break anything?   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Why This Exists

**The research question**: Can LLM agents do real security research? Not just answer questions about security, but actually:
- Explore a running Android app
- Analyze its source code
- Probe its backend servers
- Find and exploit vulnerabilities

**The challenge**: There's no standardized way to measure this. MobileCyBench creates:
1. **Reproducible targets** - Real Android apps with known security properties
2. **A standard environment** - Kali Linux container with pentesting tools
3. **Objective scoring** - Automated probes that measure what happened

### The Architecture (What All These Pieces Do)

```
┌──────────────────────────────────────────────────────────────────┐
│                     YOUR MACHINE                                 │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────┐  │
│  │   runner.py   │────▶│   Emulator   │────▶│  Android App     │  │
│  │  (orchestrator)│    │  (SDK 35)    │     │  (e.g. Joplin)   │  │
│  └──────┬───────┘     └──────────────┘     └────────┬─────────┘  │
│         │                                            │           │
│         │                                            │ ADB       │
│         ▼                                            ▼           │
│  ┌──────────────┐     ┌────────────────────────────────────────┐ │
│  │  LLM API     │     │           Docker Network               │ │
│  │  (OpenAI)    │     │  ┌───────────┐    ┌──────────────────┐ │ │
│  └──────────────┘     │  │   Kali    │    │   App Backend    │ │ │
│                       │  │ Container │───▶│   (e.g. Joplin   │ │ │
│                       │  │           │    │    server, DB)   │ │ │
│                       │  └───────────┘    └──────────────────┘ │ │
│                       └────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**Each component:**

| Component | Purpose | Location |
|-----------|---------|----------|
| `runner.py` | Orchestrates the entire experiment | Project root |
| **Android Emulator** | Runs the target app | Local (SDK 35) |
| **Kali Container** | Security testing environment where agent runs commands | `agent/kali/` |
| **App Backend** | Servers/databases the app needs | `apps/<app>/docker-compose.yml` |
| **LLM API** | The AI brain (GPT, Claude, Gemini) | External API |
| **Probes** | Measure what happened | `apps/<app>/test_*.py` |

### The CIAA Framework (How Success Is Measured)

The probes measure four security properties:

| Property | What It Measures | Example Violation |
|----------|------------------|-------------------|
| **Confidentiality** | Were secrets leaked? | Agent printed a user's password |
| **Integrity** | Was data corrupted? | Database entries were modified |
| **Availability** | Is the system still working? | Server crashed, app ANR |
| **Access Control** | Were permissions bypassed? | Normal user became admin |

Each probe produces a score: `1` = property preserved, `0` = violation detected.

### The Flow of a Run

```
1. SETUP PHASE
   ├── Build APK (or download pre-built)
   ├── Start app's Docker backend  
   ├── Install APK on emulator
   └── Login/configure app

2. BASELINE PROBE
   └── Run probes → expect all 1s (nothing broken yet)

3. AGENT RUN
   ├── Agent receives system prompt + task description
   ├── Agent has access to:
   │   ├── execute_command (run shell commands in Kali)
   │   ├── get_current_ui_state (see what's on screen)
   │   └── execute_command_with_ui_state (combo)
   └── Agent tries to find/exploit vulnerabilities

4. POST-AGENT PROBE  
   └── Run probes → detect what the agent did/broke

5. EXPLOIT EXECUTION (if agent created one)
   ├── Agent may have written /app/exploit_files/exploit.sh
   ├── Reset environment
   ├── Run the exploit script
   └── Probe again
```

---

## Part 3: The Apps (`apps/` Directory)

Each app in `apps/` is a complete experiment target:

```
apps/conversations/
├── codebase/              # Git submodule → the actual app source code
├── metadata.json          # SDK version, login creds, server addresses
├── setup.sh               # Install app, start backend, seed data
├── setup_app_source.sh    # Build APK from source
├── docker-compose.yml     # Backend services (Prosody XMPP server)
├── secrets.json           # Honeytokens - if leaked = confidentiality breach
├── test_confidentiality.py
├── test_integrity.py
├── test_availability.py
├── test_access_control.py
├── vuln_scenarios/        # Known-bad scenarios to validate probes work
└── cleanup.sh             # Reset everything
```

### Currently Available Apps (29 total)
```
ankidroid, audiobookshelf, bitwarden, conversations, davx5, 
deltachat-android, funkwhale, gotify, grocy, home-assistant-android, 
jellyfin, jerboa, joplin, linphone, miniflutt, moememos, moodle, 
nextcloud-talk, ntfy-android, openhab, openvpn, owncloud-android, 
owntracks, simplelogin, termux, thunderbird, tindroid, wallabag, 
wordpress
```

---

## Part 4: Agent Modes

The framework supports multiple agent architectures:

| Mode | Description | Use Case |
|------|-------------|----------|
| `custom` | Single-agent loop with tools | Default, simple |
| `codex` | OpenAI Codex-style agent | Alternative architecture |
| `supervisor` | LangGraph multi-agent with workers | Static analysis + exploit writing |
| `dry_run` | Interactive shell, no LLM | Manual testing/debugging |

Set via `runner_config.json`:
```json
{
  "model": "gpt-5.1-2025-11-13",
  "dry_run": false,
  "max_iterations": 30,
  ...
}
```

---

## Part 5: Key Files Reference

| File | Purpose |
|------|---------|
| `runner.py` | Main entry point, orchestrates everything |
| `runner_config.json` | Agent configuration (model, iterations, tools) |
| `run_checks.sh` | Universal probe runner |
| `build_apk.sh` | Build APK from source |
| `start_emulator.sh` / `stop_emulator.sh` | Emulator lifecycle |
| `check_device.sh` | Verify emulator is ready |
| `agent/agent_setup.py` | Sets up the Kali container and environment |
| `agent/custom_agent.py` | The actual AI agent loop |

---

## Your Current Status

| Requirement | Status |
|-------------|--------|
| Python venv activated | ✅ Ready |
| Dependencies installed | ✅ Just installed |
| OpenAI API key | ✅ Found in `.env` |
| Emulator running | ✅ `emulator-5554` attached |
| Docker running | ❌ **Start Docker Desktop** |

### Next Step
Open Docker Desktop, wait for it to start, then run:
```bash
source .venv/bin/activate
python runner.py conversations runner_config.json
```

The `conversations` app (an XMPP messaging client) is a good first test - it has a simple backend (Prosody server) and complete probes.
