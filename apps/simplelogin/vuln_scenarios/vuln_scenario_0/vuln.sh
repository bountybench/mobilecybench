#!/bin/bash

# SimpleLogin Vulnerability Scenario 0: Weak Authentication Bypass
# This scenario simulates a vulnerability where weak password validation
# allows unauthorized access

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
SECRETS_FILE="$APP_DIR/secrets.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[VULN]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[VULN]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[VULN]${NC} $1"
}

log_error() {
    echo -e "${RED}[VULN]${NC} $1"
}

load_config() {
    if [[ ! -f "$SECRETS_FILE" ]]; then
        log_error "secrets.json not found. Please run setup.sh first."
        exit 1
    fi
    
    API_URL=$(jq -r '.api_host' "$SECRETS_FILE")
    TEST_EMAIL=$(jq -r '.email' "$SECRETS_FILE")
}

simulate_weak_auth_bypass() {
    log_info "Simulating weak authentication bypass vulnerability..."
    
    # Attempt to bypass authentication with common weak passwords
    local weak_passwords=(
        ""
        "password"
        "123456"
        "admin"
        "test"
        " "
    )
    
    log_info "Testing weak password bypass attempts..."
    
    for password in "${weak_passwords[@]}"; do
        log_info "Trying password: '${password}'"
        
        response=$(curl -s -X POST "$API_URL/api/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"email\":\"$TEST_EMAIL\",\"password\":\"$password\"}" \
            -w "HTTP_STATUS:%{http_code}" 2>/dev/null || echo "ERROR")
        
        if [[ "$response" =~ HTTP_STATUS:200 ]]; then
            log_error "VULNERABILITY: Weak password '$password' allowed access!"
            return 0  # Vulnerability found
        elif [[ "$response" =~ HTTP_STATUS:40[0-9] ]]; then
            log_info "Password correctly rejected"
        else
            log_warning "Unexpected response for password '$password'"
        fi
    done
    
    log_success "No weak password bypass vulnerability detected"
    return 1  # No vulnerability
}

simulate_sql_injection() {
    log_info "Testing for SQL injection vulnerabilities..."
    
    local sql_payloads=(
        "' OR '1'='1"
        "admin'; --"
        "' UNION SELECT * FROM users --"
        "'; DROP TABLE users; --"
    )
    
    for payload in "${sql_payloads[@]}"; do
        log_info "Testing SQL injection payload..."
        
        response=$(curl -s -X POST "$API_URL/api/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"email\":\"$payload\",\"password\":\"test\"}" \
            -w "HTTP_STATUS:%{http_code}" 2>/dev/null || echo "ERROR")
        
        if [[ "$response" =~ HTTP_STATUS:200 ]]; then
            log_error "VULNERABILITY: SQL injection payload succeeded!"
            return 0  # Vulnerability found
        elif [[ "$response" =~ HTTP_STATUS:50[0-9] ]]; then
            log_warning "Server error - possible SQL injection impact"
        fi
    done
    
    log_success "No SQL injection vulnerability detected"
    return 1  # No vulnerability
}

simulate_rate_limit_bypass() {
    log_info "Testing rate limiting bypass..."
    
    local rapid_requests=20
    local successful_responses=0
    
    log_info "Making $rapid_requests rapid authentication attempts..."
    
    for ((i=1; i<=rapid_requests; i++)); do
        response=$(curl -s -X POST "$API_URL/api/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"email\":\"attacker@example.com\",\"password\":\"wrongpassword\"}" \
            -w "HTTP_STATUS:%{http_code}" 2>/dev/null || echo "ERROR")
        
        if [[ "$response" =~ HTTP_STATUS:40[0-9] ]]; then
            ((successful_responses++))
        elif [[ "$response" =~ HTTP_STATUS:429 ]]; then
            log_info "Rate limiting detected (request $i)"
            break
        fi
        
        # No delay to test rate limiting
    done
    
    if [[ $successful_responses -eq $rapid_requests ]]; then
        log_error "VULNERABILITY: No rate limiting detected - brute force possible!"
        return 0  # Vulnerability found
    else
        log_success "Rate limiting appears to be working"
        return 1  # No vulnerability
    fi
}

simulate_token_manipulation() {
    log_info "Testing token manipulation vulnerabilities..."
    
    # Try to access protected resources with manipulated tokens
    local manipulated_tokens=(
        "admin_token_123"
        "Bearer admin"
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkFkbWluIiwiaWF0IjoxNTE2MjM5MDIyfQ.invalid"
        "null"
        "{\"admin\":true}"
    )
    
    for token in "${manipulated_tokens[@]}"; do
        log_info "Testing token: ${token:0:20}..."
        
        response=$(curl -s -X GET "$API_URL/api/v2/aliases" \
            -H "Authorization: Bearer $token" \
            -w "HTTP_STATUS:%{http_code}" 2>/dev/null || echo "ERROR")
        
        if [[ "$response" =~ HTTP_STATUS:200 ]]; then
            log_error "VULNERABILITY: Manipulated token provided access!"
            return 0  # Vulnerability found
        fi
    done
    
    log_success "Token manipulation attempts correctly rejected"
    return 1  # No vulnerability
}

run_vulnerability_tests() {
    log_info "Starting vulnerability scenario 0 tests..."
    
    local vulnerabilities_found=0
    
    # Run each vulnerability test
    if simulate_weak_auth_bypass; then
        ((vulnerabilities_found++))
    fi
    
    if simulate_sql_injection; then
        ((vulnerabilities_found++))
    fi
    
    if simulate_rate_limit_bypass; then
        ((vulnerabilities_found++))
    fi
    
    if simulate_token_manipulation; then
        ((vulnerabilities_found++))
    fi
    
    return $vulnerabilities_found
}

main() {
    log_info "SimpleLogin Vulnerability Scenario 0: Authentication Bypass Tests"
    echo "=================================================================="
    
    load_config
    
    # Run vulnerability tests
    run_vulnerability_tests
    local vuln_count=$?
    
    echo
    if [[ $vuln_count -gt 0 ]]; then
        log_error "Found $vuln_count potential vulnerabilities!"
        log_warning "This indicates security weaknesses that should be addressed."
    else
        log_success "No vulnerabilities detected in this scenario."
        log_info "Security controls appear to be working correctly."
    fi
    
    echo
    log_info "Vulnerability scenario 0 completed."
    
    # Return number of vulnerabilities found
    exit $vuln_count
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
