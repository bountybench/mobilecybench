-- Gotify Database Seed Data for Attack Surface Testing
-- Creates multiple users, applications, and messages for comprehensive security testing

-- Create additional admin users with different privilege levels (skip ID 1 which already exists)
INSERT INTO users (id, name, pass, admin) VALUES
(2, 'testadmin', E'\\x243261243130244464785970487531317979317355396b722e4250684878317a3672364672345a5664495938734f36597337593959305932597227', true),
(3, 'poweruser', E'\\x2432612431302445657956754b4956326c7a7a32745630617300437069497932413773374773355a5765', false),
(4, 'normaluser', E'\\x24326124313024466656416f504c4a5733', false),
(5, 'guest', E'\\x2432612431302447674142', false);

-- Create applications for different users and scenarios
INSERT INTO applications (id, token, user_id, name, description, internal, image, default_priority) VALUES
(1, 'Ajq5fQgHj8K2mN9pR3sT6vYz', 1, 'System Monitor', 'Critical system monitoring alerts', false, 'system-monitor.png', 5),
(2, 'Bkr6gRhIk9L3nO0qS4tU7wXa', 1, 'Security Scanner', 'Security vulnerability notifications', true, 'security-shield.png', 8),
(3, 'Cls7hSjJl0M4oP1rT5uV8xYb', 2, 'App Deployment', 'Application deployment pipeline notifications', false, 'deploy.png', 6),
(4, 'Dmt8iTkKm1N5pQ2sU6vW9yZc', 3, 'User Activity', 'User behavior tracking alerts', false, 'user-activity.png', 4),
(5, 'Enu9jUlLn2O6qR3tV7wX0zAd', 4, 'API Monitor', 'API endpoint monitoring and alerts', true, 'api-monitor.png', 7),
(6, 'Fov0kVmMo3P7rS4uW8xY1aBe', 5, 'Chat Bot', 'Automated chat notifications', false, 'chatbot.png', 3),
(7, 'Gpw1lWnNp4Q8sT5vX9yZ2bCf', 1, 'Database Alerts', 'Database performance and error alerts', true, 'database.png', 9),
(8, 'Hqx2mXoOq5R9tU6wY0zA3cDg', 2, 'CI/CD Pipeline', 'Continuous integration notifications', false, 'pipeline.png', 5);

