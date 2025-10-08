import json
import uuid
from pathlib import Path

import bcrypt

PREFIX = "user_"


def main():

    users_htpasswd = []
    users_secrets = {}

    # Read password from metadata.json for user_0000
    with open("metadata.json", "r") as f:
        metadata = json.load(f)
    special_password = metadata["password"]

    # Create user_0000 first with password from metadata.json
    hashed_special_password = bcrypt.hashpw(
        special_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    users_htpasswd.append(("user_0000", hashed_special_password))
    users_secrets["user_0000"] = special_password

    # Generate remaining 9 users (user_0001 to user_0009)
    for i in range(1, 10):
        user = f"{PREFIX}{i:04d}"

        password = uuid.uuid4().hex

        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        users_htpasswd.append((user, hashed_password))
        users_secrets[user] = password

    htpasswd = Path.cwd() / "radicale/users/htpasswd"
    secrets = Path.cwd() / "secrets.json"

    htpasswd.parent.mkdir(parents=True, exist_ok=True)

    with htpasswd.open("w") as f1:
        for user, hashed_password in users_htpasswd:
            f1.write(f"{user}:{hashed_password}\n")

    with secrets.open("w") as f2:
        json.dump(users_secrets, f2, indent=2)


if __name__ == "__main__":
    main()
