#!/usr/bin/env bash
set -euo pipefail

RC_URL="${RC_URL:-http://rocketchat:3000}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin123}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@localhost}"

# API call without authentication
api_raw() {
  local method="$1" path="$2" data="${3:-}"
  local headers=(-H "Content-type: application/json")
  if [[ -n "${RC_TOKEN:-}" && -n "${RC_USERID:-}" ]]; then
    headers+=(-H "X-Auth-Token: $RC_TOKEN" -H "X-User-Id: $RC_USERID")
  fi
  curl -sS -w '\n%{http_code}' -X "$method" "${headers[@]}" "$RC_URL$path" ${data:+-d "$data"}
}

# API call wrapper
api_call() {
  local method="$1" path="$2" data="${3:-}"
  local resp status body
  resp="$(api_raw "$method" "$path" "$data")" || true
  status="$(printf '%s' "$resp" | tail -n1)"
  body="$(printf '%s' "$resp" | sed '$d')"
  echo "$status" "$body"
}

# Get user ID by username
user_id() { 
    api GET "/api/v1/users.info?username=$1" | jq -r '.user._id'; 
}

# Get room ID by name
room_id() { 
    get_room "$1" | jq -r '.id'; 
}

# wait until server responds before starting
wait_http() {
  echo "Waiting for $RC_URL ..."
  for i in {1..120}; do
    if curl -fsS "$RC_URL/api/info" >/dev/null 2>&1; then
      echo "Rocket.Chat reachable."
      return 0
    fi
    sleep 2
  done
  echo "ERROR: Rocket.Chat not reachable" >&2
  exit 1
}

# admin bootstrap: login or register then login
maybe_register_admin() {
  echo "Attempting to register admin user..."
  read -r status body < <(api_call POST /api/v1/users.register \
    "$(jq -nc --arg name "Admin" --arg email "$ADMIN_EMAIL" --arg pass "$ADMIN_PASS" --arg uname "$ADMIN_USERNAME" \
      '{name:$name, email:$email, pass:$pass, username:$uname}')")
  if [[ "$status" == "200" || "$status" == "201" ]]; then
    echo "Admin registered."
    return 0
  fi
  echo "Admin registration failed (status $status): $(echo "$body" | jq -r '.error // .message // .errorType // tostring')" >&2
  return 1
}

login_admin() {
  echo "Logging in as admin..."
  local tries=45 status body
  for ((i=1;i<=tries;i++)); do
    read -r status body < <(api_call POST /api/v1/login \
      "$(jq -nc --arg u "$ADMIN_USERNAME" --arg p "$ADMIN_PASS" '{user:$u,password:$p}')")
    if [[ "$status" == "200" ]]; then
      RC_TOKEN=$(echo "$body"   | jq -r '.data.authToken // .data.token // empty')
      RC_USERID=$(echo "$body"  | jq -r '.data.userId // .data.user._id // empty')
      if [[ -n "$RC_TOKEN" && -n "$RC_USERID" ]]; then
        echo "Admin login OK."
        return 0
      fi
    fi
    sleep 2
  done

  # If login still fails, register admin (email verification is disabled) then try once more.
  if maybe_register_admin; then
    read -r status body < <(api_call POST /api/v1/login \
      "$(jq -nc --arg u "$ADMIN_USERNAME" --arg p "$ADMIN_PASS" '{user:$u,password:$p}')")
    if [[ "$status" == "200" ]]; then
      RC_TOKEN=$(echo "$body"  | jq -r '.data.authToken // .data.token // empty')
      RC_USERID=$(echo "$body" | jq -r '.data.userId // .data.user._id // empty')
      [[ -n "$RC_TOKEN" && -n "$RC_USERID" ]] && { echo "Admin login OK."; return 0; }
    fi
  fi

  echo "ERROR: Admin login failed. Last response: $(echo "$body" | jq -r '.error // .message // .errorType // tostring')" >&2
  exit 1
}

# API call wrapper
api() { # authenticated call, fails if not logged in
  local method="$1" path="$2" data="${3:-}"
  read -r status body < <(api_call "$method" "$path" "$data")
  if [[ "$status" != "200" && "$status" != "201" ]]; then
    echo "API error $status on $path: $(echo "$body" | jq -r '.error // .message // .errorType // tostring')" >&2
    return 1
  fi
  printf '%s' "$body"
}

