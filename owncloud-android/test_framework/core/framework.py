#!/usr/bin/env python3
"""
Lightweight End-to-End Vulnerability Testing Framework
Designed for testing Android app vulnerabilities in a defensive security context
"""

import json
import time
import subprocess

from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import os
import logging

from .engine import AttackEngine
from .analyzer import TestAnalyzer
from .android_probes import AndroidSecurityProbe
from .utils import DatabaseUtils, FilesystemUtils


logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/debug.log', mode='w'),
        logging.StreamHandler()
    ]
)

class TestResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL" 
    ERROR = "ERROR"
    SKIP = "SKIP"


class TestSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TestCase:
    """Individual vulnerability test case definition"""
    name: str
    description: str
    payload: str
    severity: TestSeverity
    exploit_type: str  # "path_traversal_write", "arbitrary_upload", etc.
    category: str = "General"
    content: str = "TestPayload"
    timeout: int = 60
    enabled: bool = True


@dataclass
class TestExecutionResult:
    """Result of a single test execution"""
    test_case: TestCase
    result: TestResult
    message: str
    execution_time: float
    timestamp: str
    evidence: Optional[Dict[str, Any]] = None
    vulnerability_confirmed: bool = False


class TestExecutor:
    """Handles exploit execution and analysis only"""
    
    def __init__(self, device_id: Optional[str] = None):
        self.device_id = device_id
        self.probe = AndroidSecurityProbe(device_id, auto_enable_root=True)
        self.engine = AttackEngine(device_id)
        
        # Create timestamped working directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.working_dir = Path("output") / f"{timestamp}-data"
        self.working_dir.mkdir(parents=True, exist_ok=True)
        
        self.before_state_captured = False
        self.after_state_captured = False
    
    def capture_before_state(self) -> Dict[str, Path]:
        """Capture system state before all exploits (called once)"""
        if self.before_state_captured:
            return {
                "fs_snapshot": self.working_dir / "before_local_dir.json",
                "db_before": self.working_dir / "before_databases"
            }
        
        paths = {
            "fs_snapshot": self.working_dir / "before_local_dir.json",
            "db_before": self.working_dir / "before_databases"
        }
        
        try:
            # Capture filesystem state
            self.probe.pull_private_directory(
                local_path=str(paths["fs_snapshot"])
            )
            
            # Pull database state
            self.probe.pull_databases(str(paths["db_before"]))
            
            self.before_state_captured = True
            return paths
        except Exception as e:
            logging.error(f"Before state capture error: {e}")
            return {}
    
    def capture_after_state(self) -> Dict[str, Path]:
        """Capture system state after all exploits (called once at the end)"""
        if self.after_state_captured:
            return {
                "fs_snapshot": self.working_dir / "after_local_dir.json",
                "db_after": self.working_dir / "after_databases"
            }
        
        paths = {
            "fs_snapshot": self.working_dir / "after_local_dir.json",
            "db_after": self.working_dir / "after_databases"
        }
        
        try:
            # Capture filesystem state
            self.probe.pull_private_directory(
                local_path=str(paths["fs_snapshot"])
            )
            
            # Pull database state
            self.probe.pull_databases(str(paths["db_after"]))
            
            self.after_state_captured = True
            return paths
        except Exception as e:
            logging.error(f"After state capture error: {e}")
            return {}
    
    def execute_exploit(self, test_case: TestCase) -> Dict[str, Any]:
        """Execute the vulnerability exploit"""
        if test_case.exploit_type == "path_traversal_write":
            return self.engine.execute_path_traversal_write_txt(
                test_case.payload, test_case.content
            )
        elif test_case.exploit_type == "arbitrary_upload":
            return self.engine.execute_arbitary_file_upload_from_internal_storage(
                test_case.payload
            )
        else:
            return {"error": f"Unknown exploit type: {test_case.exploit_type}"}
    
    def analyze_all_results(self, before_paths: Dict[str, Path], 
                           after_paths: Dict[str, Path]) -> Dict[str, Any]:
        """Analyze before/after state changes"""
        analysis = {
            "filesystem_changes": {},
            "database_changes": {},
            "vulnerability_indicators": []
        }
        
        try:
            # Analyze filesystem changes
            if "fs_snapshot" in before_paths and "fs_snapshot" in after_paths:
                fs_diff = FilesystemUtils.compare_snapshots(
                    before_paths["fs_snapshot"],
                    after_paths["fs_snapshot"],
                    # extension=".txt",  # IMPORTANT - Compare all files, not just .txt
                    output_json=self.working_dir / "fs_changes.json"
                )
                analysis["filesystem_changes"] = fs_diff
            
            # Analyze database changes
            db_before = before_paths.get("db_before")
            db_after = after_paths.get("db_after")
            if db_before and db_after:
                try:
                    db_diff = DatabaseUtils.compare_table(
                        db_before / "filelist",
                        db_after / "filelist",
                        "list_of_uploads"
                    )
                    analysis["database_changes"] = db_diff
                    DatabaseUtils.save_diff_to_json(
                        db_diff, 
                        self.working_dir / "db_changes.json"
                    )
                except Exception as e:
                    logging.error(f"Database analysis error: {e}")
            
            # Run vulnerability-specific analysis
            fs_changes_file = self.working_dir / "fs_changes.json"
            db_changes_file = self.working_dir / "db_changes.json"
            
            if fs_changes_file.exists() and db_changes_file.exists():
                analyzer = TestAnalyzer(str(db_changes_file), str(fs_changes_file))
                analyzer.load_data()
                
                # Check for vulnerability indicators using active methods
                indicators = []
                
                # Check for sensitive file access/exposure (main method)
                sensitive_result = analyzer.is_sensitive_file_accessed()
                if sensitive_result["found"]:
                    for match in sensitive_result["matches"]:
                        exposure_type = match["exposure_type"]
                        if exposure_type == "database":
                            indicators.append("database exposed")
                        elif exposure_type == "log":
                            indicators.append("log files exposed")
                        elif exposure_type == "config":
                            indicators.append("config files exposed")
                        else:
                            indicators.append("other sensitive files exposed")
                
                # Check for unsafe txt file activity (path traversal)
                if analyzer._check_unsafe_txt_file_activity():
                    indicators.append("path traversal detected: txt files written in unsafe locations")
                
                # Remove duplicates while preserving order
                seen = set()
                unique_indicators = []
                for indicator in indicators:
                    if indicator not in seen:
                        seen.add(indicator)
                        unique_indicators.append(indicator)
                
                analysis["vulnerability_indicators"] = unique_indicators
                
        except Exception as e:
            logging.error(f"Analysis error: {e}")
            analysis["analysis_error"] = str(e)
        
        return analysis


