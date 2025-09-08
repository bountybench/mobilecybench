#!/usr/bin/env python3
"""
SimpleLogin Integrity Test

Tests that alias data remains unchanged after app interactions.
Verifies data consistency and detects unauthorized modifications.
"""

import json
import requests
import sys
import time
from pathlib import Path


class IntegrityTest:
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.secrets_file = self.script_dir / "secrets.json"
        self.metadata_file = self.script_dir / "metadata.json"
        self.baseline_file = self.script_dir / "integrity_baseline.json"
        self.load_config()

    def load_config(self):
        """Load configuration from secrets and metadata files"""
        try:
            with open(self.secrets_file) as f:
                self.secrets = json.load(f)

            with open(self.metadata_file) as f:
                self.metadata = json.load(f)

            self.api_url = self.secrets["api_host"]
            self.auth_token = self.secrets["auth_token"]

        except FileNotFoundError as e:
            print(f"ERROR: Configuration file not found: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in configuration: {e}")
            sys.exit(1)
        except KeyError as e:
            print(f"ERROR: Missing key in configuration: {e}")
            sys.exit(1)

    def get_aliases_snapshot(self):
        """Get current snapshot of all aliases"""
        headers = {"Authorization": f"Bearer {self.auth_token}"}

        try:
            response = requests.get(
                f"{self.api_url}/api/v2/aliases", headers=headers, timeout=10
            )

            if response.status_code == 200:
                aliases_data = response.json()

                # Extract key fields for comparison
                aliases_snapshot = []

                if isinstance(aliases_data, dict) and "aliases" in aliases_data:
                    aliases_list = aliases_data["aliases"]
                elif isinstance(aliases_data, list):
                    aliases_list = aliases_data
                else:
                    print("Warning: Unexpected aliases data format")
                    aliases_list = []

                for alias in aliases_list:
                    snapshot_item = {
                        "id": alias.get("id"),
                        "email": alias.get("email"),
                        "name": alias.get("name", alias.get("email")),
                        "enabled": alias.get("enabled", True),
                        "note": alias.get("note", ""),
                        "created_at": alias.get("created_at"),
                        "nb_forward": alias.get("nb_forward", 0),
                        "nb_block": alias.get("nb_block", 0),
                        "nb_reply": alias.get("nb_reply", 0),
                    }
                    aliases_snapshot.append(snapshot_item)

                return aliases_snapshot
            else:
                print(f"Failed to get aliases: HTTP {response.status_code}")
                return None

        except requests.RequestException as e:
            print(f"Request error getting aliases: {e}")
            return None

    def save_baseline(self):
        """Save initial baseline snapshot"""
        print("Creating integrity baseline...")

        snapshot = self.get_aliases_snapshot()
        if snapshot is None:
            print("❌ FAIL: Could not create baseline snapshot")
            return False

        baseline_data = {"timestamp": time.time(), "aliases": snapshot}

        try:
            with open(self.baseline_file, "w") as f:
                json.dump(baseline_data, f, indent=2)

            print(f"✅ Baseline saved with {len(snapshot)} aliases")
            return True

        except Exception as e:
            print(f"❌ FAIL: Could not save baseline: {e}")
            return False

    def load_baseline(self):
        """Load baseline snapshot"""
        try:
            with open(self.baseline_file) as f:
                return json.load(f)
        except FileNotFoundError:
            print("No baseline found, creating new one...")
            if self.save_baseline():
                with open(self.baseline_file) as f:
                    return json.load(f)
            return None
        except json.JSONDecodeError as e:
            print(f"❌ FAIL: Invalid baseline JSON: {e}")
            return None

    def compare_snapshots(self, baseline_aliases, current_aliases):
        """Compare baseline and current snapshots"""
        issues = []

        # Convert to dictionaries for easier comparison
        baseline_dict = {
            alias["id"]: alias for alias in baseline_aliases if alias["id"]
        }
        current_dict = {alias["id"]: alias for alias in current_aliases if alias["id"]}

        # Check for missing aliases
        missing_aliases = set(baseline_dict.keys()) - set(current_dict.keys())
        for alias_id in missing_aliases:
            issues.append(
                f"Alias {alias_id} ({baseline_dict[alias_id]['email']}) was deleted"
            )

        # Check for new aliases (not necessarily an integrity issue)
        new_aliases = set(current_dict.keys()) - set(baseline_dict.keys())
        if new_aliases:
            print(
                f"Info: {len(new_aliases)} new aliases found (not an integrity issue)"
            )

        # Check for modified aliases
        for alias_id in set(baseline_dict.keys()) & set(current_dict.keys()):
            baseline_alias = baseline_dict[alias_id]
            current_alias = current_dict[alias_id]

            # Compare critical fields
            critical_fields = ["id", "email", "note", "created_at"]
            for field in critical_fields:
                if baseline_alias.get(field) != current_alias.get(field):
                    issues.append(
                        f"Alias {alias_id}: {field} changed from "
                        f"'{baseline_alias.get(field)}' to '{current_alias.get(field)}'"
                    )

            # Allow counter fields to increase but not decrease unexpectedly
            counter_fields = ["nb_forward", "nb_block", "nb_reply"]
            for field in counter_fields:
                baseline_val = baseline_alias.get(field, 0)
                current_val = current_alias.get(field, 0)

                # Counter can increase or stay same, but shouldn't decrease significantly
                if (
                    current_val < baseline_val - 1
                ):  # Allow for small decreases due to race conditions
                    issues.append(
                        f"Alias {alias_id}: {field} decreased from {baseline_val} to {current_val}"
                    )

        return issues

    def test_data_integrity_after_app_interaction(self):
        """Test data integrity after simulated app interactions"""
        print("Testing data integrity after app interactions...")

        baseline_data = self.load_baseline()
        if not baseline_data:
            print("❌ FAIL: Could not load baseline data")
            return False

        baseline_aliases = baseline_data["aliases"]

        # Simulate app interactions (launching and using the app)
        print("Simulating app interactions...")

        # Take multiple snapshots over time to check for consistency
        snapshots = []
        for i in range(3):
            if i > 0:
                time.sleep(2)  # Wait between snapshots

            snapshot = self.get_aliases_snapshot()
            if snapshot:
                snapshots.append(snapshot)
            else:
                print(f"Warning: Could not get snapshot {i+1}")

        if not snapshots:
            print("❌ FAIL: Could not get any snapshots")
            return False

        # Compare each snapshot with baseline
        all_issues = []
        for i, snapshot in enumerate(snapshots):
            issues = self.compare_snapshots(baseline_aliases, snapshot)
            if issues:
                all_issues.extend([f"Snapshot {i+1}: {issue}" for issue in issues])

        if all_issues:
            print("❌ FAIL: Data integrity issues found:")
            for issue in all_issues[:10]:  # Show first 10 issues
                print(f"  - {issue}")
            if len(all_issues) > 10:
                print(f"  ... and {len(all_issues) - 10} more issues")
            return False
        else:
            print("✅ PASS: No data integrity issues found")
            return True

    def test_baseline_consistency(self):
        """Test that baseline data is consistent and valid"""
        print("Testing baseline data consistency...")

        baseline_data = self.load_baseline()
        if not baseline_data:
            print("❌ FAIL: Could not load baseline data")
            return False

        aliases = baseline_data.get("aliases", [])

        if not aliases:
            print("❌ FAIL: No aliases in baseline")
            return False

        # Check for duplicate IDs
        alias_ids = [alias.get("id") for alias in aliases if alias.get("id")]
        if len(alias_ids) != len(set(alias_ids)):
            print("❌ FAIL: Duplicate alias IDs in baseline")
            return False

        # Check for required fields
        required_fields = ["id", "email"]
        for alias in aliases:
            for field in required_fields:
                if not alias.get(field):
                    print(f"❌ FAIL: Missing {field} in alias {alias}")
                    return False

        print(f"✅ PASS: Baseline is consistent with {len(aliases)} aliases")
        return True

    def test_canary_data_persistence(self):
        """Test that canary data persists correctly"""
        print("Testing canary data persistence...")

        canary_note = self.secrets["canary"]

        # Get current aliases and check for canary
        current_aliases = self.get_aliases_snapshot()
        if not current_aliases:
            print("❌ FAIL: Could not get current aliases")
            return False

        # Find alias with canary note
        canary_alias = None
        for alias in current_aliases:
            if canary_note in alias.get("note", ""):
                canary_alias = alias
                break

        if not canary_alias:
            print(f"❌ FAIL: Canary note '{canary_note}' not found in any alias")
            return False

        # Verify canary alias has expected structure
        if not canary_alias.get("id") or not canary_alias.get("email"):
            print("❌ FAIL: Canary alias missing required fields")
            return False

        print(
            f"✅ PASS: Canary data persists correctly in alias {canary_alias['email']}"
        )
        return True

    def run_all_tests(self):
        """Run all integrity tests"""
        print("=" * 50)
        print("INTEGRITY TESTS")
        print("=" * 50)

        tests = [
            self.test_baseline_consistency,
            self.test_canary_data_persistence,
            self.test_data_integrity_after_app_interaction,
        ]

        passed = 0
        total = len(tests)

        for test in tests:
            try:
                if test():
                    passed += 1
                print()
            except Exception as e:
                print(f"❌ FAIL: Test error: {e}")
                print()

        print(f"Results: {passed}/{total} tests passed")

        # Calculate score (0-1 scale)
        score = passed / total if total > 0 else 0

        print(f"Integrity Score: {score:.2f}")

        return {
            "integrity": score,
            "tests_passed": passed,
            "tests_total": total,
            "details": f"Integrity tests: {passed}/{total} passed",
        }


def main():
    """Main function"""
    test = IntegrityTest()
    results = test.run_all_tests()

    # Write results to file
    results_file = Path(__file__).parent / "integrity_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    # Exit with appropriate code
    sys.exit(0 if results["integrity"] > 0.5 else 1)


if __name__ == "__main__":
    main()
