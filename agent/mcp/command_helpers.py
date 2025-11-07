import os


def is_adb_command_allowed(command):
    command = " ".join(command.strip().split())
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    blocked_patterns_path = os.path.join(script_dir, "blocked_adb_patterns.txt")

    with open(blocked_patterns_path, "r") as f:
        blocked_patterns = f.read().splitlines()
    for pattern in blocked_patterns:
        if pattern in command:
            return False
    return True
