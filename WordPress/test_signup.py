import subprocess, sys

user_info_file = "users.txt"

def main():
    raw = subprocess.check_output(["docker-compose","ps","-q","wordpress"])
    ctr = raw.decode().splitlines()[0]

    out = subprocess.check_output([
        "docker", "exec", "-i", ctr,
        "wp", "user", "list", "--format=count", "--allow-root"
    ]).decode().strip()

    with open(user_info_file) as file:
        total = sum(1 for line in file if line.strip())
    if int(out) != total:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
