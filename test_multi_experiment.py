#!/usr/bin/env python3
"""
Bare-bones Multi-Experiment Routing Check

This script performs two checks only:
1) Prerequisites: Docker is running and MCP server container is up
2) Routing: Each experiment_id routes via MCP to the correct environment using MCPToolExecutor

Usage:
    python test_multi_experiment.py

Prerequisites:
    - Docker running
    - MCP server running (docker compose up -d in agent/)
"""

import subprocess
import docker
from typing import Dict

# Test configuration
TEST_APPS = ["simplelogin", "bitwarden", "joplin"]


class MultiExperimentRoutingCheck:
    def __init__(self):
        self.docker_client = docker.from_env()

    def check_prerequisites(self) -> bool:
        print("🔍 Checking Prerequisites...")
        try:
            self.docker_client.ping()
            print("   ✅ Docker is running")
        except Exception:
            print("   ❌ Docker is not running or not accessible")
            return False
        # MCP server container
        try:
            result = subprocess.run([
                "docker", "ps", "--filter", "name=mcp-server", "--format", "{{.Status}}"
            ], capture_output=True, text=True, check=True)
            if "Up" in result.stdout:
                print("   ✅ MCP server is running")
            else:
                print("   ❌ MCP server is not running")
                print("   💡 Start it with: cd agent && docker compose up -d")
                return False
        except Exception:
            print("   ❌ Failed to check MCP server status")
            return False
        # Per-experiment Kali containers must exist and be running
        print("   🔎 Verifying Kali containers for each experiment...")
        all_ok = True
        for app in TEST_APPS:
            name = f"kali-container-{app}"
            try:
                c = self.docker_client.containers.get(name)
                is_running = (c.status == "running")
                status = "✅" if is_running else "❌"
                print(f"      {status} {app}: {name} status={c.status}")
                if not is_running:
                    all_ok = False
            except docker.errors.NotFound:
                print(f"      ❌ {app}: {name} not found")
                all_ok = False
            except Exception as e:
                print(f"      ❌ {app}: {name} check failed - {e}")
                all_ok = False
        if not all_ok:
            print("   ❌ One or more Kali containers are missing or not running")
        else:
            print("   ✅ All Kali containers are running")
        return all_ok

    def check_kali_containers(self) -> Dict[str, bool]:
        """Ensure per-experiment Kali containers are present and running."""
        print("\n🔍 Checking Kali containers per experiment...")
        results: Dict[str, bool] = {}
        for app in TEST_APPS:
            name = f"kali-container-{app}"
            try:
                c = self.docker_client.containers.get(name)
                is_running = (c.status == "running")
                results[app] = is_running
                status = "✅" if is_running else "❌"
                print(f"   {status} {app}: {name} status={c.status}")
            except docker.errors.NotFound:
                results[app] = False
                print(f"   ❌ {app}: {name} not found")
            except Exception as e:
                results[app] = False
                print(f"   ❌ {app}: {name} check failed - {e}")
        return results

    def check_routing(self) -> Dict[str, bool]:
        print("\n🔍 Testing MCP Routing via MCPToolExecutor...")
        results: Dict[str, bool] = {}
        try:
            from agent.mcp.direct_tool_executor import MCPToolExecutor
            executor = MCPToolExecutor()
            for app in TEST_APPS:
                try:
                    # Non-ADB command path
                    resp_shell = executor.call_tool(
                        tool_name="execute_command",
                        command="echo 'Hello from experiment'",
                        experiment_id=app,
                    )
                    ok_shell = ("error" not in resp_shell)

                    # ADB command path (exercises ADB branch)
                    resp_adb = executor.call_tool(
                        tool_name="execute_command",
                        command="adb shell echo routed",
                        experiment_id=app,
                    )
                    ok_adb = ("error" not in resp_adb)

                    results[app] = ok_shell and ok_adb
                    status = "✅" if results[app] else "❌"
                    print(
                        f"   {status} {app}: routing shell={'ok' if ok_shell else 'fail'}, adb={'ok' if ok_adb else 'fail'}"
                    )
                except Exception as e:
                    results[app] = False
                    print(f"   ❌ {app}: Routing failed - {e}")
        except Exception as e:
            print(f"   ❌ Failed to initialize MCPToolExecutor: {e}")
            results = {app: False for app in TEST_APPS}
        return results


def main():
    print("Bare-bones Multi-Experiment Routing Check\n")
    checker = MultiExperimentRoutingCheck()
    if not checker.check_prerequisites():
        return 1
    print("\n🚀 Running routing checks...\n")
    routing_results = checker.check_routing()
    routing_passed = sum(1 for v in routing_results.values() if v)
    routing_total = len(routing_results)
    routing_status = "✅ PASS" if routing_passed == routing_total else "❌ FAIL"
    print(f"\nSummary:")
    print(f"routing: {routing_status} ({routing_passed}/{routing_total})")
    overall_ok = (routing_passed == routing_total)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    exit(main())
