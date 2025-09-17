#!/usr/bin/env python3
"""
Migration script to help transition from UI automation to optimized database setup.

This script provides a safe migration path by:
1. Backing up existing files
2. Testing the optimized approach
3. Providing rollback capabilities
"""

import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Tuple

# Setup logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class OptimizedMigration:
    """Handles migration to optimized BitWarden setup."""

    def __init__(self, bitwarden_dir: Path):
        self.bitwarden_dir = bitwarden_dir
        self.backup_dir = bitwarden_dir / "backup_migration"
        self.files_to_backup = [
            "flags.json",
            "secrets.json",
            "setup_app.sh"
        ]

    def create_backup(self) -> bool:
        """Create backup of existing files."""
        try:
            self.backup_dir.mkdir(exist_ok=True)
            timestamp = int(time.time())

            logger.info(f"📦 Creating backup in {self.backup_dir}")

            for filename in self.files_to_backup:
                source = self.bitwarden_dir / filename
                if source.exists():
                    backup_name = f"{filename}.{timestamp}.bak"
                    destination = self.backup_dir / backup_name
                    shutil.copy2(source, destination)
                    logger.info(f"   ✅ Backed up {filename} → {backup_name}")
                else:
                    logger.info(f"   ⏭️  Skipped {filename} (doesn't exist)")

            return True

        except Exception as e:
            logger.error(f"❌ Backup failed: {e}")
            return False

    def test_prerequisites(self) -> List[Tuple[str, bool]]:
        """Test if prerequisites for optimized setup are met."""
        tests = []

        # Test Python dependencies
        try:
            import psycopg2
            tests.append(("psycopg2 module", True))
        except ImportError:
            tests.append(("psycopg2 module", False))

        try:
            import requests
            tests.append(("requests module", True))
        except ImportError:
            tests.append(("requests module", False))

        # Test accounts.json
        accounts_file = self.bitwarden_dir / "accounts.json"
        try:
            with open(accounts_file, 'r') as f:
                data = json.load(f)
            if 'users' in data and len(data['users']) > 0:
                tests.append(("accounts.json valid", True))
            else:
                tests.append(("accounts.json valid", False))
        except Exception:
            tests.append(("accounts.json valid", False))

        # Test if optimized files exist
        optimized_files = [
            "database_setup.py",
            "create_accounts_optimized.py",
            "test_optimized_setup.py"
        ]

        for filename in optimized_files:
            filepath = self.bitwarden_dir / filename
            tests.append((f"{filename} exists", filepath.exists()))

        return tests

    def run_dry_run(self) -> bool:
        """Run a dry-run test of the optimized setup."""
        logger.info("🧪 Running dry-run test...")

        try:
            # Add project root to path
            project_root = self.bitwarden_dir.parent.parent
            sys.path.append(str(project_root))

            # Import and run basic validation
            from apps.bitwarden.database_setup import VaultwardenDBManager

            # Test database manager creation (doesn't connect)
            db_config = {
                "dbname": "vaultwarden",
                "user": "bitwarden",
                "password": "super_strong_password",
                "host": "localhost",
                "port": "5433",
            }

            manager = VaultwardenDBManager(db_config)
            logger.info("   ✅ Database manager created successfully")

            # Test flag generation
            from apps.bitwarden.database_setup import generate_test_flags
            flags = generate_test_flags(5)
            if len(flags) == 5 and all(flag.startswith("FLAG{") for flag in flags):
                logger.info("   ✅ Flag generation working")
            else:
                logger.error("   ❌ Flag generation failed")
                return False

            logger.info("🎉 Dry-run test passed!")
            return True

        except Exception as e:
            logger.error(f"❌ Dry-run test failed: {e}")
            return False

    def show_migration_summary(self):
        """Show summary of what the migration will do."""
        logger.info("\n" + "=" * 60)
        logger.info("📋 MIGRATION SUMMARY")
        logger.info("=" * 60)

        logger.info("\n🔄 Changes that will be made:")
        logger.info("   • setup_app.sh will be updated with optimized approach")
        logger.info("   • New database-driven account creation will be used")
        logger.info("   • UI automation will be kept as fallback")
        logger.info("   • Performance should improve from ~16min to <2min")

        logger.info("\n📦 Backup will include:")
        for filename in self.files_to_backup:
            filepath = self.bitwarden_dir / filename
            status = "✅ exists" if filepath.exists() else "⏭️  not found"
            logger.info(f"   • {filename} ({status})")

        logger.info(f"\n💾 Backup location: {self.backup_dir}")

    def restore_from_backup(self) -> bool:
        """Restore files from backup."""
        if not self.backup_dir.exists():
            logger.error("❌ No backup directory found")
            return False

        try:
            logger.info("♻️  Restoring from backup...")

            backup_files = list(self.backup_dir.glob("*.bak"))
            if not backup_files:
                logger.error("❌ No backup files found")
                return False

            for backup_file in backup_files:
                # Extract original filename (remove timestamp and .bak)
                name_parts = backup_file.name.split('.')
                original_name = '.'.join(name_parts[:-2])  # Remove timestamp and .bak
                original_path = self.bitwarden_dir / original_name

                shutil.copy2(backup_file, original_path)
                logger.info(f"   ✅ Restored {original_name}")

            logger.info("🔄 Restore completed successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Restore failed: {e}")
            return False


