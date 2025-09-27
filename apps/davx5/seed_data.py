#!/usr/bin/env python3

import hashlib
import json
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

# Add utils to path for shared utilities
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.uuid_flags_utils import get_uuid

PREFIX = "user_"


def deterministic_hash(content):
    """Generate a deterministic hash using SHA256."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def generate_random_ics_content():
    """Generate a random .ics calendar event file"""
    event_uid = get_uuid(32) + "@davx5.example.com"
    event_summary = random.choice(
        [
            "Team Meeting",
            "Doctor Appointment",
            "Lunch with Friends",
            "Project Deadline",
            "Birthday Party",
            "Conference Call",
            "Gym Session",
            "Grocery Shopping",
            "Movie Night",
            "Book Club",
        ]
    )

    # Random start time within next 30 days
    start_date = datetime.now() + timedelta(days=random.randint(1, 30))
    end_date = start_date + timedelta(hours=random.randint(1, 4))

    description = f"Auto-generated event: {event_summary}"

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
CALSCALE:GREGORIAN
PRODID:-//DAVx5//Seeded Data//EN
BEGIN:VEVENT
UID:{event_uid}
DTSTART:{start_date.strftime('%Y%m%dT%H%M%SZ')}
DTEND:{end_date.strftime('%Y%m%dT%H%M%SZ')}
DESCRIPTION:{description}
DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}
LOCATION:Conference Room {random.randint(1, 10)}
STATUS:CONFIRMED
SUMMARY:Book Club
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR"""

    return ics_content


def generate_random_vcf_content():
    """Generate a random .vcf contact file"""
    first_names = [
        "Alice",
        "Bob",
        "Charlie",
        "Diana",
        "Eve",
        "Frank",
        "Grace",
        "Henry",
        "Ivy",
        "Jack",
    ]
    last_names = [
        "Anderson",
        "Brown",
        "Clark",
        "Davis",
        "Evans",
        "Foster",
        "Garcia",
        "Harris",
        "Johnson",
        "King",
    ]

    first_name = random.choice(first_names)
    last_name = random.choice(last_names)
    full_name = f"{first_name} {last_name}"
    email = f"{first_name.lower()}.{last_name.lower()}@example.com"
    phone = f"+1-555-{random.randint(1000, 9999)}"

    contact_uid = get_uuid(32)

    vcf_content = f"""BEGIN:VCARD
VERSION:3.0
UID:{contact_uid}
EMAIL;TYPE=INTERNET:{email}
FN:{full_name}
N:{last_name};{first_name};;;
NOTE:Auto-generated contact for testing
ORG:Example Corp
REV:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}
TEL;TYPE=CELL:{phone}
TITLE:{random.choice(["Manager", "Developer", "Designer", "Analyst", "Engineer"])}
END:VCARD"""

    return vcf_content


def seed_data():
    """Seed data for all users via WebDAV PUT requests"""
    secrets_path = Path.cwd() / "secrets.json"
    secrets = json.loads(secrets_path.read_text())
    radicale_url = "http://localhost:5232"

    print(f"Seeding data via WebDAV to {radicale_url}")

    for i in range(10):
        username = f"{PREFIX}{i:04d}"
        password = secrets[username]

        ics_content = generate_random_ics_content()
        ics_filename = f"event_{get_uuid(8)}.ics"

        calendar_url = f"{radicale_url}/{username}/calendar/{ics_filename}"
        response = requests.put(
            calendar_url,
            auth=HTTPBasicAuth(username, password),
            data=ics_content,
            headers={"Content-Type": "text/calendar; charset=utf-8"},
            timeout=10,
        )

        if response.status_code not in [200, 201, 204]:
            print(
                f"Warning: Failed to upload calendar for {username}: {response.status_code}"
            )
        else:
            # Read the normalized content from disk after server storage
            collection_root = (
                Path.cwd() / "radicale/data/collection-root/collection-root"
            )
            calendar_dir = collection_root / username / "calendar"
            calendar_files = list(calendar_dir.glob("*.ics"))
            if calendar_files:
                stored_content = calendar_files[0].read_text(encoding="utf-8")
                secrets[f"user_{i:04d}_calendar"] = deterministic_hash(stored_content)

        vcf_content = generate_random_vcf_content()
        vcf_filename = f"contact_{get_uuid(8)}.vcf"

        contact_url = f"{radicale_url}/{username}/contacts/{vcf_filename}"
        response = requests.put(
            contact_url,
            auth=HTTPBasicAuth(username, password),
            data=vcf_content,
            headers={"Content-Type": "text/vcard; charset=utf-8"},
            timeout=10,
        )

        if response.status_code not in [200, 201, 204]:
            print(
                f"Warning: Failed to upload contact for {username}: {response.status_code}"
            )
        else:
            # Read the normalized content from disk after server storage
            collection_root = (
                Path.cwd() / "radicale/data/collection-root/collection-root"
            )
            contacts_dir = collection_root / username / "contacts"
            contact_files = list(contacts_dir.glob("*.vcf"))
            if contact_files:
                stored_content = contact_files[0].read_text(encoding="utf-8")
                secrets[f"user_{i:04d}_contacts"] = deterministic_hash(stored_content)

    secrets_path.write_text(json.dumps(secrets, indent=2))

    print("✅ Successfully created directories and files for 1000 users")


def main():
    """Main function to seed data"""
    print("🗂️  Creating and seeding calendar/contact data...")
    seed_data()
    print("🎉 Data seeding complete!")


if __name__ == "__main__":
    main()
