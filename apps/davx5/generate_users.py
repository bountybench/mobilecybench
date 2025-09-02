import uuid
import bcrypt
from pathlib import Path

PREFIX = "user_"

def main():

    users = []

    for i in range(1000):
        user = f"{PREFIX}{i:04d}"

        password = uuid.uuid4().hex

        hashed_password = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

        users.append((user, hashed_password))
    
    htpasswd = Path.cwd() / "radicale/users/htpasswd"

    with htpasswd.open('w') as f:
        for user, hashed_password in users:
            f.write(f"{user}:{hashed_password}\n")

if __name__ == "__main__":
    main()