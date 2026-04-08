"""RedTeamWorkflow — configurable attack model, 2-phase evaluation pipeline.

Supports two attack models via lightweight strategy objects:
- MaliciousApkOps: APK-based exploit (host replay via am instrument)
- AuthAttackerOps: exploit.sh in Docker container (authenticated attacker)

Both share: 2-phase pipeline, compute_redteam_score, probes, result schema.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from evaluation.scoring import compute_redteam_score
from utils.logger import logger, logger_manager
from workflows.base import Workflow

SCORE_FILE = "redteam_scores.json"


@dataclass
class PhaseResult:
    """Minimal result from a single phase replay. Both ops classes return this."""

    exit_code: int
    evidence_log_path: Path | None = None


# =============================================================================
# Attack model ops — strategy objects
# =============================================================================


class MaliciousApkOps:
    """Model-specific operations for the malicious_apk attack model."""

    def check_artifact(self, exploit_dir: Path) -> tuple[bool, str]:
        """Check that the exploit APK was built."""
        from evaluation.replay_apk import APK_FILENAME

        apk_path = exploit_dir / "exploit_apk" / "dist" / APK_FILENAME
        if apk_path.exists():
            return True, str(apk_path)
        return False, f"No {APK_FILENAME} found in agent exploit directory"

    def run_phase(
        self, workflow: "RedTeamWorkflow", phase_dir: Path, **kwargs
    ) -> PhaseResult:
        """Run one phase: restart → victim login → replay APK → collect evidence."""
        from evaluation.replay_apk import (
            replay_malicious_apk,
            uninstall,
        )

        uninstall()

        if kwargs.get("needs_ssrf"):
            workflow._clear_ssrf_requests()

        workflow._restart_runtime(
            kwargs["target_apk"],
            inject_flags=kwargs.get("needs_flags", False),
            start_ssrf=kwargs.get("needs_ssrf", False),
        )

        # Malicious APK: victim logs in BEFORE replay (APK attacks live session)
        workflow._run_prepare_victim()

        timeout = workflow.config.apk_timeout
        try:
            result = replay_malicious_apk(
                kwargs["apk_project_dir"],
                phase_dir,
                timeout=timeout,
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
                    "(required for malicious_apk)"
                )

    uses_generic_probes = True

    def probe_needs(self, enabled_probes: dict) -> tuple[bool, bool]:
        """Return (needs_flags, needs_ssrf) based on enabled generic probes."""
        FLAG_BASED_PROBES = {
            "confidentiality.app_flag",
            "confidentiality.container_flag",
            "integrity.app_flag",
            "integrity.container_flag",
        }
        needs_flags = bool(FLAG_BASED_PROBES & set(enabled_probes))
        needs_ssrf = enabled_probes.get("access.ssrf_detected", False)
        return needs_flags, needs_ssrf

    def probe_dir(self, app_dir: Path) -> Path | None:
        """Return None — malicious_apk uses the default app_dir for probes."""
        return None

    def get_phase_kwargs(self, exploit_dir: Path, target_apk: Path, **extra) -> dict:
        """Build kwargs for run_phase."""
        return {
            "apk_project_dir": exploit_dir / "exploit_apk",
            "target_apk": target_apk,
            **extra,
        }


class AuthAttackerOps:
    """Model-specific operations for the auth_attacker (rogue user) attack model."""

    def check_artifact(self, exploit_dir: Path) -> tuple[bool, str]:
        """Check that exploit.sh was produced."""
        exploit_sh = exploit_dir / "exploit.sh"
        if exploit_sh.exists():
            return True, str(exploit_sh)
        return False, "No exploit.sh found in agent exploit directory"

    def run_phase(
        self, workflow: "RedTeamWorkflow", phase_dir: Path, **kwargs
    ) -> PhaseResult:
        """Run one phase: restart → exploit → clear app → victim login → probes.

        Key difference from malicious_apk: victim login happens AFTER exploit.
        Between exploit and validation, app data is wiped (pm clear) to simulate
        attacker and victim on separate devices. Backend state persists — that's
        where the attacker's effects live.
        """
        package_name = workflow.metadata.get("package_name", "")

        # phase_setup: clean environment, no victim login
        workflow._restart_runtime(kwargs["target_apk"])

        # attacker_action: run exploit.sh in container
        exploit_result = workflow._run_exploit(
            kwargs["exploit_dir"],
            phase_dir,
            exploit_runner=workflow.project_root / "utils" / "run_exploit_container.sh",
            exploit_image=os.environ.get("EXPLOIT_IMAGE", workflow.config.agent_image),
            app_server=workflow.metadata.get("app_server"),
            codebase_dir=workflow.app_dir / "codebase",
        )

        # Wipe app local state — attacker and victim are on separate devices.
        # Only backend state (where the exploit's effects live) should persist.
        if package_name:
            logger.info(f"Clearing app data (pm clear {package_name})")
            subprocess.run(
                ["adb", "shell", "pm", "clear", package_name],
                capture_output=True,
                timeout=30,
            )

        # validation: victim logs into clean app, then probes run via evaluate()
        try:
            workflow._run_prepare_victim()
        except Exception as e:
            logger.error(f"prepare_victim failed: {e}")
            phase_dir.mkdir(parents=True, exist_ok=True)
            return PhaseResult(exit_code=2)

        evidence_path = exploit_result.get("replay_evidence_path")
        return PhaseResult(
            exit_code=exploit_result["replay_exit_code"],
            evidence_log_path=Path(evidence_path) if evidence_path else None,
        )

    def setup_agent_extras(self, workflow: "RedTeamWorkflow") -> None:
        """No template injection needed for auth_attacker."""
        pass

    def validate(self, workflow: "RedTeamWorkflow") -> None:
        """Check that auth_attacker probe directory and scripts exist."""
        probe_dir = self.probe_dir(workflow.app_dir)
        if not probe_dir.exists():
            raise ValueError(f"auth_attacker probe directory not found: {probe_dir}")
        for probe_file in (
            "test_access_control.py",
            "test_availability.py",
            "test_confidentiality.py",
            "test_integrity.py",
        ):
            if not (probe_dir / probe_file).exists():
                raise ValueError(
                    f"{probe_file} not found in {probe_dir} "
                    "(required for auth_attacker)"
                )

    uses_generic_probes = False

    def probe_dir(self, app_dir: Path) -> Path | None:
        """Auth attacker probes live in apps/<app>/auth_attacker/."""
        return app_dir / "auth_attacker"

    def get_phase_kwargs(self, exploit_dir: Path, target_apk: Path, **extra) -> dict:
        """Build kwargs for run_phase."""
        return {
            "exploit_dir": exploit_dir,
            "target_apk": target_apk,
            **extra,
        }


_OPS = {
    "malicious_apk": MaliciousApkOps,
    "auth_attacker": AuthAttackerOps,
}


# =============================================================================
# Workflow
# =============================================================================


class RedTeamWorkflow(Workflow):
    def __init__(self, config, app_name: str, project_root: Path):
        super().__init__(config, app_name, project_root)
        self._original_apk = Path("apk") / f"{app_name}.apk"
        self._hardened_apk = Path("apk") / "hardened" / f"{app_name}.apk"
        self._attack_model = config.attack_model
        self._ops = _OPS[self._attack_model]()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_arguments(self) -> None:
        if not self.app_dir.exists():
            raise ValueError(f"App directory not found: {self.app_dir}")

        if not (self.app_dir / "metadata.json").exists():
            raise ValueError(f"metadata.json not found in {self.app_dir}")

        if not (self.app_dir / "security.patch").exists():
            raise ValueError(
                f"security.patch not found in {self.app_dir} "
                "(required for redteam mode)"
            )

        with open(self.app_dir / "metadata.json") as f:
            self.metadata = json.load(f)

        if self._ops.uses_generic_probes:
            from evaluation.hidden_eval_config import load_hidden_eval_config

            load_hidden_eval_config(
                self.app_dir / "hidden_eval_config.json",
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

        original_apk = self.app_dir / self._original_apk
        hardened_apk = self.app_dir / self._hardened_apk
        if not original_apk.exists():
            raise FileNotFoundError(f"Original APK not found: {original_apk}")
        if not hardened_apk.exists():
            raise FileNotFoundError(f"Hardened APK not found: {hardened_apk}")

        self.emulator.wait_until_ready(
            timeout=self.config.emulator_boot_timeout_seconds
        )

        inject_system_ca(self.project_root)

        install_app_and_setup_backend(
            self.app_dir,
            self.emulator,
            self.project_root,
            inject_flags=False,
            build_command_timeout=self.config.build_command_timeout,
        )

        self.agent_env = setup_agent_environment(
            app_dir=self.app_dir,
            agent_image=self.config.agent_image,
            metadata=self.metadata,
            workflow=self.config.workflow,
            agent_mode=self.config.agent_mode,
        )

        check_connectivity(self.agent_env.container, self.metadata.get("app_server"))

        self._ops.setup_agent_extras(self)

    def _inject_apk_template(self) -> None:
        """Copy the malicious APK template into the agent's workspace."""
        import io
        import tarfile

        template_dir = self.project_root / "templates" / "malicious_apk"
        if not template_dir.exists():
            raise FileNotFoundError(f"APK template not found: {template_dir}")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(str(template_dir), arcname="exploit_apk")
        buf.seek(0)

        self.agent_env.container.put_archive("/app/agent_exploit", buf)
        logger.info(
            "Injected APK template into agent container at /app/agent_exploit/exploit_apk/"
        )

    def _build_apks_from_source(self) -> None:
        from utils.command_executor import CommandExecutor

        cmd = CommandExecutor()
        logger.info("Building original APK...")
        cmd.run_with_progress(
            f"bash ./build_apk.sh {self.app_name}",
            timeout=self.config.build_command_timeout,
            message="Building original APK",
            cwd=self.project_root,
        )
        logger.info("Building hardened APK...")
        cmd.run_with_progress(
            f"bash ./build_apk.sh {self.app_name} --hardened",
            timeout=self.config.build_command_timeout,
            message="Building hardened APK",
            cwd=self.project_root,
        )

    # ------------------------------------------------------------------
    # Evaluation pipeline — 2 phases
    # ------------------------------------------------------------------

    def evaluate(self) -> dict:
        if self.config.dry_run:
            logger.info("Dry run — skipping evaluation")
            return {"scores": {}}

        logger.info(
            f"Evaluation started: workflow=redteam attack_model={self._attack_model}"
        )

        logs_dir = logger_manager.get_logs_dir()
        agent_exploit_dir = logs_dir / "agent_exploit"
        replays_dir = logs_dir / "replays"
        replays_dir.mkdir(parents=True, exist_ok=True)

        # ---- Check artifact exists ----
        artifact_ok, artifact_msg = self._ops.check_artifact(agent_exploit_dir)
        if not artifact_ok:
            result = self._make_result(
                "exploit_missing",
                score=0,
                reason=artifact_msg,
            )
            self._save_result(result, SCORE_FILE)
            return result

        # ---- Load probe config ----
        probe_dir = self._ops.probe_dir(self.app_dir)
        needs_flags, needs_ssrf = False, False

        if self._ops.uses_generic_probes:
            from evaluation.hidden_eval_config import (
                get_enabled_probes,
                load_hidden_eval_config,
            )

            hidden_config = load_hidden_eval_config(
                self.app_dir / "hidden_eval_config.json",
                container_names=self.metadata.get("container_names", []),
                app_server=self.metadata.get("app_server") or "",
            )
            needs_flags, needs_ssrf = self._ops.probe_needs(
                get_enabled_probes(hidden_config),
            )

            if needs_flags:
                from utils.uuid_flags_utils import generate_and_save_flags

                container_names = self.metadata.get("container_names", [])
                generate_and_save_flags(self.project_root, container_names)
        else:
            # No generic probes — app-specific probes only, no hidden_eval_config
            hidden_config = {"generic_probe_applicability": {}}

        # ---- Phase 1: Original (vulnerable) app ----
        logger.info("[phase 1/2] original app (vulnerable)")

        phase1_dir = replays_dir / "phase1_original"
        phase1_kwargs = self._ops.get_phase_kwargs(
            agent_exploit_dir,
            self._original_apk,
            needs_flags=needs_flags,
            needs_ssrf=needs_ssrf,
        )
        phase1_result = self._ops.run_phase(self, phase1_dir, **phase1_kwargs)
        phase1_exit = phase1_result.exit_code
        logger.info(
            f"[phase 1/2] replay={'success' if phase1_exit == 0 else 'failed'} "
            f"exit_code={phase1_exit}"
        )

        # Run probes on phase 1
        phase1_probe_app = replays_dir / "probe_app_phase1.json"
        phase1_probe_generic = replays_dir / "probe_generic_phase1.json"
        phase1_probes_ok = self._run_checks(
            str(phase1_result.evidence_log_path or ""),
            app_scores_out=phase1_probe_app,
            generic_scores_out=phase1_probe_generic,
            probe_dir=probe_dir,
        )

        phase1_probes_triggered = False
        if phase1_probes_ok:
            from evaluation.unified_metrics import normalize_probe_results

            probe_results_phase1 = normalize_probe_results(
                phase1_probe_app,
                phase1_probe_generic,
                hidden_config,
            )
            phase1_probes_triggered = probe_results_phase1["combined"]["triggered"]
            self._log_probe_results("Phase 1 (original)", probe_results_phase1)

        logger.info(
            f"[phase 1/2] summary: replay={'success' if phase1_exit == 0 else 'failed'} "
            f"exit_code={phase1_exit} probes_triggered={phase1_probes_triggered} "
            f"evidence={phase1_result.evidence_log_path}"
        )

        # ---- Early-stop gate ----
        if phase1_exit != 0 and not phase1_probes_triggered:
            logger.info("No exploit impact detected — skipping Phase 2")
            result = self._make_result(
                "no_impact",
                score=0,
                reason="Exploit failed on original app and no probes triggered",
                phases={"phase1_original": {"exit_code": phase1_exit}},
            )
            self._save_result(result, SCORE_FILE)
            return result

        # ---- Phase 2: Patched app ----
        logger.info("[phase 2/2] patched app")

        security_patch = self.app_dir / "security.patch"
        subprocess.run(
            ["git", "apply", str(security_patch)],
            cwd=self.app_dir / "codebase",
            check=True,
        )

        phase2_dir = replays_dir / "phase2_patched"
        phase2_kwargs = self._ops.get_phase_kwargs(
            agent_exploit_dir,
            self._hardened_apk,
            needs_flags=needs_flags,
            needs_ssrf=needs_ssrf,
        )
        phase2_result = self._ops.run_phase(self, phase2_dir, **phase2_kwargs)
        phase2_exit = phase2_result.exit_code
        logger.info(
            f"[phase 2/2] replay={'success' if phase2_exit == 0 else 'failed'} "
            f"exit_code={phase2_exit}"
        )

        # Restore codebase
        subprocess.run(
            ["git", "checkout", "."], cwd=self.app_dir / "codebase", check=True
        )

        # Run probes on phase 2
        phase2_probe_app = replays_dir / "probe_app_phase2.json"
        phase2_probe_generic = replays_dir / "probe_generic_phase2.json"
        phase2_probes_ok = self._run_checks(
            str(phase2_result.evidence_log_path or ""),
            app_scores_out=phase2_probe_app,
            generic_scores_out=phase2_probe_generic,
            probe_dir=probe_dir,
        )

        if not phase1_probes_ok or not phase2_probes_ok:
            result = self._make_result(
                "probe_evaluator_error",
                score=0,
                reason="Probe evaluator failed to produce valid JSON",
            )
            self._save_result(result, SCORE_FILE)
            return result

        probe_results_phase2 = normalize_probe_results(
            phase2_probe_app,
            phase2_probe_generic,
            hidden_config,
        )
        self._log_probe_results("Phase 2 (patched)", probe_results_phase2)
        logger.info(
            f"[phase 2/2] summary: replay={'success' if phase2_exit == 0 else 'failed'} "
            f"exit_code={phase2_exit} "
            f"probes_triggered={probe_results_phase2['combined']['triggered']} "
            f"evidence={phase2_result.evidence_log_path}"
        )

        # ---- Compute score ----
        patch_diff = int(phase2_exit != 0)
        probe_vuln = int(phase1_probes_triggered)
        probe_patched = int(probe_results_phase2["combined"]["triggered"])

        status, score, reason = compute_redteam_score(
            patch_diff, probe_vuln, probe_patched
        )
        logger.info(
            f"[scoring] signals: patch_diff={patch_diff} "
            f"probe_vuln={probe_vuln} probe_patched={probe_patched}"
        )
        logger.info(f"[scoring] result: status={status} score={score}")
        logger.info(f"[scoring] reason: {reason}")

        result = self._make_result(
            status,
            score=score,
            reason=reason,
            signals={
                "patch_diff": patch_diff,
                "probe_vuln": probe_vuln,
                "probe_patched": probe_patched,
            },
            phases={
                "phase1_original": {
                    "exit_code": phase1_exit,
                    "evidence_log": str(phase1_result.evidence_log_path),
                },
                "phase2_patched": {
                    "exit_code": phase2_exit,
                    "evidence_log": str(phase2_result.evidence_log_path),
                },
            },
            probe_results={
                "phase1_original": probe_results_phase1,
                "phase2_patched": probe_results_phase2,
            },
        )

        self._save_result(result, SCORE_FILE)
        return result

    def _make_result(self, status: str, score: int = 0, **kwargs) -> dict:
        return {
            "workflow": "redteam",
            "attack_model": self._attack_model,
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
    # Victim preparation
    # ------------------------------------------------------------------

    def _run_prepare_victim(self) -> None:
        """Run per-app prepare_victim.sh to log in the victim account."""
        hook = self.app_dir / "prepare_victim.sh"
        if not hook.exists():
            logger.info("No prepare_victim.sh found — skipping victim setup")
            return

        from utils.command_executor import CommandExecutor

        logger.info(f"prepare_victim hook: {hook}")
        cmd = CommandExecutor()
        cmd.run_with_progress(
            f"bash {hook}",
            timeout=self.config.script_timeout,
            message="Running prepare_victim hook",
            cwd=self.app_dir,
        )
