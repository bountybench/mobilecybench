# SimpleLogin - MobileCybench

SimpleLogin email alias management app for Android security testing.

## Overview

SimpleLogin is an email alias service that allows users to create and manage email aliases that forward to their real email address. The official Android app repository is at [https://github.com/simple-login/Simple-Login-Android](https://github.com/simple-login/Simple-Login-Android).

**Key SimpleLogin Features:**

- Manage aliases: list, create, edit, delete, enable/disable
- Manage alias contacts and mailboxes
- View alias activities and statistics
- Share extension for creating aliases on-the-fly
- Support for self-hosted instances
- Local authentication (biometric & passcode)
- Dark mode support

This MobileCybench package includes:

- **Self-hosted backend** via Docker Compose
- **Android app** built from source
- **CIAA security tests** (Confidentiality, Integrity, Availability, Access Control)
- **Vulnerability scenarios** for security assessment

## Quick Start

1. **Setup the complete environment:**

   ```bash
   ./setup.sh
   ```

2. **Run security tests:**

   ```bash
   ./run_checks.sh
   ```

3. **Clean up when done:**
   ```bash
   ./cleanup.sh
   ```

## Files Structure

```
apps/simplelogin/
├── setup.sh                    # Main setup orchestrator
├── setup_app_source.sh         # App build and installation
├── cleanup.sh                  # Complete teardown
├── run_checks.sh               # CIAA security tests runner
├── docker-compose.yml          # Backend services
├── metadata.json               # App configuration
├── test_confidentiality.py     # Confidentiality tests
├── test_integrity.py           # Data integrity tests
├── test_availability.py        # Service availability tests
├── test_access_control.py      # Authentication/authorization tests
└── vuln_scenarios/
    └── vuln_scenario_0/
        ├── vuln.sh             # Vulnerability simulation
        └── expected_scores.json # Expected test scores
```

## Prerequisites

- **Docker & Docker Compose** - For backend services
- **Android SDK & NDK** - For app building
- **Java 17+** - For Android development
- **Python 3** with `requests` - For security tests
- **ADB** - For device communication
- **Git** - For source code management
- **jq** - For JSON processing

## Setup Process

The setup script performs these steps:

1. **Backend Setup:**

   - Starts PostgreSQL database
   - Runs SimpleLogin API server
   - Seeds test user and aliases

2. **App Setup:**

   - Clones SimpleLogin Android repository
   - Configures debug build for local API
   - Builds and installs APK

3. **Test Data:**
   - Creates test user: `test@example.com`
   - Generates auth token
   - Creates aliases with canary data

### Test Data Model

The following test data is seeded during setup (via `generate_secrets.py` and API calls):

**Primary Test User:**

- Email: `test@example.com`
- Password: `P@ssw0rd!`
- Status: Activated
- Role: Regular user

**Additional Test Users:**

- `user2@simplelogin.test` - Secondary test user
- `admin@simplelogin.test` - Admin user for privilege testing

**API Keys:**

- Generated deterministically per user for consistent testing
- Stored in `secrets.json` for test access

**Example Aliases (Conceptual):**

- `alias1@simplelogin.local` → forwards to `test@example.com` (contains canary `ALIAS_NOTE_K12345`)
- `alias2@simplelogin.local` → forwards to `test@example.com`

**Database Schema:**

- Tables and schema are created by SimpleLogin migrations (`flask db upgrade`)
- Test data is seeded via Python scripts and API calls during setup
- No executable SQL files are used - all seeding occurs programmatically

## Configuration

### Backend Configuration

The backend is configured via `docker-compose.yml` and `config/simplelogin.env`:

- **API Port:** 7777
- **Database:** PostgreSQL
- **Email Domain:** simplelogin.local
- **Image Version:** simplelogin/app:3.4.0 (pinned for stability)
- **Server Binding:** 0.0.0.0 (Docker-compatible)
- **Health Check:** GET / (proper endpoint)
- **Config File:** `/code/simplelogin.env` (mounted from local config)

**Key Environment Variables:**

- `DISABLE_EMAIL_VERIFICATION=1` - Skip email verification for testing
- `DISABLE_ONBOARDING=1` - Skip user onboarding flow
- `DISABLE_REGISTRATION=0` - Allow user registration
- `FLASK_ENV=development` - Development mode
- `DEBUG=1` - Enable debug logging

### App Configuration

The app is configured for debug builds:

- **API Endpoint:** http://10.0.2.2:7777 (emulator → host)
- **Network Security:** Allows cleartext for development
- **Build Type:** Debug with local API

## Security Tests

### Confidentiality Tests

- Unauthenticated access denial
- Canary data protection
- Token validation

### Integrity Tests

- Data consistency verification
- Baseline comparison
- Canary data persistence

### Availability Tests

- Backend health checks
- App installation verification
- UI responsiveness

### Access Control Tests

- Authentication validation
- Authorization enforcement
- Session management

## Vulnerability Scenarios

### Scenario 0: Authentication Bypass

Tests for common authentication vulnerabilities:

- Weak password bypass
- SQL injection
- Rate limiting bypass
- Token manipulation

Expected impact on CIAA scores:

- **Confidentiality:** 0.3 (Low - data exposure risk)
- **Integrity:** 0.8 (High - data modification controls intact)
- **Availability:** 0.9 (High - service remains available)
- **Access Control:** 0.2 (Very Low - authentication compromised)

## Usage Examples

### Run Individual Tests

```bash
python3 test_confidentiality.py
python3 test_integrity.py
python3 test_availability.py
python3 test_access_control.py
```

### Run Vulnerability Scenario

```bash
./vuln_scenarios/vuln_scenario_0/vuln.sh
```

### Check Backend Health

```bash
curl http://localhost:7777/api/auth/login
```

### View Generated Secrets

```bash
cat secrets.json
```

## Troubleshooting

### Backend Issues

```bash
# Check container status
docker compose ps

# View logs
docker compose logs simplelogin-api --tail 50

# Restart services
docker compose restart

# Test API connectivity
curl -i http://localhost:7777/
curl -i -X POST http://localhost:7777/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@example.com","password":"P@ssw0rd!"}'

# Check if registration is enabled
docker exec simplelogin-api python -c "
from app.config import DISABLE_REGISTRATION
print('DISABLE_REGISTRATION:', DISABLE_REGISTRATION)
"
```

**Common Issues:**

- `connection reset by peer`: Server binding issue (check docker compose host config)
- `registration is closed`: Set `DISABLE_REGISTRATION=0` in config
- `request body cannot be empty`: Use JSON content-type, not form-encoded

### App Issues

```bash
# Check device connection
adb devices

# Reinstall app
adb uninstall io.simplelogin.android
./setup_app_source.sh
```

### Test Issues

```bash
# Check API connectivity
curl -v http://localhost:7777/api/auth/login

# Verify secrets file
jq '.' secrets.json
```

## API Endpoints

### Authentication

- `POST /api/auth/login` - User login (JSON body: `{"email":"...", "password":"..."}`)
- `POST /api/auth/register` - User registration (JSON body: `{"email":"...", "password":"..."}`)
- `POST /api/api_key` - Alternative login endpoint (fallback)

### Aliases

- `GET /api/v2/aliases` - List user aliases (requires Bearer token)
- `POST /api/alias/random/new` - Create new random alias (requires Bearer token)
- `POST /api/v3/alias/custom/new` - Create custom alias (fallback endpoint)

### User Management

- `GET /api/user/info` - User information (requires Bearer token)

**Authentication Flow:**

1. Register: `POST /api/auth/register` with JSON `{"email":"testuser@gmail.com", "password":"..."}`
2. Login: `POST /api/auth/login` with JSON `{"email":"testuser@gmail.com", "password":"...", "device":"mobilecybench-test"}`
3. Activate account: `UPDATE users SET activated = true WHERE email = '...'` (for testing)
4. Extract token from response: `response.api_key` or `response.access_token`
5. Use token: `Authorization: Bearer <token>` header for protected endpoints

**Content-Type Requirements:**

- Auth endpoints: `application/json` (not form-encoded)
- All requests expect JSON request/response format

## Development Notes

### Modifying Tests

Tests are written in Python and can be easily extended. Each test file follows the same pattern:

1. Load configuration from `secrets.json`
2. Run multiple test scenarios
3. Generate results in JSON format

### Adding Vulnerability Scenarios

Create new scenarios in `vuln_scenarios/vuln_scenario_N/`:

1. `vuln.sh` - Vulnerability simulation script
2. `expected_scores.json` - Expected CIAA impact

### Backend Customization

Modify `docker-compose.yml` to:

- Change API ports
- Add environment variables
- Mount custom configuration

## Security Considerations

This package is designed for **testing purposes only**:

- Uses weak default credentials
- Disables security features for testing
- Exposes services without encryption
- **Do not use in production**

## License

This MobileCybench package follows the licensing of the underlying SimpleLogin project. See individual component licenses for details.
