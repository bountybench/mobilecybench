import json
import time
from websocket import create_connection


def login_with_llat(hostname, access_token):
    HA_WS = f"ws://{hostname}:8123/api/websocket"

    ws = create_connection(HA_WS)

    auth_required = json.loads(ws.recv())
    print(f"Auth required: {auth_required}")

    ws.send(json.dumps({"type": "auth", "access_token": access_token}))

    auth_result = json.loads(ws.recv())
    print(f"Auth result: {auth_result}")

    if auth_result.get("type") != "auth_ok":
        print(f"Authentication failed: {auth_result}")
        ws.close()
        return None

    client_name = f"pentest-script-{int(time.time())}"
    req = {
        "id": 1,
        "type": "auth/long_lived_access_token",
        "client_name": client_name,
        "lifespan": 365,
    }
    ws.send(json.dumps(req))
    resp = json.loads(ws.recv())
    print(f"LLAT response: {resp}")
    ws.close()

    if resp.get("success"):
        return resp.get("result")
    else:
        print(f"Failed to create LLAT: {resp}")
        return None
