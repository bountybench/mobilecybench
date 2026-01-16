import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Union

from utils.logger import logger

# TODO: After https://github.com/bountybench/mobilecybench/pull/317 is merged, add unit tests
PathLike = Union[Path, str]


def _run_git_command(
    directory: Path,
    args: list[str],
    capture_output: bool = False,
    text: bool = True,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> Optional[subprocess.CompletedProcess]:
    """Helper function to run git commands with consistent error handling."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=directory,
            check=True,
            capture_output=capture_output,
            text=text,
            encoding=encoding if text else None,
            errors=errors if text else None,
        )
        logger.debug(f"Git command succeeded: git {' '.join(args)}", stacklevel=2)
        return result
    except subprocess.CalledProcessError as e:
        logger.error(
            f"Git command failed: git {' '.join(args)} - {str(e)}", stacklevel=2
        )
        raise


def git_submodule_update(directory_path: PathLike) -> None:
    """Update git submodules."""
    directory = Path(directory_path)
    _run_git_command(directory, ["submodule", "update", "--init", "."])
    logger.debug(f"Updated submodules in {directory}")


def git_checkout(
    directory_path: PathLike, target: str, force: bool = False, clean: bool = True
) -> None:
    """
    Checkout a specific commit or branch with options to clean and force.

    Args:
        directory_path: Path to the git repository
        target: Branch name, commit hash, or reference to checkout
        force: Whether to force checkout (discard local changes)
        clean: Whether to clean untracked files before checkout
    """
    directory = Path(directory_path)
    logger.debug(f"Checking out {target}")

    # Enable long paths support on Windows to handle deep node_modules directories
    if os.name == "nt":
        try:
            _run_git_command(
                directory, ["config", "core.longpaths", "true"], capture_output=True
            )
            logger.debug("Enabled core.longpaths for Windows")
        except subprocess.CalledProcessError:
            logger.warning("Failed to enable core.longpaths")

    cmd = ["checkout"]
    if force:
        cmd.append("--force")
    cmd.append(target)

    try:
        # Clean first if requested
        if clean:
            _run_git_command(directory, ["clean", "-fdx"])

        _run_git_command(directory, cmd)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to checkout {target}: {e.stderr}")
        raise


def onerror(func, path, exc_info):
    """
    Error handler for shutil.rmtree.

    If the error is due to a read-only file, add write permission and retry.
    Otherwise, re-raise the original exception.
    """
    import stat

    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    else:
        raise


def prepare_git_directory(dest_git_path):
    """Prepare the destination .git directory by removing existing one if needed."""
    if dest_git_path.exists():
        if dest_git_path.is_file():
            dest_git_path.unlink()
        else:  # is_dir
            shutil.rmtree(dest_git_path, onerror=onerror)


def initialize_git_repository(destination):
    """Initialize a new Git repository at the destination."""
    subprocess.run(
        ["git", "init"],
        cwd=str(destination),
        check=True,
        capture_output=True,
    )
    logger.debug(f"Initialized new Git repository at {destination}")


def cleanup_git_branches(destination):
    """Clean up all branches and make the current detached HEAD the new main branch.

    This function:
    1. Identifies all existing branches
    2. Creates a new main branch from the current HEAD
    3. Deletes all other branches completely

    Args:
        destination: Path to the Git repository
    """
    try:
        # Delete all branches
        deleted_branches = delete_non_current_branches(destination, exclude_branches=[])
        if deleted_branches:
            logger.debug(f"Deleted branches: {', '.join(deleted_branches)}")

        # Create a new main branch from the current HEAD
        subprocess.run(
            ["git", "checkout", "-B", "main"],
            cwd=str(destination),
            check=True,
            capture_output=True,
        )
        logger.debug(f"Created new main branch from detached HEAD in {destination}")

        # Delete all branches except main
        deleted_branches = delete_non_current_branches(destination, exclude_branches=[])
        if deleted_branches:
            logger.debug(f"Deleted branches: {', '.join(deleted_branches)}")

        # Garbage collect to ensure deleted branches are completely removed
        subprocess.run(
            ["git", "gc", "--prune=now", "--aggressive"],
            cwd=str(destination),
            check=True,
            capture_output=True,
        )
        logger.debug(f"Completed garbage collection in {destination}")

        # Final step: Explicitly checkout to the main branch to ensure we're on it
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(destination),
            check=True,
            capture_output=True,
        )
        logger.debug(f"Checked out to main branch in {destination}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Error cleaning up Git branches: {e}")
        raise


def git_setup_dev_branch(
    directory_path: PathLike, commit: Optional[str] = None
) -> None:
    """Set up dev branch from specified commit or main branch."""
    directory = Path(directory_path)
    if not commit:
        commit = _get_main_branch(directory_path)

    try:
        # Verify valid repository
        result = _run_git_command(
            directory, ["rev-parse", "--is-inside-work-tree"], capture_output=True
        )
        if result.stdout.strip() != "true":
            raise ValueError(f"Not a git repository: {directory}")

        # Checkout base commit
        _run_git_command(directory, ["checkout", "-f", commit])

        # Delete existing dev branch if it exists
        branches_output = _run_git_command(
            directory, ["branch"], capture_output=True
        ).stdout
        branch_names = [
            line.lstrip("* ").strip() for line in branches_output.splitlines()
        ]
        if "dev" in branch_names:
            _run_git_command(directory, ["branch", "-D", "dev"])

        # Create new dev branch
        _run_git_command(directory, ["checkout", "-b", "dev"])
        logger.debug(f"Created dev branch in {directory} from {commit}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to setup dev branch: {e}")
        raise


def delete_non_current_branches(destination, exclude_branches=None):
    """
    Args:
        destination: Path to the Git repository
        exclude_branches: List of branch names to exclude from deletion (default: None)

    Returns:
        List of successfully deleted branch names
    """
    if exclude_branches is None:
        exclude_branches = []

    deleted_branches = []

    # Get all branches
    result = subprocess.run(
        ["git", "branch"],
        cwd=str(destination),
        check=True,
        capture_output=True,
        text=True,
    )

    # Parse branch names
    branches = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("*"):
            # Skip the current HEAD which is likely (no branch)
            continue
        branch_name = line.strip()
        if branch_name not in exclude_branches:
            branches.append(branch_name)

    # Delete branches
    for branch in branches:
        try:
            # Force delete the branch
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=str(destination),
                check=True,
                capture_output=True,
            )
            logger.debug(f"Deleted branch {branch} from repository in {destination}")
            deleted_branches.append(branch)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to delete branch {branch}: {e}")
            raise

    return deleted_branches


def _get_main_branch(directory_path: PathLike) -> str:
    """Determine if repository uses 'main' or 'master' as default branch."""
    directory = Path(directory_path)

    # Get list of branches
    result = _run_git_command(directory, ["branch", "--list"], capture_output=True)
    branches = [
        branch.strip().lstrip("*").strip()
        for branch in result.stdout.split("\n")
        if branch.strip()
    ]

    # Check for 'main' or 'master'
    if "main" in branches:
        return "main"
    elif "master" in branches:
        return "master"
    else:
        raise ValueError("Neither 'main' nor 'master' branch found in the repository.")
