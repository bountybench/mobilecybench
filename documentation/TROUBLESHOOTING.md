# Troubleshooting

## Emulator issues

- Emulator does not start: enable hardware virtualization (Intel VT-x/AMD-V).
- Not enough RAM: close apps or increase available memory.
- Device not detected: run `./check_device.sh` and restart the emulator.

## ADB not found

- Restart the terminal after running `setup.sh`.
- Manually source your shell config: `source ~/.bashrc` or `source ~/.zshrc`.

## APK not found

- Confirm `build.sh` outputs `$SCRIPT_DIR/unsigned.apk`. `build_apk.sh` signs it to `apk/<app_name>.apk` by default (or `--output <dir>`).
- Synthetic vulnerability APKs are stored under `apps/<app_name>/apk/<vuln_id>/`.

## Build timeout (build_apk.sh)

`runner.py` enforces a 15-minute build timeout. Some apps can take longer.
If a build succeeds but the runner times out, build manually and then use `build_type: "skip-apk"` or increase the timeout in `runner.py`.

## Docker issues

- Ensure Docker Desktop is running.
- Check container status: `docker ps`.

## CI failures

- Run local CI first: `./run_ci_local.sh apps/<app_name>`.
- Check that `metadata.json` matches the actual commit and SDK.
- Ensure `start_runtime.sh` avoids flaky sleeps and uses health checks.

## Tooling and dependencies

- If static analysis scripts fail, ensure the tools are installed and uncommented in `requirements.txt`.
- Reinstall deps: `pip install -r requirements.txt` in a fresh venv.

## Venv not actually used (aliases overriding python/pip)
If `python`/`pip` are aliased to a system interpreter, installs will go to global site‑packages even when your prompt shows `.venv`.
Check with:
```bash
which python
which pip
python -c "import sys; print(sys.executable)"
```
If they point outside `.venv`, run:
```bash
unalias python pip 2>/dev/null
./.venv/bin/python -m pip install -r requirements.txt
```

## Large clone size

If the repo feels large (for example ~1GB), common causes are:

- APK artifacts under `apps/<app_name>/apk/`
- Static analysis outputs under `apps/<app_name>/static_vuln_reports/`
- Submodules initialized under `apps/<app_name>/codebase/`

Check the largest directories:

```bash
du -sh apps/* | sort -h
```

If you do not need submodules yet, avoid `--recurse-submodules` on clone and initialize only the app you are working on.
