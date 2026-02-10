<?php
/**
 * Inject API key into Grocy database for testing
 * This script runs inside the Docker container with proper permissions
 */

if ($argc < 2) {
    fwrite(STDERR, "Usage: php inject_api_key.php <api_key>\n");
    exit(1);
}

$apiKey = $argv[1];
$dbPath = '/config/data/grocy.db';
$maxAttempts = 10;
$attempt = 0;

while ($attempt < $maxAttempts) {
    $attempt++;

    try {
        // Open database connection
        $db = new PDO("sqlite:$dbPath");
        $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

        // Check if API key already exists
        $stmt = $db->prepare("SELECT COUNT(*) FROM api_keys WHERE api_key = ?");
        $stmt->execute([$apiKey]);
        $count = $stmt->fetchColumn();

        if ($count > 0) {
            fwrite(STDERR, "API key '$apiKey' already exists\n");
            exit(0);
        }

        // Insert API key for user 1 (admin)
        $stmt = $db->prepare("
            INSERT INTO api_keys (api_key, user_id, expires, last_used, key_type, description)
            VALUES (?, 1, '2099-12-31 23:59:59', NULL, 'default', 'Testing API key')
        ");
        $stmt->execute([$apiKey]);

        fwrite(STDERR, "Successfully injected API key: $apiKey\n");
        exit(0);

    } catch (PDOException $e) {
        fwrite(STDERR, "Attempt $attempt/$maxAttempts: Database error: " . $e->getMessage() . "\n");

        if ($attempt < $maxAttempts) {
            sleep(2);
        } else {
            fwrite(STDERR, "Failed to inject API key after all attempts\n");
            exit(1);
        }
    }
}

exit(1);
