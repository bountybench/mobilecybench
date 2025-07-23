import hashlib
import requests

def hash_password_direct(password, salt, iterations):
    """Directly hash password using PBKDF2-SHA256."""
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations, dklen=32)

def test_simple_password():
    """Test with a simple password to see if special characters are the issue."""
    
    # Simple password without special characters
    email = "user1@example.com"
    simple_password = "password123"
    
    print("Testing with simple password:")
    print("=" * 50)
    print(f"Email: {email}")
    print(f"Simple password: {simple_password}")
    
    # Generate hash for simple password
    salt_hex = '97d9521ac4f351ac77592f5150cd4524b51bceaf33a674c255c8677a44e9d489f861f00e1db4d34c4ebe5e1eeeb573e3213e3880f8d966aa9d528ceb8d78dd73'
    salt = bytes.fromhex(salt_hex)
    iterations = 600000
    
    simple_hash = hash_password_direct(simple_password, salt, iterations)
    simple_hash_hex = simple_hash.hex()
    
    print(f"Simple password hash: {simple_hash_hex}")
    
    # Update the database with the simple password hash
    import subprocess
    update_cmd = f"""
    docker exec -i bitwarden-db-1 psql -U bitwarden -d vaultwarden -c "
    UPDATE users 
    SET password_hash = decode('{simple_hash_hex}', 'hex') 
    WHERE email = 'user1@example.com';
    "
    """
    
    print(f"\nUpdating database with simple password hash...")
    result = subprocess.run(update_cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"   ✅ Database updated successfully")
    else:
        print(f"   ❌ Database update failed: {result.stderr}")
        return
    
    # Test login with simple password
    print(f"\nTesting login with simple password...")
    login_data = {
        "grant_type": "password",
        "client_id": "web",
        "client_secret": "",
        "username": email,
        "password": simple_password,
        "scope": "api offline_access",
        "device_identifier": "test-device-123",
        "device_name": "Test Device",
        "device_type": "10"
    }
    
    login_response = requests.post(
        "http://localhost:8080/identity/connect/token",
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    print(f"   Status: {login_response.status_code}")
    if login_response.status_code == 200:
        print(f"   ✅ SUCCESS with simple password!")
        data = login_response.json()
        print(f"   Access token: {data.get('access_token', 'N/A')[:20]}...")
    else:
        print(f"   ❌ FAILED with simple password")
        print(f"   Response: {login_response.text}")
    
    print(f"\n" + "=" * 50)
    print("Conclusion:")
    print("- If simple password works: Issue was with special characters")
    print("- If simple password fails: Issue is elsewhere")

if __name__ == "__main__":
    test_simple_password() 