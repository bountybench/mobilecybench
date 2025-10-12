def is_adb_command_allowed(command):
    command = " ".join(command.strip().split())
    with open("blocked_adb_patterns.txt", "r") as f:
        blocked_patterns = f.read().splitlines()
        print(blocked_patterns)
    for pattern in blocked_patterns:
        if pattern in command:
            print(f"{pattern} -- {command}")
            return False
    return True
