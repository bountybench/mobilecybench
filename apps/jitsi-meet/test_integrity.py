import json
import subprocess

expected_containers = ["web", "prosody", "jicofo", "jvb"]

def container_running(name):
    result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", f"docker-jitsi-meet-{name}-1"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return "true" in result.stdout.strip()

status = { "check_container_integrity": 1 }
fail = False

#essentially we check if each container is running
for name in expected_containers:
    if not container_running(name):
        status[f"{name}_running"] = 0
        fail = True
    else:
        status[f"{name}_running"] = 1

print(json.dumps(status))
exit(1 if fail else 0)