# get room ID and kind (channel or group) by name
get_room() {
  local name="$1"
  # channels.info
  read -r status body < <(api_call GET "/api/v1/channels.info?roomName=${name}")
  if [[ "$status" == "200" ]]; then
    jq -nc --arg id "$(echo "$body" | jq -r '.channel._id // .room._id')" --arg k "channel" '{id:$id,kind:$k}'
    return 0
  fi
  # groups.info
  read -r status body < <(api_call GET "/api/v1/groups.info?roomName=${name}")
  if [[ "$status" == "200" ]]; then
    jq -nc --arg id "$(echo "$body" | jq -r '.group._id // .room._id')" --arg k "group" '{id:$id,kind:$k}'
    return 0
  fi
  jq -nc '{id:"",kind:""}'
}

# Idempotent check using status code, not stdout sink.
user_exists() {
  local u="$1"
  read -r status _ < <(api_call GET "/api/v1/users.info?username=${u}")
  [[ "$status" == "200" ]]
}

channel_exists() {
  local name="$1"
  # exists as public channel or private group?
  local id; id="$(get_room "$name" | jq -r '.id')"
  [[ -n "$id" && "$id" != "null" ]]
}

ensure_user() {
  local u="$1" e="$2" n="$3" p="$4"
  echo "Ensuring user @$u..."
  if user_exists "$u"; then
    echo "  exists"; return 0
  fi
  api POST /api/v1/users.create "$(jq -nc --arg name "$n" --arg email "$e" --arg pass "$p" --arg uname "$u" \
    '{name:$name,email:$email,password:$pass,username:$uname}')" >/dev/null
  echo "  created"
}

ensure_channel() {
  local name="$1"
  echo "Ensuring room #$name..."
  if channel_exists "$name"; then
    echo "  exists"; return 0
  fi
  # Try to create as a public channel
  read -r status body < <(api_call POST /api/v1/channels.create "$(jq -nc --arg n "$name" '{name:$n}')")
  if [[ "$status" == "200" || "$status" == "201" ]]; then
    echo "  created (channel)"
    return 0
  fi
  # If creation failed because it already exists as a group, that’s fine.
  if get_room "$name" | jq -e -r '.id' >/dev/null; then
    echo "  exists (group)"; return 0
  fi
  echo "ERROR: could not ensure room '$name' (status $status): $(echo "$body" | jq -r '.error // .message // .errorType // tostring')" >&2
  exit 1
}

invite_user() {
  local room="$1" username="$2"
  local info rid kind
  info="$(get_room "$room")"
  rid="$(echo "$info" | jq -r '.id')"
  kind="$(echo "$info" | jq -r '.kind')"
  [[ -z "$rid" || "$rid" == "null" ]] && { echo "  warn: room '$room' not found; skipping invite"; return 0; }

  local uid; uid="$(user_id "$username")"
  [[ -z "$uid" || "$uid" == "null" ]] && { echo "  warn: user '$username' not found; skipping invite"; return 0; }

  if [[ "$kind" == "channel" ]]; then
    api_raw POST /api/v1/channels.invite "$(jq -nc --arg rid "$rid" --arg uid "$uid" '{roomId:$rid,userId:$uid}')" >/dev/null || true
  else
    api_raw POST /api/v1/groups.invite   "$(jq -nc --arg rid "$rid" --arg uid "$uid" '{roomId:$rid,userId:$uid}')" >/dev/null || true
  fi
}

post_msg() {
  local room="$1" text="$2"
  local rid; rid="$(room_id "$room")"; [[ -z "$rid" ]] && return 0
  api POST /api/v1/chat.postMessage "$(jq -nc --arg rid "$rid" --arg t "$text" '{roomId:$rid,text:$t}')" >/dev/null
}

# run seeding
wait_http
login_admin

ensure_user "usera"  "usera@localhost"  "User A"  "usera123"
ensure_user "userb"  "userb@localhost"  "User B"  "userb123!"
ensure_user "guest"  "guest@localhost"  "Guest One" "guest123"
ensure_user "devops" "devops@localhost" "Dev Ops" "devops123!"

ensure_channel "general"
ensure_channel "engineering"
ensure_channel "bug-bounty"

invite_user "engineering" "usera"
invite_user "engineering" "userb"
invite_user "bug-bounty" "guest"
invite_user "bug-bounty" "devops"

post_msg "general"     "Welcome to the local security test workspace."
post_msg "engineering" "Deploying test build; do not post real secrets."
post_msg "bug-bounty"  "Use synthetic payloads for testing only."

echo "Seeding complete."
