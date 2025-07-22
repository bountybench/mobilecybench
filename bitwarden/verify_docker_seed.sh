#!/bin/bash
set -e

# Database connection details (must match docker-compose.yml)
DB_CONTAINER="db"
DB_NAME="vaultwarden"
DB_USER="bitwarden"

echo "[INFO] Verifying Bitwarden database seed..."

# Check that the db container is running
if ! docker-compose ps | grep -q "${DB_CONTAINER}"; then
  echo "[ERROR] Database container '${DB_CONTAINER}' is not running."
  exit 1
fi

# Query for user count
USER_COUNT=$(docker-compose exec -T ${DB_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME} -t -c "SELECT COUNT(*) FROM public.users;")
USER_COUNT=$(echo $USER_COUNT | xargs) # trim whitespace

# Query for cipher count
CIPHER_COUNT=$(docker-compose exec -T ${DB_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME} -t -c "SELECT COUNT(*) FROM public.ciphers;")
CIPHER_COUNT=$(echo $CIPHER_COUNT | xargs)

# Optionally, print user emails for confirmation
USER_EMAILS=$(docker-compose exec -T ${DB_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME} -t -c "SELECT email FROM public.users ORDER BY email;")

echo "[INFO] Found $USER_COUNT users and $CIPHER_COUNT ciphers in the database."
echo "[INFO] User emails:"
echo "$USER_EMAILS"

# Check expected counts
if [[ "$USER_COUNT" -eq 3 && "$CIPHER_COUNT" -eq 15 ]]; then
  echo "[SUCCESS] Database was successfully seeded with expected users and ciphers."
else
  echo "[FAIL] Database seed verification failed."
  exit 2
fi

# Additional check: verify UUIDs from accounts.json
ACCOUNTS_JSON="accounts.json"
if [ ! -f "$ACCOUNTS_JSON" ]; then
  echo "[WARN] $ACCOUNTS_JSON not found, skipping UUID verification."
  exit 0
fi

MISSING_UUIDS=0

# Check user UUIDs
for i in 1 2 3; do
  uuid=$(jq -r ".user${i}_uuid" "$ACCOUNTS_JSON")
  found=$(docker-compose exec -T ${DB_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME} -t -c "SELECT COUNT(*) FROM public.users WHERE uuid = '$uuid';" | xargs)
  if [[ "$found" -ne 1 ]]; then
    echo "[FAIL] User UUID $uuid not found in users table."
    MISSING_UUIDS=1
  fi
  for j in 1 2 3 4 5; do
    cipher_uuid=$(jq -r ".c${i}_${j}_uuid" "$ACCOUNTS_JSON")
    found=$(docker-compose exec -T ${DB_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME} -t -c "SELECT COUNT(*) FROM public.ciphers WHERE uuid = '$cipher_uuid';" | xargs)
    if [[ "$found" -ne 1 ]]; then
      echo "[FAIL] Cipher UUID $cipher_uuid not found in ciphers table."
      MISSING_UUIDS=1
    fi
  done
done

if [[ "$MISSING_UUIDS" -eq 0 ]]; then
  echo "[SUCCESS] All user and cipher UUIDs from accounts.json are present in the database."
  # exit 0
else
  echo "[FAIL] Some UUIDs from accounts.json are missing in the database."
  exit 3
fi

# Print all cipher UUIDs from the database
DB_CIPHER_UUIDS=$(docker-compose exec -T ${DB_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME} -t -c "SELECT uuid FROM public.ciphers ORDER BY uuid;")
DB_CIPHER_UUIDS=$(echo "$DB_CIPHER_UUIDS" | xargs -n1)

# Print all cipher UUIDs from accounts.json
JSON_CIPHER_UUIDS=$(jq -r 'to_entries | map(select(.key | test("^c[0-9]+_[0-9]+_uuid$"))) | .[].value' "$ACCOUNTS_JSON" | sort)

# Print both lists
# echo "[INFO] Cipher UUIDs in database:"
# echo "$DB_CIPHER_UUIDS"
# echo "[INFO] Cipher UUIDs in accounts.json:"
# echo "$JSON_CIPHER_UUIDS"

# Compare the two lists
MISSING_IN_DB=()
EXTRA_IN_DB=()

for uuid in $JSON_CIPHER_UUIDS; do
  if ! echo "$DB_CIPHER_UUIDS" | grep -qx "$uuid"; then
    MISSING_IN_DB+=("$uuid")
  fi
done

for uuid in $DB_CIPHER_UUIDS; do
  if ! echo "$JSON_CIPHER_UUIDS" | grep -qx "$uuid"; then
    EXTRA_IN_DB+=("$uuid")
  fi
done

if [[ ${#MISSING_IN_DB[@]} -eq 0 && ${#EXTRA_IN_DB[@]} -eq 0 ]]; then
  echo "[SUCCESS] All cipher UUIDs in accounts.json match those in the database."
else
  if [[ ${#MISSING_IN_DB[@]} -gt 0 ]]; then
    echo "[FAIL] The following cipher UUIDs are in accounts.json but missing in the database:"
    printf '%s\n' "${MISSING_IN_DB[@]}"
  fi
  if [[ ${#EXTRA_IN_DB[@]} -gt 0 ]]; then
    echo "[FAIL] The following cipher UUIDs are in the database but not in accounts.json:"
    printf '%s\n' "${EXTRA_IN_DB[@]}"
  fi
  exit 4
fi