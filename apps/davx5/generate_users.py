import uuid
import bcrypt
from pathlib import Path

PREFIX = "user_"

def main():

    users = []

    for i in range(10):
        user = f"{PREFIX}{i:04d}"

        password = uuid.uuid4().hex

        hashed_password = bcrypt.hashpw(
            password.encode('utf-8')
        )

        users.append((user, password))
    
    htpasswd = Path.cwd() / "radicale/users/htpasswd"

    with htpasswd.open('w') as f:
        for user, hashed_password in users:
            f.write(f"{user}:{hashed_password}\n")

if __name__ == "__main__":
    main()