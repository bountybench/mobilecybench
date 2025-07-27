#!/bin/bash

echo "Setting up Tinode environment..."
echo "==================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Creating .env file with default values..."
    cat > .env <<EOF
# MySQL Configuration
MYSQL_ROOT_PASSWORD=root
MYSQL_USER=tinode
MYSQL_PASSWORD=tinode
MYSQL_DATABASE=tinode

# Tinode Server Configuration
TINODE_MYSQL_DSN=tinode:tinode@tcp(db)/tinode
EOF
    echo ".env file created with default values. You can modify it if needed."
fi

# Load environment variables
source .env

echo "Running docker compose up to start the db and tinode-server containers..."
docker-compose up -d

echo "Waiting for the containers to be ready"
echo "==================="

while ! docker-compose exec -T db mysqladmin ping -h localhost -u $MYSQL_USER -p$MYSQL_PASSWORD --silent; do
    echo "Waiting for MySQL to be ready..."
    sleep 2
done
echo "MySQL is ready!"

while ! curl -s http://localhost:6060/v0/ > /dev/null 2>&1; do
    echo "Waiting for Tinode server to be ready..."
    sleep 2
done
echo "Tinode server is ready!"

echo "Seeding database with seed_db.sql..."
docker-compose exec -T db mysql -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE < seed_db.sql

if [ $? -eq 0 ]; then
    echo "Database seeded successfully!"
else
    echo "Error seeding database!"
    exit 1
fi

echo "Setup complete! Tinode server should be running on port 6060"
echo "You can check the logs with: docker-compose logs -f tinode-server"
