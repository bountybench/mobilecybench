import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

if __name__ == "__main__":
    """
    This is useful for running this test file directly. The utils.git_utils import needs sys.path[0] as project root.
    To avoid this, you can use python -m tests.utils.test_git_utils to treat sys.path[0] as the actual project root
    I have this functionality for convenience in workflow CI.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.git_utils import (
    _get_main_branch,
    cleanup_git_branches,
    delete_non_current_branches,
    git_checkout,
    initialize_git_repository,
    onerror,
    prepare_git_directory,
)

# >>PROJECT SETUP<<


def _create_basic_repo(tmp_path: Path) -> Path:
    """
    Creates a fresh repo with at least one commit.
    Repo is temporary and will be deleted after test.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    initialize_git_repository(repo_dir)

    # create an initial commit
    (repo_dir / "README.md").write_text("# Test Repo", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    # set a local identity for CI/test environments
    subprocess.run(
        ["git", "config", "user.name", "ci_test"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ci@test"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_dir


# >>TEST CASES<<


def test_prepare_git_directory():
    print("Testing prepare_git_directory...")
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        repo = _create_basic_repo(temp_path)
        git_path = repo / ".git"

        # ensure .git exists
        assert git_path.exists()

        # prepare directory (should delete .git)
        prepare_git_directory(git_path)

        assert not git_path.exists(), ".git directory should be removed"
    print("prepare_git_directory passed")


def test_initialize_and_detect_main():
    print("Testing initialize + _get_main_branch...")
    with tempfile.TemporaryDirectory() as temp:
        repo = _create_basic_repo(Path(temp))
        branch = _get_main_branch(repo)
        assert branch in ("main", "master"), f"Unexpected main branch: {branch}"
    print("main branch detected correctly")


def test_git_checkout_force_clean():
    print("Testing git_checkout force + clean...")
    with tempfile.TemporaryDirectory() as temp:
        repo = _create_basic_repo(Path(temp))

        # create new branch
        subprocess.run(
            ["git", "checkout", "-b", "test"], cwd=str(repo), check=True, text=True
        )

        # modify file without commit
        (repo / "dirty.txt").write_text("dirty", encoding="utf-8")

        # checkout main/master with force+clean: dirty file should vanish
        main_branch = _get_main_branch(repo)
        git_checkout(repo, target=main_branch, force=True, clean=True)

        assert not (repo / "dirty.txt").exists(), "Dirty file should be removed"
    print("force-clean checkout works")


def test_delete_non_current_branches():
    print("Testing delete_non_current_branches...")
    with tempfile.TemporaryDirectory() as temp:
        repo = _create_basic_repo(Path(temp))

        # create multiple branches
        subprocess.run(
            ["git", "checkout", "-b", "a"], cwd=str(repo), check=True, text=True
        )
        subprocess.run(
            ["git", "checkout", "-b", "b"], cwd=str(repo), check=True, text=True
        )
        subprocess.run(
            ["git", "checkout", "-b", "c"], cwd=str(repo), check=True, text=True
        )

        deleted = delete_non_current_branches(repo, exclude_branches=[])
        assert set(deleted) == {
            "a",
            "b",
            "master",
        }, f"Unexpected deleted branches: {deleted}"

        # ensure branch c remains because it's current HEAD
        branches_output = subprocess.run(
            ["git", "branch"], cwd=str(repo), capture_output=True, text=True
        ).stdout
        assert "c" in branches_output
    print("branch deletion correct")


def test_onerror_readonly_file_removal():
    """Test that the onerror handler allows deleting read-only files."""
    print("Testing onerror handler for read-only files...")

    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        # create a directory with a read-only file
        nested_dir = temp_path / "nested"
        nested_dir.mkdir()
        read_only_file = nested_dir / "readonly.txt"
        read_only_file.write_text("read-only content", encoding="utf-8")
        # make file read-only
        read_only_file.chmod(stat.S_IREAD)

        # attempt to delete the directory using shutil.rmtree with onerror function in git_utils file
        try:
            shutil.rmtree(nested_dir, onerror=onerror)
        except Exception as e:
            assert False, f"onerror failed to remove read-only file: {e}"

        # assert the directory no longer exists
        assert not nested_dir.exists(), "Directory should be deleted"
    print("onerror handler works for read-only files")


def test_cleanup_git_branches_main_reset():
    print("Testing cleanup_git_branches...")
    with tempfile.TemporaryDirectory() as temp:
        repo = _create_basic_repo(Path(temp))

        # create temporary branches
        subprocess.run(
            ["git", "checkout", "-b", "temp1"], cwd=str(repo), check=True, text=True
        )
        subprocess.run(
            ["git", "checkout", "-b", "temp2"], cwd=str(repo), check=True, text=True
        )

        cleanup_git_branches(repo)

        branches_output = subprocess.run(
            ["git", "branch"], cwd=str(repo), capture_output=True, text=True
        ).stdout
        assert "main" in branches_output or "master" in branches_output
        assert "temp1" not in branches_output
        assert "temp2" not in branches_output
    print("cleanup_git_branches passed")


# >>MAIN START<<


def run_all_tests():
    print("Git Utilities Test Suite")
    print("=" * 50)

    tests = [
        test_prepare_git_directory,
        test_initialize_and_detect_main,
        test_git_checkout_force_clean,
        test_delete_non_current_branches,
        test_onerror_readonly_file_removal,
        test_cleanup_git_branches_main_reset,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as ex:
            failed += 1
            print(f"{test.__name__} failed: {ex}")
            import traceback

            traceback.print_exc()
        print()

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")

    return failed == 0


if __name__ == "__main__":
    ok = run_all_tests()
    sys.exit(0 if ok else 1)