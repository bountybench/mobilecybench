import json
import ssl
import time
import uuid

from websocket import create_connection


def login_with_llat(hostname, access_token):
    HA_WS = f"wss://{hostname}:8123/api/websocket"

    ws = create_connection(HA_WS, sslopt={"cert_reqs": ssl.CERT_NONE})

    auth_required = json.loads(ws.recv())
    print(f"Auth required: {auth_required}")

    ws.send(json.dumps({"type": "auth", "access_token": access_token}))

    auth_result = json.loads(ws.recv())
    print(f"Auth result: {auth_result}")

    if auth_result.get("type") != "auth_ok":
        print(f"Authentication failed: {auth_result}")
        ws.close()
        return None

    # This helper can be called several times in quick succession during the
    # access-control test suite; a second-granularity name can collide.
    client_name = f"pentest-script-{int(time.time())}-{uuid.uuid4().hex[:8]}"
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
