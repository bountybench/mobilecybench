# Synthetic Vulnerability Support in Redteam Pipeline — Design & Plan

Status: implementation snapshot on branch `plan/synthetic-redteam-support` off `upstream/main` (`b0feb056c9`). Core redteam plumbing is implemented. Remaining Phase 1 work is local smoke-test execution plus `termux/vuln_0` malicious-APK shape cleanup.

## 1. Goals

1. Make the redteam workflow accept synthetic vulnerability bundles at `apps/<app>/synthetic_vulnerabilities/<vuln_id>/` with no workflow-level branching on bundle kind.
2. Require every synthetic bundle to declare an `attacker_model` (`malicious_app` or `remote_attacker`) and resolve it from metadata the same way zeroday tasks do.
3. Validate Phase 1 locally with one synthetic task per attacker model.
4. Preserve SOLID/DRY boundaries: attacker-model dispatch stays in `AttackerModelOps`; bundle layout/patch direction stays in `TaskBundle`; `RedTeamWorkflow` owns the phase loop and scoring only.

## 2. Non-goals

- CI changes in `run_ci_local.sh`, `.github/workflows/ci.yml`, or `scripts/synthetic_task_common.sh`.
- Collapsing `workflows/exploit.py` into redteam.
- Reward-hack CI gates, held-out split, or pass@k policy.
- Changing zeroday task layout or semantics.
- Converting every `malicious_app` synthetic bundle from legacy `exploit.sh` / `helper_apk/` shape to canonical `exploit_apk/` in this PR.
- Replacing stub `remote_attacker` probes with real checks in this PR.

## 3. Current status

### 3.1 Implemented now

| Area | Location | Status |
|---|---|---|
| Bundle abstraction | `evaluation/task_bundle.py`, `tests/evaluation/test_task_bundle.py` | Implemented. `SyntheticBundle`, `ZerodayBundle`, strict XOR `resolve_bundle`, path/patch/build/artifact logic covered by tests. |
| Redteam bundle delegation | `workflows/redteam.py:267-696` | Implemented. Workflow resolves `self._bundle`, validates bundle patch + verifier + metadata, builds via bundle, and evaluates phases via bundle hooks. |
| Metadata-authoritative attacker model | `models/config.py:20-126`, `runner.py:190-303` | Implemented. `attacker_model` is optional in config, required in task metadata, and reconciled before workflow creation. |
| Gold source resolution | `utils/exploit_source.py:138-184` | Implemented. Redteam gold source uses `resolve_bundle()` for both synthetic and zeroday. |
| Replay normalization | `utils/exploit_source.py:41-135`, `runner.py:264-303` | Implemented. Redteam replay supports either `task` or `synthetic_vuln_id`, and clears stale opposite selectors so TaskBundle XOR holds. |
| Live-agent Phase 1 source parity | `workflows/redteam.py:352-376`, `agent/agent_container.py:47-66`, `agent/agent_container.py:324-433` | Implemented. Redteam installs the Phase 1 APK and passes a `post_checkout_hook` so the agent snapshot matches Phase 1 source state for synthetic bundles. |
| Synthetic metadata schema | `synthetic_vuln_metadata_schema.json:11-15,72-79`, `tests/test_synthetic_vuln_metadata.py:14-91` | Implemented. `attacker_model` is required and validated across all synthetic bundles. |
| Zeroday schema cleanup | `zero_day_task_bundle_schema.json` | Implemented. Duplicate `attacker_model` property removed. |
| Synthetic metadata backfill | `apps/*/synthetic_vulnerabilities/*/metadata.json` | Implemented. All 25 in-tree synthetic metadata files now declare `attacker_model`. |
| Remote-attacker probe stubs | `apps/conversations/remote_attacker/test_*.py` | Implemented. Enough to unblock pipeline validation and smoke tests. |

### 3.2 Targeted regression checks already passing

Command run locally:

```bash
python3 -m pytest \
  tests/agent/test_agent_container.py \
  tests/utils/test_exploit_source.py \
  tests/test_synthetic_vuln_metadata.py \
  tests/evaluation/test_task_bundle.py \
  tests/workflows/test_redteam_evaluation.py \
  tests/test_runner.py \
  tests/workflows/test_exploit_codebase.py
```

Result: `77 passed`

Key coverage added by this branch:

- `tests/workflows/test_redteam_evaluation.py:475-621` checks Phase 1 APK wiring, `post_checkout_hook` forwarding, and missing-patch validation.
- `tests/agent/test_agent_container.py:161-243` checks `post_checkout_hook` applies to the staged copy, not the host codebase.
- `tests/test_runner.py:396-485` checks replay normalization for zeroday and synthetic redteam selectors.
- `tests/utils/test_exploit_source.py:27-68` checks synthetic redteam replay source resolution and stale-selector cleanup.

### 3.3 Remaining blockers for Phase 1 smoke tests

