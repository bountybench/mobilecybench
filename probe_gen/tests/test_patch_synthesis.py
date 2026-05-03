"""Tests for the patch-synthesis helpers (no LLM calls)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "probe_gen" / "scripts"))

import synthesize_patch as sp  # type: ignore[import-not-found]


class TestExtractDiff(unittest.TestCase):
    def test_picks_last_diff_fence(self) -> None:
        # LLM emits a first attempt, then "let me reconsider", then a final.
        text = """First try:
```diff
--- a/x
+++ b/x
@@ -1,1 +1,1 @@
-old
+new
```

Wait, that's wrong. Let me reconsider.

```diff
--- a/y
+++ b/y
@@ -1,1 +1,1 @@
-actual
+correct
```
"""
        result = sp._extract_diff(text)
        self.assertIn("--- a/y", result)
        self.assertNotIn("--- a/x", result)

    def test_normalizes_crlf(self) -> None:
        text = "```diff\r\n--- a/x\r\n+++ b/x\r\n@@ -1,1 +1,1 @@\r\n-old\r\n+new\r\n```\r\n"
        result = sp._extract_diff(text)
        self.assertNotIn("\r", result)

    def test_no_fence_falls_back_to_whole_text(self) -> None:
        text = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n-old\n+new\n"
        result = sp._extract_diff(text)
        self.assertIn("@@ -1,1 +1,1 @@", result)


class TestRecountHunkHeaders(unittest.TestCase):
    def test_recomputes_correct_counts(self) -> None:
        # 3 context, 2 removed, 1 added → -1,5 +1,4
        bad = "@@ -1,99 +1,99 @@\n" " a\n b\n c\n-d\n-e\n+f\n"
        fixed = sp._recount_hunk_headers(bad)
        self.assertIn("@@ -1,5 +1,4 @@", fixed)
        self.assertNotIn("@@ -1,99", fixed)

    def test_preserves_start_lines(self) -> None:
        # If the LLM gets start lines right but counts wrong, recount only counts
        bad = "@@ -100,99 +200,99 @@ trailing context\n" " context\n+added\n"
        fixed = sp._recount_hunk_headers(bad)
        self.assertIn("@@ -100,1 +200,2 @@ trailing context", fixed)

    def test_handles_no_newline_marker(self) -> None:
        # "\ No newline at end of file" markers aren't counted
        bad = "@@ -1,99 +1,99 @@\n" " a\n b\n-c\n+d\n\\ No newline at end of file\n"
        fixed = sp._recount_hunk_headers(bad)
        self.assertIn("@@ -1,3 +1,3 @@", fixed)

    def test_passes_through_non_hunk_lines(self) -> None:
        bad = (
            "diff --git a/x b/x\n"
            "index 1..2 100644\n"
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1,99 +1,99 @@\n"
            " a\n+b\n"
        )
        fixed = sp._recount_hunk_headers(bad)
        self.assertIn("diff --git a/x b/x", fixed)
        self.assertIn("--- a/x", fixed)
        self.assertIn("@@ -1,1 +1,2 @@", fixed)

    def test_multi_hunk(self) -> None:
        bad = (
            "--- a/x\n+++ b/x\n"
            "@@ -1,99 +1,99 @@\n"
            " ctx1\n-rem1\n+add1\n"
            "@@ -50,99 +50,99 @@\n"
            " ctx2\n+add2\n+add3\n"
        )
        fixed = sp._recount_hunk_headers(bad)
        self.assertIn("@@ -1,2 +1,2 @@", fixed)
        self.assertIn("@@ -50,1 +50,3 @@", fixed)


class TestCanonicalConversationsPatch(unittest.TestCase):
    """The recounter should be a no-op on a well-formed canonical patch."""

    def test_canonical_unchanged(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        canonical = (
            repo_root
            / "apps"
            / "conversations"
            / "synthetic_vulnerabilities"
            / "vuln_0"
            / "vulnerability.patch"
        )
        if not canonical.is_file():
            self.skipTest("canonical patch not present")
        original = canonical.read_text(encoding="utf-8")
        recounted = sp._recount_hunk_headers(
            original.replace("\r\n", "\n").replace("\r", "\n")
        )
        # The canonical patch is well-formed, so recount should be idempotent
        # (modulo line-ending normalization)
        self.assertEqual(
            recounted.strip(),
            original.replace("\r\n", "\n").strip(),
        )


if __name__ == "__main__":
    unittest.main()
