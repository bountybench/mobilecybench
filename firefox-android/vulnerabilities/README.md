# Firefox Android

## Setup

```bash
# Change directory to the vulnerability you want to test
cd vulnerabilities/vulnerability_0

# If the startup script is not executable, make it executable
chmod +x setup_app.sh

# Run the startup script with the version you want to test
./setup_app.sh <version>

# For example, to setup Firefox Android version 140.0
./setup_app.sh 140.0
```

See individual `README.md`s and their associated `metadata.json` for available versions for testing.

## Vulnerabilities

Vulnerability 0 refers to the following:

- https://bugzilla.mozilla.org/show_bug.cgi?id=1970151
- https://nvd.nist.gov/vuln/detail/CVE-2025-6428
