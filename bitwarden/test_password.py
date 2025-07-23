import hashlib
import os

# Test the password hashing
def hash_password_direct(password, salt, iterations):
    """
    Directly hash password using PBKDF2-SHA256, matching Vaultwarden's implementation.
    """
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations, dklen=32)

# Test with the actual values from the database
email = 'user1@example.com'
password = 'MasterPassword1!'
salt_hex = '97d9521ac4f351ac77592f5150cd4524b51bceaf33a674c255c8677a44e9d489f861f00e1db4d34c4ebe5e1eeeb573e3213e3880f8d966aa9d528ceb8d78dd73'
stored_hash_hex = 'a00261bd1078d9d1d798fc746d337bf4df58c2980ad6f53a2a70e70fa89f5092'
iterations = 600000

# Convert hex to bytes
salt = bytes.fromhex(salt_hex)
stored_hash = bytes.fromhex(stored_hash_hex)

print(f"Testing password verification:")
print(f"Email: {email}")
print(f"Password: {password}")
print(f"Salt (hex): {salt_hex}")
print(f"Stored hash (hex): {stored_hash_hex}")
print(f"Iterations: {iterations}")

# Generate hash with our function
generated_hash = hash_password_direct(password, salt, iterations)
generated_hash_hex = generated_hash.hex()

print(f"\nGenerated hash (hex): {generated_hash_hex}")
print(f"Stored hash (hex):   {stored_hash_hex}")
print(f"Match: {generated_hash == stored_hash}")

# Test with the exact same parameters from our script
print(f"\n--- Testing with our script parameters ---")
print(f"Using SERVER_ITERATIONS: {600000}")
print(f"Using PASSWORD_ITERATIONS: {600000}")

# Test with the same salt generation (but we can't reproduce the exact salt since it's random)
# Let's test with a known salt
test_salt = b'x' * 64  # 64 bytes of 'x'
test_hash = hash_password_direct(password, test_salt, iterations)
print(f"Test hash with known salt: {test_hash.hex()}") 