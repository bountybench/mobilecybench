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

cp env.example .env
echo "DOMAIN=localhost" >> .env
echo "POSTGRES_PASSWORD=mmuser_password52o6h8ko" >> .env


sudo mkdir -p ./volumes/app/mattermost/{config,data,logs,plugins,client/plugins,bleve-indexes}
sudo chown -R 2000:2000 ./volumes/app/mattermost
#bash scripts/issue-certificate.sh -d example.com -o ${PWD}/certs
sudo docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml up -d --remove-orphans
sleep 20
docker exec -it docker-mattermost-1 mmctl --local user create --email "admin@localhost" --username "admin" --password "AdminPassXBp5TQAJ" --system-admin
docker exec -it docker-mattermost-1 mmctl --local user create --email "qilsklo@cybench.com" --username "qilsklo" --password "qilskloSPmFVi592K<H"
docker exec -it docker-mattermost-1 mmctl --local user create --email "theqin0@cybench.com" --username "theqin0" --password "theqin0Qt7DTuh6"
