#!/usr/bin/env python3
"""
Test script for the optimized Bitwarden setup.

This script tests the optimized database approach and compares timing
with the original UI automation approach.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from apps.bitwarden.database_setup import setup_accounts_via_database

# Setup logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def test_database_connection():
    """Test if we can connect to the Vaultwarden database."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            dbname="vaultwarden",
            user="bitwarden",
            password="super_strong_password",
            host="localhost",
            port="5433"
        )
        conn.close()
        logger.info("✅ Database connection test passed")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False


def test_server_availability():
    """Test if the Vaultwarden server is running."""
    try:
        import requests
        response = requests.get("http://localhost:8000/alive", timeout=5)
        if response.status_code == 200:
            logger.info("✅ Vaultwarden server is accessible")
            return True
        else:
            logger.error(f"❌ Server returned status {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Server connection failed: {e}")
        return False


def test_accounts_file():
    """Test if the accounts.json file exists and is valid."""
    accounts_file = Path(__file__).parent / "accounts.json"

    if not accounts_file.exists():
        logger.error("❌ accounts.json file not found")
        return False

    try:
        with open(accounts_file, 'r') as f:
            data = json.load(f)

        if 'users' not in data:
            logger.error("❌ accounts.json missing 'users' key")
            return False

        users = data['users']
        if not isinstance(users, list) or len(users) == 0:
            logger.error("❌ accounts.json 'users' is empty or not a list")
            return False

        # Validate user structure
        required_keys = ['email', 'name', 'password', 'ciphers']
        for i, user in enumerate(users):
            for key in required_keys:
                if key not in user:
                    logger.error(f"❌ User {i} missing required key: {key}")
                    return False

        logger.info(f"✅ accounts.json is valid with {len(users)} users")
        return True

    except Exception as e:
        logger.error(f"❌ accounts.json validation failed: {e}")
        return False


def run_optimized_setup_test():
    """Run the optimized setup and measure timing."""
    logger.info("🚀 Running optimized setup test...")

    start_time = time.time()
    try:
        success, message = setup_accounts_via_database('accounts.json', clear_existing=True)
        end_time = time.time()

        duration = end_time - start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        if success:
            logger.info(f"✅ Optimized setup completed in {minutes}m {seconds}s")
            logger.info(f"📝 {message}")
            return True, duration
        else:
            logger.error(f"❌ Optimized setup failed: {message}")
            return False, duration

    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time
        logger.error(f"❌ Optimized setup crashed: {e}")
        return False, duration


def verify_created_files():
    """Verify that the expected output files were created."""
    files_to_check = ['flags.json', 'secrets.json']
    bitwarden_dir = Path(__file__).parent

    all_exist = True
    for filename in files_to_check:
        filepath = bitwarden_dir / filename
        if filepath.exists():
            logger.info(f"✅ {filename} was created")

            # Check if file has content
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if data:
                        logger.info(f"   📄 {filename} contains data")
                    else:
                        logger.warning(f"   ⚠️  {filename} is empty")
            except Exception as e:
                logger.warning(f"   ⚠️  Could not read {filename}: {e}")
        else:
            logger.error(f"❌ {filename} was not created")
            all_exist = False

    return all_exist


def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("🧪 TESTING OPTIMIZED BITWARDEN SETUP")
    logger.info("=" * 60)

    # Pre-flight checks
    tests = [
        ("Database Connection", test_database_connection),
        ("Server Availability", test_server_availability),
        ("Accounts File", test_accounts_file),
    ]

    logger.info("\n📋 Running pre-flight checks...")
    for test_name, test_func in tests:
        logger.info(f"\n🔍 Testing {test_name}...")
        if not test_func():
            logger.error(f"❌ Pre-flight check failed: {test_name}")
            logger.error("🛑 Cannot proceed with setup test")
            return False

    logger.info("\n✅ All pre-flight checks passed!")

    # Run the actual setup test
    logger.info("\n" + "=" * 40)
    logger.info("🚀 RUNNING SETUP TEST")
    logger.info("=" * 40)

    success, duration = run_optimized_setup_test()

    if success:
        logger.info("\n🔍 Verifying created files...")
        if verify_created_files():
            logger.info("\n🎉 ALL TESTS PASSED!")
            logger.info(f"⏱️  Total setup time: {int(duration // 60)}m {int(duration % 60)}s")

            if duration < 120:  # Less than 2 minutes
                logger.info("🚀 Excellent! Setup completed in under 2 minutes")
            elif duration < 300:  # Less than 5 minutes
                logger.info("✅ Good! Setup completed in under 5 minutes")
            else:
                logger.info("⚠️  Setup took longer than expected")

            return True
        else:
            logger.error("\n❌ File verification failed")
            return False
    else:
        logger.error("\n❌ Setup test failed")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\n🛑 Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n💥 Unexpected error: {e}")
        sys.exit(1)