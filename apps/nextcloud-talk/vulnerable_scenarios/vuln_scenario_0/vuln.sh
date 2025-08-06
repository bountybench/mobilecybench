#!/bin/bash
set -a
source ../.env
set +a

docker exec -u www-data nextcloud-server php occ user:setting ${USER_B_USERNAME} settings email HACKED_EMAIL@email.com