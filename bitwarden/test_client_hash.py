import hashlib

def make_stretched_key(password, email, iterations):
    """Derives the master key using PBKDF2-SHA256 - this is what the client does."""
    salt = email.lower().encode('utf-8')
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations, dklen=32)

def hash_password_direct(password, salt, iterations):
    """
    Directly hash password using PBKDF2-SHA256, matching Vaultwarden's implementation.
    """
    if isinstance(password, bytes):
        password_bytes = password
    else:
        password_bytes = password.encode('utf-8')
    return hashlib.pbkdf2_hmac('sha256', password_bytes, salt, iterations, dklen=32)

# Test with the actual values from the database
email = 'user1@example.com'
password = 'MasterPassword1!'
salt_hex = '97d9521ac4f351ac77592f5150cd4524b51bceaf33a674c255c8677a44e9d489f861f00e1db4d34c4ebe5e1eeeb573e3213e3880f8d966aa9d528ceb8d78dd73'
stored_hash_hex = 'a00261bd1078d9d1d798fc746d337bf4df58c2980ad6f53a2a70e70fa89f5092'
iterations = 600000

# Convert hex to bytes
salt = bytes.fromhex(salt_hex)
stored_hash = bytes.fromhex(stored_hash_hex)

print(f"Testing different password formats:")
print(f"Email: {email}")
print(f"Raw password: {password}")
print(f"Salt (hex): {salt_hex}")
print(f"Stored hash (hex): {stored_hash_hex}")
print(f"Iterations: {iterations}")

# Test 1: Raw password (what Vaultwarden expects)
print(f"\n--- Test 1: Raw password ---")
raw_password_hash = hash_password_direct(password, salt, iterations)
raw_password_hash_hex = raw_password_hash.hex()
print(f"Raw password hash: {raw_password_hash_hex}")
print(f"Stored hash:        {stored_hash_hex}")
print(f"Match: {raw_password_hash == stored_hash}")

# Test 2: Master password hash (what client might send)
print(f"\n--- Test 2: Master password hash (client-side KDF) ---")
master_key = make_stretched_key(password, email, iterations)
master_key_hex = master_key.hex()
print(f"Master key (client-side): {master_key_hex}")

# The client might send the master key as the "password"
master_key_hash = hash_password_direct(master_key, salt, iterations)
master_key_hash_hex = master_key_hash.hex()
print(f"Master key hash: {master_key_hash_hex}")
print(f"Stored hash:      {stored_hash_hex}")
print(f"Match: {master_key_hash == stored_hash}")

# Test 3: Base64 encoded master key (what client might actually send)
print(f"\n--- Test 3: Base64 encoded master key ---")
import base64
master_key_b64 = base64.b64encode(master_key).decode('ascii')
print(f"Master key (base64): {master_key_b64}")

# Test if the client sends the base64 master key as the password
master_key_b64_hash = hash_password_direct(master_key_b64, salt, iterations)
master_key_b64_hash_hex = master_key_b64_hash.hex()
print(f"Base64 master key hash: {master_key_b64_hash_hex}")
print(f"Stored hash:             {stored_hash_hex}")
print(f"Match: {master_key_b64_hash == stored_hash}")

print(f"\n--- Conclusion ---")
print(f"The issue is likely that the Bitwarden client sends a master password hash")
print(f"(generated from client-side KDF) instead of the raw password.")
print(f"Vaultwarden expects the raw password for verification.") 