\i /seed/accounts.sql
-- bitwarden-seed.sql
-- This file populates the database with dynamic, secure test data.
-- It is designed to be concatenated with secrets.sql and piped into psql.

-- For simplicity, we'll clear existing data from these tables before seeding.
-- Use CASCADE to handle foreign key constraints properly.
TRUNCATE TABLE public.users, public.ciphers, public.devices CASCADE;

----------------------------------------
-- 1. INSERT USERS
----------------------------------------
-- Inserts 3 users with dynamically generated and hashed credentials.
INSERT INTO public.users (
    uuid, created_at, updated_at, email, name, password_hash, salt,
    password_iterations, password_hint, akey, private_key, public_key, security_stamp,
    equivalent_domains, excluded_globals, client_kdf_type, client_kdf_iter, enabled
) VALUES
(
    :'user1_uuid', NOW(), NOW(), :'user1_email', :'user1_name', decode(:'user1_password_hash', 'hex'), decode(:'user1_salt', 'hex'),
    :'user1_password_iterations', :'user1_password_hint', :'user1_akey', :'user1_private_key', :'user1_public_key', :'user1_security_stamp',
    :'user1_equivalent_domains', :'user1_excluded_globals', 0, :'user1_client_kdf_iter', TRUE
),
(
    :'user2_uuid', NOW(), NOW(), :'user2_email', :'user2_name', decode(:'user2_password_hash', 'hex'), decode(:'user2_salt', 'hex'),
    :'user2_password_iterations', :'user2_password_hint', :'user2_akey', :'user2_private_key', :'user2_public_key', :'user2_security_stamp',
    :'user2_equivalent_domains', :'user2_excluded_globals', 0, :'user2_client_kdf_iter', TRUE
),
(
    :'user3_uuid', NOW(), NOW(), :'user3_email', :'user3_name', decode(:'user3_password_hash', 'hex'), decode(:'user3_salt', 'hex'),
    :'user3_password_iterations', :'user3_password_hint', :'user3_akey', :'user3_private_key', :'user3_public_key', :'user3_security_stamp',
    :'user3_equivalent_domains', :'user3_excluded_globals', 0, :'user3_client_kdf_iter', TRUE
);

----------------------------------------
-- 2. INSERT CIPHERS (VAULT ITEMS)
----------------------------------------
-- Inserts 5 ciphers for each of the 3 users.

-- Ciphers for User 1
INSERT INTO public.ciphers (uuid, created_at, updated_at, user_uuid, atype, name, data) VALUES
(:'c1_1_uuid', NOW(), NOW(), :'user1_uuid', 1, :'c1_1_name', :'c1_1_data'),
(:'c1_2_uuid', NOW(), NOW(), :'user1_uuid', 1, :'c1_2_name', :'c1_2_data'),
(:'c1_3_uuid', NOW(), NOW(), :'user1_uuid', 1, :'c1_3_name', :'c1_3_data'),
(:'c1_4_uuid', NOW(), NOW(), :'user1_uuid', 1, :'c1_4_name', :'c1_4_data'),
(:'c1_5_uuid', NOW(), NOW(), :'user1_uuid', 1, :'c1_5_name', :'c1_5_data');

-- Ciphers for User 2
INSERT INTO public.ciphers (uuid, created_at, updated_at, user_uuid, atype, name, data) VALUES
(:'c2_1_uuid', NOW(), NOW(), :'user2_uuid', 1, :'c2_1_name', :'c2_1_data'),
(:'c2_2_uuid', NOW(), NOW(), :'user2_uuid', 1, :'c2_2_name', :'c2_2_data'),
(:'c2_3_uuid', NOW(), NOW(), :'user2_uuid', 1, :'c2_3_name', :'c2_3_data'),
(:'c2_4_uuid', NOW(), NOW(), :'user2_uuid', 1, :'c2_4_name', :'c2_4_data'),
(:'c2_5_uuid', NOW(), NOW(), :'user2_uuid', 1, :'c2_5_name', :'c2_5_data');

-- Ciphers for User 3
INSERT INTO public.ciphers (uuid, created_at, updated_at, user_uuid, atype, name, data) VALUES
(:'c3_1_uuid', NOW(), NOW(), :'user3_uuid', 1, :'c3_1_name', :'c3_1_data'),
(:'c3_2_uuid', NOW(), NOW(), :'user3_uuid', 1, :'c3_2_name', :'c3_2_data'),
(:'c3_3_uuid', NOW(), NOW(), :'user3_uuid', 1, :'c3_3_name', :'c3_3_data'),
(:'c3_4_uuid', NOW(), NOW(), :'user3_uuid', 1, :'c3_4_name', :'c3_4_data'),
(:'c3_5_uuid', NOW(), NOW(), :'user3_uuid', 1, :'c3_5_name', :'c3_5_data');

-- ----------------------------------------
-- 3. INSERT DEVICES
-- ----------------------------------------
-- Inserts 1 device for each of the 3 users, mimicking the dump file.
-- INSERT INTO public.devices (
--     uuid, created_at, updated_at, user_uuid, name, atype, push_token,
--     refresh_token, twofactor_remember, push_uuid
-- ) VALUES
-- (
--     :'device1_uuid', NOW(), NOW(), :'device1_user_uuid', :'device1_name', :'device1_type', NULL,
--     :'device1_refresh_token', NULL, :'device1_push_uuid'
-- ),
-- (
--     :'device2_uuid', NOW(), NOW(), :'device2_user_uuid', :'device2_name', :'device2_type', NULL,
--     :'device2_refresh_token', NULL, :'device2_push_uuid'
-- ),
-- (
--     :'device3_uuid', NOW(), NOW(), :'device3_user_uuid', :'device3_name', :'device3_type', NULL,
--     :'device3_refresh_token', NULL, :'device3_push_uuid'
-- );

-- End of seed.sql 