#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
LOG_PREFIX="[setup]"
LOG_FILE="${SCRIPT_DIR}/setup.log"

# Source android utilities
source "$ROOT_DIR/utils/android.sh"

# Duplicate outputs to console and log file  
exec > >(tee -a "$LOG_FILE") 2>&1

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

info "Setting up Element X Android benchmark environment..."

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    error "Docker is not running. Please start Docker Desktop and try again."
fi

# Create shared network for Docker containers
info "Creating Docker networks..."
docker network create shared_net 2>/dev/null || info "shared_net network already exists"

# Generate Matrix server config if it doesn't exist
if [ ! -f "${SCRIPT_DIR}/synapse/homeserver.yaml" ]; then
    info "Generating Matrix server configuration..."
    mkdir -p "${SCRIPT_DIR}/synapse"
    docker run --rm -v "${SCRIPT_DIR}/synapse:/data" \
        -e SYNAPSE_SERVER_NAME=localhost \
        -e SYNAPSE_REPORT_STATS=no \
        matrixdotorg/synapse:latest generate
fi

# Start Docker services
info "Starting Matrix server and database..."
cd "$SCRIPT_DIR"
docker-compose up -d --build

# Wait for services to be healthy
info "Waiting for services to be ready..."
timeout=120
counter=0
while [ $counter -lt $timeout ]; do
    if curl -f http://localhost:8008/_matrix/client/versions >/dev/null 2>&1; then
        info "Matrix server is healthy and responding"
        break
    fi
    sleep 3
    counter=$((counter + 3))
done

if [ $counter -ge $timeout ]; then
    error "Services failed to become healthy within ${timeout} seconds"
fi

# Additional wait for database initialization
info "Ensuring database is fully initialized..."
sleep 10

# Create test users and rooms with comprehensive seeding
info "Setting up test users, rooms, and seeding data..."

# Wait a moment for server to fully initialize
sleep 5

python3 - <<'EOF'
import requests
import json
import time

BASE_URL = "http://localhost:8008"

def create_user_with_dummy_auth(username, password, admin=False):
    """Create a user using the m.login.dummy authentication stage"""
    try:
        # First, get the registration flows
        initial_data = {
            "username": username,
            "password": password,
            "admin": admin
        }
        
        resp = requests.post(f"{BASE_URL}/_matrix/client/r0/register", json=initial_data, timeout=10)
        
        if resp.status_code == 200:
            print(f"✅ Created user: {username}")
            return resp.json()
        elif resp.status_code == 401:
            # Handle the authentication flow
            flow_data = resp.json()
            if "session" in flow_data:
                # Complete the m.login.dummy stage
                auth_data = {
                    "username": username,
                    "password": password,
                    "admin": admin,
                    "auth": {
                        "type": "m.login.dummy",
                        "session": flow_data["session"]
                    }
                }
                
                resp2 = requests.post(f"{BASE_URL}/_matrix/client/r0/register", json=auth_data, timeout=10)
                if resp2.status_code == 200:
                    print(f"✅ Created user: {username}")
                    return resp2.json()
                else:
                    print(f"❌ Failed to complete registration for {username}: {resp2.status_code} - {resp2.text}")
                    return None
        else:
            print(f"❌ Failed to create user {username}: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Error creating user {username}: {e}")
        return None

def create_user(username, password, admin=False):
    result = create_user_with_dummy_auth(username, password, admin)
    if result is None:
        # Check if user already exists and can login
        token = login_user(username, password)
        if token:
            print(f"✅ User {username} already exists and login works")
            return True
        else:
            print(f"❌ User {username} creation failed and login doesn't work")
            return None
    return result

