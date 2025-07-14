#!/usr/bin/env python3
import unittest
import subprocess
import uuid

class TestPosts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = subprocess.check_output(["docker-compose", "ps", "-q", "wordpress"])
        cls.ctr = raw.decode().strip()
        cls.wp = ["docker", "exec", "-i", cls.ctr, "wp", "--allow-root"]

        cls.user_login = "user_a"
        cls.user_pass = None
        with open("users.txt") as file:
            for line in file:
                if '"base":"user_a"' in line:
                    parts = {}
                    for tok in line.split(","):
                        if ":" in tok:
                            k, v = tok.split(":", 1)
                            parts[k.strip().strip('"')] = v.strip().strip('"')
                    cls.user_pass = parts.get("pass")
                    break
        assert cls.user_pass, "user_a password not found in users.txt"

        result = subprocess.check_output(cls.wp + ["user", "get", cls.user_login, "--field=ID"])
        cls.user_id = result.decode().strip()

    def test_create_and_delete_post(self):
        title = f"TestPost-{uuid.uuid4()}"
        create_cmd = self.wp + [
            "post", "create",
            "--post_title=" + title,
            f"--post_author={self.user_id}",
            "--post_status=publish",
            "--porcelain"
        ]
        result = subprocess.check_output(create_cmd)
        post_id = result.decode().strip()

        list_cmd = self.wp + ["post", "list", "--post_type=post", "--format=ids", "--post_status=publish"]
        all_posts = subprocess.check_output(list_cmd).decode().strip()
        self.assertIn(post_id, all_posts, "Post not found after creation")

        delete_cmd = self.wp + ["post", "delete", post_id, "--force"]
        delete_result = subprocess.check_output(delete_cmd).decode().strip()
        self.assertIn("Deleted post", delete_result)

        all_posts_after = subprocess.check_output(list_cmd).decode().strip()
        self.assertNotIn(post_id, all_posts_after, "Post still exists after deletion")

if __name__ == "__main__":
    unittest.main()