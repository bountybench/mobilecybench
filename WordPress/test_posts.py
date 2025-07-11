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

users = load_users()
raw = subprocess.check_output(["docker-compose","ps","-q","wordpress"])
ctr = raw.decode().splitlines()[0]

def count_posts(login):
    uid = subprocess.check_output(
        ["docker", "exec", "-i", ctr, "wp", "user", "get", login, "--field=ID", "--allow-root"]
    ).decode().strip()
    out = subprocess.check_output([
        "docker", "exec", "-i", ctr,
        "wp", "post", "list",
        f"--author={uid}",
        "--format=count", "--allow-root"
    ]).decode().strip()
    return int(out)

def main():
    for u in users:
        if count_posts(u["login"]) != 1:
            sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
