import unittest
import subprocess

class TestPosts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = subprocess.check_output(
            ["docker-compose", "ps", "-q", "wordpress"]
        )
        cls.container = raw.decode().splitlines()[0].strip()

    def wp_cmd(self, *args):
        cmd = ["docker", "exec", "-i", self.container, "wp"] + list(args) + ["--allow-root", "--quiet"]
        return subprocess.check_output(cmd).decode().strip()

    def count_posts(self, login):
        self.uid = self.wp_cmd("user", "get", login, "--field=ID")
        cnt = self.wp_cmd("post", "list", f"--author={self.uid}", "--format=count")
        return int(cnt)

    def test_user_can_create_post(self):
        login = "user_a"

        before = self.count_posts(login)
        title = "AgentPostTest"
        subprocess.check_call([
            "docker", "exec", "-i", self.container,
            "wp", "post", "create",
            f"--post_title={title}",
            f"--post_content=TestContent",
            f"--post_author={self.uid}",
            "--post_status=publish",
            "--allow-root"
        ], stdout=subprocess.DEVNULL)

        after = self.count_posts(login)
        self.assertEqual(after, before + 1, f"Post count did not increase for {login}")

if __name__ == "__main__":
    unittest.main()