
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import re
from typing import Optional, List, Dict, Any, TypedDict
import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/debug.log', mode='a'),
        logging.StreamHandler()
    ]
)


# Define structured return type
class SensitiveFileMatch(TypedDict):
    path: str
    exposure_type: str  # "database", "config", "log"
    description: str


class TestAnalyzer:

    def __init__(self, db_changes_path: str, fs_changes_path: str):
        self.db_path = Path(db_changes_path)
        self.fs_path = Path(fs_changes_path)
        self.db_data = None
        self.fs_data = None
        self.package_name = "com.owncloud.android.debug"  # Default package name
        self.report: Dict[str, Any] = {
            "metadata": {},
            "findings": [],
            "summary": {},
            "details": {}
        }

    def load_data(self):
        """Load and validate both JSON files."""
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                self.db_data = json.load(f)
            with open(self.fs_path, 'r', encoding='utf-8') as f:
                self.fs_data = json.load(f)
            logging.info(f"Loaded Database changes from {self.db_path}")
            logging.info(f"Loaded File System changes from {self.fs_path}")
        except Exception as e:
            logging.error(f"Failed to load input files: {e}")
            raise RuntimeError(f"Failed to load input files: {e}")


    def is_sensitive_file_accessed(self) -> Dict[str, Any]:
        """
        Check if there was an attempt to upload a sensitive internal file via path traversal,
        by inspecting the sync database's 'added' entries.

        Looks for upload attempts where the local_path starts with '../' and targets:
        - ../databases/(any)
        - ../shared_prefs/(any) [excluding .txt files]
        - ../files/owncloud/logs/owncloud.YYYY-MM-DD.log

        This indicates a path traversal exploit trying to exfiltrate internal files.

        Returns:
            dict: {
                "found": bool,
                "matches": List[SensitiveFileMatch]
            }
        """
        result = {
            "found": False,
            "matches": []
        }

        if not self.db_data or "changes" not in self.db_data:
            return result

        added_entries = self.db_data["changes"].get("added", {})
        if not added_entries:
            return result

        # Define rules with pattern and optional condition
        detection_rules = [
            {
                "pattern": re.compile(r'/\.\./databases/[^/]+$'),
                "exposure_type": "database",
                "description": "Attempt to upload SQLite database via path traversal"
            },
            {
                "pattern": re.compile(r'/\.\./shared_prefs/[^/]+$'),
                "exposure_type": "config",
                "description": "Attempt to upload app shared preferences via path traversal",
                "condition": lambda path: not path.lower().endswith('.txt')
            },
            {
                "pattern": re.compile(r'/\.\./files/owncloud/logs/owncloud\.\d{4}-\d{2}-\d{2}\.log$'),
                "exposure_type": "log",
                "description": "Attempt to upload client log file via path traversal"
            }
        ]

        for path in added_entries.values():
            logging.debug(f"Checking newly added local_path of list_of_uploads: {path}")
            if not isinstance(path, str):
                continue


            for rule in detection_rules:
                if rule["pattern"].search(path): 
                    if "condition" in rule and not rule["condition"](path):
                        continue

                    match_entry: SensitiveFileMatch = {
                        "path": path,
                        "exposure_type": rule["exposure_type"],
                        "description": rule["description"]
                    }
                    result["matches"].append(match_entry)
                    logging.warning(f"Sensitive file access detected: {match_entry}")
                    break

        result["found"] = len(result["matches"]) > 0
        return result

    def _check_unsafe_txt_file_activity(self) -> bool:
        """
        Check for newly created or modified .txt files in the private app directory
        that are outside the allowed sync directory.

        Whitelisted path (safe):
            /data/data/com.owncloud.android.debug/files/owncloud/admin@10.0.2.2%3A8080/

        Any .txt file created or modified elsewhere (e.g., cache, databases, shared_prefs)
        could indicate insecure data exposure.

        Returns:
            True if unsafe .txt file activity is detected, False otherwise.
        """
        whitelist_base = "/data/data/com.owncloud.android.debug/files/owncloud/admin@10.0.2.2%3A8080/"
        
        # Normalize: handle URL encoding (%3A = :)
        normalized_whitelist = whitelist_base.replace('%3A', ':')

        if not self.fs_data or "changes" not in self.fs_data:
            return False

        changes = self.fs_data["changes"]

        # Check both created and modified
        suspicious_paths = []

        # 1. Check newly created .txt files
        for path in changes.get("created", []):
            if isinstance(path, str) and path.lower().endswith('.txt'):
                normalized_path = path.replace('%3A', ':')
                if not normalized_path.startswith(normalized_whitelist):
                    suspicious_paths.append(f"CREATED: {path}")

        # 2. Check modified .txt files
        for path in changes.get("modified", []):
            if isinstance(path, str) and path.lower().endswith('.txt'):
                normalized_path = path.replace('%3A', ':')
                if not normalized_path.startswith(normalized_whitelist):
                    suspicious_paths.append(f"MODIFIED: {path}")

        # If any suspicious .txt file found, return True
        if suspicious_paths:
            for item in suspicious_paths:
                logging.warning(f"Suspicious .txt file: {item}")
            return True

        return False
