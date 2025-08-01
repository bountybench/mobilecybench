"""
Android Device Probes for ownCloud Vulnerability Testing
"""


import re
import time
import subprocess
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import os
from datetime import datetime
from pathlib import Path
import json

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/debug.log', mode='a'),
        logging.StreamHandler()
    ]
)


@dataclass
class DeviceInfo:
    """Android device information"""
    device_id: str
    android_version: str
    api_level: int
    manufacturer: str
    model: str
    is_rooted: bool = False


@dataclass
class AppInfo:
    """ownCloud app information"""
    package_name: str
    version_code: str
    version_name: str
    data_dir: str
    is_installed: bool = False
    permissions: List[str] = None


class AndroidSecurityProbe:
    """Advanced Android security testing probe"""
    
    def __init__(self, device_id: Optional[str] = None, auto_enable_root: bool = False):
        self.device_id = device_id
        self.owncloud_package = "com.owncloud.android.debug"
        self.device_info: Optional[DeviceInfo] = None
        self.app_info: Optional[AppInfo] = None
        self.root_enabled = False
        
        # Automatically try to enable root if requested
        if auto_enable_root:
            self.enable_root()


    def is_adb_root(self, verbose: bool = False) -> bool:
        """Check if the device is rooted"""

        success, output, _ = self._run_adb_command(["adb", "shell", "id"])
        if success and "uid=0" in output:
            return True
        return False

    def enable_root(self) -> bool:
        try:
            logging.info("Attempt to enable ADB root. May take a second to reboot")
            root_cmd = ["adb", "root"]
            if self.device_id:
                root_cmd.insert(1, "-s")
                root_cmd.insert(2, self.device_id)
            root_result = subprocess.run(root_cmd, capture_output=True, text=True, timeout=10)
            if root_result.returncode == 0:
                time.sleep(2)
                if self.is_adb_root():
                    self.root_enabled = True
                    logging.info("ROOT ACCESS ENABLED!")
                else:
                    logging.warning("ADB root command succeeded but not running as root")
                    return False
            else:
                logging.error(f"Failed to enable root: {root_result.stderr}")
                return False
        except Exception as e:
            logging.error(f"Error enabling root: {e}")
            return False
    
    def _run_shell_command(self, command: str) -> Tuple[bool, str, str]:
        """Run a shell command via ADB (for complex commands with pipes, etc.)"""
        return self._run_adb_command(["adb", "shell", command])

    def _run_adb_command(self, cmd: List[str], timeout: int = 30) -> Tuple[bool, str, str]:
        """ADB Wrapper: Run ADB command with proper error handling"""
        try:
            if self.device_id:
                cmd = ["adb", "-s", self.device_id] + cmd[1:]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=timeout
            )
            
            return (
                result.returncode == 0,
                result.stdout.strip(),
                result.stderr.strip()
            )
        except subprocess.TimeoutExpired:
            return False, "", "Command timeout"
        except Exception as e:
            return False, "", str(e)
    
    def probe_device_info(self, verbose: bool = False) -> Optional[DeviceInfo]:
        """Collect detailed device information"""
        success, output, _ = self._run_adb_command(["adb", "shell", "getprop"])
        if not success:
            if verbose:
                logging.error("Failed to get device properties")
            return None
        props = {}
        for line in output.split('\n'):
            match = re.match(r'\[(.+?)\]: \[(.+?)\]', line)
            if match:
                props[match.group(1)] = match.group(2)
        is_rooted = self.is_adb_root()
        self.device_info = DeviceInfo(
            device_id=self.device_id or "unknown",
            android_version=props.get("ro.build.version.release", "unknown"),
            api_level=int(props.get("ro.build.version.sdk", "0")),
            manufacturer=props.get("ro.product.manufacturer", "unknown"),
            model=props.get("ro.product.model", "unknown"),
            is_rooted=is_rooted
        )
        if verbose:
            logging.info(f"Device: {self.device_info.manufacturer} {self.device_info.model}")
            logging.info(f"Android: {self.device_info.android_version} (API {self.device_info.api_level})")
            logging.info(f"Rooted: {self.device_info.is_rooted}")
        return self.device_info
    
    def probe_app_info(self) -> Optional[AppInfo]:
        """Collect ownCloud app information"""
        # Check if app is installed
        success, output, _ = self._run_adb_command([
            "adb", "shell", "pm", "list", "packages", self.owncloud_package
        ])
        
        if not success or self.owncloud_package not in output:
            return AppInfo(
                package_name=self.owncloud_package,
                version_code="",
                version_name="",
                data_dir="",
                is_installed=False
            )
        
        # Get app version info
        success, version_output, _ = self._run_adb_command([
            "adb", "shell", "dumpsys", "package", self.owncloud_package
        ])
        
        version_code = ""
        version_name = ""
        if success:
            for line in version_output.split('\n'):
                if "versionCode=" in line:
                    version_code = re.search(r'versionCode=(\d+)', line)
                    version_code = version_code.group(1) if version_code else ""
                elif "versionName=" in line:
                    version_name = re.search(r'versionName=(.+)', line)
                    version_name = version_name.group(1) if version_name else ""
        
        # Get app permissions
        permissions = []
        if success:
            in_permissions = False
            for line in version_output.split('\n'):
                if "requested permissions:" in line:
                    in_permissions = True
                elif in_permissions and line.strip().startswith("android.permission"):
                    permissions.append(line.strip())
                elif in_permissions and not line.strip().startswith("android.permission"):
                    if line.strip() and not line.startswith(" "):
                        break
        
        self.app_info = AppInfo(
            package_name=self.owncloud_package,
            version_code=version_code,
            version_name=version_name,
            data_dir=f"/data/data/{self.owncloud_package}",
            is_installed=True,
            permissions=permissions
        )
        
        return self.app_info
    
    def probe_file_system_access(self, target_path: str) -> Dict[str, Any]:
        """Probe file system access and permissions"""
        evidence = {
            "target_path": target_path,
            "exists": False,
            "file_type": "unknown",
            "size": 0,
            "permissions": "",
            "owner": "",
            "error": ""
        }
        
        # Check if file exists
        success, _, error = self._run_adb_command([
            "adb", "shell", "test", "-e", target_path
        ])
        evidence["exists"] = success
        
        if not success:
            evidence["error"] = f"File does not exist: {target_path}"
            return evidence
        
        # Get file stats - use -ld for directories to get directory info, not contents
        success, output, error = self._run_adb_command([
            "adb", "shell", "ls", "-ld", target_path
        ])

        _, size, error = self._run_adb_command([
            "adb", "shell", "du", "-sh", target_path
        ]) 
        
        if success and output:
            # Parse the ls -ld output (single line for the target path itself)
            line = output.strip()
            if line and not line.startswith('total'):
                parts = line.split()
                if len(parts) >= 8:  # Changed from 9 to 8
                    evidence["permissions"] = parts[0]
                    evidence["owner"] = f"{parts[2]}:{parts[3]}"
                    evidence["size"] = size.split()[0] if size and size.strip() else "unknown"  # Use size from du command
                    evidence["file_type"] = "directory" if parts[0].startswith('d') else "file"
        else:
            evidence["error"] = f"Failed to get file stats: {error}"
        
        return evidence
    
    def explore_private_directory(self, app_package: str = None) -> Dict[str, Any]:
        """Explore private app directory structure with metadata (size, mtime, sha256)"""
        if not app_package:
            app_package = self.owncloud_package
        private_dir = f"/data/data/{app_package}"
        evidence = {
            "package": app_package,
            "private_dir": private_dir,
            "accessible": False,
            "directory_structure": {"files": [], "directories": []},
            "total_files": 0,
            "total_directories": 0,
            "databases": [],
            "shared_prefs": [],
            "cache_files": [],
            "file_metadata": {},  # ← NEW: Will store size, mtime, sha256
            "error": ""
        }

        # Check access
        access_info = self.probe_file_system_access(private_dir)
        if not access_info["exists"]:
            evidence["error"] = "Cannot access private directory - root required"
            return evidence
        evidence["accessible"] = True

        # Use `find` to list all files and dirs
        success, output, error = self._run_shell_command(f"find {private_dir} -type f -o -type d | head -200")
        if not success:
            evidence["error"] = f"Failed to list directory contents: {error}"
            return evidence

        files = []
        directories = []
        databases = []
        shared_prefs = []
        cache_files = []
        metadata = {}  # ← This will hold metadata for each file

        # if not output or not output.strip():
        #     evidence["error"] = "No output from find command - directory may be empty or inaccessible"
        #     return evidence
            
        for line in output.strip().split('\n'):
            path = line.strip()
            if not path:
                continue

            # Check if it's a directory
            is_dir, _, _ = self._run_shell_command(f"test -d '{path}'")
            if is_dir:
                directories.append(path)
                continue

            # It's a file
            files.append(path)

            # Categorize
            # if path.endswith(('.db', '.db-journal', '.sqlite', '.sqlite3')):
            #     databases.append(path)
            if '/databases/' in path:
                databases.append(path)
            if '/shared_prefs/' in path:
                shared_prefs.append(path)
            if '/cache/' in path:
                cache_files.append(path)

            # Gather metadata
            meta = {}

            # Size
            size_ok, size_out, _ = self._run_shell_command(f"stat -c %s '{path}'")
            if size_ok:
                try:
                    meta['size'] = int(size_out.strip())
                except:
                    meta['size'] = None
            else:
                meta['size'] = None

            # Mtime (Unix timestamp)
            mtime_ok, mtime_out, _ = self._run_shell_command(f"stat -c %Y '{path}'")
            if mtime_ok:
                try:
                    meta['mtime'] = float(mtime_out.strip())
                except:
                    meta['mtime'] = None
            else:
                meta['mtime'] = None

            # SHA-256 hash (only for small files)
            meta['sha256'] = None
            meta['hash_error'] = None
            if meta['size'] not in (None, 0) and meta['size'] < 1024 * 1024:  # < 1MB
                hash_ok, hash_out, hash_err = self._run_shell_command(f"sha256sum '{path}'")
                if hash_ok and hash_out:
                    try:
                        meta['sha256'] = hash_out.strip().split()[0]
                    except:
                        meta['hash_error'] = "Failed to parse sha256sum output"
                else:
                    meta['hash_error'] = hash_err or "sha256sum failed"
            else:
                meta['hash_error'] = "File too large or zero size"

            metadata[path] = meta  # ← Save metadata for this file

        # Finalize evidence
        evidence["directory_structure"] = {"files": files, "directories": directories}
        evidence["total_files"] = len(files)
        evidence["total_directories"] = len(directories)
        evidence["databases"] = databases
        evidence["shared_prefs"] = shared_prefs
        evidence["cache_files"] = cache_files
        evidence["file_metadata"] = metadata  # ← Attach all metadata

        return evidence

    def pull_private_directory(
        self,
        app_package: str = None,
        local_path: str = "data/before_local_dir.json"
    ) -> Dict[str, Any]:
        """
        Explore private app directory, collect metadata (size, mtime, sha256),
        and save the full snapshot to a user-defined JSON file.

        Args:
            app_package (str): App package name (e.g., 'com.owncloud.android.debug')
            local_path (str): Full path to save the JSON (e.g., 'OUTPUT/before.json')

        Returns:
            Dict[str, Any]: The evidence dictionary
        """
        if not app_package:
            app_package = self.owncloud_package

        # Step 1: Run the exploration
        evidence = self.explore_private_directory(app_package)

        # Step 2: Prepare local file path
        output_path = Path(local_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)  # Create parent dirs if needed

        # Step 3: Save evidence to the exact user-specified path
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(evidence, f, indent=2, ensure_ascii=False)
            logging.info(f"Snapshot saved to: {output_path}")
        except Exception as e:
            logging.error(f"Failed to save snapshot to {output_path}: {e}")
            evidence["save_error"] = str(e)

        return evidence
    
    def explore_databases(self, app_package: str = None) -> Dict[str, Any]:
        """Explore all databases in app's private directory"""
        if not app_package:
            app_package = self.owncloud_package
            
        private_dir = f"/data/data/{app_package}"
        
        evidence = {
            "package": app_package,
            "databases_found": [],
            "database_details": {},
            "total_databases": 0,
            "error": ""
        }
        
        # Find all database files
        success, output, error = self._run_shell_command(f"find {private_dir} -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3'")
        
        if not success:
            evidence["error"] = f"Failed to find databases: {error}"
            return evidence
        
        if output:
            ## IMPORTANT: CHECK this. TODO!!
            databases = [db.strip() for db in output.split('\n') if db.strip()]
            evidence["databases_found"] = databases
            evidence["total_databases"] = len(databases)
            
            # Get detailed info for each database
            for db_path in databases:
                db_info = self.probe_database_structure(db_path)
                evidence["database_details"][db_path] = db_info
        
        return evidence
    
    def pull_databases(self, local_folder: str = "before_databases") -> dict:
        """
        Pull all files from the app's databases directory to a specified local folder.
        Ideal for capturing state before/after an exploit.

        Args:
            local_folder (str): Name of the local directory (e.g., 'before_databases', 'after_databases')

        Returns:
            Dict with success status and file details
        """
        remote_db_dir = f"/data/data/{self.owncloud_package}/databases"
        local_target = local_folder  # Use exactly the name you provided

        # Create local directory
        os.makedirs(local_target, exist_ok=True)

        result = {
            "success": False,
            "remote_dir": remote_db_dir,
            "local_dir": local_target,
            "pulled_files": [],
            "failed_files": [],
            "error": ""
        }

        logging.info(f"Pulling databases from: {remote_db_dir}")
        logging.info(f"Saving to: {local_target}")

        # List all files in the databases directory
        list_cmd = f"ls -1 {remote_db_dir}"
        success, file_list_output, error = self._run_shell_command(list_cmd)

        if not success:
            result["error"] = f"Failed to list files: {error}"
            logging.error(error)
            return result

        filenames = [f.strip() for f in file_list_output.strip().split('\n') if f.strip()]

        if not filenames:
            result["error"] = "No files found in remote databases directory."
            logging.warning("No files found.")
            return result

        # Pull each file
        for filename in filenames:
            remote_path = f"{remote_db_dir}/{filename}"
            local_path = os.path.join(local_target, filename)
            logging.info(f"Pulling: {filename}")
            pull_success, _, pull_error = self._run_adb_command([
                "adb", "pull", remote_path, local_path
            ])
            if pull_success:
                result["pulled_files"].append({
                    "remote": remote_path,
                    "local": local_path
                })
                logging.info(f"Pulled: {filename}")
            else:
                result["failed_files"].append({
                    "remote": remote_path,
                    "error": pull_error
                })
                logging.error(f"Failed: {filename} - {pull_error}")

        # Final result
        result["success"] = len(result["pulled_files"]) > 0
        if result["success"]:
            logging.info(f"All databases pulled to: ./{local_target}/")
        else:
            logging.error("Failed to pull any database files.")

        return result
