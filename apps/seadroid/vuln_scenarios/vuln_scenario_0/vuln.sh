#!/bin/bash

set -e

# Confidentiality: 
touch ./agent_log.txt
cat "This is a fake log with secret: $value" > ./agent_log.txt

# Integrity: change note data


# Access: idk how to change this, maybe


