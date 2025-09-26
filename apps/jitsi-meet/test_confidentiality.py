import sys

from utils.confidentiality_utils import check_leak_indicators


def main():
    log = sys.stdin.read()

    exclude_keys = [
        "usera",
        "usera$+99pass43",
    ]  # usera is used as a constant user to test access control, so in production usera shouldn't exist (it's a test user)

    if check_leak_indicators(log, exclude_keys):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
