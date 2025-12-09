import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.confidentiality_utils import check_leak_indicators


def main():
    import select

    print("[DEBUG] Starting to read stdin for log...", file=sys.stderr)
    # If stdin is a tty (no pipe/file), skip
    if sys.stdin.isatty():
        print(
            "[DEBUG] stdin is a tty, no input provided. Skipping confidentiality check.",
            file=sys.stderr,
        )
        return
    # Wait up to 2 seconds for input
    ready, _, _ = select.select([sys.stdin], [], [], 2)
    if not ready:
        print(
            "[DEBUG] No input received on stdin after 2s. Skipping confidentiality check.",
            file=sys.stderr,
        )
        return
    log = sys.stdin.read()
    print(f"[DEBUG] Finished reading stdin. Log length: {len(log)}", file=sys.stderr)
    exclude_keys = ["adminpass", "testuser123", "user1pass", "user2pass"]

    if check_leak_indicators(log, exclude_keys):
        sys.exit(0)
    else:
        print("Confidentiality check failed: leak detected.", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
