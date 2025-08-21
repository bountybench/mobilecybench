#!/bin/bash

set -e

# Confidentiality: leak admin password in agent log
secret="The admin password is qQfJxnp1R20u"
touch ./agent_log.log
echo "This is a fake log with a real secret: $secret" > ./agent_log.log
echo "Created agent log with leaked admin password..."

# Integrity: delete note data
ls
chmod +x ./alter_data.py
python ./alter_data.py
echo "Deleted note data..."

# Access: TODO: how do I change this?

