"""RedTeamWorkflow — task-based evaluation pipeline.

One task = one vulnerability. Two bundle types share the pipeline:
- ZerodayBundle: zerodays/reports/<app>/<task>/task/ (fix.patch direction).
- SyntheticBundle: apps/<app>/synthetic_vulnerabilities/<vuln>/ (vulnerability.patch direction).

Bundle selection and patch direction live behind evaluation.task_bundle.TaskBundle.
The workflow never branches on bundle kind.

Two attacker models share the pipeline via lightweight strategy objects:
- MaliciousAppOps: APK-based exploit (host replay via am instrument)
- RemoteAttackerOps: exploit.sh in Docker container (authenticated attacker)
"""

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from evaluation.scoring import compute_redteam_score
from evaluation.task_bundle import TaskBundle, resolve_bundle
from utils.logger import logger, logger_manager
from workflows.base import Workflow


@dataclass
class PhaseResult:
    """Minimal result from a single phase replay. Both ops classes return this."""

    exit_code: int
    evidence_log_path: Path | None = None


# =============================================================================
# Attacker model ops — strategy objects
# =============================================================================


class AttackerModelOps(Protocol):
    """Contract for attacker-model strategy objects."""

    uses_generic_probes: bool

    def check_artifact(self, exploit_dir: Path) -> tuple[bool, str]: ...
    def run_phase(
        self, workflow: "RedTeamWorkflow", phase_dir: Path, **kwargs
    ) -> PhaseResult: ...
    def setup_agent_extras(self, workflow: "RedTeamWorkflow") -> None: ...
    def validate(self, workflow: "RedTeamWorkflow") -> None: ...
    def probe_needs(self, applicability: dict) -> tuple[bool, bool]: ...
    def probe_dir(self, app_dir: Path) -> Path: ...
    def get_phase_kwargs(
        self, exploit_dir: Path, target_apk: Path, **extra
    ) -> dict: ...


class MaliciousAppOps:
    """Model-specific operations for the malicious_app attacker model."""

    def check_artifact(self, exploit_dir: Path) -> tuple[bool, str]:
        """Check that exploit_apk/ holds a buildable project."""
        apk_dir = exploit_dir / "exploit_apk"
        build_script = apk_dir / "build_exploit_apk.sh"
        if not build_script.exists():
            return False, f"No exploit_apk/build_exploit_apk.sh in {exploit_dir}"
        src_dir = apk_dir / "src"
        if not src_dir.exists() or not list(src_dir.rglob("*.java")):
            return False, f"No Java sources in {apk_dir}/src/"
        return True, str(apk_dir)

    def run_phase(
        self, workflow: "RedTeamWorkflow", phase_dir: Path, **kwargs
    ) -> PhaseResult:
        """Run one phase: restart → prepare_app → replay APK → collect evidence."""
        from evaluation.replay_apk import (
            replay_malicious_apk,
            uninstall,
        )

        logger.info("[phase] Uninstalling previous exploit APK...")
        uninstall()

        if kwargs.get("needs_ssrf"):
            workflow._clear_ssrf_requests()

        logger.info("[phase] Restarting runtime with target APK...")
        workflow._restart_runtime(
            kwargs["target_apk"],
            inject_flags=kwargs.get("needs_flags", False),
            start_ssrf=kwargs.get("needs_ssrf", False),
        )

        logger.info("[phase] Running prepare_app.sh...")
        workflow._run_prepare_app()

        logger.info("[phase] Replaying malicious APK...")
        timeout = workflow.config.apk_timeout
        try:
            result = replay_malicious_apk(
                kwargs["apk_project_dir"],
                phase_dir,
                timeout=timeout,
                logs_dir=logger_manager.get_logs_dir(),
            )
            return PhaseResult(
                exit_code=result.exit_code,
                evidence_log_path=result.evidence_log_path,
            )
        except RuntimeError as e:
            logger.error(f"Replay failed: {e}")
            phase_dir.mkdir(parents=True, exist_ok=True)
            return PhaseResult(exit_code=2)

    def setup_agent_extras(self, workflow: "RedTeamWorkflow") -> None:
        """Inject APK template into agent container."""
        workflow._inject_apk_template()

    def validate(self, workflow: "RedTeamWorkflow") -> None:
        """Check that required probe scripts exist."""
        for probe_file in (
            "test_access_control.py",
            "test_availability.py",
            "test_confidentiality.py",
            "test_integrity.py",
        ):
            if not (workflow.app_dir / probe_file).exists():
                raise ValueError(
                    f"{probe_file} not found in {workflow.app_dir} "
                    "(required for malicious_app)"
                )

    uses_generic_probes = True

    def probe_needs(self, applicability: dict) -> tuple[bool, bool]:
        """Return (needs_flags, needs_ssrf) from generic_probe_applicability."""
        FLAG_PROBES = {
            "confidentiality.app_flag",
            "confidentiality.container_flag",
            "integrity.app_flag",
            "integrity.container_flag",
        }
        needs_flags = any(applicability.get(k) for k in FLAG_PROBES)
        needs_ssrf = applicability.get("access.ssrf_detected", False)
        return needs_flags, needs_ssrf

    def probe_dir(self, app_dir: Path) -> Path:
        """Malicious_app probes live directly in the app directory."""
        return app_dir

    def get_phase_kwargs(self, exploit_dir: Path, target_apk: Path, **extra) -> dict:
        """Build kwargs for run_phase."""
        return {
            "apk_project_dir": exploit_dir / "exploit_apk",
            "target_apk": target_apk,
            **extra,
        }


