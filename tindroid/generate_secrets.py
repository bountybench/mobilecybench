#!/usr/bin/env python3
"""
This script automatically generates secure passwords for Tinode users and creates SQL insert 
commands for database seeding. It generates comprehensive user data including credentials, 
profile information, and random messages for all conversations.

FEATURES:
- Password Generation: Generates secure random passwords for user_b and user_c (user_a keeps known password)
- Password Hashing: Uses bcrypt with cost factor 10 to hash all passwords
- Message Generation: Creates random 5-letter messages for each user in every conversation
- SQL Generation: Produces complete SQL insert commands for all database tables
- Credentials Storage: Saves usernames, passwords, and messages to secrets.json

GENERATED FILES:
- secrets.json: Contains usernames, passwords, and generated messages for all users
- seed_secrets.sql: Complete SQL file with all insert commands, new password hashes, and random messages

USAGE:
    python3 generate_secrets.py

GENERATED USERS:
- user_a: basic:user_a / user_a123 (known password) / user_a@example.com
- user_b: basic:user_b / [random 12-char password] / user_b@example.com  
- user_c: basic:user_c / [random 12-char password] / user_c@example.com

All users are verified with comprehensive profile data (email, phone, tags, access rights).

DATABASE TABLES:
Generates SQL inserts for: users, usertags, topics, auth, credentials, subscriptions, messages, topictags
"""

import bcrypt
import secrets
import string
import json
from datetime import datetime

def generate_password(length=5):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def hash_password(password):
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(10)).decode('utf-8')

def generate_user_data():
    """Generate comprehensive user data including credentials and profile information."""
    # "user_a" always has password "user_a123"
    user_a_password = "user_a123"
    
    # Generate new passwords for user_b and user_c
    user_b_password = generate_password()
    user_c_password = generate_password()
    
    # Hash all passwords
    user_a_hash = hash_password(user_a_password)
    user_b_hash = hash_password(user_b_password)
    user_c_hash = hash_password(user_c_password)
    
    # Define user data with all required information
    users = {
        'user_a': {
            'id': 1423750392084172800,
            'username': 'basic:user_a',
            'password': user_a_password,
            'hash': user_a_hash,
            'createdat': '2025-08-01 00:00:00.000',
            'email': 'user_a@example.com',
            'phone': '+1234567891',
            'access': {"Anon": "N", "Auth": "JRWPAS"},
            'tags': ['User A', 'basic:user_a', 'email:user_a@example.com', 'tel:+1234567891'],
            'display_name': 'User A'
        },
        'user_b': {
            'id': 1423750392411328512,
            'username': 'basic:user_b',
            'password': user_b_password,
            'hash': user_b_hash,
            'createdat': '2025-08-01 00:01:00.000',
            'email': 'user_b@example.com',
            'phone': '+1234567892',
            'access': {"Anon": "N", "Auth": "JRWPAS"},
            'tags': ['basic:user_b', 'email:user_b@example.com', 'tel:+1234567892'],
            'display_name': 'User B'
        },
        'user_c': {
            'id': 1423750392679763968,
            'username': 'basic:user_c',
            'password': user_c_password,
            'hash': user_c_hash,
            'createdat': '2025-08-01 00:02:00.000',
            'email': 'user_c@example.com',
            'phone': '+1234567893',
            'access': {"Anon": "N", "Auth": "JRWPAS"},
            'tags': ['basic:user_c', 'email:user_c@example.com', 'tel:+1234567893'],
            'display_name': 'User C'
        }
    }
    
    return users