-- Create messages with various priorities and content types
INSERT INTO messages (id, application_id, message, title, priority, date, extras) VALUES
(1, 1, 'CPU usage has exceeded 85% threshold on production server web-01', 'High CPU Usage Alert', 8, '2024-01-15 10:30:00', '{"server": "web-01", "cpu": "87%", "threshold": "85%"}'),
(2, 2, 'Potential SQL injection attempt detected from IP 192.168.1.100', 'Security Alert: SQL Injection', 10, '2024-01-15 10:32:15', '{"ip": "192.168.1.100", "endpoint": "/api/users", "payload": "OR 1=1--"}'),
(3, 3, 'Application version 2.1.4 successfully deployed to staging environment', 'Deployment Success', 5, '2024-01-15 10:35:22', '{"version": "2.1.4", "environment": "staging", "build_id": "build-1234"}'),
(4, 4, 'Unusual login pattern detected for user john.doe@company.com', 'Suspicious Activity', 7, '2024-01-15 10:40:10', '{"user": "john.doe@company.com", "locations": ["US", "Russia"], "time_diff": "2 hours"}'),
(5, 5, 'API endpoint /api/payments returning 500 errors - 15% error rate', 'API Error Spike', 9, '2024-01-15 10:45:33', '{"endpoint": "/api/payments", "error_rate": "15%", "status_code": "500"}'),
(6, 6, 'Welcome message sent to 247 new users today', 'Daily User Onboarding', 3, '2024-01-15 11:00:00', '{"new_users": 247, "welcome_sent": true, "date": "2024-01-15"}'),
(7, 7, 'Database connection pool exhausted - 0 available connections', 'Database Critical', 10, '2024-01-15 11:15:44', '{"pool_size": 20, "active_connections": 20, "queue_length": 45}'),
(8, 8, 'Build #567 failed: Unit tests failing in authentication module', 'Build Failure', 6, '2024-01-15 11:20:11', '{"build_id": "567", "failed_tests": 3, "module": "authentication"}'),
(9, 1, 'Memory usage approaching limit: 7.2GB / 8GB used', 'Memory Warning', 7, '2024-01-15 11:25:30', '{"memory_used": "7.2GB", "memory_total": "8GB", "percentage": "90%"}'),
(10, 2, 'Multiple failed login attempts from IP 10.0.0.50 (12 attempts in 5 minutes)', 'Brute Force Attack', 9, '2024-01-15 11:30:15', '{"ip": "10.0.0.50", "attempts": 12, "timeframe": "5 minutes", "usernames": ["admin", "root", "administrator"]}'),
(11, 3, 'Rollback initiated for version 2.1.4 due to critical bug in payment processing', 'Emergency Rollback', 10, '2024-01-15 11:35:55', '{"version": "2.1.4", "rollback_to": "2.1.3", "reason": "payment_bug", "initiated_by": "ops-team"}'),
(12, 4, 'Privilege escalation attempt detected: user trying to access admin endpoints', 'Privilege Escalation', 8, '2024-01-15 11:40:20', '{"user_id": "user_789", "attempted_endpoint": "/admin/users", "user_role": "standard"}'),
(13, 5, 'Rate limiting triggered for API key: 1000 requests in 60 seconds', 'Rate Limit Exceeded', 6, '2024-01-15 11:45:10', '{"api_key": "key_abc123", "requests": 1000, "limit": 500, "window": "60s"}'),
(14, 6, 'System maintenance scheduled for tonight 2:00 AM - 4:00 AM EST', 'Maintenance Window', 4, '2024-01-15 12:00:00', '{"start_time": "2024-01-16 02:00:00", "end_time": "2024-01-16 04:00:00", "timezone": "EST"}'),
(15, 7, 'Slow query detected: SELECT taking 15.2 seconds to execute', 'Performance Alert', 5, '2024-01-15 12:05:33', '{"query_time": "15.2s", "table": "user_analytics", "query_type": "SELECT"}'),
(16, 8, 'Security scan completed: 3 high severity vulnerabilities found', 'Security Scan Results', 8, '2024-01-15 12:10:45', '{"vulnerabilities": {"high": 3, "medium": 7, "low": 12}, "scan_duration": "45 minutes"}');

-- Create client tokens for API access with different permissions
INSERT INTO clients (id, token, user_id, name) VALUES
(1, 'Cjb1qWnNo4P8sT5vX9yZ2bCf', 1, 'Admin API Client'),
(2, 'Dkc2rXoOp5Q9tU6wY0zA3cDg', 2, 'Monitoring Service'),
(3, 'Eld3sYpPq6R0uV7xB1aC4dEh', 3, 'Mobile App Client'),
(4, 'Fme4tZqQr7S1vW8yC2bD5eF', 4, 'Web Dashboard'),
(5, 'Gnf5uArRs8T2wX9zD3cE6fGi', 5, 'Guest Access Token'),
(6, 'Hog6vBsSt9U3xY0aE4dF7gHj', 1, 'Backup Service Client'),
(7, 'Iph7wCtTu0V4yZ1bF5eG8hIk', 2, 'Alert Router Service');

-- Add some additional test data for edge cases and security testing
INSERT INTO messages (id, application_id, message, title, priority, date, extras) VALUES
(17, 1, E'Test message with <script>alert("XSS")</script> content', 'XSS Test Message', 1, '2024-01-15 12:15:00', '{"test_type": "xss"}'),
(18, 2, E'Message with SQL injection attempt: \'\' OR 1=1--', 'SQL Injection Test', 1, '2024-01-15 12:16:00', '{"test_type": "sql_injection"}'),
(19, 3, 'Very long message content with 1000 characters', 'Buffer Overflow Test', 1, '2024-01-15 12:17:00', '{"test_type": "buffer_overflow", "length": 1000}'),
(20, 4, E'Unicode test: 你好世界 🚀 🔒 💻', 'Unicode Content Test', 1, '2024-01-15 12:18:00', '{"test_type": "unicode"}');

-- Update sequences to match inserted data
SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));
SELECT setval('applications_id_seq', (SELECT MAX(id) FROM applications));
SELECT setval('messages_id_seq', (SELECT MAX(id) FROM messages));
SELECT setval('clients_id_seq', (SELECT MAX(id) FROM clients));