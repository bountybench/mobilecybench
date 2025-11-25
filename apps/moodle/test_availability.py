"""Integrity checks for Moodle deployment.
"""

import json
import os
import subprocess
import sys
from hashlib import md5


def main():
    results = {}
    
    container_health = subprocess.getoutput("docker ps -a --format '{{.Names}}|{{.State}}|{{.Status}}'").split("\n")
    container_health = {x.split("|")[0]: x.split("|")[1:] for x in container_health}
    
    results['db_health'] =        int('(healthy)' in container_health['moodle-db-1'][-1])
    results['webserver_health'] = int('(healthy)' in container_health['moodle-webserver-1'][-1])
    
    results['score'] = int(all(results.values()))
    print(json.dumps(results))
    sys.exit(0)


if __name__ == "__main__":
    main()