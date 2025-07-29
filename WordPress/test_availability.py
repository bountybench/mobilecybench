import sys
import argparse
import subprocess
import re

def check_docker_health(container):
    try:
        status = subprocess.check_output(
            ['docker', 'inspect', '--format={{.State.Health.Status}}', container],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        return status == 'healthy'
    except:
        return False

def check_logcat(package):
    try:
        raw = subprocess.check_output(['adb', 'logcat', '-d'], stderr=subprocess.DEVNULL)
        text = raw.decode(errors='ignore')
    except:
        return False
    if re.search(r'FATAL EXCEPTION|ANR in', text):
        return False
    return True

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--app-container', default='wordpress-app')
    p.add_argument('--db-container',  default='wordpress-db')
    p.add_argument('--package',       default='org.wordpress.android')
    args = p.parse_args()

    if not check_docker_health(args.app_container):
        sys.exit(1)
    if not check_docker_health(args.db_container):
        sys.exit(1)
    if not check_logcat(args.package):
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    main()
