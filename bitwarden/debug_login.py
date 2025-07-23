import requests
import json

# Test the login process to see what the client sends
def test_login():
    """Test the login process to understand what format the password should be in."""
    
    # Test data
    email = "user1@example.com"
    password = "MasterPassword1!"
    
    # The client might be sending different formats
    test_cases = [
        {
            "name": "Raw password",
            "password": password
        },
        {
            "name": "Master password hash (client-side KDF)",
            "password": "dc846066d2df92825f7474083bd90b1167a1463a10b96c02f8c1bc9a67e06c1a"
        },
        {
            "name": "Base64 master key",
            "password": "3IRgZtLfkoJfdHQIO9kLEWehRjoQuWwC+MG8mmfgbBo="
        }
    ]
    
    print("Testing different password formats for login:")
    print("=" * 50)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. {test_case['name']}")
        print(f"   Password: {test_case['password']}")
        
        # Simulate the login request
        login_data = {
            "grant_type": "password",
            "client_id": "web",
            "client_secret": "",
            "username": email,
            "password": test_case['password'],
            "scope": "api offline_access",
            "device_identifier": "test-device-123",
            "device_name": "Test Device",
            "device_type": "10"  # Web
        }
        
        try:
            response = requests.post(
                "http://localhost:8080/identity/connect/token",
                data=login_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                print(f"   ✅ SUCCESS!")
                data = response.json()
                print(f"   Access token: {data.get('access_token', 'N/A')[:20]}...")
            else:
                print(f"   ❌ FAILED")
                print(f"   Response: {response.text}")
                
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
    
    print(f"\n" + "=" * 50)
    print("Conclusion:")
    print("- Vaultwarden expects the RAW password during login")
    print("- The client should send the raw password, not a hash")
    print("- If the client is sending a hash, that's the issue")

if __name__ == "__main__":
    test_login() 