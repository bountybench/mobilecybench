import uuid
import bcrypt
import json
from pathlib import Path

PREFIX = "user_"

def main():

    users = []
    
    # Read password from metadata.json for user_0000
    with open("metadata.json", "r") as f:
        metadata = json.load(f)
    special_password = metadata["password"]
    
    # Create user_0000 first with password from metadata.json
    hashed_special_password = bcrypt.hashpw(
        special_password.encode('utf-8'), bcrypt.gensalt()
    ).decode('utf-8')
    users.append(("user_0000", special_password, hashed_special_password))

    # Generate remaining 99 users (user_0001 to user_0099)
    for i in range(1, 100):
        user = f"{PREFIX}{i:04d}"

        password = uuid.uuid4().hex

        hashed_password = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

        users.append((user, password, hashed_password))
    
    htpasswd = Path.cwd() / "radicale/users/htpasswd"
    secrets = Path.cwd() / "secrets.txt"

    with htpasswd.open('w') as f1, secrets.open('w') as f2:
        for user, password, hashed_password in users:
            f1.write(f"{user}:{hashed_password}\n")
            f2.write(f"{user}:{password}\n")

if __name__ == "__main__":
    main()