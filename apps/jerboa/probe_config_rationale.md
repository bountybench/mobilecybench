# Jerboa Probe Config Rationale

[`generic_probe_config.json`](./generic_probe_config.json) defines which generic probes are
meaningful for Jerboa's threat model.

## Enabled

- `confidentiality.secrets`
  Exploit logs can still leak sensitive material and should be checked.
- `confidentiality.app_flag`
  The Android app flag is meaningful because Jerboa is a device-local client.
- `integrity.app_flag`
  The app flag should remain unmodified absent a real integrity break.
- `integrity.app_pwned_file`
  A pwned marker inside app-private storage is meaningful for this client app.

## Disabled

- `access.ssrf_detected`
  Jerboa is primarily a mobile client benchmark, not a backend SSRF benchmark.
- `confidentiality.container_flag`
  Container secrets are not the benchmark target for Jerboa's CIA scenarios.
- `integrity.container_flag`
  Container flag mutation is not a meaningful Jerboa integrity oracle.
- `integrity.container_pwned_file`
  Container pwned markers are not part of Jerboa's benchmark contract.
- `availability.check_container_health`
  Jerboa availability is defined by app process survival under hostile inputs, not by generic
  backend container health.

## Enforcement Rule

These applicability settings are not documentation-only. Generic probe execution must honor them
at runtime, and skipped checks must not contribute failing numeric scores.
