CREATE TABLE IF NOT EXISTS accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    login VARCHAR(255) UNIQUE NOT NULL,
    domain VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    algorithm VARCHAR(50) DEFAULT 'MD5',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

INSERT INTO accounts (login, domain, password, algorithm, created_at, updated_at)
VALUES 
    ('user1', '10.0.2.2', SHA2('user1:10.0.2.2:$Rogexechlw1', 256), 'SHA-256', NOW(), NOW()),
    ('user2', '10.0.2.2', SHA2('user2:10.0.2.2:9Ud!6!TusWiN', 256), 'SHA-256', NOW(), NOW()),
    ('admin', '10.0.2.2', SHA2('admin:10.0.2.2:31Ic4p=odRet', 256), 'SHA-256', NOW(), NOW()),
    ('usera', '10.0.2.2', SHA2('usera:10.0.2.2:userAPW123', 256), 'SHA-256', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    password = VALUES(password),
    algorithm = VALUES(algorithm),
    updated_at = NOW();

SELECT login, domain, algorithm, created_at FROM accounts ORDER BY login;

SELECT 
    algorithm,
    COUNT(*) as account_count
FROM accounts 
GROUP BY algorithm
ORDER BY algorithm;