class TestRunner:
    """Main test runner that orchestrates test execution"""
    
    def __init__(self, device_id: Optional[str] = None):
        self.executor = TestExecutor(device_id)
        self.test_cases: List[TestCase] = []
        self.results: List[TestExecutionResult] = []
        self.analysis: Dict[str, Any] = {}
        
    def add_test_case(self, test_case: TestCase):
        """Add a test case to the runner"""
        self.test_cases.append(test_case)
    
    def load_test_cases_from_file(self, config_file: str):
        """Load test cases from JSON configuration file"""
        with open(config_file, 'r') as f:
            config = json.load(f)
        for test_config in config.get("test_cases", []):
            test_case = TestCase(
                name=test_config["name"],
                description=test_config["description"],
                payload=test_config["payload"],
                severity=TestSeverity(test_config.get("severity", "medium")),
                exploit_type=test_config["exploit_type"],
                category=test_config.get("category", "General"),
                content=test_config.get("content", "TestPayload"),
                timeout=test_config.get("timeout", 60),
                enabled=test_config.get("enabled", True)
            )
            self.add_test_case(test_case)
    
    def run_single_test(self, test_case: TestCase) -> Dict[str, Any]:
        """Execute a single test case (exploit only - no state capture)"""
        start_time = time.time()

        logging.info(f"[>] Running exploit: {test_case.name}")

        try:
            # Execute exploit only
            logging.info("Executing exploit...")
            exploit_result = self.executor.execute_exploit(test_case)

            # Remove any file checking/verification fields from exploit_result if present
            minimal_result = {
                k: v for k, v in exploit_result.items()
                if k in ("command_executed", "output", "error", "ui_interaction", "source_file")
            }

            return {
                "test_case": test_case,
                "exploit_result": minimal_result,
                "execution_time": time.time() - start_time,
                "success": minimal_result.get("command_executed", False)
            }

        except Exception as e:
            return {
                "test_case": test_case,
                "exploit_result": {"error": str(e)},
                "execution_time": time.time() - start_time,
                "success": False
            }
    
    def run_all_tests(self) -> List[TestExecutionResult]:
        """Execute all enabled test cases with optimized state capture"""
        logging.info("Starting vulnerability test framework")
        logging.info(f"Running {len([tc for tc in self.test_cases if tc.enabled])} enabled test cases")
        logging.info("Note: Assumes app is installed and environment is ready")
        
        # Step 1: Capture before state (once)
        logging.info("Capturing initial state...")
        before_paths = self.executor.capture_before_state()
        if not before_paths:
            logging.error("Failed to capture before state")
            return []
        
        # Step 2: Run all exploits
        exploit_results = []
        for test_case in self.test_cases:
            if not test_case.enabled:
                logging.info(f"Skipping disabled test: {test_case.name}")
                continue
                
            result = self.run_single_test(test_case)
            exploit_results.append(result)
            
            # Print exploit result
            status_icon = "✅" if result["success"] else "❌"
            logging.info(f"[{status_icon}] Exploit executed: {result['success']}")
            logging.info(f"Execution time: {result['execution_time']:.2f}s")
        
        # Step 3: Capture after state (once)
        logging.info("Capturing final state...")
        after_paths = self.executor.capture_after_state()
        
        # Step 4: Analyze all results (once)
        logging.info("Analyzing all results...")
        analysis = self.executor.analyze_all_results(before_paths, after_paths)
        
        # Step 5: Generate final test results
        self.results = []
        vulnerability_indicators = analysis.get("vulnerability_indicators", [])
        
        for exploit_result in exploit_results:
            test_case = exploit_result["test_case"]
            
            # Determine if this specific test contributed to vulnerabilities
            vulnerability_confirmed = len(vulnerability_indicators) > 0
            
            if vulnerability_confirmed:
                result = TestResult.PASS
                message = f"Vulnerability confirmed: {', '.join(vulnerability_indicators)}"
            elif exploit_result["success"]:
                result = TestResult.FAIL
                message = "Exploit executed but no vulnerability indicators detected"
            else:
                result = TestResult.ERROR
                message = f"Exploit failed: {exploit_result['exploit_result'].get('error', 'Unknown error')}"
            
            test_execution_result = TestExecutionResult(
                test_case=test_case,
                result=result,
                message=message,
                execution_time=exploit_result["execution_time"],
                timestamp=datetime.now().isoformat(),
                evidence={
                    "exploit_result": exploit_result["exploit_result"]
                },
                vulnerability_confirmed=vulnerability_confirmed
            )
            
            self.results.append(test_execution_result)
        
        # Store analysis separately to avoid duplication
        self.analysis = analysis
        
        self.print_summary()
        return self.results
    
    def run_test_by_name(self, test_name: str) -> Optional[TestExecutionResult]:
        """Run a specific test by name with full analysis workflow"""
        target_test = None
        for test_case in self.test_cases:
            if test_case.name == test_name:
                target_test = test_case
                break
        
        if not target_test:
            print(f"❌ Test case '{test_name}' not found")
            return None
        
        # Run single test with full workflow
        print(f"🚀 Running single test: {test_name}")
        
        # Step 1: Capture before state
        print("📊 Capturing initial state...")
        before_paths = self.executor.capture_before_state()
        if not before_paths:
            print("❌ Failed to capture before state")
            return None
        
        # Step 2: Execute exploit
        exploit_result = self.run_single_test(target_test)
        
        # Step 3: Capture after state
        print("📊 Capturing final state...")
        after_paths = self.executor.capture_after_state()
        
        # Step 4: Analyze results
        print("🔍 Analyzing results...")
        analysis = self.executor.analyze_all_results(before_paths, after_paths)
        
        # Generate result
        vulnerability_indicators = analysis.get("vulnerability_indicators", [])
        vulnerability_confirmed = len(vulnerability_indicators) > 0
        
        if vulnerability_confirmed:
            result = TestResult.PASS
            message = f"Vulnerability confirmed: {', '.join(vulnerability_indicators)}"
        elif exploit_result["success"]:
            result = TestResult.FAIL
            message = "Exploit executed but no vulnerability indicators detected"
        else:
            result = TestResult.ERROR
            message = f"Exploit failed: {exploit_result['exploit_result'].get('error', 'Unknown error')}"
        
        test_execution_result = TestExecutionResult(
            test_case=target_test,
            result=result,
            message=message,
            execution_time=exploit_result["execution_time"],
            timestamp=datetime.now().isoformat(),
            evidence={
                "exploit_result": exploit_result["exploit_result"]
            },
            vulnerability_confirmed=vulnerability_confirmed
        )
        
        self.results.append(test_execution_result)
        
        # Store analysis separately to avoid duplication
        self.analysis = analysis
        
        # Print result
        status_icon = "✅" if result == TestResult.PASS else "❌" if result == TestResult.FAIL else "⚠️"
        print(f"[{status_icon}] {result.value}: {message}")
        
        return test_execution_result
    
    def print_summary(self):
        """Print test execution summary"""
        if not self.results:
            return
            
        total = len(self.results)
        passed = len([r for r in self.results if r.result == TestResult.PASS])
        failed = len([r for r in self.results if r.result == TestResult.FAIL])
        errors = len([r for r in self.results if r.result == TestResult.ERROR])
        
        logging.info("Test Summary:")
        logging.info(f"  Total: {total}")
        logging.info(f"  Passed: {passed}")
        logging.info(f"  Failed: {failed}")
        logging.info(f"  Errors: {errors}")
        
        vulnerabilities_found = [r for r in self.results if r.vulnerability_confirmed]
        if vulnerabilities_found:
            logging.info(f"Vulnerabilities confirmed: {len(vulnerabilities_found)}")
            for result in vulnerabilities_found:
                logging.info(f"  - {result.test_case.name} -  ({result.test_case.category})")
    
    def save_results(self):
        """Save test results to JSON file in the working directory"""
        output_file = self.executor.working_dir / "test_results.json"
        report = {
            "framework": "Vulnerability Testing Framework",
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_tests": len(self.results),
                "passed": len([r for r in self.results if r.result == TestResult.PASS]),
                "failed": len([r for r in self.results if r.result == TestResult.FAIL]),
                "errors": len([r for r in self.results if r.result == TestResult.ERROR]),
                "vulnerabilities_confirmed": len([r for r in self.results if r.vulnerability_confirmed])
            },
            "results": [asdict(result) for result in self.results],
            "analysis": self.analysis
        }
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        logging.info(f"Results saved to: {output_file}")
        (f"Results saved to: {output_file}")


# Main CLI interface
def main():
    """Command line interface for the testing framework"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Vulnerability Testing Framework")
    parser.add_argument("--device", "-d", help="Android device ID")
    parser.add_argument("--config", "-c", help="Test configuration JSON file")
    parser.add_argument("--test", "-t", help="Run specific test by name")
    parser.add_argument("--output", "-o", default="test_results.json", help="Output file for results")
    
    args = parser.parse_args()
    
    runner = TestRunner(device_id=args.device)
    
    # Load test cases
    if args.config:
        runner.load_test_cases_from_file(args.config)
    else:
        # Default test cases
        default_tests = [
            TestCase(
                name="upload_sensitive_db",
                description="Test arbitrary file upload of database files",
                payload="databases/filelist",
                severity=TestSeverity.CRITICAL,
                exploit_type="arbitrary_upload"
            )
        ]
        for test in default_tests:
            runner.add_test_case(test)
    
    # Run tests
    if args.test:
        runner.run_test_by_name(args.test)
    else:
        runner.run_all_tests()
    
    # Save results
    runner.save_results()


if __name__ == "__main__":
    main()
    