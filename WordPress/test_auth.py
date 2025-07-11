import subprocess, sys

def load_users(path="users.txt"):
    users = []
    with open(path) as f:
        for line in f:
            line = line.strip().rstrip(',')
            if not line:
                continue
            d = {}
            for pair in line.split(','):
                k,v = pair.split(':',1)
                d[k.strip('"')] = v.strip('"')
            users.append(d)
    return users

def main():
    users = load_users()
    user_authentification = next(u for u in users if u["base"] == "user_a")
    raw = subprocess.check_output(["docker-compose", "ps", "-q", "wordpress"])
    ctr = raw.decode().splitlines()[0]

    r = subprocess.run(
        ["docker", "exec", "-i", ctr, "wp", "user", "get", user_authentification["login"], "--field=user_email", "--allow-root"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    if r.returncode != 0 or r.stdout.decode().strip() != user_authentification["email"]:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()