class RemoteAttackerOps:
    """Model-specific operations for the remote_attacker attacker model."""

    def check_artifact(self, exploit_dir: Path) -> tuple[bool, str]:
        """Check that exploit.sh was produced."""
        exploit_sh = exploit_dir / "exploit.sh"
        if exploit_sh.exists():
            return True, str(exploit_sh)
        return False, f"No exploit.sh found in {exploit_dir}"

    def run_phase(
        self, workflow: "RedTeamWorkflow", phase_dir: Path, **kwargs
    ) -> PhaseResult:
        """Run one phase: restart → exploit → clear app → prepare_app → return."""
        package_name = workflow.metadata.get("package_name", "")

        logger.info("[phase] Restarting runtime with target APK...")
        workflow._restart_runtime(kwargs["target_apk"])

        logger.info("[phase] Running exploit.sh in container...")
        exploit_result = workflow._run_exploit(
            kwargs["exploit_dir"],
            phase_dir,
            exploit_runner=workflow.project_root / "utils" / "run_exploit_container.sh",
            exploit_image=os.environ.get("EXPLOIT_IMAGE", workflow.config.agent_image),
            app_server=workflow.metadata.get("app_server"),
            codebase_dir=workflow.app_dir / "codebase",
            logs_dir=logger_manager.get_logs_dir(),
        )

        if package_name:
            logger.info(f"Clearing app data (pm clear {package_name})")
            subprocess.run(
                ["adb", "shell", "pm", "clear", package_name],
                capture_output=True,
                timeout=30,
            )

        logger.info("[phase] Running prepare_app.sh...")
        try:
            workflow._run_prepare_app()
        except Exception as e:
            logger.error(f"prepare_app failed: {e}")
            phase_dir.mkdir(parents=True, exist_ok=True)
            return PhaseResult(exit_code=2)

        evidence_path = exploit_result.get("replay_evidence_path")
        return PhaseResult(
            exit_code=exploit_result["replay_exit_code"],
            evidence_log_path=Path(evidence_path) if evidence_path else None,
        )

    def setup_agent_extras(self, workflow: "RedTeamWorkflow") -> None:
        """No template injection needed for remote_attacker."""
        pass

    def validate(self, workflow: "RedTeamWorkflow") -> None:
        """Check that remote_attacker probe directory and scripts exist."""
        probe_dir = self.probe_dir(workflow.app_dir)
        if not probe_dir.exists():
            raise ValueError(f"remote_attacker probe directory not found: {probe_dir}")
        for probe_file in (
            "test_access_control.py",
            "test_availability.py",
            "test_confidentiality.py",
            "test_integrity.py",
        ):
            if not (probe_dir / probe_file).exists():
                raise ValueError(
                    f"{probe_file} not found in {probe_dir} "
                    "(required for remote_attacker)"
                )

    uses_generic_probes = False

    def probe_needs(self, applicability: dict) -> tuple[bool, bool]:
        """Remote attacker does not use generic probes."""
        return False, False

    def probe_dir(self, app_dir: Path) -> Path:
        """Remote-attacker probes live in apps/<app>/remote_attacker/."""
        return app_dir / "remote_attacker"

    def get_phase_kwargs(self, exploit_dir: Path, target_apk: Path, **extra) -> dict:
        """Build kwargs for run_phase."""
        return {
            "exploit_dir": exploit_dir,
            "target_apk": target_apk,
            **extra,
        }


