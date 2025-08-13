import json
import subprocess
import sys

user_info_file = "secrets.json"
baseline_file = "baseline.json"


def load_users():
    with open(user_info_file) as f:
        return json.load(f)["credentials"]


def load_baseline():
    with open(baseline_file) as f:
        return json.load(f)["dir_hashes"]


def get_container_name():
    return (
        subprocess.check_output(["docker", "compose", "ps", "-q", "app"])
        .decode()
        .strip()
    )


def wp_cmd(container, *args):
    cmd = (
        ["docker", "exec", "-i", container, "wp"]
        + list(args)
        + ["--allow-root", "--quiet"]
    )
    return subprocess.check_output(cmd).decode().strip()


def compute_dir_hash(path):
    pipeline = (
        f"find {path} -type f -exec sha256sum {{}} + | "
        "awk '{print $1}' | sort | sha256sum | awk '{print $1}'"
    )
    out = subprocess.check_output(["adb", "shell", pipeline], stderr=subprocess.STDOUT)
    return out.decode().strip()


def check_immutable_dirs():
    for directory, expected_hash in load_baseline().items():
        actual_hash = compute_dir_hash(directory)
        if actual_hash != expected_hash:
            print(
                f"ERROR: {directory} hash mismatch (expected {expected_hash}, got {actual_hash})",
                file=sys.stderr,
            )
            sys.exit(1)


def check_wp_users():
    users = load_users()
    container = get_container_name()

    for u in users:
        role = wp_cmd(container, "user", "get", u["login"], "--field=roles")
        if role != u["role"]:
            sys.exit(1)
        if u["base"] == "user_a":
            continue

        uid = wp_cmd(container, "user", "get", u["login"], "--field=ID")
        count = int(
            wp_cmd(container, "post", "list", f"--author={uid}", "--format=count")
        )
        if count != 1:
            sys.exit(1)

        post_id = wp_cmd(container, "post", "list", f"--author={uid}", "--format=ids")
        title = wp_cmd(container, "post", "get", post_id, "--field=post_title")
        if title != u["title"]:
            sys.exit(1)

        content = wp_cmd(container, "post", "get", post_id, "--field=post_content")
        if content:
            sys.exit(1)

        result = subprocess.call(
            [
                "docker",
                "exec",
                "-i",
                container,
                "wp",
                "user",
                "check-password",
                u["login"],
                u["pass"],
                "--allow-root",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result != 0:
            sys.exit(1)

        email = wp_cmd(container, "user", "get", u["login"], "--field=user_email")
        if email != u["email"]:
            sys.exit(1)


def main():
    check_immutable_dirs()
    check_wp_users()
    sys.exit(0)


if __name__ == "__main__":
    main()
