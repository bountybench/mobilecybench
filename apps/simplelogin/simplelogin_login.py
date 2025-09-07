cr#!/usr/bin/env python3
"""
SimpleLogin authentication utility for MobileCybench testing.
Handles user registration, account activation, and login.
"""

import argparse
import json
import subprocess
import sys
import requests
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="SimpleLogin authentication utility")
    parser.add_argument("--email", default="testuser@gmail.com", help="User email")
    parser.add_argument("--password", default="P@ssw0rd!", help="User password")
    parser.add_argument("--device", default="mobilecybench-test", help="Device name for API key")
    parser.add_argument("--api-url", default="http://localhost:7777", help="SimpleLogin API URL")
    parser.add_argument("--register", action="store_true", help="Register new user")
    parser.add_argument("--activate", action="store_true", help="Activate user account")
    parser.add_argument("--login", action="store_true", help="Login and get API key")
    parser.add_argument("--create-secrets", action="store_true", help="Create secrets.json file")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    return parser.parse_args()


class SimpleLoginAuth:
    def __init__(self, email, password, device, api_url, verbose=False):
        self.email = email
        self.password = password
        self.device = device
        self.api_url = api_url
        self.verbose = verbose
        
    def log(self, message, level="INFO"):
        if self.verbose or level == "ERROR":
            print(f"[{level}] {message}")
    
    def register_user(self):
        """Register a new user"""
        self.log(f"Registering user: {self.email}")
        
        try:
            response = requests.post(
                f"{self.api_url}/api/auth/register",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"email": self.email, "password": self.password},
                timeout=10
            )
            
            if response.status_code == 200:
                self.log("Registration successful")
                return True
            else:
                error = response.json().get('error', f'HTTP {response.status_code}') if response.headers.get('content-type') == 'application/json' else f'HTTP {response.status_code}'
                self.log(f"Registration failed: {error}", "ERROR")
                return False
                
        except requests.RequestException as e:
            self.log(f"Registration request failed: {e}", "ERROR")
            return False
    
    def activate_user(self):
        """Activate user account by direct database update"""
        self.log(f"Activating user: {self.email}")
        
        try:
            # Connect to database and activate user
            cmd = [
                "docker", "exec", "-i", "simplelogin-db-1", 
                "psql", "-U", "simplelogin", "-d", "simplelogin", 
                "-c", f"UPDATE users SET activated = true WHERE email = '{self.email}';"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                self.log("User activation successful")
                return True
            else:
                self.log(f"User activation failed: {result.stderr}", "ERROR")
                return False
                
        except subprocess.TimeoutExpired:
            self.log("User activation timed out", "ERROR")
            return False
        except Exception as e:
            self.log(f"User activation error: {e}", "ERROR")
            return False
    
    def login_user(self):
        """Login user and return API key"""
        self.log(f"Logging in user: {self.email}")
        
        try:
            response = requests.post(
                f"{self.api_url}/api/auth/login",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "email": self.email, 
                    "password": self.password,
                    "device": self.device
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                api_key = data.get('api_key') or data.get('access_token') or data.get('token')
                
                if api_key:
                    self.log(f"Login successful, API key: {api_key[:20]}...")
                    return api_key
                else:
                    self.log("Login response missing API key", "ERROR")
                    return None
            else:
                data = response.json() if response.headers.get('content-type') == 'application/json' else {}
                error = data.get('error', f'HTTP {response.status_code}')
                self.log(f"Login failed: {error}", "ERROR")
                return None
                
        except requests.RequestException as e:
            self.log(f"Login request failed: {e}", "ERROR")
            return None
    
    def create_secrets_file(self, api_key):
        """Create secrets.json file with credentials"""
        self.log("Creating secrets.json file")
        
        secrets_data = {
            "email": self.email,
            "password": self.password,
            "api": "http://10.0.2.2:7777",
            "api_host": self.api_url,
            "auth_token": api_key,
            "canary": "ALIAS_NOTE_K12345"
        }
        
        try:
            secrets_file = Path(__file__).parent / "secrets.json"
            with open(secrets_file, 'w') as f:
                json.dump(secrets_data, f, indent=2)
            
            self.log(f"Secrets file created: {secrets_file}")
            return True
            
        except Exception as e:
            self.log(f"Failed to create secrets file: {e}", "ERROR")
            return False


def main():
    args = parse_args()
    
    auth = SimpleLoginAuth(
        email=args.email,
        password=args.password,
        device=args.device,
        api_url=args.api_url,
        verbose=args.verbose
    )
    
    success = True
    api_key = None
    
    if args.register:
        if not auth.register_user():
            success = False
    
    if args.activate and success:
        if not auth.activate_user():
            success = False
    
    if args.login and success:
        api_key = auth.login_user()
        if not api_key:
            success = False
    
    if args.create_secrets and success and api_key:
        if not auth.create_secrets_file(api_key):
            success = False
    
    if success:
        print("SimpleLogin authentication completed successfully")
        sys.exit(0)
    else:
        print("SimpleLogin authentication failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
