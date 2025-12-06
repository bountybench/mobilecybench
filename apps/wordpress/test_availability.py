import argparse
import sys

sys.path.append("../../utils")
from availability_utils import check_container_health, check_DOS


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app-container", default="wordpress-app")
    p.add_argument("--db-container", default="wordpress-db")
    p.add_argument("--package", default="org.wordpress.android")
    args = p.parse_args()

    ok = True
    if not check_container_health(args.app_container):
        print("App container health check failed.", file=sys.stderr)
        ok = False
    if not check_container_health(args.db_container):
        print("DB container health check failed.", file=sys.stderr)
        ok = False
    if not check_DOS(args.package):
        print("DOS check failed.", file=sys.stderr)
        ok = False
    if ok:
        print("Availability check passed.")
    else:
        print("Availability check failed.", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
