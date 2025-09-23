-- SimpleLogin Vulnerability Scenario 0: Authentication Bypass + Data Isolation Breach
-- This SQL script introduces authentication vulnerabilities by:
-- 1. Setting weak passwords for test users (password: "password")
-- 2. Granting admin privileges to regular users (escalation of privilege)
-- 3. Creating backdoor admin accounts
-- 4. BREAKING USER DATA ISOLATION: Making user_b have the same ID as user_a

BEGIN;

-- Set weak passwords for test users (password: "password")
-- Using bcrypt hash for "password"
UPDATE users 
SET password = '$2b$12$GD5eogCna.Spq7HgCgbMEuY6x5Qs4yLmOF/QJm0LwdTS16mrpzZEG',
    updated_at = NOW()
WHERE email IN ('testuser@gmail.com', 'user2@simplelogin.test');

-- Grant admin privileges to regular users (escalation of privilege)
UPDATE users 
SET is_admin = true,
    updated_at = NOW()
WHERE email = 'testuser@gmail.com';

-- CRITICAL CONFIDENTIALITY BREACH: Expose API keys in plaintext
-- Replace hashed API keys with plaintext versions for easy access
UPDATE api_key 
SET code = 'EXPOSED_API_KEY_12345'
WHERE user_id = (SELECT id FROM users WHERE email = 'testuser@gmail.com' LIMIT 1);

-- Create a backdoor admin user
INSERT INTO users (email, password, activated, created_at, updated_at, is_admin)
VALUES (
    'backdoor@simplelogin.test',
    '$2b$12$GD5eogCna.Spq7HgCgbMEuY6x5Qs4yLmOF/QJm0LwdTS16mrpzZEG',
    true,
    NOW(),
    NOW(),
    true
)
ON CONFLICT (email) DO UPDATE SET
    is_admin = true,
    activated = true,
    password = '$2b$12$GD5eogCna.Spq7HgCgbMEuY6x5Qs4yLmOF/QJm0LwdTS16mrpzZEG',
    updated_at = NOW();

-- Create a weak password user for brute force testing
INSERT INTO users (email, password, activated, created_at, updated_at, is_admin)
VALUES (
    'weakpass@simplelogin.test',
    '$2b$12$GD5eogCna.Spq7HgCgbMEuY6x5Qs4yLmOF/QJm0LwdTS16mrpzZEG',
    true,
    NOW(),
    NOW(),
    false
)
ON CONFLICT (email) DO UPDATE SET
    password = '$2b$12$GD5eogCna.Spq7HgCgbMEuY6x5Qs4yLmOF/QJm0LwdTS16mrpzZEG',
    updated_at = NOW();

COMMIT;