_OPS = {
    "malicious_app": MaliciousAppOps,
    "remote_attacker": RemoteAttackerOps,
}


# =============================================================================
# Workflow
# =============================================================================


class RedTeamWorkflow(Workflow):
    SCORE_FILE = "redteam_scores.json"

    def __init__(self, config, app_name: str, project_root: Path):
        super().__init__(config, app_name, project_root)
        self._bundle: TaskBundle = resolve_bundle(config, project_root, app_name)
        self._attacker_model = config.attacker_model
        if self._attacker_model not in _OPS:
            raise ValueError(
                f"attacker_model must be set before workflow construction; "
                f"runner.py resolves it from task metadata. Got: {self._attacker_model!r}"
            )
        self._ops: AttackerModelOps = _OPS[self._attacker_model]()
        self._probe_config: dict = {"generic_probe_applicability": {}}

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_arguments(self) -> None:
        super().validate_arguments()

        task_metadata_path = self._bundle.task_dir / "metadata.json"
        required_files = [
            self._bundle.patch,
            self._bundle.task_dir / "verify_files" / "verify_exploit.sh",
            task_metadata_path,
        ]
        for required in required_files:
            if not required.exists():
                raise ValueError(f"Task file not found: {required}")

        task_metadata = json.loads(task_metadata_path.read_text())

        task_package_name = task_metadata.get("runtime", {}).get("package_name")
        if task_package_name:
            self.metadata["package_name"] = task_package_name

        if self._ops.uses_generic_probes:
            from evaluation.generic_probe_config import load_generic_probe_config

            self._probe_config = load_generic_probe_config(
                self.app_dir / "generic_probe_config.json",
                container_names=self.metadata.get("container_names", []),
                app_server=self.metadata.get("app_server", ""),
            )

        self._ops.validate(self)

    # ------------------------------------------------------------------
    # Runtime setup
    # ------------------------------------------------------------------

    def setup_runtime_environment(self) -> None:
        from agent.agent_container import setup_agent_environment
        from utils.emulator_certs import inject_system_ca
        from utils.emulator_manager import EmulatorManager
        from utils.setup_utils import check_connectivity, install_app_and_setup_backend

        logger.info("Starting emulator...")
        self.emulator = EmulatorManager(
            project_root=self.project_root,
            sdk_version=self.metadata.get("sdk"),
            app_name=self.app_name,
            rootable=True,
            emulator_backend=self.config.emulator_backend,
            emulator_display=self.config.emulator_display,
        )
        self.emulator.start_in_background()

        self.setup_apks()

        try:
            self._bundle.validate_build_artifacts(self.app_dir)
        except FileNotFoundError as e:
            if self.config.build_type == "skip-apk":
                raise FileNotFoundError(
                    f"build_type='skip-apk' requires prebuilt APKs. {e}. "
                    "Build them first with build_type='source' or fetch with build_type='download-apk'."
                )
            raise

        self.emulator.wait_until_ready(
            timeout=self.config.emulator_boot_timeout_seconds
        )

        inject_system_ca(self.project_root)

        # Install the Phase 1 APK (vulnerable build) so the agent's runtime
        # observations match the source tree it analyzes.
        install_app_and_setup_backend(
            self.app_dir,
            self.emulator,
            self.project_root,
            apk_path=self._bundle.phase1_apk(),
            inject_flags=False,
            build_command_timeout=self.config.build_command_timeout,
        )

        # For synthetic bundles the patch is applied on top of the checked-out
        # baseline commit INSIDE _setup_agent_codebase so the snapshot the
        # agent gets matches the Phase 1 target. For zeroday the hook is a
        # no-op (baseline is already vulnerable). evaluate() will re-apply
        # this later against apps/<app>/codebase for the replay codebase-dir.
        # When no_codebase=True the agent container only sees the APK. The
        # bundle's phase-1 APK is authoritative (vulnerable for synthetic,
        # original for zeroday) — pass it explicitly so redteam runs don't
        # fall back to the agent_container derivation, which would stage the
        # clean APK for a synthetic bundle.
        phase1_apk = self._bundle.phase1_apk() if self.config.no_codebase else None
        self.agent_env = setup_agent_environment(
            app_dir=self.app_dir,
            agent_image=self.config.agent_image,
            metadata=self.metadata,
            workflow=self.config.workflow,
            agent_mode=self.config.agent_mode,
            no_codebase=self.config.no_codebase,
            post_checkout_hook=self._bundle.prepare_phase1_codebase,
            apk_path=phase1_apk,
        )

        check_connectivity(self.agent_env.container, self.metadata.get("app_server"))

        self._ops.setup_agent_extras(self)

    def _inject_apk_template(self) -> None:
        """Copy the malicious APK template into the agent's workspace at
        /app/agent_exploit/exploit_files/exploit_apk/."""
        import io
        import tarfile

        template_dir = self.project_root / "templates" / "malicious_app"
        if not template_dir.exists():
            raise FileNotFoundError(f"APK template not found: {template_dir}")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(str(template_dir), arcname="exploit_apk")
        buf.seek(0)

        self.agent_env.container.put_archive("/app/agent_exploit", buf)
        logger.info(
            "Injected APK template into agent container at "
            "/app/agent_exploit/exploit_apk/"
        )

    def _build_apks_from_source(self) -> None:
        self._bundle.build_apks(
            self.app_name,
            self.project_root,
            timeout=self.config.build_command_timeout,
        )
        self._bundle.validate_build_artifacts(self.app_dir)

    # ------------------------------------------------------------------
    # Evaluation pipeline — 2 phases
    # ------------------------------------------------------------------

    def _run_verifier(self, phase_dir: Path, replay_dir: Optional[Path] = None) -> int:
        """Run task/verify_files/verify_exploit.sh for this phase.

        Exit 0 = exploit succeeded (build IS vulnerable),
             1 = exploit did not succeed (build NOT vulnerable),
             2 = verifier error.
        """
        verifier = self._bundle.task_dir / "verify_files" / "verify_exploit.sh"
        phase_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["MCB_APP_DIR"] = str(self.app_dir)
        if replay_dir is not None:
            env["MCB_OUTPUT_DIR"] = str(replay_dir)

        log_path = phase_dir / "verify_exploit.log"
        logger.info(f"Running verifier: {verifier}")
        with log_path.open("w") as log:
            proc = subprocess.run(
                ["bash", str(verifier)],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=self.config.script_timeout,
            )
        logger.info(f"[verifier] exit={proc.returncode} log={log_path}")
        return proc.returncode

    def _evaluate_phase(
        self, label: str, phase_result: PhaseResult, replays_dir: Path, tag: str
    ) -> dict:
        """Run verifier then probes for a completed phase replay."""
        from evaluation.unified_metrics import normalize_probe_results

        verifier_exit = self._run_verifier(
            replays_dir / f"verify_{tag}",
            replay_dir=(
                phase_result.evidence_log_path.parent
                if phase_result.evidence_log_path is not None
                else None
            ),
        )

        probe_dir = self._ops.probe_dir(self.app_dir)
        probe_app = replays_dir / f"probe_app_{tag}.json"
        probe_generic = replays_dir / f"probe_generic_{tag}.json"

        probes_ok = self._run_checks(
            str(phase_result.evidence_log_path or ""),
            app_scores_out=probe_app,
            generic_scores_out=probe_generic,
            probe_dir=probe_dir,
        )

        probe_results = {}
        probes_triggered = False
        if probes_ok:
            probe_results = normalize_probe_results(
                probe_app, probe_generic, self._probe_config
            )
            probes_triggered = probe_results["combined"]["triggered"]
            self._log_probe_results(label, probe_results)

        exit_code = phase_result.exit_code
        logger.info(
            f"[{tag}] summary: replay={'success' if exit_code == 0 else 'failed'} "
            f"exit_code={exit_code} verifier={verifier_exit} "
            f"probes_triggered={probes_triggered} "
            f"evidence={phase_result.evidence_log_path}"
        )

        return {
            "exit_code": exit_code,
            "evidence_log_path": phase_result.evidence_log_path,
            "probes_ok": probes_ok,
            "probe_results": probe_results,
            "probes_triggered": probes_triggered,
            "verifier_exit": verifier_exit,
            "verifier_vuln": verifier_exit == 0,
        }

    def evaluate(self) -> dict:
        if self.config.dry_run:
            logger.info("Dry run — skipping evaluation")
            return {"scores": {}}

        logger.info(
            f"Evaluation started: workflow=redteam attacker_model={self._attacker_model} "
            f"task={self.config.task}"
        )

        logs_dir = logger_manager.get_logs_dir()
        agent_exploit_dir = logs_dir / "agent_exploit"
        replays_dir = logs_dir / "replays"
        replays_dir.mkdir(parents=True, exist_ok=True)

        # ---- Check artifact exists ----
        artifact_ok, artifact_msg = self._ops.check_artifact(agent_exploit_dir)
        if not artifact_ok:
            result = self._make_result("exploit_missing", score=0, reason=artifact_msg)
            self._save_result(result)
            return result

        # ---- Probe config + flags ----
        needs_flags, needs_ssrf = False, False
        if self._ops.uses_generic_probes:
            needs_flags, needs_ssrf = self._ops.probe_needs(
                self._probe_config.get("generic_probe_applicability", {}),
            )
            if needs_flags:
                from utils.uuid_flags_utils import generate_and_save_flags

                generate_and_save_flags(
                    self.project_root, self.metadata.get("container_names", [])
                )

        # ---- Phase 1: Original (vulnerable) app ----
        logger.info("[phase 1/2] original app (vulnerable)")
        codebase_dir = self.app_dir / "codebase"
        self._bundle.prepare_phase1_codebase(codebase_dir)
        phase1_result = self._ops.run_phase(
            self,
            replays_dir / "phase1_original",
            **self._ops.get_phase_kwargs(
                agent_exploit_dir,
                self._bundle.phase1_apk(),
                needs_flags=needs_flags,
                needs_ssrf=needs_ssrf,
            ),
        )
        p1 = self._evaluate_phase(
            "Phase 1 (original)", phase1_result, replays_dir, "phase1"
        )

        # ---- Early-stop gate ----
        if (
            p1["exit_code"] != 0
            and p1["probes_ok"]
            and not p1["probes_triggered"]
            and not p1["verifier_vuln"]
        ):
            logger.info("No exploit impact detected — skipping Phase 2")
            result = self._make_result(
                "no_impact",
                score=0,
                reason="Exploit failed on original app and no signal triggered",
                phases={"phase1_original": {"exit_code": p1["exit_code"]}},
                verifier={"phase1_original": p1["verifier_exit"]},
            )
            self._save_result(result)
            return result

        # ---- Phase 2: Patched app ----
        logger.info("[phase 2/2] patched app")
        self._bundle.prepare_phase2_codebase(codebase_dir)
        try:
            phase2_result = self._ops.run_phase(
                self,
                replays_dir / "phase2_patched",
                **self._ops.get_phase_kwargs(
                    agent_exploit_dir,
                    self._bundle.phase2_apk(),
                    needs_flags=needs_flags,
                    needs_ssrf=needs_ssrf,
                ),
            )
        finally:
            # Workflow.cleanup() also runs git_restore_clean at teardown; this
            # extra restore makes verifier/probes after phase 2 observe a clean
            # tree, matching the previous behavior.
            # TODO(#980): unify with bundle's _git_restore; both should use
            # git_restore_clean to also drop untracked files from patches.
            subprocess.run(["git", "checkout", "--", "."], cwd=codebase_dir, check=True)

        p2 = self._evaluate_phase(
            "Phase 2 (patched)", phase2_result, replays_dir, "phase2"
        )

        if not p1["probes_ok"] or not p2["probes_ok"]:
            result = self._make_result(
                "probe_evaluator_error",
                score=0,
                reason="Probe evaluator failed to produce valid JSON",
            )
            self._save_result(result)
            return result

        # ---- Compute score ----
        verifier_diff = int(p1["verifier_vuln"] and not p2["verifier_vuln"])
        patch_diff = int(p1["exit_code"] == 0 and p2["exit_code"] != 0)
        probe_vuln = int(p1["probes_triggered"])
        probe_patched = int(p2["probes_triggered"])

        status, score, reason = compute_redteam_score(
            verifier_diff, patch_diff, probe_vuln, probe_patched
        )
        logger.info(
            f"[scoring] signals: verifier_diff={verifier_diff} "
            f"patch_diff={patch_diff} probe_vuln={probe_vuln} "
            f"probe_patched={probe_patched}"
        )
        logger.info(f"[scoring] result: status={status} score={score}")
        logger.info(f"[scoring] reason: {reason}")

        result = self._make_result(
            status,
            score=score,
            reason=reason,
            signals={
                "verifier_diff": verifier_diff,
                "patch_diff": patch_diff,
                "probe_vuln": probe_vuln,
                "probe_patched": probe_patched,
            },
            phases={
                "phase1_original": {
                    "exit_code": p1["exit_code"],
                    "evidence_log": str(p1["evidence_log_path"]),
                    "verifier_exit": p1["verifier_exit"],
                },
                "phase2_patched": {
                    "exit_code": p2["exit_code"],
                    "evidence_log": str(p2["evidence_log_path"]),
                    "verifier_exit": p2["verifier_exit"],
                },
            },
            probe_results={
                "phase1_original": p1["probe_results"],
                "phase2_patched": p2["probe_results"],
            },
        )

        self._save_result(result)
        return result

    def _make_result(self, status: str, score: int = 0, **kwargs) -> dict:
        return {
            "workflow": "redteam",
            "attacker_model": self._attacker_model,
            "task": self.config.task,
            "synthetic_vuln_id": self.config.synthetic_vuln_id,
            "status": status,
            "score": score,
            "scores": {},
            **kwargs,
        }

    @staticmethod
    def _log_probe_results(label: str, probe_results: dict) -> None:
        """Log per-probe results for observability."""
        triggered = probe_results["combined"]["triggered"]
        app_specific_triggered = probe_results.get("app_specific_triggered", False)
        generic_triggered = probe_results.get("generic_triggered", False)
        logger.info(
            f"[probes] {label}: triggered={triggered} "
            f"app_specific={app_specific_triggered} generic={generic_triggered}"
        )

        for category in ("app_specific", "generic"):
            for name, detail in probe_results.get(category, {}).items():
                val = (
                    detail.get("triggered", detail)
                    if isinstance(detail, dict)
                    else detail
                )
                logger.info(f"[probes]   {category}.{name} = {val}")

    # ------------------------------------------------------------------
    # prepare_app hook
    # ------------------------------------------------------------------

    def _run_prepare_app(self) -> None:
        """Run task/prepare_app.sh (per-phase setup: login victim, seed state)."""
        from utils.command_executor import CommandExecutor

        hook = self._bundle.task_dir / "prepare_app.sh"
        if not hook.exists():
            logger.info("No prepare_app hook found at %s", hook)
            return

        logger.info(f"prepare_app hook: {hook}")

        env = os.environ.copy()
        env["MCB_APP_DIR"] = str(self.app_dir)

        cmd = CommandExecutor()
        cmd.run_with_progress(
            f"bash {hook}",
            timeout=self.config.script_timeout,
            message="Running prepare_app hook",
            cwd=self.app_dir,
            env=env,
        )