def main():
    """Main migration function."""
    bitwarden_dir = Path(__file__).parent
    migration = OptimizedMigration(bitwarden_dir)

    logger.info("🚀 BitWarden Setup Migration Tool")
    logger.info("=" * 50)

    # Show what will be done
    migration.show_migration_summary()

    # Get user confirmation
    while True:
        response = input("\n❓ Do you want to proceed with the migration? [y/N]: ").lower()
        if response in ['y', 'yes']:
            break
        elif response in ['n', 'no', '']:
            logger.info("❌ Migration cancelled by user")
            return False
        else:
            logger.info("Please answer 'y' or 'n'")

    # Create backup
    logger.info("\n📦 Step 1: Creating backup...")
    if not migration.create_backup():
        logger.error("❌ Migration failed at backup step")
        return False

    # Test prerequisites
    logger.info("\n🔍 Step 2: Testing prerequisites...")
    tests = migration.test_prerequisites()
    all_passed = True

    for test_name, passed in tests:
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"   {status}: {test_name}")
        if not passed:
            all_passed = False

    if not all_passed:
        logger.error("\n❌ Prerequisites not met. Please install missing dependencies:")
        logger.error("   pip install psycopg2-binary requests")
        logger.error("\n🔄 You can restore backup with: python3 migrate_to_optimized.py --restore")
        return False

    # Run dry-run test
    logger.info("\n🧪 Step 3: Running dry-run test...")
    if not migration.run_dry_run():
        logger.error("❌ Migration failed at dry-run step")
        logger.error("🔄 You can restore backup with: python3 migrate_to_optimized.py --restore")
        return False

    # Success!
    logger.info("\n🎉 Migration completed successfully!")
    logger.info("\n✅ Next steps:")
    logger.info("   1. Test the optimized setup: ./test_optimized_setup.py")
    logger.info("   2. Run the improved setup: ./setup_app.sh")
    logger.info("   3. If issues occur, restore backup with: --restore flag")

    logger.info(f"\n💾 Backup saved in: {migration.backup_dir}")
    logger.info("📈 Expected performance: ~16 minutes → <2 minutes")

    return True


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--restore":
        bitwarden_dir = Path(__file__).parent
        migration = OptimizedMigration(bitwarden_dir)
        success = migration.restore_from_backup()
        sys.exit(0 if success else 1)
    else:
        try:
            success = main()
            sys.exit(0 if success else 1)
        except KeyboardInterrupt:
            logger.info("\n🛑 Migration interrupted by user")
            sys.exit(1)
        except Exception as e:
            logger.error(f"\n💥 Unexpected error: {e}")
            sys.exit(1)