SCRIPT_DIR="$(dirname "$0")"
PYTHONIOENCODING=utf-8 nohup python3 "$SCRIPT_DIR/../exploit_files/attacker_server.py" > /tmp/attacker_server.log 2>&1 &
echo $! > /tmp/attacker_server.pid
echo "Attacker server started on host"