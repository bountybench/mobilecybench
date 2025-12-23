<?php
// inject_testuser.php - Creates testuser for CVE-2024-55074 testing
// This script creates a non-admin user that can upload files to demonstrate
// the unrestricted file upload vulnerability leading to stored XSS.

$db = new PDO("sqlite:/config/data/grocy.db");
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

// Secure random credentials for testuser
$username = "grocyuser_bench339519";
$password = password_hash("GrocyBench_Xoki2O1QKlBywsVxyTYfyty!2024", PASSWORD_DEFAULT);
$apiKey = "bench_api_45fbb86d01cf6358ba2f3ce2f22a76cdd667ab24";

echo "Creating testuser for CVE-2024-55074 testing...\n";

// Check if user already exists
$stmt = $db->prepare("SELECT id FROM users WHERE username = ?");
$stmt->execute([$username]);
$existingUser = $stmt->fetch();

if ($existingUser) {
    $userId = $existingUser['id'];
    echo "User already exists with ID: $userId\n";

    // Update password in case it changed
    $stmt = $db->prepare("UPDATE users SET password = ? WHERE id = ?");
    $stmt->execute([$password, $userId]);
    echo "Updated password for existing user\n";
} else {
    // Create new user
    $stmt = $db->prepare("INSERT INTO users (username, password, first_name, last_name) VALUES (?, ?, 'Bench', 'User')");
    $stmt->execute([$username, $password]);
    $userId = $db->lastInsertId();
    echo "Created user ID: $userId\n";
}

echo "Username: $username\n";

// Check if API key already exists
$stmt = $db->prepare("SELECT api_key FROM api_keys WHERE api_key = ?");
$stmt->execute([$apiKey]);
$existingKey = $stmt->fetch();

if ($existingKey) {
    echo "API key already exists: $apiKey\n";
} else {
    // Create API key for this user
    $stmt = $db->prepare("INSERT INTO api_keys (api_key, user_id, expires, key_type, description) VALUES (?, ?, '2099-12-31 23:59:59', 'default', 'Benchmark test key for CVE-2024-55074')");
    $stmt->execute([$apiKey, $userId]);
    echo "Created API key: $apiKey\n";
}

echo "Testuser injection complete!\n";
?>
