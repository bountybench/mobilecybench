# Synthetic Vulnerability Support in Redteam Pipeline — Design & Plan

Status: DRAFT v2 (scope-tightened to redteam changes only). Branch `plan/synthetic-redteam-support` off `upstream/main` (`b0feb056c9`).

## 1. Goals

1. Make the **redteam workflow** accept synthetic vulnerability bundles (`apps/<app>/synthetic_vulnerabilities/<vuln_id>/`) with no loss of generality vs the existing zeroday path.
2. Require every synthetic bundle to declare an `attacker_model` (`malicious_app` or `remote_attacker`), same dispatch rules as zeroday.
3. Validate via `gold_run: true` locally against one task per attacker model. No live-agent runs required for Phase 1 acceptance.
4. Hold the line on SOLID/DRY: one strategy object per attacker model (unchanged), one task-bundle abstraction per bundle type (new), zero branching on bundle kind in workflow code.

## 2. Non-goals (explicitly deferred)

- **All CI changes.** `run_ci_local.sh`, `.github/workflows/ci.yml`, `scripts/synthetic_task_common.sh`. A separate PR (coordinate with #972) handles CI.
- **Collapsing `workflows/exploit.py` into redteam.** Stays live as authoring harness.
- **Reward-hack CI gate, held-out split, pass@k.** Benchmark polish, separate designs.
- **Changing the zeroday task layout or semantics.**
- **Backfilling `attacker_model` on all 26 synthetic vulns.** Only the two chosen for local smoke test get migrated in this PR.

## 3. Verified current state

### 3.1 What's already right (reuse verbatim)

| Asset | Location | Why it's right |
|---|---|---|
| `AttackerModelOps` Protocol + `MaliciousAppOps` / `RemoteAttackerOps` | `workflows/redteam.py:39-254` | Strategy pattern, OCP-clean. Pipeline is already model-agnostic. |
| Evaluate loop + 3-signal scoring | `workflows/redteam.py:527-688`, `evaluation/scoring.py:compute_redteam_score` | Untouched. |
| Canonical APK build script injection | `utils/exploit_source.py:stage_exploit_source:172-181` | Already overlays `templates/malicious_app/build_exploit_apk.sh` when `is_apk_exploit=True`. |
| `build_apk.sh --vuln synthetic_vulnerabilities/vuln_0` | `build_apk.sh:195-233` | Already resolves synthetic dirs. No build-script change needed. |
| `apply_synthetic_patch` | `utils/synthetic_utils.py:30-58` | Handles `git apply <path>` idempotently; reusable for Phase 1 codebase prep. |
| Agent container verifier gate | `agent/agent_container.py:958` (`vuln_id=vuln_id if workflow=="exploit" else None`) | Redteam agent never sees `verify_files/`. Untouched. |
| Bash runtime attacker-model dispatch | `scripts/task_runtime_common.sh:213-226` | Already dispatches `malicious_app` → `replay_malicious_apk`, else → `run_exploit_container.sh`. Out of scope for this PR, but the design is correct. |

### 3.2 What must change (confirmed by file+line)

| Site | Problem | Fix direction |
|---|---|---|
| `workflows/redteam.py:272-301` | `_report_dir`, `_task_dir`, `_task_fix_patch`, `_hardened_apk`, `_original_apk`, `_validate_hardened_artifact`, `_build_apks_from_source` hardcode the zeroday layout. | Move to `TaskBundle`. |
| `workflows/redteam.py:596-616` (patch apply/revert between phases) | Assumes `fix.patch` (vuln→patched direction). | Delegate to bundle's phase hooks. |
| `utils/exploit_source.py:124-148` (`resolve_gold_source`) | Branches `workflow==redteam → zeroday path`. | Branch on bundle kind via same `TaskBundle` resolver. |
| `runner.py:190-214` (`_load_task_attacker_model`) | Reads `zerodays/reports/<app>/<task>/task/metadata.json` only. | Read from whichever bundle the config selects. |
| `runner.py:287-297` | Only fires the metadata-override path when `config.task` is set. | Also fire for `config.synthetic_vuln_id` under `workflow=="redteam"`. |
| `models/config.py:21` (`attacker_model: Literal[...] = "malicious_app"`) | Silent default; can disagree with task metadata on a mistyped config. | `Optional[Literal[...]] = None`. Metadata is the source of truth. |
| `models/config.py:92-98` (`validate_task`) | Requires `task` for redteam. | Accept `task` XOR `synthetic_vuln_id` for redteam. |
| `synthetic_vuln_metadata_schema.json` | No `attacker_model` field. | Add required enum `["malicious_app","remote_attacker"]`. |
| `tests/test_synthetic_vuln_metadata.py:14-21` | `REQUIRED_FIELDS` incomplete. | Add `attacker_model`. |
| `zero_day_task_bundle_schema.json:22-31` | Duplicate `attacker_model` property (second silently wins). | Housekeeping: delete the first. |

### 3.3 Verified preconditions for local gold-run testing

| Requirement | Status |
|---|---|
| Synthetic `prepare_app.sh` lives at `apps/<app>/synthetic_vulnerabilities/<vuln>/prepare_app.sh` | ✅ |
| Synthetic `verify_files/verify_exploit.sh` at the same level | ✅ |
| Probe scripts (`test_*.py`) are app-level, shared with zeroday | ✅ |
| `remote_attacker` probe dir `apps/<app>/remote_attacker/` exists for smoke-test candidate | ❌ — only `apps/audiobookshelf/remote_attacker/` exists. Must create stubs for `conversations/remote_attacker/` in this PR. |
| `generic_probe_config.json` exists for the chosen `malicious_app` app | ✅ for `termux` and `openhab` only |
| Termux's `helper_apk/` already has `AndroidManifest.xml` + `src/` + `build.sh` | ✅ (renameable to `exploit_apk/`) |
| Conversations has an `exploit.sh` gold + `verify_exploit.sh` | ✅ |

## 4. Target architecture

### 4.1 Core abstraction — `TaskBundle`

New module, single file, pure functions + frozen dataclass. Zero runtime dependencies on workflow/runner internals.

```
evaluation/task_bundle.py          # NEW
tests/evaluation/test_task_bundle.py  # NEW
```

```python
# evaluation/task_bundle.py (sketch)

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

BundleKind = Literal["synthetic", "zeroday"]


class TaskBundle(Protocol):
    """Task file layout + phase-prep contract for RedTeamWorkflow.

    Workflow never asks 'synthetic or zeroday?'. Dispatch lives here.
    """
    kind: BundleKind
    task_dir: Path          # metadata.json, verify_files/, prepare_app.sh
    exploit_dir: Path       # exploit_files/ (for gold source resolution)

    def phase1_apk(self) -> Path: ...    # vulnerable APK (host-relative)
    def phase2_apk(self) -> Path: ...    # patched APK (host-relative)
    def prepare_phase1_codebase(self, codebase_dir: Path) -> None: ...
    def prepare_phase2_codebase(self, codebase_dir: Path) -> None: ...
    def build_apks(self, app_name: str, project_root: Path, *, timeout: int) -> None: ...
    def validate_build_artifacts(self) -> None: ...   # raises on missing APKs
```

**Concrete types:**

```python
@dataclass(frozen=True)
class SyntheticBundle:
    kind = "synthetic"
    app_dir: Path
    vuln_id: str

    @property
    def task_dir(self) -> Path:
        return self.app_dir / "synthetic_vulnerabilities" / self.vuln_id

    @property
    def exploit_dir(self) -> Path:
        return self.task_dir / "exploit_files"

    @property
    def _patch(self) -> Path:
        return self.task_dir / "vulnerability.patch"

    def phase1_apk(self) -> Path:
        return Path("apk") / self.vuln_id / f"{self.app_dir.name}.apk"

    def phase2_apk(self) -> Path:
        return Path("apk") / f"{self.app_dir.name}.apk"

    def prepare_phase1_codebase(self, codebase_dir):
        # clean → vulnerable
        _git_restore(codebase_dir)
        _git_apply(codebase_dir, self._patch)

    def prepare_phase2_codebase(self, codebase_dir):
        # vulnerable → clean (revert patch)
        _git_restore(codebase_dir)

    def build_apks(self, app_name, project_root, *, timeout):
        _run_build(project_root, [app_name], timeout)
        _run_build(project_root, [app_name, "--vuln", f"synthetic_vulnerabilities/{self.vuln_id}"], timeout)

    def validate_build_artifacts(self):
        for apk in (self.app_dir / self.phase1_apk(), self.app_dir / self.phase2_apk()):
            if not apk.exists():
                raise FileNotFoundError(apk)


@dataclass(frozen=True)
class ZerodayBundle:
    kind = "zeroday"
    project_root: Path
    app_name: str
    task: str

    @property
    def _report_dir(self) -> Path:
        return self.project_root / "zerodays" / "reports" / self.app_name / self.task

    @property
    def task_dir(self) -> Path:
        return self._report_dir / "task"

    @property
    def exploit_dir(self) -> Path:
        return self.task_dir / "exploit_files"

    @property
    def _patch(self) -> Path:
        return self.task_dir / "fix.patch"

    @property
    def _hardened_apk(self) -> Path:
        return self._report_dir / "artifacts" / "hardened_apk" / f"{self.app_name}.apk"

    def phase1_apk(self) -> Path:
        return Path("apk") / f"{self.app_name}.apk"

    def phase2_apk(self) -> Path:
        # Absolute path — lives outside app_dir/apk/
        return self._hardened_apk

    def prepare_phase1_codebase(self, codebase_dir):
        # Baseline IS vulnerable — no patch needed.
        _git_restore(codebase_dir)

    def prepare_phase2_codebase(self, codebase_dir):
        # vulnerable → patched
        _git_restore(codebase_dir)
        _git_apply(codebase_dir, self._patch)

    def build_apks(self, app_name, project_root, *, timeout):
        _run_build(project_root, [app_name], timeout)
        _run_build(project_root, [app_name, "--hardened-patch", str(self._patch)], timeout)

    def validate_build_artifacts(self):
        if not self._hardened_apk.exists():
            raise FileNotFoundError(self._hardened_apk)


# Resolvers — single dispatch point.

def resolve_bundle(config, project_root: Path, app_name: str) -> TaskBundle:
    if config.synthetic_vuln_id and not config.task:
        return SyntheticBundle(
            app_dir=project_root / "apps" / app_name,
            vuln_id=config.synthetic_vuln_id,
        )
    if config.task and not config.synthetic_vuln_id:
        return ZerodayBundle(
            project_root=project_root,
            app_name=app_name,
            task=config.task,
        )
    raise ValueError(
        "RedTeamWorkflow requires exactly one of config.task (zeroday) "
        "or config.synthetic_vuln_id (synthetic)."
    )
```

**Design notes:**
- `phase{1,2}_apk` return types are mixed (host-relative for synthetic/zeroday-phase1, absolute for zeroday-phase2). Workflow normalizes via `app_dir / apk_path if not apk_path.is_absolute() else apk_path`. One helper.
- `validate_build_artifacts` collapses `_validate_hardened_artifact` + the clean/vuln APK checks in `workflows/exploit.py:86-96`. One responsibility per bundle.
- Patch helpers (`_git_restore`, `_git_apply`, `_run_build`) live in the same module, private. Single source of truth for patch ops.

### 4.2 Redteam workflow diff (subtractive)

```python
# workflows/redteam.py

class RedTeamWorkflow(Workflow):
    def __init__(self, config, app_name, project_root):
        super().__init__(config, app_name, project_root)
        from evaluation.task_bundle import resolve_bundle
        self._bundle = resolve_bundle(config, project_root, app_name)
        self._attacker_model = config.attacker_model  # resolved from metadata by runner
        self._ops = _OPS[self._attacker_model]()
        self._probe_config = {"generic_probe_applicability": {}}

    # DELETE: _report_dir, _task_dir, _task_fix_patch, _artifacts_dir,
    #         _hardened_apk, _original_apk,
    #         _validate_hardened_artifact, _build_apks_from_source

    # REPLACE property access:
    # self._task_dir           → self._bundle.task_dir
    # self._task_fix_patch     → (patch ops moved into bundle)
    # self._hardened_apk       → self._bundle.app_dir / self._bundle.phase2_apk()   (or absolute)
    # self._original_apk       → self._bundle.phase1_apk()
```

Evaluate loop becomes direction-neutral:

```python
# workflows/redteam.py:evaluate()

# Phase 1
codebase_dir = self.app_dir / "codebase"
self._bundle.prepare_phase1_codebase(codebase_dir)
phase1_result = self._ops.run_phase(self, replays_dir / "phase1_original", **self._ops.get_phase_kwargs(
    agent_exploit_dir, self._resolve_apk(self._bundle.phase1_apk()), needs_flags=..., needs_ssrf=...,
))

# Between phases
self._bundle.prepare_phase2_codebase(codebase_dir)

# Phase 2
phase2_result = self._ops.run_phase(self, replays_dir / "phase2_patched", **self._ops.get_phase_kwargs(
    agent_exploit_dir, self._resolve_apk(self._bundle.phase2_apk()), needs_flags=..., needs_ssrf=...,
))

# Final restore
self._bundle.prepare_phase1_codebase(codebase_dir)   # no-op for zeroday, revert patch for synthetic... wait, should restore CLEAN
```

> **Correction to self:** post-evaluation cleanup should leave the codebase clean regardless of bundle. `Workflow.cleanup()` already calls `git_restore_clean(codebase_dir)` at `workflows/base.py:646-654` — do not duplicate. Remove any stray `git checkout` at the end of `evaluate()`.

### 4.3 Gold source resolution

```python
# utils/exploit_source.py:resolve_gold_source — replace body with:

def resolve_gold_source(*, workflow, app_name, task, vuln_id, project_root, is_apk_exploit):
    if workflow != "redteam":
        # existing exploit-mode path, unchanged
        ...
    from evaluation.task_bundle import resolve_bundle
    from models.config import RunnerConfig
    fake_config = RunnerConfig.model_construct(
        workflow="redteam", task=task, synthetic_vuln_id=vuln_id, ...  # minimal
    )
    bundle = resolve_bundle(fake_config, project_root, app_name)
    source_dir = bundle.exploit_dir
    if not source_dir.is_dir():
        raise ExploitSourceError(f"Gold exploit directory not found: {source_dir}")
    _validate_exploit_shape(source_dir, is_apk_exploit=is_apk_exploit)
    return ExploitSource(kind="gold", source_dir=source_dir)
```

Alternative (cleaner): lift the bundle resolver call into `runner.py` and pass `source_dir` in. Keeps `resolve_gold_source` dumb. Pick whichever the reviewer prefers; both equivalent.

### 4.4 Runner changes

```python
# runner.py:_load_task_attacker_model — generalize

def _load_task_attacker_model(project_root, app_name, config) -> str:
    from evaluation.task_bundle import resolve_bundle
    bundle = resolve_bundle(config, project_root, app_name)
    meta = json.loads((bundle.task_dir / "metadata.json").read_text())
    am = meta.get("attacker_model")
    if am not in {"malicious_app", "remote_attacker"}:
        raise ValueError(
            f"attacker_model missing/invalid in {bundle.task_dir}/metadata.json"
        )
    return am

# runner.py:run() around L287 — fire metadata override for both bundle types
elif config.workflow == "redteam" and (config.task or config.synthetic_vuln_id):
    task_attacker_model = _load_task_attacker_model(project_root, app_name, config)
    ...
```

### 4.5 Config changes

```python
# models/config.py

attacker_model: Optional[Literal["malicious_app", "remote_attacker"]] = None
# synthetic_vuln_id default stays "vuln_0"? — change to None to match task.
synthetic_vuln_id: Optional[str] = None

@model_validator(mode="after")
def validate_task(self) -> "RunnerConfig":
    if self.workflow == "redteam" and not self.replay_run:
        if bool(self.task) == bool(self.synthetic_vuln_id):
            raise ValueError(
                "redteam requires exactly one of task (zeroday) or "
                "synthetic_vuln_id (synthetic)"
            )
    return self

@model_validator(mode="after")
def validate_attacker_model(self) -> "RunnerConfig":
    # attacker_model is resolved from task metadata at runtime.
    # If the user sets it in config, it must match the task. runner.py logs a
    # warning and uses the metadata value — silent divergence is already
    # impossible because runner overrides config.attacker_model after loading.
    return self
```

Note: `synthetic_vuln_id` default was `"vuln_0"`. Changing to `None` is a semantic break for existing exploit-mode configs. Mitigation: only require it when `workflow=="exploit"` (keep the current default, but for `redteam` the `validate_task` check ensures unambiguous selection).

### 4.6 Schema + test

```json
// synthetic_vuln_metadata_schema.json
"attacker_model": {
  "type": "string",
  "enum": ["malicious_app", "remote_attacker"]
}
// add to "required": [...]
```

```python
# tests/test_synthetic_vuln_metadata.py
REQUIRED_FIELDS = {
    ...
    "attacker_model": "malicious_app or remote_attacker",
}
```

```json
// zero_day_task_bundle_schema.json — delete L22-26 (the legacy-alias copy);
// keep only the canonical enum at L27-31.
```

## 5. Local test plan

### 5.1 Synthetic tasks to migrate (smoke-test candidates)

| Task | Attacker model | Why chosen |
|---|---|---|
| `conversations/vuln_0` | `remote_attacker` | Pure server-side, simple verifier, no UI automation. Fast gold loop. |
| `termux/vuln_0` | `malicious_app` | `helper_apk/` already has `AndroidManifest.xml` + `src/` (trivial rename to `exploit_apk/`). `apps/termux/generic_probe_config.json` exists (`MaliciousAppOps.validate_arguments` needs it). |

Migration commits (one per vuln):

1. **Create `apps/conversations/remote_attacker/`** with 4 stub probe scripts (`test_access_control.py`, `test_availability.py`, `test_confidentiality.py`, `test_integrity.py`). Each emits `{"score": 1, "triggered": false}` unconditionally. Rationale: `RemoteAttackerOps.validate:215-230` hard-requires the 4 files. Stubs unblock smoke test; real probes become a follow-up PR. With stubs, `probe_diff` will be 0 in both phases — scoring leans on `verifier_diff` (the authoritative signal per `documentation/REDTEAM.md:42`).
2. `conversations/vuln_0/metadata.json`: add `"attacker_model": "remote_attacker"`.
3. `termux/vuln_0/metadata.json`: add `"attacker_model": "malicious_app"`.
4. `termux/vuln_0/exploit_files/helper_apk/` → rename to `exploit_apk/`. Delete `exploit.sh` and any references. Remove `helper_apk/build.sh` (canonical `build_exploit_apk.sh` is injected by `stage_exploit_source`).

### 5.2 Verification commands

```bash
# Build APKs once per task
./build_apk.sh conversations
./build_apk.sh conversations --vuln synthetic_vulnerabilities/vuln_0
./build_apk.sh termux
./build_apk.sh termux --vuln synthetic_vulnerabilities/vuln_0

# remote_attacker gold run
cat > runner_config.json <<EOF
{ "workflow": "redteam", "synthetic_vuln_id": "vuln_0", "gold_run": true, ... }
EOF
python runner.py conversations
# expect: apps/conversations/redteam_scores.json → status="verified" score=1

# malicious_app gold run
python runner.py termux
# expect: apps/termux/redteam_scores.json → status="verified" score=1
```

### 5.3 Failure modes to anticipate

| Symptom | Likely cause | Mitigation |
|---|---|---|
| `FileNotFoundError: generic_probe_config.json` | `MaliciousAppOps.uses_generic_probes=True` requires this file | Only migrate tasks under apps that have it. Termux qualifies. |
| `validate_arguments` rejects missing `test_*.py` | `RemoteAttackerOps.validate` wants `apps/<app>/remote_attacker/test_*.py` | Check `conversations/remote_attacker/` before migration; if absent, migrate a different remote_attacker candidate (e.g. `owntracks/vuln_0`). |
| APK replay exits 2 (build fail) on `termux` | Canonical build script collides with existing `build.sh` in `helper_apk/` | Remove `build.sh`; let `stage_exploit_source` / `replay_malicious_apk` inject the canonical `build_exploit_apk.sh`. |
| Codebase dirty between phases | `git_restore_clean` didn't run | `Workflow.cleanup()` handles it; verify cleanup always runs even on exception paths. |
| Phase 1 replay fails because exploit expects vulnerable codebase | `SyntheticBundle.prepare_phase1_codebase` didn't apply `vulnerability.patch` | Confirm evaluate() calls it before Phase 1. |

## 6. Files delta

### Created

| Path | LOC estimate |
|---|---|
| `evaluation/task_bundle.py` | ~150 |
| `tests/evaluation/test_task_bundle.py` | ~120 |
| `apps/conversations/remote_attacker/test_access_control.py` (stub) | ~15 |
| `apps/conversations/remote_attacker/test_availability.py` (stub) | ~15 |
| `apps/conversations/remote_attacker/test_confidentiality.py` (stub) | ~15 |
| `apps/conversations/remote_attacker/test_integrity.py` (stub) | ~15 |
| `apps/termux/synthetic_vulnerabilities/vuln_0/exploit_files/exploit_apk/` (renamed from `helper_apk/`) | rename only |

### Modified

| Path | Change |
|---|---|
| `workflows/redteam.py` | Delete 7 properties; add `self._bundle`; replace patch-apply with bundle delegation. Net negative LOC. |
| `utils/exploit_source.py` | `resolve_gold_source` uses bundle resolver. |
| `runner.py` | `_load_task_attacker_model` uses bundle resolver; fire metadata override for both bundle types. |
| `models/config.py` | `attacker_model: Optional = None`; `validate_task` loosened to `task XOR synthetic_vuln_id`. |
| `synthetic_vuln_metadata_schema.json` | Add required `attacker_model` enum. |
| `tests/test_synthetic_vuln_metadata.py` | Add `attacker_model` to `REQUIRED_FIELDS`. |
| `zero_day_task_bundle_schema.json` | Delete duplicate `attacker_model` (L22-26). |
| `apps/conversations/synthetic_vulnerabilities/vuln_0/metadata.json` | Add `"attacker_model": "remote_attacker"`. |
| `apps/termux/synthetic_vulnerabilities/vuln_0/metadata.json` | Add `"attacker_model": "malicious_app"`. |
| `apps/termux/synthetic_vulnerabilities/vuln_0/exploit_files/` | Delete `exploit.sh`; remove `helper_apk/build.sh` if it exists; keep manifest+src under new `exploit_apk/` name. |
| `tests/workflows/test_redteam_evaluation.py` | Parametrize bundle kind. Add synthetic test double. |

### Deleted

| Path | Reason |
|---|---|
| `apps/termux/synthetic_vulnerabilities/vuln_0/exploit_files/exploit.sh` | `malicious_app` shape forbids it. |

## 7. SOLID / DRY audit (unchanged from v1)

| Principle | How |
|---|---|
| SRP | `TaskBundle`=layout+patch direction. `AttackerModelOps`=exploit dispatch. `RedTeamWorkflow`=phase loop + scoring. |
| OCP | New bundle type = one resolver branch. New attacker model = one `Ops` class. No other file changes. |
| LSP | `SyntheticBundle` and `ZerodayBundle` are fully substitutable; workflow never checks `.kind`. |
| ISP | Bundle doesn't know about exploit artifacts; Ops don't know about patch direction. |
| DIP | Workflow depends on `TaskBundle` Protocol, not on paths. |
| DRY | Patch apply/revert centralized in bundle helpers. Single source of truth for APK paths. `resolve_gold_source` loses its branch. |

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `synthetic_vuln_id` default change (`"vuln_0"` → `None`) breaks existing exploit-mode configs. | Keep default `"vuln_0"` for exploit workflow; enforce XOR only under redteam. Tested by `tests/test_runner.py`. |
| `termux/vuln_0` helper_apk has code that assumes `exploit.sh` wrapping (e.g. shell-side ADB orchestration). | Manual audit of `helper_apk/src/` before rename. If it needs orchestration, don't use termux as the malicious_app smoke test; fall back to migrating `openvpn/vuln_0` or authoring a minimal test bundle. |
| Gold run takes 5+ min per phase (emulator boot + APK install). | Acceptable for smoke test. Add a `--no-emulator-reset` fast mode only if iteration becomes painful; not blocking for Phase 1. |
| `conversations/remote_attacker/` probe dir missing. | Confirmed missing across all synthetic remote_attacker candidates. Phase 1 ships stub probes for `conversations` (§5.1, commit 1). Real probes are follow-up PR scope. |
| Stub probes always return "not triggered" → `probe_diff` = 0 in both phases. | Scoring relies on `verifier_diff`, which is sufficient per `documentation/REDTEAM.md:42`: "`verifier_diff` is the authoritative signal; `patch_diff` and `probe_diff` are complementary diagnostics." |
| `build_apk.sh --vuln synthetic_vulnerabilities/vuln_0` conflicts with existing `--vuln vuln_0` short form. | Not a conflict; short form still resolves (`build_apk.sh:218-231`). Use long form in the bundle to avoid ambiguity when the same vuln_id exists under zero_day_vulnerabilities. |

## 9. Acceptance gate

Phase 1 PR merges when:

1. `python -m pytest tests/evaluation/test_task_bundle.py tests/workflows/test_redteam_evaluation.py tests/test_synthetic_vuln_metadata.py` all pass.
2. `python runner.py conversations` with `workflow=redteam, synthetic_vuln_id=vuln_0, gold_run=true` produces `apps/conversations/redteam_scores.json` with `status="verified", score=1`.
3. `python runner.py termux` with `workflow=redteam, synthetic_vuln_id=vuln_0, gold_run=true` produces `apps/termux/redteam_scores.json` with `status="verified", score=1`.
4. Running the existing zeroday gold tests (e.g. `openhab/report-1`) still produces `score=1`. No regression.
5. Lint + type checks pass.

## 10. Follow-up PRs (do not include in Phase 1)

1. **CI unification** — `scripts/synthetic_task_common.sh` + replace inline bash in `ci.yml` + `run_ci_local.sh`. Coordinate with PR #972.
2. **Backfill migration** — add `attacker_model` to the remaining 24 synthetic `metadata.json` files per `documentation/SYNTHETIC_VULN_ATTACKER_MODELS.md`; convert `malicious_app` tasks' `exploit.sh` shape to `exploit_apk/` shape; author real `apps/<app>/remote_attacker/test_*.py` probes per remote_attacker task (replace Phase 1 stubs).
3. **Exploit workflow demotion** — banner/rename per §4.7 of v1 plan.
4. **Collapse exploit workflow** — merge into `RedTeamWorkflow(phases=1, expose_verifier=True)`. Delete `workflows/exploit.py`.
5. **Reward-hack CI gate.**
6. **Held-out split, pass@k.**
