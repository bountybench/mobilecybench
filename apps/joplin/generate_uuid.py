import json
import uuid

import bcrypt


def get_uuid(length=36):
    uuid_str = str(uuid.uuid4())
    return uuid_str[:length]


# Generate UUIDs
userb_pass = get_uuid()
admin_pass = get_uuid()
secrets = {
    "notebook1_id": get_uuid(32),
    "notebook2_id": get_uuid(32),
    "notebook3_id": get_uuid(32),
    "notebook4_id": get_uuid(32),
    "notebook1_name": get_uuid(),
    "notebook2_name": get_uuid(),
    "notebook3_name": get_uuid(),
    "notebook4_name": get_uuid(),
    "note1_id": get_uuid(32),
    "note2_id": get_uuid(32),
    "note3_id": get_uuid(32),
    "note1_name": get_uuid(),
    "note2_name": get_uuid(),
    "note3_name": get_uuid(),
    "note1_content": get_uuid(),
    "note2_content": get_uuid(),
    "note3_content": get_uuid(),
    "userb_password": userb_pass,
    "admin_password": admin_pass,
    "userb_password_hash": bcrypt.hashpw(
        userb_pass.encode(), bcrypt.gensalt()
    ).decode(),
    "admin_password_hash": bcrypt.hashpw(
        admin_pass.encode(), bcrypt.gensalt()
    ).decode(),
}

with open("secrets.sql", "w") as sql_file:
    for key, value in secrets.items():
        sql_file.write(f"\\set {key} '''{value}'''\n")

with open("secrets.json", "w") as json_file:
    json.dump(secrets, json_file, indent=4)

print("✅ Secrets written to secrets.sql and secrets.json")
