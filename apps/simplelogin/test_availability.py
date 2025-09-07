#!/usr/bin/env python3
"""
SimpleLogin Availability Test

Tests that the app and backend services are available and responsive.
Verifies system health and basic functionality.
"""

import json
import requests
import subprocess
import sys
import time
from pathlib import Path


class AvailabilityTest:
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.secrets_file = self.script_dir / "secrets.json"
        self.metadata_file = self.script_dir / "metadata.json"
        self.load_config()
    
    def load_config(self):
        """Load configuration from secrets and metadata files"""
        try:
            with open(self.metadata_file) as f:
                self.metadata = json.load(f)
            
            # Use metadata for primary config, fallback to secrets for compatibility
            if self.secrets_file.exists():
                with open(self.secrets_file) as f:
                    self.secrets = json.load(f)
                self.api_url = self.secrets.get("api_host", self.metadata["backend"]["base_url_host"])
            else:
                self.api_url = self.metadata["backend"]["base_url_host"]
            
            self.app_id = self.metadata["app_id"]
            self.endpoints = self.metadata["backend"]["endpoints"]
            self.expected_codes = self.metadata["backend"]["expected_status_codes"]
            
        except FileNotFoundError as e:
            print(f"ERROR: Configuration file not found: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in configuration: {e}")
            sys.exit(1)
        except KeyError as e:
            print(f"ERROR: Missing key in configuration: {e}")
            sys.exit(1)
    
    def _detect_compose_cmd(self):
        """Detect available docker compose command"""
        try:
            subprocess.run(["docker", "compose", "--version"], 
                         capture_output=True, check=True)
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                subprocess.run(["docker-compose", "--version"], 
                             capture_output=True, check=True)
                return ["docker-compose"]
            except (subprocess.CalledProcessError, FileNotFoundError):
                return None
    
    def test_backend_health(self):
        """Test backend service health"""
        print("Testing backend service health...")
        
        # Test multiple endpoints for comprehensive health check
        endpoints = [
            {"path": "/api/auth/login", "method": "GET", "expect_codes": [200, 405, 401]},
            {"path": "/api/user/info", "method": "GET", "expect_codes": [200, 401, 403]},
            {"path": "/", "method": "GET", "expect_codes": [200, 404]},
            {"path": "/health", "method": "GET", "expect_codes": [200, 404]},
        ]
        
        healthy_endpoints = 0
        
        for endpoint in endpoints:
            try:
                if endpoint["method"] == "GET":
                    response = requests.get(
                        f"{self.api_url}{endpoint['path']}",
                        timeout=10
                    )
                else:
                    continue
                
                if response.status_code in endpoint["expect_codes"]:
                    healthy_endpoints += 1
                    print(f"  ✅ {endpoint['path']}: {response.status_code}")
                else:
                    print(f"  ❌ {endpoint['path']}: {response.status_code} (expected {endpoint['expect_codes']})")
                    
            except requests.RequestException as e:
                print(f"  ❌ {endpoint['path']}: Connection error - {e}")
        
        # Consider backend healthy if at least half the endpoints respond correctly
        if healthy_endpoints >= len(endpoints) // 2:
            print("✅ PASS: Backend service is healthy")
            return True
        else:
            print(f"❌ FAIL: Backend unhealthy ({healthy_endpoints}/{len(endpoints)} endpoints working)")
            return False
    
    def test_docker_containers_running(self):
        """Test that Docker containers are running"""
        print("Testing Docker containers status...")
        
        try:
            # Check docker-compose services
            result = subprocess.run(
                ["docker-compose", "ps", "--services", "--filter", "status=running"],
                cwd=self.script_dir,
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode == 0:
                running_services = result.stdout.strip().split('\n')
                running_services = [s for s in running_services if s]  # Remove empty strings
                
                if len(running_services) >= 2:  # Expect at least db and api
                    print(f"✅ PASS: {len(running_services)} Docker services running")
                    return True
                else:
                    print(f"❌ FAIL: Only {len(running_services)} Docker services running")
                    return False
            else:
                print(f"❌ FAIL: docker-compose ps failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ FAIL: Docker command timeout")
            return False
        except subprocess.CalledProcessError as e:
            print(f"❌ FAIL: Docker command error: {e}")
            return False
        except FileNotFoundError:
            print("❌ FAIL: docker-compose not found")
            return False
    
    def test_app_installation(self):
        """Test that the app is installed on the device"""
        print("Testing app installation...")
        
        try:
            result = subprocess.run(
                ["adb", "shell", "pm", "list", "packages", self.app_id],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and self.app_id in result.stdout:
                print(f"✅ PASS: App {self.app_id} is installed")
                return True
            else:
                print(f"❌ FAIL: App {self.app_id} is not installed")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ FAIL: ADB command timeout")
            return False
        except subprocess.CalledProcessError as e:
            print(f"❌ FAIL: ADB command error: {e}")
            return False
        except FileNotFoundError:
            print("❌ FAIL: adb not found")
            return False
    
    def test_app_launch(self):
        """Test that the app can be launched"""
        print("Testing app launch capability...")
        
        try:
            # Try to launch the app
            result = subprocess.run(
                ["adb", "shell", "monkey", "-p", self.app_id, "-c", "android.intent.category.LAUNCHER", "1"],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            # Wait a moment for app to start
            time.sleep(3)
            
            # Check if app is running
            ps_result = subprocess.run(
                ["adb", "shell", "pidof", self.app_id],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if ps_result.returncode == 0 and ps_result.stdout.strip():
                print(f"✅ PASS: App launched successfully (PID: {ps_result.stdout.strip()})")
                return True
            else:
                print("❌ FAIL: App did not start or is not running")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ FAIL: App launch timeout")
            return False
        except subprocess.CalledProcessError as e:
            print(f"❌ FAIL: App launch error: {e}")
            return False
    
    def test_device_connectivity(self):
        """Test Android device/emulator connectivity"""
        print("Testing device connectivity...")
        
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Look for connected devices
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                connected_devices = [line for line in lines if 'device' in line and not line.endswith('offline')]
                
                if connected_devices:
                    print(f"✅ PASS: {len(connected_devices)} device(s) connected")
                    return True
                else:
                    print("❌ FAIL: No devices connected")
                    return False
            else:
                print(f"❌ FAIL: adb devices failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ FAIL: ADB devices command timeout")
            return False
        except subprocess.CalledProcessError as e:
            print(f"❌ FAIL: ADB devices command error: {e}")
            return False
        except FileNotFoundError:
            print("❌ FAIL: adb not found")
            return False
    
    def test_api_response_time(self):
        """Test API response time"""
        print("Testing API response time...")
        
        try:
            start_time = time.time()
            response = requests.get(
                f"{self.api_url}/api/auth/login",
                timeout=10
            )
            end_time = time.time()
            
            response_time = end_time - start_time
            
            # Consider response time good if under 5 seconds
            if response_time < 5.0:
                print(f"✅ PASS: API response time: {response_time:.2f}s")
                return True
            else:
                print(f"❌ FAIL: API response time too slow: {response_time:.2f}s")
                return False
                
        except requests.RequestException as e:
            print(f"❌ FAIL: API request error: {e}")
            return False
    
    def test_ui_elements_present(self):
        """Test that basic UI elements are present"""
        print("Testing UI elements presence...")
        
        try:
            # Get UI dump
            result = subprocess.run(
                ["adb", "shell", "uiautomator", "dump", "--compressed", "/dev/stdout"],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode == 0:
                ui_content = result.stdout.lower()
                
                # Look for common login/app elements
                expected_elements = [
                    "email",
                    "password",
                    "login",
                    "simplelogin"
                ]
                
                found_elements = []
                for element in expected_elements:
                    if element in ui_content:
                        found_elements.append(element)
                
                if len(found_elements) >= 2:  # At least 2 expected elements
                    print(f"✅ PASS: Found UI elements: {', '.join(found_elements)}")
                    return True
                else:
                    print(f"❌ FAIL: Only found {len(found_elements)} expected UI elements")
                    return False
            else:
                print("❌ FAIL: Could not get UI dump")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ FAIL: UI dump timeout")
            return False
        except subprocess.CalledProcessError as e:
            print(f"❌ FAIL: UI dump error: {e}")
            return False
    
    def run_all_tests(self):
        """Run all availability tests"""
        print("=" * 50)
        print("AVAILABILITY TESTS")
        print("=" * 50)
        
        tests = [
            self.test_device_connectivity,
            self.test_docker_containers_running,
            self.test_backend_health,
            self.test_api_response_time,
            self.test_app_installation,
            self.test_app_launch,
            self.test_ui_elements_present
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
        
        print(f"Availability Score: {score:.2f}")
        
        return {
            "availability": score,
            "tests_passed": passed,
            "tests_total": total,
            "details": f"Availability tests: {passed}/{total} passed"
        }


def main():
    """Main function"""
    test = AvailabilityTest()
    results = test.run_all_tests()
    
    # Write results to file
    results_file = Path(__file__).parent / "availability_results.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Exit with appropriate code
    sys.exit(0 if results["availability"] > 0.5 else 1)


if __name__ == "__main__":
    main()
