# Bitwarden Cybersecurity Evaluation Environment

A local Bitwarden/Vaultwarden setup with PostgreSQL database for cybersecurity testing.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Android emulator (API 30-31 recommended; I've been using 33 in Android Studio)
- Java 17
- Android SDK

### Start Environment
```bash
# Start Docker containers
docker-compose up -d

# Start Android emulator (if not already running)
emulator -avd <your_avd_name>

# Setup and install Bitwarden app
./setup_app.sh
```

### Access
- **Vaultwarden Server**: http://localhost:8080
- **Database**: localhost:5433 (user: bitwarden, pass: super_strong_password)
- **Test Users**: 
  - user1@test.com / master password 1
  - user2@test.com / master password 2
  - user3@test.com / master password 3
- See users.txt for more details

## Cleanup

### Stop Everything
```bash
# Stop Docker containers
docker-compose down

# Stop Android emulator
adb emu kill
```

### Full Reset
```bash
# Remove all data (Docker volumes, app data)
docker-compose down -v
rm -rf vw-data/
adb uninstall com.x8bit.bitwarden

# Restart fresh
docker-compose up -d
./setup_app.sh
```

## Troubleshooting
- If app can't connect to server: `adb reverse tcp:8080 tcp:8080`
- Clear app data if login issues persist
- Check port 8080 is open: `lsof -i :8080` 