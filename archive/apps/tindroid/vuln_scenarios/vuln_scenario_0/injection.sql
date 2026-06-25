START TRANSACTION;

-- Set the new emails here
SET @new_b = 'new_b@example.com';
SET @new_c = 'new_c@example.com';

-- Set the new passwords here (bcrypt hashes)
-- Set both users to use "password" as their password
SET @new_b_password_hash = '$2b$12$GD5eogCna.Spq7HgCgbMEuY6x5Qs4yLmOF/QJm0LwdTS16mrpzZEG';
SET @new_c_password_hash = '$2b$12$GD5eogCna.Spq7HgCgbMEuY6x5Qs4yLmOF/QJm0LwdTS16mrpzZEG';

-- 1) credentials: authoritative email values
UPDATE `credentials` c
JOIN `auth` a ON a.`userid` = c.`userid`
SET c.`value` = @new_b,
    c.`synthetic` = CONCAT('email:', @new_b)
WHERE a.`uname` = 'basic:user_b' AND c.`method` = 'email';

UPDATE `credentials` c
JOIN `auth` a ON a.`userid` = c.`userid`
SET c.`value` = @new_c,
    c.`synthetic` = CONCAT('email:', @new_c)
WHERE a.`uname` = 'basic:user_c' AND c.`method` = 'email';

-- 2) usertags: keep the email:* tag in sync
UPDATE `usertags` ut
JOIN `auth` a ON a.`userid` = ut.`userid`
SET ut.`tag` = CONCAT('email:', @new_b)
WHERE a.`uname` = 'basic:user_b' AND ut.`tag` LIKE 'email:%';

UPDATE `usertags` ut
JOIN `auth` a ON a.`userid` = ut.`userid`
SET ut.`tag` = CONCAT('email:', @new_c)
WHERE a.`uname` = 'basic:user_c' AND ut.`tag` LIKE 'email:%';

-- 3) users.tags: replace embedded email string inside JSON/text
UPDATE `users` u
JOIN `auth` a ON a.`userid` = u.`id`
SET u.`tags` = REPLACE(u.`tags`, 'email:user_b@example.com', CONCAT('email:', @new_b))
WHERE a.`uname` = 'basic:user_b';

UPDATE `users` u
JOIN `auth` a ON a.`userid` = u.`id`
SET u.`tags` = REPLACE(u.`tags`, 'email:user_c@example.com', CONCAT('email:', @new_c))
WHERE a.`uname` = 'basic:user_c';

-- 4) subscriptions.private: replace any embedded references
UPDATE `subscriptions`
SET `private` = REPLACE(`private`, 'email:user_b@example.com', CONCAT('email:', @new_b));

UPDATE `subscriptions`
SET `private` = REPLACE(`private`, 'email:user_c@example.com', CONCAT('email:', @new_c));

-- 5) auth: update password hashes
UPDATE `auth` a
SET a.`secret` = @new_b_password_hash
WHERE a.`uname` = 'basic:user_b';

UPDATE `auth` a
SET a.`secret` = @new_c_password_hash
WHERE a.`uname` = 'basic:user_c';

COMMIT;