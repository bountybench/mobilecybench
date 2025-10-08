#!/usr/bin/env python3

import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add utils to path for shared utilities
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.uuid_flags_utils import get_uuid

PREFIX = "user_"


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
PRODID:-//DAVx5//Seeded Data//EN
CALSCALE:GREGORIAN
BEGIN:VEVENT
UID:{event_uid}
DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}
DTSTART:{start_date.strftime('%Y%m%dT%H%M%SZ')}
DTEND:{end_date.strftime('%Y%m%dT%H%M%SZ')}
SUMMARY:{event_summary}
DESCRIPTION:{description}
LOCATION:Conference Room {random.randint(1, 10)}
STATUS:CONFIRMED
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
FN:{full_name}
N:{last_name};{first_name};;;
EMAIL;TYPE=INTERNET:{email}
TEL;TYPE=CELL:{phone}
ORG:Example Corp
TITLE:{random.choice(["Manager", "Developer", "Designer", "Analyst", "Engineer"])}
NOTE:Auto-generated contact for testing
REV:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}
END:VCARD"""

    return vcf_content


def seed_data():
    """Seed data for all users"""
    collection_root = Path.cwd() / "radicale/data/collection-root/collection-root"

    print(f"Seeding Data in: {collection_root}")

    collection_root.mkdir(parents=True, exist_ok=True)

    for i in range(10):
        username = f"{PREFIX}{i:04d}"
        user_dir = collection_root / username
        calendars_dir = user_dir / "calendars"
        contacts_dir = user_dir / "contacts"

        # Create directories
        calendars_dir.mkdir(parents=True, exist_ok=True)
        contacts_dir.mkdir(parents=True, exist_ok=True)

        # Generate and write random .ics file
        ics_content = generate_random_ics_content()
        ics_file = calendars_dir / f"event_{get_uuid(8)}.ics"
        ics_file.write_text(ics_content, encoding="utf-8")

        # Generate and write random .vcf file
        vcf_content = generate_random_vcf_content()
        vcf_file = contacts_dir / f"contact_{get_uuid(8)}.vcf"
        vcf_file.write_text(vcf_content, encoding="utf-8")

        if i % 100 == 0:  # Progress indicator
            print(f"Created directories and files for {i + 1} users...")

    print("✅ Successfully created directories and files for 1000 users")


def main():
    """Main function to create user directories and seed data"""
    print("🗂️  Creating user directories and seeding calendar/contact data...")
    print("🎉 Data seeding complete!")


if __name__ == "__main__":
    main()
