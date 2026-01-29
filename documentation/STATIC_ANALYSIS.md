# Static Analysis Reports

The supervisor agent consumes pre-generated static analysis reports stored under:
```
apps/<app_name>/static_vuln_reports/
```

## Tools
- Semgrep (required)
- MobSFScan (optional)
- QARK (optional)

## Install dependencies
The heavy tools are commented out in `requirements.txt`. Uncomment them locally before running scans.

## Generate reports
From the repo root:
```bash
# Semgrep (required)
python tools/run_semgrep_scan.py <app_name> --source-dir apps/<app_name>/codebase

# MobSFScan (optional)
python tools/run_mobsfscan.py <app_name> --source-dir apps/<app_name>/codebase

# QARK (optional)
python tools/generate_qark_report.py <app_name> --apk apps/<app_name>/apk/<app_name>.apk
```

Expected outputs:
- `apps/<app_name>/static_vuln_reports/semgrep/report.json`
- `apps/<app_name>/static_vuln_reports/mobsfscan/report.json`
- `apps/<app_name>/static_vuln_reports/qark/report.json`

## When to run
Run these scans before running the supervisor agent so it can prioritize and validate findings.
