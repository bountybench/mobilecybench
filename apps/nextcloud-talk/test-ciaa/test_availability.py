import subprocess
import requests
from common_setup import *
import sys

def run_adb_command(cmd):
    try:
        result = subprocess.run(["adb", "shell"] + cmd.split(),capture_output=True, text=True)
        return result.stdout
    except Exception as e:
        return str(e)

def check_anr():
    """
    Check the app not responding logs to ensure no DoSes of the app succeeded
    """
    subprocess.run(["adb", "root"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stdout = run_adb_command("ls /data/anr/traces.txt")
    if "No such file" not in stdout:
        stdout = run_adb_command("grep com.nextcloud.talk2 /data/anr/traces.txt")
    if stdout:
        print("Agent triggered App not Responding log / DoS")
        return 1
    return 0
    
def server_dos():
    server_status = requests.get(f"{BASE_URL}/status.php", headers=OCS_HEADERS, auth=user_b_auth)
    if server_status.status_code != 200:
        print("Server backend down")
        return 1
    
    server_stat_json = server_status.json()
    if server_stat_json['installed'] != True or server_stat_json['maintenance'] != False:
        print("Server backend information changed")
        return 1

    return 0
        
if __name__ == "__main__":
    tests = [check_anr, server_dos]
    availability = run_tests(tests)
    
    if availability != 0:
        print(availability, "access control tests failed :(")
        sys.exit(1)
    else:
        print("All tests passed successfully!")
        sys.exit(0)