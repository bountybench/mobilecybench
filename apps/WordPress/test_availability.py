import sys
import argparse
sys.path.append("../../utils")
from availability_utils import check_container_health, check_DOS

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--app-container', default='wordpress-app')
    p.add_argument('--db-container',  default='wordpress-db')
    p.add_argument('--package',       default='org.wordpress.android')
    args = p.parse_args()

    if not check_container_health(args.app_container):
        sys.exit(1)
    if not check_container_health(args.db_container):
        sys.exit(1)
    if not check_DOS(args.package):
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    main()