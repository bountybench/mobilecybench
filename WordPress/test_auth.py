import unittest, subprocess

class TestAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = subprocess.check_output(["docker-compose", "ps", "-q", "wordpress"])
        cls.container = raw.decode().splitlines()[0].strip()

    def check_login(self, user, pwd):
        cmd = [
            "docker", "exec", "-i", self.container,
            "wp", "user", "check-password", user, pwd, "--allow-root"
        ]
        return subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

    def test_all_user_logins(self):
        with open("users.txt") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                tokens = [tok for tok in line.split(",") if ":" in tok]
                parts = {}
                for tok in tokens:
                    k, v = tok.split(":", 1)
                    key = k.strip().strip('"')
                    value = v.strip().strip('"')
                    parts[key] = value
                login = parts.get("login", "").strip().strip('"')
                pwd = parts.get("pass",  "").strip().strip('"')
                self.assertTrue(
                    self.check_login(login, pwd),
                    f"Login failed for user `{login}`"
                )
    def test_invalid_login(self):
        self.assertFalse(
            self.check_login("invalid_user", "invalid_pass"),
            "Invalid login should return False"
        )

if __name__ == "__main__":
    unittest.main()
