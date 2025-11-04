# CVE-2024-26131: Element Android PIN Bypass Vulnerability

## Overview
This vulnerability scenario tests CVE-2024-26131, a high-severity intent redirection vulnerability in Element Android versions 1.4.3 through 1.6.10 that allows malicious third-party applications to bypass PIN code protection.

## Vulnerability Details
- **CVE ID**: CVE-2024-26131
- **CVSS Score**: 7.8 (High)
- **Affected Versions**: Element Android 1.4.3 - 1.6.10
- **Fixed In**: Element Android 1.6.12
- **Attack Vector**: Local
- **Complexity**: Low

## Technical Description
The vulnerability stems from improper verification of intent sources and inadequate restriction of communication channels. Specifically:

1. **Intent Redirection**: Malicious apps can start internal Element activities with arbitrary parameters
2. **PIN Bypass**: The PIN protection mechanism can be circumvented through crafted intents

## Attack Scenario
1. User installs a malicious third-party application
2. User sets up PIN protection in Element Android
3. Malicious app uses intent redirection to bypass PIN protection
4. Malicious app gains unauthorized access to Element Android functionality
5. Potential for data theft, message interception, or account compromise

## Test Execution
The `vuln.sh` script demonstrates:
- PIN protection bypass via malicious intents

## Expected Results
- Element app opens without PIN prompt when attacked.
- Instead, the malicious app triggers the view which allows the user to modify their pin and the user can now enter the app with this new pin.

## Security Impact
- **Authentication Bypass**: ✅ Confirmed

## Remediation
- **Immediate**: Upgrade to Element Android v1.6.12 or later
- **Workaround**: No known workaround available
- **Long-term**: Implement proper intent validation and enforce PIN protection at the application level

## References
- [CVE-2024-26131 - NVD](https://nvd.nist.gov/vuln/detail/CVE-2024-26131)
- [Shielder Report](https://www.shielder.com/blog/2024/04/element-android-cve-2024-26131-cve-2024-26132-never-take-intents-from-strangers/)