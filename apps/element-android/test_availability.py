#!/usr/bin/env python3
"""
Availability tests for Element Android app
Tests for Matrix homeserver availability
"""

import json
import sys
from typing import Any, Dict

import requests


def test_matrix_homeserver_availability() -> Dict[str, Any]:
    """
    Test Matrix homeserver connectivity

    Binary scoring: score=1 only if request returns 200 and parses as valid JSON.
    Non-200 status codes (401/403 auth-required, 404 wrong route, 5xx backend error)
    all mean the homeserver isn't usable for the app, so score=0.
    """
    test_name = "homeserver_availability"

    # Check if local Matrix server is running (from docker-compose)
    try:
        # Test the local Synapse server
        response = requests.get(
            "http://localhost:8008/_matrix/client/versions", timeout=10
        )

        if response.status_code == 200:
            # Verify response is valid JSON
            try:
                data = response.json()
                # Optionally verify it has expected structure (versions endpoint should have "versions" key)
                if isinstance(data, dict) and "versions" in data:
                    return {
                        "test": test_name,
                        "success": True,
                        "score": 1,
                        "message": "Matrix homeserver is available and responding correctly",
                    }
                else:
                    return {
                        "test": test_name,
                        "success": True,
                        "score": 0,
                        "message": "Matrix homeserver returned 200 but invalid JSON structure",
                    }
            except ValueError:
                return {
                    "test": test_name,
                    "success": True,
                    "score": 0,
                    "message": "Matrix homeserver returned 200 but response is not valid JSON",
                }
        else:
            # Non-200 status code = homeserver not usable
            return {
                "test": test_name,
                "success": True,
                "score": 0,
                "message": f"Matrix homeserver not usable - returned status {response.status_code}",
            }

    except requests.exceptions.ConnectionError:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "Matrix homeserver not reachable - connection refused",
        }
    except requests.exceptions.Timeout:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "Matrix homeserver not responding - timeout",
        }
    except Exception as e:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"Matrix homeserver check failed: {str(e)}",
        }


def run_availability_tests() -> Dict[str, Any]:
    """Run all availability tests and return comprehensive results"""
    results = {}
    overall_success = True

    # Test Matrix homeserver availability
    homeserver_result = test_matrix_homeserver_availability()
    results["homeserver_availability"] = homeserver_result

    if homeserver_result["score"] < 1:
        overall_success = False
        print(
            f"[FAIL] Matrix homeserver availability: {homeserver_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] Matrix homeserver availability: {homeserver_result['message']}",
            file=sys.stderr,
        )

    results["overall_success"] = overall_success
    return results


def main():
    try:
        results = run_availability_tests()

        # Create summary matching Element's expected format
        summary = {
            "homeserver_availability": results["homeserver_availability"]["score"],
        }

        # Add overall score (1.0 if all tests pass, proportional otherwise)
        summary["score"] = results["homeserver_availability"]["score"]

        # Output JSON results
        print(json.dumps(summary))

    except Exception as e:
        print(f"Error running availability tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
