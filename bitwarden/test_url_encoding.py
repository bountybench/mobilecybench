import requests
import urllib.parse

def test_url_encoding():
    """Test if URL encoding is the issue with special characters."""
    
    email = "user1@example.com"
    password = "MasterPassword1!"
    
    print("Testing URL encoding with special characters:")
    print("=" * 50)
    print(f"Email: {email}")
    print(f"Password: {password}")
    print(f"URL encoded password: {urllib.parse.quote(password)}")
    
    # Test 1: Without URL encoding
    print(f"\n1. Testing without URL encoding...")
    login_data = {
        "grant_type": "password",
        "client_id": "web",
        "client_secret": "",
        "username": email,
        "password": password,
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
        print(f"   ✅ SUCCESS without URL encoding!")
        data = login_response.json()
        print(f"   Access token: {data.get('access_token', 'N/A')[:20]}...")
    else:
        print(f"   ❌ FAILED without URL encoding")
        print(f"   Response: {login_response.text}")
    
    # Test 2: With URL encoding
    print(f"\n2. Testing with URL encoding...")
    login_data["password"] = urllib.parse.quote(password)
    
    login_response = requests.post(
        "http://localhost:8080/identity/connect/token",
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    print(f"   Status: {login_response.status_code}")
    if login_response.status_code == 200:
        print(f"   ✅ SUCCESS with URL encoding!")
        data = login_response.json()
        print(f"   Access token: {data.get('access_token', 'N/A')[:20]}...")
    else:
        print(f"   ❌ FAILED with URL encoding")
        print(f"   Response: {login_response.text}")
    
    # Test 3: Manual form data with URL encoding
    print(f"\n3. Testing with manual form data...")
    form_data = (
        f"grant_type=password&"
        f"client_id=web&"
        f"client_secret=&"
        f"username={urllib.parse.quote(email)}&"
        f"password={urllib.parse.quote(password)}&"
        f"scope=api offline_access&"
        f"device_identifier=test-device-123&"
        f"device_name=Test Device&"
        f"device_type=10"
    )
    
    login_response = requests.post(
        "http://localhost:8080/identity/connect/token",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    print(f"   Status: {login_response.status_code}")
    if login_response.status_code == 200:
        print(f"   ✅ SUCCESS with manual form data!")
        data = login_response.json()
        print(f"   Access token: {data.get('access_token', 'N/A')[:20]}...")
    else:
        print(f"   ❌ FAILED with manual form data")
        print(f"   Response: {login_response.text}")
    
    print(f"\n" + "=" * 50)
    print("Conclusion:")
    print("- If URL encoding works: Web client needs proper encoding")
    print("- If manual form data works: Issue is with request format")
    print("- If all fail: Issue is elsewhere")

if __name__ == "__main__":
    test_url_encoding() 