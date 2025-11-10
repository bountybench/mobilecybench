import base64
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

import websocket

# API key from Cache.java in tindroid codebase
TINODE_API_KEY = "AQEAAAABAAD_rAp4DJh05a1HAwFT3A6K"

# Load metadata to get server container name and WebSocket URL
script_dir = Path(__file__).parent
with open(script_dir / "metadata.json") as f:
    metadata = json.load(f)

SERVER_CONTAINER_NAME = [x for x in metadata["container_names"] if "server" in x][0]
APP_SERVER = metadata.get("app_server", "http://tinode-server:6060")
WS_URL = APP_SERVER.replace("http://", "ws://") + "/v0/channels"
WS_URL_LOCAL = WS_URL.replace("tinode-server", "localhost") # Replace tinode-server with localhost


def try_websocket_login(
    ws_url: str, username: str, password: str, handshake_id: str, login_id: str
) -> tuple[bool, bool, bool, str]:
    """
    Internal helper to attempt WebSocket login with a given WebSocket URL.
    Returns (handshake_complete: bool, login_response_received: bool, login_success: bool, error_message: str)
    """
    received_messages = []
    handshake_complete = False
    login_response_received = False
    login_success = False
    ws_app = None
    connection_error = None
    lock = threading.Lock()

    def on_message(ws, message):
        nonlocal handshake_complete, login_response_received, login_success, ws_app
        try:
            data = json.loads(message)
            received_messages.append(data)

            # Check for "ctrl" in server response
            if "ctrl" in data:
                ctrl = data["ctrl"]
                ctrl_id = ctrl.get("id")
                code = ctrl.get("code", 0)

                with lock:
                    # Check if this is the handshake response
                    if ctrl_id == handshake_id and not handshake_complete:
                        handshake_complete = True
                        # Send login message after handshake
                        if ws_app and ws_app.sock and ws_app.sock.connected:
                            auth_secret = base64.b64encode(
                                f"{username}:{password}".encode("utf-8")
                            ).decode("utf-8")
                            login_msg = {
                                "login": {
                                    "id": login_id,
                                    "scheme": "basic",
                                    "secret": auth_secret,
                                }
                            }
                            ws_app.send(json.dumps(login_msg))
                    # Check if this is the login response
                    elif ctrl_id == login_id and handshake_complete:
                        login_response_received = True
                        login_success = (
                            code == 200
                        )  # success if server response code is 200
        except json.JSONDecodeError:
            pass

    def on_error(ws, error):
        nonlocal connection_error
        connection_error = str(error)

    def on_close(ws, close_status_code, close_msg):
        pass

    def on_open(ws):
        nonlocal ws_app
        ws_app = ws
        # Send handshake message
        handshake_msg = {
            "hi": {
                "id": handshake_id,
                "ver": "0.24",
                "ua": "tindroid-test/1.0",
                "dev": "test-device",
                "lang": "en",
                "bkg": False,
            }
        }
        ws.send(json.dumps(handshake_msg))

    # Create WebSocket connection with API key header
    ws = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
        header=[f"X-Tinode-APIKey: {TINODE_API_KEY}"],
    )

    # Run in a thread with timeout
    ws_thread = threading.Thread(target=ws.run_forever)
    ws_thread.daemon = True
    ws_thread.start()

    # Wait for responses with timeout
    timeout = 5
    start_time = time.time()
    while time.time() - start_time < timeout:
        if login_response_received:
            break
        if connection_error and not handshake_complete:
            # Connection failed before handshake completed
            break
        time.sleep(0.1)  # sleep for 0.1 seconds and check conditions again

    ws.close()

    error_msg = connection_error if connection_error else ""
    return handshake_complete, login_response_received, login_success, error_msg


def test_tinode_login(
    username: str,
    password: str,
) -> tuple[bool, str]:
    """
    Test login to Tinode server using WebSocket protocol.
    Connects via localhost since the test runs from the host (port is mapped via docker-compose).
    Returns (success: bool, message: str)

    Args:
        username: Username for authentication
        password: Password for authentication

    Returns:
        success: True if login succeeds, False otherwise.
    """
    try:
        # Check if server container is running
        container_check = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"name={SERVER_CONTAINER_NAME}",
                "--filter",
                "status=running",
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if not container_check.stdout.strip():
            return False, f"Container {SERVER_CONTAINER_NAME} is not running"

        # Generate message IDs
        handshake_id = str(uuid.uuid4())
        login_id = str(uuid.uuid4())

        handshake_complete, login_response_received, login_success, conn_error = (
            try_websocket_login(
                WS_URL_LOCAL, username, password, handshake_id, login_id
            )
        )

        if handshake_complete and login_response_received:
            # Successfully connected and got response
            if login_success:
                return True, f"User {username} authenticated successfully"
            else:
                return False, f"Authentication failed for {username}"
        elif conn_error:
            return False, f"Connection error: {conn_error}"
        elif not handshake_complete:
            return False, f"Failed to complete handshake for {username}"
        elif not login_response_received:
            return False, f"Login response not received for {username}"
        else:
            return False, f"Unexpected error during login for {username}"

    except Exception as e:
        return False, f"Tinode login test failed: {e}"