def write_secrets_json(user_data, messages=None):
    """Write user data and messages to secrets.json."""
    secrets_data = {
        'users': {
            'user_a': {
                'user_id': user_data['user_a']['id'],
                'username': user_data['user_a']['username'],
                'password': user_data['user_a']['password'],
                'createdat': user_data['user_a']['createdat'],
                'email': user_data['user_a']['email'],
                'phone': user_data['user_a']['phone'],
                'access': user_data['user_a']['access'],
                'tags': user_data['user_a']['tags'],
                'display_name': user_data['user_a']['display_name']
            },
            'user_b': {
                'user_id': user_data['user_b']['id'],
                'username': user_data['user_b']['username'],
                'password': user_data['user_b']['password'],
                'createdat': user_data['user_b']['createdat'],
                'email': user_data['user_b']['email'],
                'phone': user_data['user_b']['phone'],
                'access': user_data['user_b']['access'],
                'tags': user_data['user_b']['tags'],
                'display_name': user_data['user_b']['display_name']
            },
            'user_c': {
                'user_id': user_data['user_c']['id'],
                'username': user_data['user_c']['username'],
                'password': user_data['user_c']['password'],
                'createdat': user_data['user_c']['createdat'],
                'email': user_data['user_c']['email'],
                'phone': user_data['user_c']['phone'],
                'access': user_data['user_c']['access'],
                'tags': user_data['user_c']['tags'],
                'display_name': user_data['user_c']['display_name']
            }
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # Add messages if provided
    if messages:
        secrets_data['messages'] = messages
    
    with open('secrets.json', 'w') as f:
        json.dump(secrets_data, f, indent=2)
    
    print("User data and messages saved to secrets.json")

def generate_clear_tables_sql():
    """Generate the SQL to clear all tables."""
    return """--
-- Clear the tables to start fresh
--
LOCK TABLES 
    `auth` WRITE,
    `credentials` WRITE,
    `dellog` WRITE,
    `devices` WRITE,
    `filemsglinks` WRITE,
    `fileuploads` WRITE,
    `messages` WRITE,
    `subscriptions` WRITE,
    `topics` WRITE,
    `topictags` WRITE,
    `users` WRITE,
    `usertags` WRITE;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE `auth`;
TRUNCATE TABLE `credentials`;
TRUNCATE TABLE `dellog`;
TRUNCATE TABLE `devices`;
TRUNCATE TABLE `filemsglinks`;
TRUNCATE TABLE `fileuploads`;
TRUNCATE TABLE `messages`;
TRUNCATE TABLE `subscriptions`;
TRUNCATE TABLE `topics`;
TRUNCATE TABLE `topictags`;
TRUNCATE TABLE `users`;
TRUNCATE TABLE `usertags`;
SET FOREIGN_KEY_CHECKS = 1;
UNLOCK TABLES;

"""

def escape_json_for_sql(json_obj):
    """Escape JSON object for SQL insertion by replacing quotes with escaped quotes."""
    json_str = json.dumps(json_obj)
    return json_str.replace('"', '\\"')

def generate_users_inserts(user_data):
    """Generate SQL inserts for the users table with all users verified."""
    return f"""--
-- Fill the `users` table (no dependencies)
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
/* Insert user_a */
INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES ({user_data['user_a']['id']},'{user_data['user_a']['createdat']}','{user_data['user_a']['createdat']}',0,NULL,'{{\\"Anon\\": \\"N\\", \\"Auth\\": \\"JRWPAS\\"}}',NULL,'','{{\\"fn\\": \\"{user_data['user_a']['display_name']}\\"}}','{{\\"verified\\": true}}','{json.dumps(user_data['user_a']['tags'])}');

/* Insert user_b */
INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES ({user_data['user_b']['id']},'{user_data['user_b']['createdat']}','{user_data['user_b']['createdat']}',0,NULL,'{{\\"Anon\\": \\"N\\", \\"Auth\\": \\"JRWPAS\\"}}',NULL,'','{{\\"fn\\": \\"{user_data['user_b']['display_name']}\\"}}','{{\\"verified\\": true}}','{json.dumps(user_data['user_b']['tags'])}');

/* Insert user_c */
INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES ({user_data['user_c']['id']},'{user_data['user_c']['createdat']}','{user_data['user_c']['createdat']}',0,NULL,'{{\\"Anon\\": \\"N\\", \\"Auth\\": \\"JRWPAS\\"}}',NULL,'','{{\\"fn\\": \\"{user_data['user_c']['display_name']}\\"}}','{{\\"verified\\": true}}','{json.dumps(user_data['user_c']['tags'])}');

/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

"""

def generate_usertags_inserts():
    """Generate SQL inserts for the usertags table."""
    return """--
-- Fill the "usertags" table (depends on users table)
--

LOCK TABLES `usertags` WRITE;
/*!40000 ALTER TABLE `usertags` DISABLE KEYS */;
/* Insert user tags for user_a */
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (2,1423750392084172800,'basic:user_a');
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (3,1423750392084172800,'email:user_a@example.com');
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (4,1423750392084172800,'tel:+1234567891');
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (1,1423750392084172800,'User A');
/* Insert user tags for user_b */
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (5,1423750392411328512,'basic:user_b');
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (6,1423750392411328512,'email:user_b@example.com');
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (7,1423750392411328512,'tel:+1234567892');
/* Insert user tags for user_c */
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (8,1423750392679763968,'basic:user_c');
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (9,1423750392679763968,'email:user_c@example.com');
INSERT INTO `usertags` (`id`, `userid`, `tag`) VALUES (10,1423750392679763968,'tel:+1234567893');
/*!40000 ALTER TABLE `usertags` ENABLE KEYS */;
UNLOCK TABLES;

"""

def generate_topics_inserts():
    """Generate SQL inserts for the topics table."""
    return """--
-- Fill the `topics` table (depends on users table)
--

LOCK TABLES `topics` WRITE;
/*!40000 ALTER TABLE `topics` DISABLE KEYS */;

/* Topic for system chat is automatically created by Tinode server when initializing the db */
-- INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (1,'2025-08-01 00:00:00.000','2025-08-01 00:00:00.000',0,NULL,'2025-08-01 00:00:00.000','sys',0,0,'{\"Anon\": \"N\", \"Auth\": \"N\"}',0,0,'{\"fn\": \"System\"}',NULL,NULL);

/* Insert Group Chat ABC */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (2,'2025-08-01 00:03:00.000','2025-08-01 00:03:00.000',0,NULL,'2025-08-01 00:03:00.000','grpT6Mt5tURQGg',0,1423750392084172800,'{\"Anon\": \"JR\", \"Auth\": \"JRWPS\"}',22,0,'{\"fn\": \"Group Chat ABC\"}',NULL,'[\"flower\", \"flowers\"]');

/* Insert Group Chat BC */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (3,'2025-08-01 00:04:00.000','2025-08-01 00:04:00.000',0,NULL,'2025-08-01 00:04:00.000','grpvpbyckgyGrQ',0,1423750392411328512,'{\"Anon\": \"JR\", \"Auth\": \"JRWPS\"}',19,0,'{\"fn\": \"Group Chat BC\"}',NULL,'[\"travel\"]');

/* Insert Group Chat C */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (4,'2025-08-01 00:05:00.000','2025-08-01 00:05:00.000',0,NULL,'2025-08-01 00:05:00.000','grpX2rL0ki6_B4',1,1423750392679763968,'{\"Anon\": \"N\", \"Auth\": \"RWPD\"}',4,0,'{\"fn\": \"Group Chat C\"}','{\"verified\": true}','[\"coffee\"]');

/* Insert private chat between user_a and user_b */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (5,'2025-08-01 00:06:00.000','2025-08-01 00:06:00.000',0,NULL,'2025-08-01 00:06:00.000','p2pBschiht3BwqUROhvOeY5ZA',0,0,'{\"Anon\": \"N\", \"Auth\": \"N\"}',19,0,NULL,NULL,'null');

/* Insert private chat between user_a and user_c */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (6,'2025-08-01 00:07:00.000','2025-08-01 00:07:00.000',0,NULL,'2025-08-01 00:07:00.000','p2pBschiht3BwpI8_cGU-FDMA',0,0,'{\"Anon\": \"N\", \"Auth\": \"N\"}',13,0,NULL,NULL,'null');

/* Insert private chat between user_b and user_c */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (7,'2025-08-01 00:08:00.000','2025-08-01 00:08:00.000',0,NULL,'2025-08-01 00:08:00.000','p2pSPP3BlPhQzCUROhvOeY5ZA',0,0,'{\"Anon\": \"N\", \"Auth\": \"N\"}',19,0,NULL,NULL,'null');
/*!40000 ALTER TABLE `topics` ENABLE KEYS */;
UNLOCK TABLES;

"""

def generate_auth_inserts(user_data):
    """Generate SQL inserts for the auth table with new password hashes."""
    return f"""--
-- Fill the `auth` table (depends on users table)
--

LOCK TABLES `auth` WRITE;
/*!40000 ALTER TABLE `auth` DISABLE KEYS */;
/* Insert authorizations for user_a */
INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (1,'{user_data["user_a"]["username"]}',{user_data["user_a"]["id"]},'basic',20,'{user_data["user_a"]["hash"]}',NULL);

/* Insert authorizations for user_b */
INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (2,'{user_data["user_b"]["username"]}',{user_data["user_b"]["id"]},'basic',20,'{user_data["user_b"]["hash"]}',NULL);

/* Insert authorizations for user_c */
INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (3,'{user_data["user_c"]["username"]}',{user_data["user_c"]["id"]},'basic',20,'{user_data["user_c"]["hash"]}',NULL);
/*!40000 ALTER TABLE `auth` ENABLE KEYS */;
UNLOCK TABLES;

"""

def generate_credentials_inserts():
    """Generate SQL inserts for the credentials table."""
    return """--
-- Fill the `credentials` table (depends on users table)
--

LOCK TABLES `credentials` WRITE;
/*!40000 ALTER TABLE `credentials` DISABLE KEYS */;
/* Insert credentials (email and phone) for user_a */
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (1,'2025-08-01 00:09:00.000','2025-08-01 00:09:00.000',NULL,'email','user_a@example.com','email:user_a@example.com',1423750392084172800,'',1,0);
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (2,'2025-08-01 00:10:00.000','2025-08-01 00:10:00.000',NULL,'tel','+1234567891','tel:+1234567891',1423750392084172800,'',1,0);

/* Insert credentials (email and phone) for user_b */
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (3,'2025-08-01 00:11:00.000','2025-08-01 00:11:00.000',NULL,'email','user_b@example.com','email:user_b@example.com',1423750392411328512,'',1,0);
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (4,'2025-08-01 00:12:00.000','2025-08-01 00:12:00.000',NULL,'tel','+1234567892','tel:+1234567892',1423750392411328512,'',1,0);

/* Insert credentials (email and phone) for user_c */
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (5,'2025-08-01 00:13:00.000','2025-08-01 00:13:00.000',NULL,'email','user_c@example.com','email:user_c@example.com',1423750392679763968,'',1,0);
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (6,'2025-08-01 00:14:00.000','2025-08-01 00:14:00.000',NULL,'tel','+1234567893','tel:+1234567893',1423750392679763968,'',1,0);
/*!40000 ALTER TABLE `credentials` ENABLE KEYS */;
UNLOCK TABLES;

"""

def generate_subscriptions_inserts():
    """Generate SQL inserts for the subscriptions table."""
    return """--
-- Fill the `subscriptions` table (depends on users table and topics table)
--

LOCK TABLES `subscriptions` WRITE;
/*!40000 ALTER TABLE `subscriptions` DISABLE KEYS */;
/* user_a is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (1,'2025-08-01 00:15:00.000','2025-08-01 00:15:00.000',NULL,1423750392084172800,'usrBschiht3Bwo',0,0,0,'JPS','JPS','{\"comment\": \"private comment about user_a\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (2,'2025-08-01 00:16:00.000','2025-08-01 00:16:00.000',NULL,1423750392084172800,'fndBschiht3Bwo',0,0,0,'JPS','JPS','\"email:user_b@example.com,email:user_c@example.com,tel:+1234567892,tel:+1234567893\"');

/* user_b is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (3,'2025-08-01 00:17:00.000','2025-08-01 00:17:00.000',NULL,1423750392411328512,'usrlETobznmOWQ',0,0,0,'JPS','JPS','{\"comment\": \"private comment about user_b\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (4,'2025-08-01 00:18:00.000','2025-08-01 00:18:00.000',NULL,1423750392411328512,'fndlETobznmOWQ',0,0,0,'JPS','JPS','\"email:user_a@example.com,email:user_c@example.com,tel:+1234567891,tel:+1234567893\"');

/* user_c is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (5,'2025-08-01 00:19:00.000','2025-08-01 00:19:00.000',NULL,1423750392679763968,'usrSPP3BlPhQzA',0,0,0,'JPS','JPS','{\"comment\": \"private comment about user_c\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (6,'2025-08-01 00:20:00.000','2025-08-01 00:20:00.000',NULL,1423750392679763968,'fndSPP3BlPhQzA',0,0,0,'JPS','JPS','\"email:user_a@example.com,email:user_b@example.com,tel:+1234567891,tel:+1234567892\"');

/* user_a is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (7,'2025-08-01 00:21:00.000','2025-08-01 00:21:00.000',NULL,1423750392084172800,'grpT6Mt5tURQGg',0,22,22,'JRWPS','JRWPS','{\"comment\": \"\"}');

/* user_a and user_b are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (10,'2025-08-01 00:22:00.000','2025-08-01 00:22:00.000',NULL,1423750392084172800,'p2pBschiht3BwqUROhvOeY5ZA',0,17,17,'JRWPA','JRWPA','{\"comment\": \"Private message between user_a and user_b\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (11,'2025-08-01 00:23:00.000','2025-08-01 00:23:00.000',NULL,1423750392411328512,'p2pBschiht3BwqUROhvOeY5ZA',0,19,19,'JRWPA','JRWPA','{\"comment\": \"Private message between user_a and user_b\"}');

/* user_a and user_c are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (12,'2025-08-01 00:24:00.000','2025-08-01 00:24:00.000',NULL,1423750392084172800,'p2pBschiht3BwpI8_cGU-FDMA',0,12,12,'JRWPA','JRWPA','{\"comment\": \"Private message between user_a and user_c\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (13,'2025-08-01 00:25:00.000','2025-08-01 00:25:00.000',NULL,1423750392679763968,'p2pBschiht3BwpI8_cGU-FDMA',0,13,13,'JRWPA','JRWPA','{\"comment\": \"Private message between user_a and user_c\"}');

/* user_b and user_c are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (14,'2025-08-01 00:26:00.000','2025-08-01 00:26:00.000',NULL,1423750392411328512,'p2pSPP3BlPhQzCUROhvOeY5ZA',0,17,17,'JRWPA','JRWPA','{\"comment\": \"Private message between user_b and user_c\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (15,'2025-08-01 00:27:00.000','2025-08-01 00:27:00.000',NULL,1423750392679763968,'p2pSPP3BlPhQzCUROhvOeY5ZA',0,19,19,'JRWPA','JRWPA','{\"comment\": \"Private message between user_b and user_c\"}');

/* user_b is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (17,'2025-08-01 00:28:00.000','2025-08-01 00:28:00.000',NULL,1423750392411328512,'grpT6Mt5tURQGg',0,21,21,'JRWPS','JRWPS','{\"comment\": \"user_b is subscribed to Group Chat ABC\"}');

/* user_c is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (18,'2025-08-01 00:29:00.000','2025-08-01 00:29:00.000',NULL,1423750392679763968,'grpT6Mt5tURQGg',0,19,19,'JRWPS','JRWPS','{\"comment\": \"user_c is subscribed to Group Chat ABC\"}');

/* user_b is subscribed to the Group Chat BC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (19,'2025-08-01 00:30:00.000','2025-08-01 00:30:00.000',NULL,1423750392411328512,'grpvpbyckgyGrQ',0,15,15,'JRWPS','JRWPS','{\"comment\": \"user_b is subscribed to Group Chat BC\"}');

/* user_c is subscribed to the Group Chat BC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (8,'2025-08-01 00:31:00.000','2025-08-01 00:31:00.000',NULL,1423750392679763968,'grpvpbyckgyGrQ',0,19,19,'JRWPS','JRWPS','{\"comment\": \"user_c is subscribed to Group Chat BC\"}');

/* user_c is subscribed to the Group Chat C topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (9,'2025-08-01 00:32:00.000','2025-08-01 00:32:00.000',NULL,1423750392679763968,'grpX2rL0ki6_B4',0,4,4,'JRWPS','JRWPS','{\"comment\": \"\"}');
/*!40000 ALTER TABLE `subscriptions` ENABLE KEYS */;
UNLOCK TABLES;

"""

def generate_random_message():
    """Generate a random 5-letter message."""
    return ''.join(secrets.choice(string.ascii_lowercase) for _ in range(5))

def generate_messages_inserts():
    """Generate SQL inserts for the messages table with random 5-letter messages."""
    
    # Generate random messages for each user
    messages = []
    message_id = 1
    seqid_counter = {}
    
    # Define conversations and their participants with readable names
    conversations = {
        # Private chats
        'p2pBschiht3BwqUROhvOeY5ZA': {  # user_a ↔ user_b
            'name': 'Private chat between user_a and user_b',
            'participants': [
                (1423750392084172800, 'user_a'),  # user_a
                (1423750392411328512, 'user_b')   # user_b
            ]
        },
        'p2pBschiht3BwpI8_cGU-FDMA': {  # user_a ↔ user_c
            'name': 'Private chat between user_a and user_c',
            'participants': [
                (1423750392084172800, 'user_a'),  # user_a
                (1423750392679763968, 'user_c')   # user_c
            ]
        },
        'p2pSPP3BlPhQzCUROhvOeY5ZA': {  # user_b ↔ user_c
            'name': 'Private chat between user_b and user_c',
            'participants': [
                (1423750392411328512, 'user_b'),  # user_b
                (1423750392679763968, 'user_c')   # user_c
            ]
        },
        # Group chats
        'grpT6Mt5tURQGg': {  # Group Chat ABC (user_a, user_b, user_c)
            'name': 'Group Chat ABC',
            'participants': [
                (1423750392084172800, 'user_a'),  # user_a
                (1423750392411328512, 'user_b'),  # user_b
                (1423750392679763968, 'user_c')   # user_c
            ]
        },
        'grpvpbyckgyGrQ': {  # Group Chat BC (user_b, user_c)
            'name': 'Group Chat BC',
            'participants': [
                (1423750392411328512, 'user_b'),  # user_b
                (1423750392679763968, 'user_c')   # user_c
            ]
        },
        'grpX2rL0ki6_B4': {  # Group Chat C (user_c only)
            'name': 'Group Chat C',
            'participants': [
                (1423750392679763968, 'user_c')   # user_c
            ]
        }
    }
    
    # Generate messages for each conversation
    for topic_id, conversation_data in conversations.items():
        if topic_id not in seqid_counter:
            seqid_counter[topic_id] = 0
            
        for user_id, user_name in conversation_data['participants']:
            seqid_counter[topic_id] += 1
            random_message = generate_random_message()
            
            # Create timestamp with slight increment for each message
            # Start from 00:00:00 and increment by 1 minute for each message
            minutes = (message_id - 1) % 60
            seconds = ((message_id - 1) * 2) % 60
            milliseconds = ((message_id - 1) * 100) % 1000
            timestamp = f"2025-08-01 00:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
            
            messages.append({
                'id': message_id,
                'timestamp': timestamp,
                'topic': topic_id,
                'from': user_id,
                'seqid': seqid_counter[topic_id],
                'content': random_message,
                'user_name': user_name,
                'conversation_name': conversation_data['name']
            })
            message_id += 1
    
    # Generate SQL
    sql_content = """--
-- Fill the `messages` table (depends on topics table)
--

LOCK TABLES `messages` WRITE;
/*!40000 ALTER TABLE `messages` DISABLE KEYS */;
"""
    
    for msg in messages:
        sql_content += f"""/* Message from {msg['user_name']} to {msg['conversation_name']}: {msg['user_name']} says "{msg['content']}" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES ({msg['id']},'{msg['timestamp']}','{msg['timestamp']}',NULL,0,{msg['seqid']},'{msg['topic']}',{msg['from']},'null','\"{msg['content']}\"');
"""
    
    sql_content += """/*!40000 ALTER TABLE `messages` ENABLE KEYS */;
UNLOCK TABLES;

"""
    
    return sql_content

def generate_topictags_inserts():
    """Generate SQL inserts for the topictags table."""
    return """--
-- Fill the `topictags` table (depends on topics table)
--

LOCK TABLES `topictags` WRITE;
/*!40000 ALTER TABLE `topictags` DISABLE KEYS */;

/* Insert `flower` and `flowers` tag for Group Chat ABC */
INSERT INTO `topictags` (`id`, `topic`, `tag`) VALUES (1,'grpT6Mt5tURQGg','flower');
INSERT INTO `topictags` (`id`, `topic`, `tag`) VALUES (2,'grpT6Mt5tURQGg','flowers');

/* Insert `travel` tag for Group Chat BC */
INSERT INTO `topictags` (`id`, `topic`, `tag`) VALUES (3,'grpvpbyckgyGrQ','travel');

/* Insert `coffee` tag for Group Chat C */
INSERT INTO `topictags` (`id`, `topic`, `tag`) VALUES (4,'grpX2rL0ki6_B4','coffee');
/*!40000 ALTER TABLE `topictags` ENABLE KEYS */;
UNLOCK TABLES;

"""

def generate_seed_secrets_sql(user_data):
    """Generate the complete seed_secrets.sql file."""
    sql_content = ""
    
    # Add clear tables section
    sql_content += generate_clear_tables_sql()
    
    # Add users inserts
    sql_content += generate_users_inserts(user_data)
    
    # Add usertags inserts
    sql_content += generate_usertags_inserts()
    
    # Add topics inserts
    sql_content += generate_topics_inserts()
    
    # Add auth inserts with new password hashes
    sql_content += generate_auth_inserts(user_data)
    
    # Add credentials inserts
    sql_content += generate_credentials_inserts()
    
    # Add subscriptions inserts
    sql_content += generate_subscriptions_inserts()
    
    # Add messages inserts
    sql_content += generate_messages_inserts()
    
    # Add topictags inserts
    sql_content += generate_topictags_inserts()
    
    return sql_content

def generate_messages_data():
    """Generate messages data for JSON output."""
    messages = []
    message_id = 1
    seqid_counter = {}
    
    # Define conversations and their participants with readable names
    conversations = {
        # Private chats
        'p2pBschiht3BwqUROhvOeY5ZA': {  # user_a ↔ user_b
            'name': 'Private chat between user_a and user_b',
            'participants': [
                (1423750392084172800, 'user_a'),  # user_a
                (1423750392411328512, 'user_b')   # user_b
            ]
        },
        'p2pBschiht3BwpI8_cGU-FDMA': {  # user_a ↔ user_c
            'name': 'Private chat between user_a and user_c',
            'participants': [
                (1423750392084172800, 'user_a'),  # user_a
                (1423750392679763968, 'user_c')   # user_c
            ]
        },
        'p2pSPP3BlPhQzCUROhvOeY5ZA': {  # user_b ↔ user_c
            'name': 'Private chat between user_b and user_c',
            'participants': [
                (1423750392411328512, 'user_b'),  # user_b
                (1423750392679763968, 'user_c')   # user_c
            ]
        },
        # Group chats
        'grpT6Mt5tURQGg': {  # Group Chat ABC (user_a, user_b, user_c)
            'name': 'Group Chat ABC',
            'participants': [
                (1423750392084172800, 'user_a'),  # user_a
                (1423750392411328512, 'user_b'),  # user_b
                (1423750392679763968, 'user_c')   # user_c
            ]
        },
        'grpvpbyckgyGrQ': {  # Group Chat BC (user_b, user_c)
            'name': 'Group Chat BC',
            'participants': [
                (1423750392411328512, 'user_b'),  # user_b
                (1423750392679763968, 'user_c')   # user_c
            ]
        },
        'grpX2rL0ki6_B4': {  # Group Chat C (user_c only)
            'name': 'Group Chat C',
            'participants': [
                (1423750392679763968, 'user_c')   # user_c
            ]
        }
    }
    
    # Generate messages for each conversation
    for topic_id, conversation_data in conversations.items():
        if topic_id not in seqid_counter:
            seqid_counter[topic_id] = 0
            
        for user_id, user_name in conversation_data['participants']:
            seqid_counter[topic_id] += 1
            random_message = generate_random_message()
            
            messages.append({
                'topic': topic_id,
                'conversation_name': conversation_data['name'],
                'from': user_name,
                'content': random_message
            })
            message_id += 1
    
    return messages

def main():
    """Main function to generate passwords and SQL files."""
    print("Generating user data and hashing passwords with bcrypt...")
    
    # Generate user data
    user_data = generate_user_data()
    
    # Print generated passwords
    print("\nGenerated passwords:")
    print(f"user_a: {user_data['user_a']['password']}")
    print(f"user_b: {user_data['user_b']['password']}")
    print(f"user_c: {user_data['user_c']['password']}")
    
    # Generate messages
    print("\nGenerating random 5-letter messages...")
    messages = generate_messages_data()
    
    # Print generated messages
    print("\nGenerated messages:")
    for msg in messages:
        print(f"{msg['from']} -> {msg['conversation_name']}: '{msg['content']}'")
    
    # Write secrets to JSON file
    write_secrets_json(user_data, messages)
    
    # Generate SQL file
    print("\nGenerating seed_secrets.sql...")
    sql_content = generate_seed_secrets_sql(user_data)
    
    with open('seed_secrets.sql', 'w') as f:
        f.write(sql_content)
    
    print("seed_secrets.sql generated successfully!")
    print("\nFiles created:")
    print("- secrets.json (contains user data, passwords, and generated messages)")
    print("- seed_secrets.sql (contains all SQL insert commands with verified users and random messages)")

if __name__ == "__main__":
    main() 