| Item | Status | Notes |
|---|---|---|
| `conversations/vuln_0` remote-attacker smoke test | Ready enough | Bundle metadata updated; verifier exists; probe stubs exist. This is the clean first `remote_attacker` candidate. |
| `termux/vuln_0` malicious-app smoke test | Not ready yet | Still in legacy `helper_apk/` + `exploit.sh` shape. Must convert to canonical `exploit_apk/` shape before redteam malicious-APK gold run can succeed. |
| Local gold-run execution logs | Not done yet | No checked-in evidence yet that `python3 runner.py conversations` or `python3 runner.py termux` has produced `score=1` under redteam synthetic gold-run mode. |

### 3.4 Preconditions re-checked

| Requirement | Status | Notes |
|---|---|---|
| Synthetic `prepare_app.sh` lives in synthetic bundle dir | ✅ | Bundle layout unchanged. |
| Synthetic `verify_files/verify_exploit.sh` lives in synthetic bundle dir | ✅ | Used via `self._bundle.task_dir`. |
| `remote_attacker` probe dir exists for smoke-test candidate | ✅ | `apps/conversations/remote_attacker/` now exists with 4 stub probes. |
| `generic_probe_config.json` exists for malicious-app smoke-test candidate | ✅ | `termux` still qualifies. |
| All synthetic bundles declare `attacker_model` | ✅ | Backfilled across all 25 metadata files. |
| `termux/vuln_0` already uses canonical `exploit_apk/` layout | ❌ | Still legacy `helper_apk/` plus `exploit.sh`. |

## 4. Current architecture

### 4.1 `TaskBundle`

Implemented interface:

```python
class TaskBundle(Protocol):
    @property
    def kind(self) -> BundleKind: ...

    @property
    def task_dir(self) -> Path: ...

    @property
    def exploit_dir(self) -> Path: ...

    @property
    def patch(self) -> Path: ...

    def phase1_apk(self) -> Path: ...
    def phase2_apk(self) -> Path: ...
    def prepare_phase1_codebase(self, codebase_dir: Path) -> None: ...
    def prepare_phase2_codebase(self, codebase_dir: Path) -> None: ...
    def build_apks(self, app_name: str, project_root: Path, *, timeout: int) -> None: ...
    def validate_build_artifacts(self, app_dir: Path) -> None: ...
```

Concrete behavior:

- `SyntheticBundle`: Phase 1 is vulnerable APK plus `vulnerability.patch`; Phase 2 is clean APK.
- `ZerodayBundle`: Phase 1 is baseline APK; Phase 2 is hardened APK plus `fix.patch`.
- `resolve_bundle()` enforces strict XOR between `config.task` and `config.synthetic_vuln_id`.

### 4.2 `RedTeamWorkflow`

Current flow:

1. Resolve `self._bundle` in `__init__`.
2. Resolve `attacker_model` from metadata in `runner.py`, not from config defaults.
3. Validate bundle patch, verifier, metadata, and probe prerequisites in `validate_arguments()`.
4. Install the Phase 1 APK during runtime setup.
5. Pass `post_checkout_hook=self._bundle.prepare_phase1_codebase` into `setup_agent_environment()` so synthetic live-agent runs see the vulnerable Phase 1 source snapshot.
6. Run Phase 1 and Phase 2 via `self._bundle.prepare_phase{1,2}_codebase()` and `self._bundle.phase{1,2}_apk()`.

Important note:

- `Workflow.cleanup()` still owns final host-codebase restore. The extra `git checkout -- .` in `evaluate()` remains only as a between-phase hygiene step matching previous redteam behavior.

### 4.3 Gold and replay source resolution

- `resolve_gold_source()` now resolves redteam exploit files through `TaskBundle`, so synthetic and zeroday share one path.
- `resolve_replay_source()` now supports synthetic redteam replays by reading `synthetic_vuln_id` from `run_summary.json`.
- Legacy zeroday replays that still carry a stale synthetic default are normalized to `task` only.

## 5. Recommended Phase 1 smoke-test pair

| Task | Attacker model | Why this is still the best pair |
|---|---|---|
| `conversations/vuln_0` | `remote_attacker` | Pure server-side exploit path, simple verifier, low UI churn, probe stubs already added. |
| `termux/vuln_0` | `malicious_app` | Clear model fit, `generic_probe_config.json` exists, helper APK source already exists and can be converted to canonical shape. |

### 5.1 `termux/vuln_0` cleanup required before smoke test

1. Rename `apps/termux/synthetic_vulnerabilities/vuln_0/exploit_files/helper_apk/` to `exploit_apk/`.
2. Delete `apps/termux/synthetic_vulnerabilities/vuln_0/exploit_files/exploit.sh`.
3. Delete `apps/termux/synthetic_vulnerabilities/vuln_0/exploit_files/exploit_apk/build.sh`.
4. Ensure the APK still builds when `stage_exploit_source()` overlays canonical `build_exploit_apk.sh`.