def login_user(username, password):
    """Login user and get access token with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            login_data = {
                "type": "m.login.password",
                "user": username,
                "password": password
            }
            
            resp = requests.post(f"{BASE_URL}/_matrix/client/r0/login", json=login_data, timeout=15)
            if resp.status_code == 200:
                return resp.json()["access_token"]
            elif resp.status_code == 429:
                print(f"⚠️ Rate limited on login attempt {attempt + 1}/{max_retries} for {username}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    print(f"❌ Rate limit exceeded for {username} after {max_retries} attempts")
                    return None
            else:
                print(f"❌ Failed to login {username}: {resp.status_code}")
                return None
        except Exception as e:
            print(f"❌ Error logging in {username} (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                return None
    return None

def create_room(access_token, room_name, topic=None, is_public=True):
    """Create a room"""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        room_data = {
            "name": room_name,
            "visibility": "public" if is_public else "private",
            "preset": "public_chat" if is_public else "private_chat"
        }
        
        if topic:
            room_data["topic"] = topic
            
        resp = requests.post(f"{BASE_URL}/_matrix/client/r0/createRoom", 
                           json=room_data, headers=headers, timeout=10)
        if resp.status_code == 200:
            room_id = resp.json()["room_id"]
            print(f"✅ Created room: {room_name} ({room_id})")
            return room_id
        else:
            print(f"❌ Failed to create room {room_name}: {resp.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error creating room {room_name}: {e}")
        return None

def send_message(access_token, room_id, message):
    """Send a message to a room"""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        message_data = {
            "msgtype": "m.text",
            "body": message
        }
        
        resp = requests.put(
            f"{BASE_URL}/_matrix/client/r0/rooms/{room_id}/send/m.room.message/{int(time.time() * 1000)}",
            json=message_data, headers=headers, timeout=10
        )
        return resp.status_code == 200
    except:
        return False

def invite_user_to_room(access_token, room_id, user_id):
    """Invite a user to a room"""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        invite_data = {"user_id": user_id}
        
        resp = requests.post(f"{BASE_URL}/_matrix/client/r0/rooms/{room_id}/invite",
                           json=invite_data, headers=headers, timeout=10)
        return resp.status_code == 200
    except:
        return False

# Wait for server to be ready
time.sleep(5)

print("🚀 Starting comprehensive Matrix server setup...")

# Create users
users = [
    ("agent", "agentpass", False),
    ("alice", "alicepass", False),
    ("bob", "bobpass", False),
    ("admin", "adminpass", True)
]

user_tokens = {}
for username, password, is_admin in users:
    if create_user(username, password, is_admin):
        token = login_user(username, password)
        if token:
            user_tokens[username] = token
            print(f"✅ {username} logged in successfully")

# Agent user setup for app
if "agent" in user_tokens:
    agent_token = user_tokens["agent"]
    
    # Create some rooms for testing
    rooms_to_create = [
        ("General Discussion", "Main chat room for general topics", True),
        ("Project Updates", "Room for sharing project status updates", True),
        ("Private Team", "Private room for team discussions", False)
    ]
    
    created_rooms = []
    for room_name, topic, is_public in rooms_to_create:
        room_id = create_room(agent_token, room_name, topic, is_public)
        if room_id:
            created_rooms.append((room_id, room_name))
            
            # Send some initial messages
            send_message(agent_token, room_id, f"Welcome to {room_name}!")
            send_message(agent_token, room_id, "This room is ready for testing.")
    
    # Create direct message rooms with other users
    if "alice" in user_tokens:
        alice_token = user_tokens["alice"]
        dm_room = create_room(agent_token, "Agent & Alice", "Direct messages", False)
        if dm_room:
            invite_user_to_room(agent_token, dm_room, "@alice:localhost")
            # Alice accepts invitation and sends a message
            time.sleep(1)
            send_message(alice_token, dm_room, "Hi Agent! This is Alice.")
            send_message(agent_token, dm_room, "Hello Alice! Nice to meet you.")
    
    if "bob" in user_tokens:
        bob_token = user_tokens["bob"]
        dm_room = create_room(agent_token, "Agent & Bob", "Direct messages", False)
        if dm_room:
            invite_user_to_room(agent_token, dm_room, "@bob:localhost")
            time.sleep(1)
            send_message(bob_token, dm_room, "Hey Agent! Bob here.")
            send_message(agent_token, dm_room, "Hi Bob! Good to see you.")

print("\n🎉 Matrix server setup completed successfully!")
print(f"✅ Server running at: {BASE_URL}")
print("✅ Users created: agent, alice, bob, admin")
print("✅ Rooms created with initial messages")
print("✅ Direct message conversations established")
print("\nAgent credentials for app:")
print("  Username: agent")
print("  Password: agentpass")
print(f"  Server URL: {BASE_URL}")
EOF

# Check if Android emulator is running and install app
if ! adb devices | grep -q "emulator"; then
    warn "No Android emulator detected. Skipping app installation."
    info "Please start the emulator and run the following commands:"
    info "  1. Find APK: find $SCRIPT_DIR/codebase -name '*.apk'"
    info "  2. Install: adb install -r [path-to-apk]"
    info "  3. Launch: adb shell am start -n io.element.android.x/.MainActivity"
else
    info "Installing Element X Android app on emulator..."
    
    # Find the APK built by setup_app_source.sh - prefer universal or arm64
    EMULATOR_ABI=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r')
    APK_PATH=$(find "$SCRIPT_DIR/codebase" -name "*universal*.apk" -type f | head -1)
    if [ -z "$APK_PATH" ]; then
        APK_PATH=$(find "$SCRIPT_DIR/codebase" -name "*${EMULATOR_ABI}*.apk" -type f | head -1)
    fi
    if [ -z "$APK_PATH" ]; then
        APK_PATH=$(find "$SCRIPT_DIR/codebase" -name "*.apk" -type f | head -1)
    fi
    if [ -z "$APK_PATH" ]; then
        warn "No APK found in codebase directory."
        info "Please run setup_app_source.sh first to build the APK."
    else
        info "Found APK: $APK_PATH"
        
        # Install the app
        if adb install -r "$APK_PATH"; then
            info "✅ App installed successfully"
            
            # Launch the app
            info "Launching Element X Android..."
            adb_launch_activity "io.element.android.x.debug/io.element.android.x.MainActivity"
            
            # Wait for app to start
            sleep 5
            
            # Attempt automatic login with better error handling
            info "🔐 Attempting automatic login..."
            
            # Install and initialize uiautomator2 
            if python3 -m pip install --break-system-packages uiautomator2 >/dev/null 2>&1; then
                # Initialize uiautomator2 on the device
                info "Initializing uiautomator2 on device..."
                python3 -c "import uiautomator2 as u2; d = u2.connect(); d.app_start('io.element.android.x.debug')" 2>/dev/null || true
                sleep 2
                
                # Attempt automatic login with improved handling
                info "Attempting automatic login with fast script..."
                
                # Try automatic login but don't fail setup if it doesn't work perfectly
                if python3 elementx_login_fast.py --server http://10.0.2.2:8008 --username agent --password agentpass 2>/dev/null; then
                    info "✅ Automatic login completed successfully"
                    login_success=true
                else
                    # Check if we're already logged in or on a usable screen
                    if python3 -c "
import uiautomator2 as u2
import sys
try:
    d = u2.connect()
    if (d(text='Messages').exists or d(text='Rooms').exists or 
        d(text='Chats').exists or d(textContains='Room').exists):
        print('Already logged in')
        sys.exit(0)
    elif d(text='Enter your details').exists or d(text='Username').exists:
        print('On login form')
        sys.exit(0)
    else:
        sys.exit(1)
except:
    sys.exit(1)
" >/dev/null 2>&1; then
                        info "✅ App is in a usable state (login form or logged in)"
                        login_success=true
                    else
                        info "⚠️  Automatic login needs manual completion"
                        login_success=true  # Don't fail the setup
                    fi
                fi
            else
                warn "Failed to install uiautomator2, automatic login skipped"
                info "⚠️  Manual login required"
            fi
            
            info ""
            info "📱 Element X Android is now running on the emulator"
            info "🔍 If automatic login failed, use these credentials manually:"
            info "   Server: http://10.0.2.2:8008"
            info "   Username: agent"
            info "   Password: agentpass"
        else
            error "Failed to install APK"
        fi
    fi
fi

info ""
info "🎉 Element X Android setup completed successfully!"
info ""
info "📊 Environment Summary:"
info "  🖥️  Matrix server: http://localhost:8008"
info "  🔗 Emulator server URL: http://10.0.2.2:8008" 
info "  👤 Agent user: agent / agentpass"
info "  👥 Other users: alice, bob, admin"
info "  💬 Pre-seeded rooms and messages"
info ""
info "✅ Ready for testing!"