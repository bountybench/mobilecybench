### Description
- [ ] **What does this PR do?**
- Adds `no_codebase` mode: when enabled, the agent receives only the built APK instead of the source codebase, enabling APK-only ablation experiments.

- [ ] **Why are these changes needed?/Changes made**
- We need to measure how much source code access contributes to agent exploit success. This PR adds the infrastructure to run experiments where the agent must reverse-engineer the APK rather than reading source directly.
- Changes:
  - Added `no_codebase` config field (default false) — mutually exclusive with codebase access
  - Refactored prompt templates: extracted `_build_resource_access()` and `_analysis_target()` helpers so resource sections are composed dynamically instead of hardcoded per workflow
  - Added `_setup_agent_apk()` in `agent_container.py` to copy and mount the APK into the container at `/app/apk/`
  - Threaded `no_codebase` through all 4 workflows, 3 agent types, and `setup_agent_environment()`
  - Fixed `get_directory_tree()` to target `/app/codebase` instead of the entire `/app/` working directory
  - Pre-installed `jadx` in `kali-security-tools.txt` so agents don't waste turns installing it at runtime

### Checklist (Review before submitting)
- [x] **Unit Tests:**
  - All 36 existing prompt tests pass.
  - Verified APK-only prompt contains no codebase references.
- [ ] **Documentation:**
  - Inline comments on `no_codebase` field explain mutual exclusivity.
- [ ] **Peer Review:**
  - The PR must be reviewed by at least one team member before merging.

### Linked Issues
- #897

### Additional Notes
- Most apps currently build with `-dontobfuscate` in their ProGuard rules, so jadx produces near-source-quality output. For the APK-only ablation to be meaningful, we should rebuild all APKs with obfuscation enabled.
- The kali Docker image needs to be rebuilt to pick up the `jadx` dependency.
