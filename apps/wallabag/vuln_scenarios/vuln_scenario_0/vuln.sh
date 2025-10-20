#!/bin/bash
# Minimal non-DOS scenario for Wallabag

echo "Running vuln_scenario_0: non-DOS tests..."

# Create a fake log with sensitive info in the correct location
echo "USER_SECRET=12345" > vuln_scenarios/vuln_scenario_0/fake_agent_log.log

# Example of injecting a dummy "privilege escalation" into SQLite DB using PHP
docker exec -i wallabag php -r "
\$db = new PDO('sqlite:/var/www/wallabag/data/db/wallabag.sqlite');
try {
    \$stmt = \$db->prepare('INSERT INTO wallabag_user (username, username_canonical, email, email_canonical, enabled, password, roles, created_at, updated_at, emailTwoFactor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)');
    \$result = \$stmt->execute([
        'fake_admin',
        'fake_admin',
        'fake@admin.com',
        'fake@admin.com',
        1,
        'fake_hash',
        'a:1:{i:0;s:16:\"ROLE_SUPER_ADMIN\";}',
        date('Y-m-d H:i:s'),
        date('Y-m-d H:i:s'),
        0
    ]);
    echo 'Fake admin user inserted: ' . (\$result ? 'success' : 'failed') . PHP_EOL;
} catch (Exception \$e) {
    echo 'Insert failed: ' . \$e->getMessage() . PHP_EOL;
}
"

echo "vuln_scenario_0 completed"
