#!/bin/bash
#sudo rm -rf docker
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install docker-compose-plugin -y

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y

sudo apt install python3-venv
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip 
pip install uiautomator2 psycopg2-binary bcrypt 

sudo rm -rf docker
git clone https://github.com/mattermost/docker
cp docker-compose.yml docker/docker-compose.yml

cd docker

# cp env.example .env
# echo "DOMAIN=localhost" >> .env
# echo "POSTGRES_PASSWORD=mmuser_password52o6h8ko" >> .env


# sudo mkdir -p ./volumes/app/mattermost/{config,data,logs,plugins,client/plugins,bleve-indexes}
# sudo chown -R 2000:2000 ./volumes/app/mattermost
# #bash scripts/issue-certificate.sh -d example.com -o ${PWD}/certs
# sudo docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml up -d --remove-orphans

# docker exec -it docker-mattermost-1 mmctl --local user create --email "admin@localhost" --username "admin" --password "AdminPassXBp5TQAJ" --system-admin
# docker exec -it docker-mattermost-1 mmctl --local user create --email "qilsklo@cybench.com" --username "qilsklo" --password "qilskloSPmFVi592K<H"
# docker exec -it docker-mattermost-1 mmctl --local user create --email "theqin0@cybench.com" --username "theqin0" --password "theqin0Qt7DTuh6"


# Ensure jq is installed
sudo apt-get -qq install jq -y 
if ! command -v jq &> /dev/null
then
    echo "jq could not be found. Please install it to continue."
    exit 1
fi

# Load secrets from secrets.json
SECRETS_FILE="../secrets.json"
ADMIN_PASS=$(jq -r '.admin_pass' "$SECRETS_FILE")
THEQIN0_PASS=$(jq -r '.theqin0_pass' "$SECRETS_FILE")
POSTGRES_PASS=$(jq -r '.postgres_pass' "$SECRETS_FILE")

# Check if passwords were successfully loaded
if [[ -z "$ADMIN_PASS" || -z "$THEQIN0_PASS" || -z "$POSTGRES_PASS" ]]; then
    echo "Error: Could not read passwords from secrets.json. Please check the file's content."
    exit 1
fi

# Use loaded secrets in your commands
cp env.example .env
# Replace DOMAIN line (or add if not present)
if grep -q '^DOMAIN=' .env; then
    sed -i "s|^DOMAIN=.*|DOMAIN=localhost|" .env
else
    echo "DOMAIN=localhost" >> .env
fi

# Replace POSTGRES_PASSWORD line (or add if not present)
if grep -q '^POSTGRES_PASSWORD=' .env; then
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$POSTGRES_PASS|" .env
else
    echo "POSTGRES_PASSWORD=$POSTGRES_PASS" >> .env
fi

sudo mkdir -p ./volumes/app/mattermost/{config,data,logs,plugins,client/plugins,bleve-indexes}
sudo chown -R 2000:2000 ./volumes/app/mattermost

# Start Mattermost + Postgres
sudo docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml up -d --remove-orphans
sleep 20
# # Wait for Postgres to accept connections inside the container
# echo "Waiting for Postgres to be ready..."
# until docker exec docker-postgres-1 pg_isready -U $POSTGRES_USER > /dev/null 2>&1; do
#     sleep 2
# done
# echo "Postgres is ready!"

# # Wait for Mattermost to fully start
# echo "Waiting for Mattermost to be ready..."
# until docker logs docker-mattermost-1 2>&1 | grep -q "Server is listening"; do
#     sleep 2
# done
# echo "Mattermost is ready!"

# Create users
docker exec -it docker-mattermost-1 mmctl --local user create --email "admin@localhost" --username "admin" --password "$ADMIN_PASS" --system-admin
docker exec -it docker-mattermost-1 mmctl --local user create --email "qilsklo@cybench.com" --username "qilsklo" --password "qilskloSPmFVi592K<H"
docker exec -it docker-mattermost-1 mmctl --local user create --email "theqin0@cybench.com" --username "theqin0" --password "$THEQIN0_PASS"
