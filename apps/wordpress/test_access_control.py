#!/usr/bin/env python3
import json
import subprocess
import sys
import uuid

user_info_file = "secrets.json"


def load_users():
    with open(user_info_file) as f:
        return json.load(f)["credentials"]


def wp_cmd(container, *args):
    return (
        subprocess.check_output(
            ["docker", "exec", "-i", container, "wp"]
            + list(args)
            + ["--allow-root", "--quiet"]
        )
        .decode()
        .strip()
    )


def wp_call(container, *args):
    return subprocess.call(
        ["docker", "exec", "-i", container, "wp"]
        + list(args)
        + ["--allow-root", "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def check_role_and_permissions(users, container):
    for u in users:
        if wp_call(container, "user", "check-password", u["login"], u["pass"]) != 0:
            print(f"Password check failed for {u['login']}", file=sys.stderr)
            return False
    return True


def check_authentication(users, container):
    invalid_tests = [
        ("invalid_user", "invalid_pass"),
        (users[0]["login"], "wrong_password"),
        ("nonexistent", "nopass"),
        ("", ""),
    ]
    for user, pwd in invalid_tests:
        if wp_call(container, "user", "check-password", user, pwd) == 0:
            print(f"Invalid credentials accepted for {user}", file=sys.stderr)
            return False
    return True


def test_user_lifecycle(container):
    suffix = uuid.uuid4().hex[:8]
    login = f"ci_user_{suffix}"
    email = f"{login}@example.com"
    password = "TempPass!23"
    role = "author"
    if (
        wp_call(
            container,
            "user",
            "create",
            login,
            email,
            f"--role={role}",
            f"--user_pass={password}",
        )
        != 0
    ):
        print(f"User creation failed for {login}", file=sys.stderr)
        return False
    uid = wp_cmd(container, "user", "get", login, "--field=ID")
    if wp_call(container, "user", "delete", uid, "--yes") != 0:
        print(f"User deletion failed for {login}", file=sys.stderr)
        return False
    return True


def test_post_lifecycle(container):
    title = f"CI Post {uuid.uuid4()}"
    post_id = wp_cmd(
        container,
        "post",
        "create",
        "--post_title=" + title,
        "--post_status=publish",
        "--porcelain",
    )
    posts = wp_cmd(container, "post", "list", "--format=ids", "--post_status=publish")
    if post_id not in posts.split():
        print(f"Post creation failed for {title}", file=sys.stderr)
        return False
    if wp_call(container, "post", "delete", post_id, "--force") != 0:
        print(f"Post deletion failed for {title}", file=sys.stderr)
        return False
    posts_after = wp_cmd(
        container, "post", "list", "--format=ids", "--post_status=publish"
    )
    if post_id in posts_after.split():
        print(f"Post still exists after deletion for {title}", file=sys.stderr)
        return False
    return True


def test_duplicate_user(container, existing_login):
    ret = wp_call(
        container,
        "user",
        "create",
        existing_login,
        f"{existing_login}@example.com",
        "--role=author",
        "--user_pass=DummyPass",
    )
    if ret == 0:
        print(f"Duplicate user creation succeeded for {existing_login}", file=sys.stderr)
        return False
    return True


def main():
    users = load_users()
    container = (
        subprocess.check_output(["docker", "compose", "ps", "-q", "app"])
        .decode()
        .strip()
    )
    ok = True
    ok &= check_role_and_permissions(users, container)
    ok &= check_authentication(users, container)
    ok &= test_user_lifecycle(container)
    ok &= test_post_lifecycle(container)
    ok &= test_duplicate_user(container, users[0]["login"])
    if ok:
        print("Access control check passed.")
    else:
        print("Access control check failed.", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
