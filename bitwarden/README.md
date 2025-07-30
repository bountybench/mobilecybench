# Bitwarden Cybersecurity Benchmark

This directory contains a comprehensive cybersecurity benchmark for evaluating AI agent performance against the Bitwarden password manager application.

## 🏗️ Architecture Overview

### Core Design Philosophy

The benchmark is designed to test AI agents against a realistic, production-like password management system. Rather than using synthetic vulnerabilities, we use the actual Bitwarden application with a self-hosted Vaultwarden server to create authentic security challenges.

### Key Design Choices

#### 1. **Vaultwarden vs Official Bitwarden Server**
- **Choice:** Self-hosted Vaultwarden server
- **Rationale:** 
  - Open-source, allowing full control over the environment
  - Compatible with Bitwarden clients (no API differences)
  - Can be containerized and easily reset between tests
  - Maintains the same security model as official Bitwarden

#### 2. **UI Automation vs API Testing**
- **Choice:** UI automation using `uiautomator2`
- **Rationale:**
  - Tests the complete user journey as a real attacker would experience
  - Captures authentication bypass attempts that API-only tests might miss
  - More realistic simulation of actual user interactions
  - Tests the full application stack (UI → API → Database)

#### 3. **Database-Driven Integrity Checks**
- **Choice:** Direct PostgreSQL queries for integrity verification
- **Rationale:**
  - Provides ground truth for data modifications
  - Can detect unauthorized additions/deletions that UI tests might miss
  - Enables comprehensive state comparison against known baselines
  - Supports both structural and cryptographic integrity validation

## 📊 Test Suite Architecture

### Four Pillars of Security Testing

The benchmark implements a comprehensive security testing framework covering all major security principles:

#### 1. **Availability Testing** (`test_availability.py`)
- **Purpose:** Ensures the application remains functional and responsive
- **Checks:**
  - Docker container health (Vaultwarden, PostgreSQL)
  - Server API responsiveness (`/alive` endpoint)
  - App launch capability and UI responsiveness
  - Crash/ANR detection in system logs

#### 2. **Confidentiality Testing** (`test_confidentiality.py`)
- **Purpose:** Detects information leakage in agent outputs
- **Methodology:**
  - Pre-defines sensitive data (UUIDs, passwords, keys) from `secrets.json`
  - Scans agent logs/output for exact matches
  - Masks sensitive data in failure reports
  - Tests for data exfiltration attempts

#### 3. **Integrity Testing** (`test_integrity.py`)
- **Purpose:** Verifies data hasn't been unauthorizedly modified
- **Three-Layer Approach:**
  - **Structural Integrity:** User/cipher counts, UUID verification
  - **Cryptographic Integrity:** Key pairs, security stamps validation
  - **Data Integrity:** Encrypted cipher data blob verification
- **Enhanced Detection:** Total count verification catches unauthorized additions/deletions

#### 4. **Access Control Testing** (`test_access_control.py`)
- **Purpose:** Tests authentication and authorization mechanisms
- **UI-Based Authentication:**
  - Invalid credential rejection testing
  - Valid credential verification
  - Realistic login simulation via `uiautomator2`
- **Database-Level Authorization:**
  - Privilege escalation detection via organization membership
  - Role-based access control verification

## 🔄 Data Population Strategy

### Automated Account Creation
- **Script:** `create_accounts_ui.py`
- **Method:** UI automation to create multiple user accounts
- **Features:**
  - Server configuration (localhost:8080)
  - User registration with unique credentials
  - Cipher creation with embedded flags
  - Database dump generation for baseline

### Secrets Management
- **File:** `secrets.json` (generated from database dump)
- **Content:** User credentials, UUIDs, cryptographic keys, flags
- **Purpose:** Provides ground truth for integrity and confidentiality checks

### Fast Mode Setup
- **Script:** `setup.sh` with `--fast` flag
- **Method:** Database restoration from `dump.sql`
- **Benefits:** Consistent, reproducible test environment

## 🧪 Test Execution Flow

### 1. Environment Setup
```bash
./setup.sh --fast  # Restore from dump.sql
```

### 2. Agent Interaction Phase
- AI agent interacts with the application
- All interactions logged for analysis

### 3. Comprehensive Testing
```bash
python test_availability.py      # Service health
python test_confidentiality.py   # Data leakage detection
python test_integrity.py         # Data modification detection  
python test_access_control.py    # Authentication/authorization
```

### 4. Scoring
- Each test returns binary pass/fail results
- Aggregate scores provide overall security assessment

## 🔧 Technical Implementation

### Docker Architecture
- **Vaultwarden:** Self-hosted Bitwarden-compatible server
- **PostgreSQL:** Persistent database with proper volume mounting
- **Networking:** Isolated private network for service communication
- **Security:** Environment variables for credential management

### UI Automation Framework
- **Tool:** `uiautomator2` for Android UI interaction
- **Approach:** Modular helper functions in `util.py`
- **Features:** Robust error handling, screenshot capture, state verification

### Database Integration
- **Connection:** Direct PostgreSQL queries via `psycopg2`
- **Baseline:** `secrets.json` provides expected state
- **Verification:** Multi-layer integrity checking

## 🎯 Key Advantages

1. **Realistic Testing:** Uses actual Bitwarden application with real security mechanisms
2. **Comprehensive Coverage:** Tests all major security principles (AIDA)
3. **Reproducible:** Docker-based setup ensures consistent environments
4. **Scalable:** Modular design allows easy addition of new test cases
5. **Authentic Vulnerabilities:** Tests against real application behavior, not synthetic flaws

## 📈 Benchmark Effectiveness

This setup provides a robust foundation for evaluating AI agent security capabilities by:
- Testing against a real, complex application
- Using multiple detection methods (UI, API, database)
- Providing comprehensive security coverage
- Maintaining realistic attack scenarios
- Supporting reproducible and consistent evaluation

The benchmark successfully balances realism with controllability, making it an effective tool for cybersecurity AI evaluation. 