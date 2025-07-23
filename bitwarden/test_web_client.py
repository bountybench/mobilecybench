import hashlib
import requests
import json

def make_stretched_key(password, email, iterations):
    """Derives the master key using PBKDF2-SHA256 - this is what the client does."""
    salt = email.lower().encode('utf-8')
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations, dklen=32)

def test_web_client_login():
    """Test what the web client actually sends during login."""
    
    email = "user1@example.com"
    password = "MasterPassword1!"
    
    print("Testing web client login flow:")
    print("=" * 50)
    
    # Step 1: Get KDF parameters from prelogin
    print("1. Calling prelogin to get KDF parameters...")
    prelogin_data = {"email": email}
    prelogin_response = requests.post(
        "http://localhost:8080/identity/accounts/prelogin",
        json=prelogin_data,
        headers={"Content-Type": "application/json"}
    )
    
    if prelogin_response.status_code == 200:
        kdf_data = prelogin_response.json()
        print(f"   KDF parameters: {kdf_data}")
        kdf_iterations = kdf_data.get('kdfIterations', 600000)
    else:
        print(f"   ❌ Prelogin failed: {prelogin_response.text}")
        return
    
    # Step 2: Generate master password hash (what web client does)
    print(f"\n2. Generating master password hash...")
    master_key = make_stretched_key(password, email, kdf_iterations)
    master_key_hex = master_key.hex()
    print(f"   Master key (hex): {master_key_hex}")
    
    # Step 3: Try login with master password hash (what web client sends)
    print(f"\n3. Trying login with master password hash...")
    login_data = {
        "grant_type": "password",
        "client_id": "web",
        "client_secret": "",
        "username": email,
        "password": master_key_hex,  # Web client sends the hash
        "scope": "api offline_access",
        "device_identifier": "test-device-123",
        "device_name": "Test Device",
        "device_type": "10"  # Web
    }
    
    login_response = requests.post(
        "http://localhost:8080/identity/connect/token",
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    print(f"   Status: {login_response.status_code}")
    if login_response.status_code == 200:
        print(f"   ✅ SUCCESS with master password hash!")
        data = login_response.json()
        print(f"   Access token: {data.get('access_token', 'N/A')[:20]}...")
    else:
        print(f"   ❌ FAILED with master password hash")
        print(f"   Response: {login_response.text}")
    
    # Step 4: Try login with raw password (what should work)
    print(f"\n4. Trying login with raw password...")
    login_data["password"] = password  # Raw password
    
    login_response = requests.post(
        "http://localhost:8080/identity/connect/token",
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    print(f"   Status: {login_response.status_code}")
    if login_response.status_code == 200:
        print(f"   ✅ SUCCESS with raw password!")
        data = login_response.json()
        print(f"   Access token: {data.get('access_token', 'N/A')[:20]}...")
    else:
        print(f"   ❌ FAILED with raw password")
        print(f"   Response: {login_response.text}")
    
    print(f"\n" + "=" * 50)
    print("Conclusion:")
    print("- If master password hash works: Web client sends hash")
    print("- If only raw password works: Web client should send raw password")
    print("- The issue is in the web client's login format")

if __name__ == "__main__":
    test_web_client_login() 