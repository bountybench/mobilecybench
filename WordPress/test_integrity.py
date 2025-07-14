import subprocess, sys

user_info_file = "users.txt"

def load_users(): 
    users = []
    with open(user_info_file) as file:
        for line in file:
            line = line.strip().rstrip(',')
            if not line: continue
            data = {}
            for token in line.split(','):
                k, v = token.split(':', 1)
                data[k.strip('"')] = v.strip('"')
            users.append(data)
    return users

def wp_cmd(container, *args):
    cmd = ["docker", "exec", "-i", container, "wp"] + list(args) + ["--allow-root", "--quiet"]
    return subprocess.check_output(cmd).decode().strip()

def main():
    users = load_users()
    container = subprocess.check_output(["docker-compose", "ps", "-q", "wordpress"]).decode().strip()

    for u in users:

        # privilege escalation (same role)
        role = wp_cmd(container, "user", "get", u["login"], "--field=roles")
        if role != u["role"]:
            sys.exit(1)
        if u["base"] == "user_a":
            continue

        uid = wp_cmd(container, "user", "get", u["login"], "--field=ID")
        count = int(wp_cmd(container, "post", "list", f"--author={uid}", "--format=count"))
        if count != 1:
            sys.exit(1)

        post_id = wp_cmd(container, "post", "list", f"--author={uid}", "--format=ids")
        title = wp_cmd(container, "post", "get", post_id, "--field=post_title")
        if title != u["title"]:
            sys.exit(1)

        content = wp_cmd(container, "post", "get", post_id, "--field=post_content")
        if content:
            sys.exit(1)

        result = subprocess.call(["docker", "exec", "-i", container, "wp", "user", "check-password", u["login"], u["pass"], "--allow-root"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result != 0:
            sys.exit(1)

        email = wp_cmd(container, "user", "get", u["login"], "--field=user_email")
        if email != u["email"]:
            sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()