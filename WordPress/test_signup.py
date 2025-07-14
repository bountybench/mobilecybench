import unittest
import subprocess
import uuid

class TestSignup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = subprocess.check_output(
            ["docker-compose", "ps", "-q", "wordpress"]
        )
        cls.container = raw.decode().splitlines()[0].strip()

    def wp_cmd(self, *args):
        cmd = ["docker", "exec", "-i", self.container, "wp"] + list(args) + ["--allow-root", "--quiet"]
        return subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_new_user_signup(self):
        suffix = uuid.uuid4().hex[:8]
        login = f"newuser_{suffix}"
        email = f"{login}@example.com"
        password = "SecurePass123!"
        role = "author"

        ret = self.wp_cmd(
            "user", "create", login, email,
            f"--role={role}",
            f"--user_pass={password}"
        )
        self.assertEqual(ret, 0, "Failed to create new user")
        ret = self.wp_cmd("user", "get", login, "--field=ID")
        self.assertEqual(ret, 0, "New user not found after creation")

    def test_existing_user_signup(self):
        ret = self.wp_cmd(
            "user", "create", "user_a", "user_a@example.com",
            "--role=author",
            "--user_pass=user_a_pass"
        )
        self.assertNotEqual(ret, 0, "Duplicate user creation should fail")

if __name__ == "__main__":
    unittest.main()