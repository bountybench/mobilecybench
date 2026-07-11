# Server-side zero-day tasks via backend image swap  *(draft)*

## Problem

The redteam two-phase rescore assumes the vulnerability — and its fix — live in
the **Android app**. Phase 1 replays the exploit against the vulnerable app;
Phase 2 replays it against a `fix.patch`-hardened app; the verifier flips its
verdict between them (`workflows/redteam.py`, `evaluation/task_bundle.py`). The
victim backend is a Docker Compose stack brought up **identically** in both
phases (`workflows/base.py::_reset_app_backend_state` +
`utils/setup_utils.install_app_and_setup_backend`) and is never patched.

Some real zero-days are **server-side**: the bug and fix are in the backend
server, not the app. Examples now in the benchmark:

| task | vuln | fix target |
|---|---|---|
| `wallabag/report-2` | `/api/annotations/{entry}` IDOR (cross-user write) | `src/Wallabag/AnnotationBundle/Controller/WallabagAnnotationController.php` (PHP backend) |
| `home-assistant-android/report-3` | `mobile_app` registration entity-squatting | `homeassistant/components/mobile_app/...` (HA-core Python) |

For these the APK is byte-identical across phases, so the app-side machine
produces no phase difference and `git apply` of a backend patch into
`apps/<app>/codebase` fails outright. These were historically scored
**off-harness** (hand-built vulnerable-vs-patched backend pair). This draft makes
the harness do it natively.

## Strategy: image swap

Keep the APK identical across phases; swap the **backend image** per phase.

- **Phase 1 (vulnerable):** bring the backend up from a prebuilt *vulnerable*
  image (the authored vulnerable baseline, e.g. `wallabag 2.6.10`).
- **Phase 2 (secure):** bring the backend up from a prebuilt *patched* image
  (the same baseline + `fix.patch`).

Both images are produced once, ahead of time, by
`scripts/build_zeroday_backend_images.sh` from the bundle's own `fix.patch`. At
run time the runner writes a small Compose override repointing the backend
service at the phase image and layers it via `COMPOSE_FILE` — no edits to the
app's `docker-compose.*` or `start_runtime.sh`.

## Data model

A server-side task declares a `server_side` block in its `task/metadata.json`
(schema: `zero_day_task_bundle_schema.json`). Presence of the block is what
flips the runner into server-side mode.

```jsonc
"server_side": {
  "service": "wallabag",                 // compose service to swap
  "images": {                            // prebuilt, pin by digest for repro
    "vulnerable": "ghcr.io/.../mcb-zeroday-wallabag:report-2-vulnerable@sha256:…",
    "secure":     "ghcr.io/.../mcb-zeroday-wallabag:report-2-patched@sha256:…"
  },
  "build": {                             // recipe for the build script
    "base_image": "wallabag/wallabag:2.6.10",
    "context": "backend",                // optional bundle dir w/ harness-tweak Dockerfile
    "patch_workdir": "/var/www/wallabag",
    "patch_strip": 1
  }
}
```

## Runtime flow (what changed)

1. `evaluation/task_bundle.py` — `ZerodayBundle` reads `server_side`. When
   present: `phase2_apk() == phase1_apk()` (no hardened APK), `build_apks` skips
   the `--hardened-patch` build, `validate_build_artifacts` skips the hardened
   APK check, and `prepare_phase2_codebase` does **not** touch the app codebase.
   New accessors: `is_server_side()`, `backend_service()`,
   `backend_image_for_phase(phase_slug)`.
2. `evaluation/backend_image_swap.py` (new) — `write_phase_override()` writes
   `.mcb-zeroday-backend.override.yml` into the app dir and returns
   `{"COMPOSE_FILE": "docker-compose.yml:.mcb-zeroday-backend.override.yml"}`.
   The override uses the Compose Spec `!reset` tag to drop any `build:` section
   so a locally-built service (wallabag) uses the prebuilt image instead of
   rebuilding.
3. `workflows/redteam.py` — `_backend_compose_env_for_phase(phase_dir)` maps the
   phase (`phase1_original`→`vulnerable`, `phase2_patched`→`secure`) to the image
   and writes the override. Both `run_phase` paths thread the result into
   `_restart_runtime(..., backend_compose_env=…)`.
4. `workflows/base.py` + `utils/setup_utils.py` — `_reset_app_backend_state`,
   `_restart_runtime`, and `install_app_and_setup_backend` accept the compose
   env and merge it into the `docker compose down -v` and `start_runtime.sh`
   subprocesses. App-side / probe-only runs pass `None` and are unaffected.

The verifier, exploit, probes, scoring, and `MCB_PHASE` plumbing are unchanged —
they already run against whatever backend is up.

## Build flow

```bash
scripts/build_zeroday_backend_images.sh wallabag report-2 [--push]
```

Builds the *vulnerable* image (FROM `base_image`, through the bundle's optional
`context` Dockerfile that re-adds the app's harness tweaks — entrypoint, tools),
then the *patched* image (FROM the vulnerable image + `git apply` of `fix.patch`
in `patch_workdir`). Push and pin the digests into `server_side.images`.

- **wallabag** — the app service is locally built (`apps/wallabag/Dockerfile`,
  FROM `wallabag/wallabag:2.6.14`). The vulnerable baseline is `2.6.10`; the
  `context` Dockerfile mirrors `apps/wallabag/Dockerfile` with an
  `ARG BASE_IMAGE`. Patch dir `/var/www/wallabag`, strip 1.
- **home-assistant** — the app service is a *pulled* image
  (`ghcr.io/home-assistant/home-assistant:2026.7.1`). Vulnerable baseline
  `2026.6.0`; usually no `context` Dockerfile needed. Patch dir is the HA-core
  install root (`/usr/src/homeassistant`), strip 1.

## Status / validation

Implemented and unit-tested (pure Python): bundle branching and override
generation — `tests/test_server_side_zeroday_bundle.py` (14 tests, green).

**Pending (needs a Docker host / VM, cannot run here):**
- End-to-end: build both images for `wallabag/report-2`, run the redteam replay
  for one saved RA exploit, confirm the verifier flips (Phase 1 vulnerable →
  Phase 2 patched) and the run scores `verified` — matching the off-harness
  result (wallabag 6/6, HA 1/1).
- Confirm the installed Docker Compose supports `!reset` (v2.24.4+); otherwise
  switch the override to a full service redeclaration.
- `git apply` inside the image assumes `git` is present in the base/context
  layer (add it in the `context` Dockerfile if not); verify strip level per app.
- Un-gate these tasks in CI (they are currently skipped via
  `mobilecybench_patch_applicable: false` / `target_scope: upstream_repo_only`
  in the zerodays `report.json`).

## Note on scope

This does not change any published numbers — the off-harness verdicts for these
7 cells are already folded into the attribution grid. This is about making the
result **reproducible in-rig** and letting future server-side tasks run natively.
Example bundle fragments: `documentation/examples/server_side/`.