### 5.2 `conversations/vuln_0` caveat

- `apps/conversations/remote_attacker/test_*.py` are stub probes returning `triggered=false`.
- That is acceptable for Phase 1 smoke testing because scoring can still hinge on `verifier_diff`.
- It is not sufficient as the long-term probe story.

## 6. Suggested verification commands

Build APKs once per app:

```bash
./build_apk.sh conversations
./build_apk.sh conversations --vuln synthetic_vulnerabilities/vuln_0
./build_apk.sh termux
./build_apk.sh termux --vuln synthetic_vulnerabilities/vuln_0
```

Run focused regression tests:

```bash
python3 -m pytest \
  tests/agent/test_agent_container.py \
  tests/utils/test_exploit_source.py \
  tests/test_synthetic_vuln_metadata.py \
  tests/evaluation/test_task_bundle.py \
  tests/workflows/test_redteam_evaluation.py \
  tests/test_runner.py \
  tests/workflows/test_exploit_codebase.py
```

Remote-attacker gold run example:

```json
{
  "workflow": "redteam",
  "build_type": "skip-apk",
  "synthetic_vuln_id": "vuln_0",
  "gold_run": true,
  "server_access": true,
  "adb_access": "full",
  "model": "gpt-5.2",
  "agent_image": "cybench/mobilecybench:latest",
  "max_iterations": 30,
  "max_model_response_tokens": 8192,
  "screenshot_mode": false,
  "dry_run": false
}
```

Then:

```bash
python3 runner.py conversations
```

Expected result:

- `apps/conversations/redteam_scores.json`
- `status="verified"`
- `score=1`

Malicious-app gold run should follow the same pattern for `termux` after the exploit-shape cleanup above.

## 7. Files implemented in this branch

### Created

- `evaluation/task_bundle.py`
- `tests/evaluation/test_task_bundle.py`
- `apps/conversations/remote_attacker/test_access_control.py`
- `apps/conversations/remote_attacker/test_availability.py`
- `apps/conversations/remote_attacker/test_confidentiality.py`
- `apps/conversations/remote_attacker/test_integrity.py`
- `tests/utils/test_exploit_source.py`

### Modified

- `workflows/redteam.py`
- `runner.py`
- `models/config.py`
- `utils/exploit_source.py`
- `agent/agent_container.py`
- `synthetic_vuln_metadata_schema.json`
- `tests/test_synthetic_vuln_metadata.py`
- `zero_day_task_bundle_schema.json`
- `tests/workflows/test_redteam_evaluation.py`
- `tests/test_runner.py`
- `tests/agent/test_agent_container.py`
- all 25 `apps/*/synthetic_vulnerabilities/*/metadata.json`

## 8. Risks and notes

| Risk | Current handling |
|---|---|
| `termux/vuln_0` helper APK assumes shell-side orchestration in legacy `exploit.sh` | Still open. This is the main blocker for the malicious-app smoke test. |
| `conversations` probe stubs never trigger | Accepted for Phase 1 smoke-test scope; verifier remains the authoritative signal. |
| Some backfilled attacker-model labels are provisional (`davx5/vuln_0`, `funkwhale/vuln_0`, `jellyfin/vuln_0`) | Accepted to make schema/runtime consistent. Revisit when those tasks are actually migrated into redteam coverage. |
| Future bundle patches that add files may need stronger restore semantics than plain `git checkout -- .` | Not a current blocker for active bundle patches; revisit if a synthetic or zeroday patch starts creating tracked files from `/dev/null`. |

## 9. Acceptance gate

Phase 1 is done when:

1. The focused regression suite in §6 passes.
2. `python3 runner.py conversations` with `workflow=redteam`, `synthetic_vuln_id=vuln_0`, `gold_run=true` produces `score=1`.
3. `python3 runner.py termux` with the same redteam synthetic gold-run setup produces `score=1` after the malicious-APK shape cleanup.
4. Existing zeroday redteam gold runs still pass.
5. Lint and type checks pass.

## 10. Follow-up PRs

1. CI unification in `scripts/synthetic_task_common.sh`, `ci.yml`, and `run_ci_local.sh`.
2. Convert remaining `malicious_app` synthetic bundles from legacy `exploit.sh` / `helper_apk/` shape to canonical `exploit_apk/` shape.
3. Replace `conversations` stub probes and author real `apps/<app>/remote_attacker/test_*.py` probes for other remote-attacker tasks.
4. Revisit provisional attacker-model labels for tasks currently marked `needs review` or effectively `drop` from a benchmark-policy perspective.
5. Demote or collapse `workflows/exploit.py` once redteam fully subsumes synthetic evaluation.
6. Reward-hack CI gate, held-out split, and pass@k work.
