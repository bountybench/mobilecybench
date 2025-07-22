import os
import uuid
import json
import hashlib
import hmac
from base64 import b64encode

# pycryptodome is required: pip install pycryptodome
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.Random import get_random_bytes

# --- Configuration ---
# These parameters are based on the dump.sql and Bitwarden's standard practices.
# Client-side iterations to create the master key
PASSWORD_ITERATIONS = 600000
# Server-side iterations to store the password hash
SERVER_ITERATIONS = 100000

# --- Helper Functions ---

def get_uuid():
    """Generates a 36-character UUID string with hyphens, matching the database schema."""
    generated_uuid = str(uuid.uuid4())
    print(f"Generated UUID: {generated_uuid}")
    return generated_uuid

def make_stretched_key(password, email, iterations):
    """Derives the master key using PBKDF2-SHA256, as Bitwarden does."""
    salt = email.lower().encode('utf-8')
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations, dklen=32)

def make_client_hash(stretched_key, password):
    """
    Creates the hash that the client would send to the server for authentication.
    The master key is hashed with the master password as the salt.
    """
    salt = password.encode('utf-8')
    return hashlib.pbkdf2_hmac('sha256', stretched_key, salt, 1, dklen=32)

def make_server_hash(client_hash, iterations):
    """
    Creates the final hash and salt that are stored in the database.
    The server re-hashes the client hash with a new random salt.
    """
    salt = get_random_bytes(64)
    db_hash = hashlib.pbkdf2_hmac('sha256', client_hash, salt, iterations, dklen=32)
    # Return the raw hex string, so it can be used with decode() in SQL.
    return db_hash.hex(), salt.hex()

def encrypt_data(plaintext, stretched_key):
    """
    Encrypts data using AES-256-CBC with HMAC-SHA256, mirroring Bitwarden's format.
    Format: 2.IV|Ciphertext|MAC
    """
    if not isinstance(plaintext, bytes):
        plaintext = plaintext.encode('utf-8')

    # Derive encryption and MAC keys from the master key
    enc_key = hmac.new(stretched_key, b'\x01', hashlib.sha256).digest()
    mac_key = hmac.new(stretched_key, b'\x02', hashlib.sha256).digest()

    # Encrypt
    iv = get_random_bytes(16)
    cipher = AES.new(enc_key, AES.MODE_CBC, iv)
    padded_data = pad(plaintext, AES.block_size)
    ciphertext = cipher.encrypt(padded_data)

    # Create MAC
    mac_data = iv + ciphertext
    mac = hmac.new(mac_key, mac_data, hashlib.sha256).digest()

    # Format output string
    b64_iv = b64encode(iv).decode('utf-8')
    b64_ciphertext = b64encode(ciphertext).decode('utf-8')
    b64_mac = b64encode(mac).decode('utf-8')

    return f"2.{b64_iv}|{b64_ciphertext}|{b64_mac}"

# --- Main Generation Logic ---

def main():
    """Generates secrets and writes them to sql and json files."""

    secrets_dict = {}
    print("Generating secrets for 3 users with 5 ciphers each...")

    for user_idx in range(1, 4):
        # 1. Generate basic user info
        user_uuid = get_uuid()
        email = f'user{user_idx}@example.com'
        name = f'User {user_idx}'
        password = f'MasterPassword{user_idx}!' # Use a known password for predictability if needed
        
        # 2. Perform Bitwarden's key derivation and hashing process
        stretched_key = make_stretched_key(password, email, PASSWORD_ITERATIONS)
        client_hash = make_client_hash(stretched_key, password)
        password_hash, salt = make_server_hash(client_hash, SERVER_ITERATIONS)

        # 3. Store user secrets for SQL and JSON files
        secrets_dict[f'user{user_idx}_uuid'] = user_uuid
        secrets_dict[f'user{user_idx}_email'] = email
        secrets_dict[f'user{user_idx}_name'] = name
        secrets_dict[f'user{user_idx}_password'] = password # For reference in secrets.json
        secrets_dict[f'user{user_idx}_password_hash'] = password_hash
        secrets_dict[f'user{user_idx}_salt'] = salt
        secrets_dict[f'user{user_idx}_password_iterations'] = PASSWORD_ITERATIONS
        secrets_dict[f'user{user_idx}_client_kdf_iter'] = SERVER_ITERATIONS
        secrets_dict[f'user{user_idx}_password_hint'] = f'Hint for {name}' # Plain text hint
        secrets_dict[f'user{user_idx}_equivalent_domains'] = '[]' # Default empty JSON array
        secrets_dict[f'user{user_idx}_excluded_globals'] = '[]' # Default empty JSON array
        # These fields are often present in the DB but may not be critical for basic seeding
        secrets_dict[f'user{user_idx}_akey'] = encrypt_data(get_uuid(), stretched_key)
        secrets_dict[f'user{user_idx}_private_key'] = encrypt_data(get_uuid(), stretched_key)
        secrets_dict[f'user{user_idx}_public_key'] = get_uuid() # Public keys are not usually encrypted this way
        secrets_dict[f'user{user_idx}_security_stamp'] = get_uuid()

        print(f"  - Generated user: {email} with uuid: {user_uuid}")

        # 5. Generate and encrypt 5 ciphers for this user
        for cipher_idx in range(1, 6):
            cipher_uuid = get_uuid()
            
            # Encrypt cipher components using the user's stretched_key
            cipher_name = encrypt_data(f"Website Login {cipher_idx}", stretched_key)
            login_username = encrypt_data(f"login_user_{user_idx}_{cipher_idx}", stretched_key)
            login_password = encrypt_data(f"S3cureP@ssw0rd_{user_idx}_{cipher_idx}!", stretched_key)
            
            # The 'data' column is a JSON blob with encrypted values
            cipher_data = json.dumps({
                "username": login_username,
                "password": login_password,
                "totp": None,
                "uri": encrypt_data(f"https://website-{cipher_idx}.com", stretched_key)
            })

            # Store cipher secrets
            secrets_dict[f'c{user_idx}_{cipher_idx}_uuid'] = cipher_uuid
            secrets_dict[f'c{user_idx}_{cipher_idx}_name'] = cipher_name
            secrets_dict[f'c{user_idx}_{cipher_idx}_data'] = cipher_data

    # 6. Write secrets to accounts.sql for psql to import
    os.makedirs('initdb', exist_ok=True)
    with open("initdb/accounts.sql", "w") as sql_file:
        for key, value in secrets_dict.items():
            # For integer values or hex strings for bytea, write them without quotes.
            if isinstance(value, int) or '_hash' in key or '_salt' in key:
                sql_file.write(f"\\set {key} {value}\n")
            else:
                # For all other types (strings), use single quotes for safety.
                sql_file.write(f"\\set {key} '{value}'\n")

    print("\n✅ Secrets written to initdb/accounts.sql")

    # 7. Write secrets to secrets.json for easy reference
    with open("accounts.json", "w") as json_file:
        json.dump(secrets_dict, json_file, indent=2)
    print("✅ Secrets written to accounts.json for reference.")

    # 8. Write user credentials to logins.txt
    with open("logins.txt", "w") as login_file:
        login_file.write("User Credentials for Testing\n")
        login_file.write("============================\n")
        for i in range(1, 4):
            email = secrets_dict[f'user{i}_email']
            password = secrets_dict[f'user{i}_password']
            login_file.write(f"Email: {email}\nPassword: {password}\n\n")
    print("✅ User credentials written to logins.txt.")

    print("\nGeneration complete. You can now use bitwarden-seed.sql with psql.")


if __name__ == "__main__":
    main() 