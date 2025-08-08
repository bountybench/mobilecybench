import subprocess

def run_adb_command(command):
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None