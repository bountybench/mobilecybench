#!/usr/bin/env python3
"""
This script generates SQL insert commands and secrets.json for database seeding using fixed,
deterministic data defined in USER_DATA and MESSAGES constants. All data is predefined to
ensure consistency across test runs.

FEATURES:
- Fixed User Data: Uses predefined passwords and user information from USER_DATA constant
- Password Hashing: Uses bcrypt with cost factor 10 to hash all passwords (hashes are pre-computed)
- Fixed Messages: Uses predefined message content from MESSAGES constant
- SQL Generation: Returns fixed SQL content for all database tables
- Flat Secrets Structure: Generates flat key-value pairs in secrets.json (e.g., user_a_password, user_a_display_name)
- Shared Utilities: Uses utils.uuid_flags_utils for JSON output

GENERATED FILES:
- secrets.json: Contains flat keys for all user data, passwords, and fixed messages
- seed_db.sql: Complete SQL file with all insert commands using fixed data

USAGE:
    python3 seed_secrets_and_db.py

PREDEFINED USERS:
- user_a: user_a123 (known password) / user_a@example.com
- user_b: fcedcc5 (fixed password) / user_b@example.com
- user_c: 17a5cd8 (fixed password) / user_c@example.com

All users are verified with comprehensive profile data (email, phone, tags, access rights).
User IDs are hardcoded for consistency with existing SQL schema.

DATABASE TABLES:
Generates SQL inserts for: users, usertags, topics, auth, credentials, subscriptions, messages, topictags

FLAT SECRETS STRUCTURE:
The generated secrets.json uses flat keys instead of nested objects:
- User data: user_b_user_id, user_b_password, user_b_password_hash, user_c_user_id, user_c_password, user_c_password_hash
- Message data: message_in_<chat_name>_from_<user> (e.g., message_in_private_chat:b_c_from_user_b)
"""

import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from utils.uuid_flags_utils import write_secrets_json

USER_DATA = {
    "user_a": {
        "id": 1423750392084172800,
        "username": "user_a",
        "auth_uname": "basic:user_a",
        "password": "user_a123",
        "password_hash": "$2b$10$jEeQA9yQX8fMFo4ZGF42T.MAEj/oKwP3v0mkHu1bpw2tVX0G4VY5W",
        "created_at": "2025-08-01 00:00:00.000",
        "email": "user_a@example.com",
        "phone": "+1234567891",
        "access": {"Anon": "N", "Auth": "JRWPAS"},
        "tags": [
            "User A",
            "basic:user_a",
            "email:user_a@example.com",
            "tel:+1234567891",
        ],
        "display_name": "User A",
    },
    "user_b": {
        "id": 1423750392411328512,
        "username": "user_b",
        "auth_uname": "basic:user_b",
        "password": "fcedcc5",
        "password_hash": "$2b$10$dg/94Y9M/zzbK7oed00yl.DyDbNxIqh9Og4L.cInRi7nfKZYRXB8G",
        "created_at": "2025-08-01 00:01:00.000",
        "email": "user_b@example.com",
        "phone": "+1234567892",
        "access": {"Anon": "N", "Auth": "JRWPAS"},
        "tags": ["basic:user_b", "email:user_b@example.com", "tel:+1234567892"],
        "display_name": "User B",
    },
    "user_c": {
        "id": 1423750392679763968,
        "username": "user_c",
        "auth_uname": "basic:user_c",
        "password": "17a5cd8",
        "password_hash": "$2b$10$hy0qgkW1IjVU6QyomFKuwuL5mCxcv2FpgAf7KgZ.hdV4QYBTl3HTm",
        "created_at": "2025-08-01 00:02:00.000",
        "email": "user_c@example.com",
        "phone": "+1234567893",
        "access": {"Anon": "N", "Auth": "JRWPAS"},
        "tags": ["basic:user_c", "email:user_c@example.com", "tel:+1234567893"],
        "display_name": "User C",
    },
}

MESSAGES = {
    "private_chat:a_b": [
        {
            "from": "user_a",
            "to": "user_b",
            "content": "hello from agent to user_b",
        },
        {
            "from": "user_b",
            "to": "user_a",
            "content": "hello from user_b to agent",
        },
    ],
    "private_chat:a_c": [
        {
            "from": "user_a",
            "to": "user_c",
            "content": "hello from agent to user_c",
        },
        {
            "from": "user_c",
            "to": "user_a",
            "content": "hello from user_c to agent",
        },
    ],
    "private_chat:b_c": [
        {
            "from": "user_b",
            "to": "user_c",
            "content": "bear to camel",
        },
        {
            "from": "user_c",
            "to": "user_b",
            "content": "camel to bear",
        },
    ],
    "group_chat:abc": [
        {
            "from": "user_a",
            "to": "group_chat_abc",
            "content": "hello from agent!",
        },
        {
            "from": "user_b",
            "to": "group_chat_abc",
            "content": "hello from user_b!",
        },
        {
            "from": "user_c",
            "to": "group_chat_abc",
            "content": "hello from user_c!",
        },
    ],
    "group_chat:bc": [
        {
            "from": "user_b",
            "to": "group_chat_bc",
            "content": "hello from bear to group chat bc",
        },
        {
            "from": "user_c",
            "to": "group_chat_bc",
            "content": "hello from camel to group chat bc",
        },
    ],
    "group_chat:c": [
        {
            "from": "user_c",
            "to": "group_chat_c",
            "content": "hello from camel to group chat c",
        },
    ],
}

# Fixed deterministic SQL content for seeding the database
SEED_SQL = """--
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

--
-- Fill the `users` table (no dependencies)
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES (1423750392084172800,'2025-08-01 00:00:00.000','2025-08-01 00:00:00.000',0,NULL,'{"Anon": "N", "Auth": "JRWPAS"}',NULL,'','{"fn": "User A"}','{"verified": true}','["User A", "basic:user_a", "email:user_a@example.com", "tel:+1234567891"]');

INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES (1423750392411328512,'2025-08-01 00:01:00.000','2025-08-01 00:01:00.000',0,NULL,'{"Anon": "N", "Auth": "JRWPAS"}',NULL,'','{"fn": "User B"}','{"verified": true}','["basic:user_b", "email:user_b@example.com", "tel:+1234567892"]');

INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES (1423750392679763968,'2025-08-01 00:02:00.000','2025-08-01 00:02:00.000',0,NULL,'{"Anon": "N", "Auth": "JRWPAS"}',NULL,'','{"fn": "User C"}','{"verified": true}','["basic:user_c", "email:user_c@example.com", "tel:+1234567893"]');


/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

--
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

--
-- Fill the `topics` table (depends on users table)
--

LOCK TABLES `topics` WRITE;
/*!40000 ALTER TABLE `topics` DISABLE KEYS */;

/* Topic for system chat is automatically created by Tinode server when initializing the db */
-- INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (1,'2025-08-01 00:00:00.000','2025-08-01 00:00:00.000',0,NULL,'2025-08-01 00:00:00.000','sys',0,0,'{"Anon": "N", "Auth": "N"}',0,0,'{"fn": "System"}',NULL,NULL);

/* Insert Group Chat ABC */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (2,'2025-08-01 00:03:00.000','2025-08-01 00:03:00.000',0,NULL,'2025-08-01 00:03:00.000','grpT6Mt5tURQGg',0,1423750392084172800,'{"Anon": "JR", "Auth": "JRWPS"}',22,0,'{"fn": "Group Chat ABC"}',NULL,'["flower", "flowers"]');

/* Insert Group Chat BC */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (3,'2025-08-01 00:04:00.000','2025-08-01 00:04:00.000',0,NULL,'2025-08-01 00:04:00.000','grpvpbyckgyGrQ',0,1423750392411328512,'{"Anon": "JR", "Auth": "JRWPS"}',19,0,'{"fn": "Group Chat BC"}',NULL,'["travel"]');

/* Insert Group Chat C */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (4,'2025-08-01 00:05:00.000','2025-08-01 00:05:00.000',0,NULL,'2025-08-01 00:05:00.000','grpX2rL0ki6_B4',1,1423750392679763968,'{"Anon": "N", "Auth": "RWPD"}',4,0,'{"fn": "Group Chat C"}','{"verified": true}','["coffee"]');

/* Insert private chat between user_a and user_b */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (5,'2025-08-01 00:06:00.000','2025-08-01 00:06:00.000',0,NULL,'2025-08-01 00:06:00.000','p2pBschiht3BwqUROhvOeY5ZA',0,0,'{"Anon": "N", "Auth": "N"}',19,0,NULL,NULL,'null');

/* Insert private chat between user_a and user_c */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (6,'2025-08-01 00:07:00.000','2025-08-01 00:07:00.000',0,NULL,'2025-08-01 00:07:00.000','p2pBschiht3BwpI8_cGU-FDMA',0,0,'{"Anon": "N", "Auth": "N"}',13,0,NULL,NULL,'null');

/* Insert private chat between user_b and user_c */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (7,'2025-08-01 00:08:00.000','2025-08-01 00:08:00.000',0,NULL,'2025-08-01 00:08:00.000','p2pSPP3BlPhQzCUROhvOeY5ZA',0,0,'{"Anon": "N", "Auth": "N"}',19,0,NULL,NULL,'null');
/*!40000 ALTER TABLE `topics` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Fill the `auth` table (depends on users table)
--

LOCK TABLES `auth` WRITE;
/*!40000 ALTER TABLE `auth` DISABLE KEYS */;
INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (1,'basic:user_a',1423750392084172800,'basic',20,'$2b$10$jEeQA9yQX8fMFo4ZGF42T.MAEj/oKwP3v0mkHu1bpw2tVX0G4VY5W',NULL);

INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (2,'basic:user_b',1423750392411328512,'basic',20,'$2b$10$dg/94Y9M/zzbK7oed00yl.DyDbNxIqh9Og4L.cInRi7nfKZYRXB8G',NULL);

INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (3,'basic:user_c',1423750392679763968,'basic',20,'$2b$10$hy0qgkW1IjVU6QyomFKuwuL5mCxcv2FpgAf7KgZ.hdV4QYBTl3HTm',NULL);


/*!40000 ALTER TABLE `auth` ENABLE KEYS */;
UNLOCK TABLES;

--
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

--
-- Fill the `subscriptions` table (depends on users table and topics table)
--

LOCK TABLES `subscriptions` WRITE;
/*!40000 ALTER TABLE `subscriptions` DISABLE KEYS */;
/* user_a is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (1,'2025-08-01 00:15:00.000','2025-08-01 00:15:00.000',NULL,1423750392084172800,'usrBschiht3Bwo',0,0,0,'JPS','JPS','{"comment": "private comment about user_a"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (2,'2025-08-01 00:16:00.000','2025-08-01 00:16:00.000',NULL,1423750392084172800,'fndBschiht3Bwo',0,0,0,'JPS','JPS','"email:user_b@example.com,email:user_c@example.com,tel:+1234567892,tel:+1234567893"');

/* user_b is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (3,'2025-08-01 00:17:00.000','2025-08-01 00:17:00.000',NULL,1423750392411328512,'usrlETobznmOWQ',0,0,0,'JPS','JPS','{"comment": "private comment about user_b"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (4,'2025-08-01 00:18:00.000','2025-08-01 00:18:00.000',NULL,1423750392411328512,'fndlETobznmOWQ',0,0,0,'JPS','JPS','"email:user_a@example.com,email:user_c@example.com,tel:+1234567891,tel:+1234567893"');

/* user_c is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (5,'2025-08-01 00:19:00.000','2025-08-01 00:19:00.000',NULL,1423750392679763968,'usrSPP3BlPhQzA',0,0,0,'JPS','JPS','{"comment": "private comment about user_c"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (6,'2025-08-01 00:20:00.000','2025-08-01 00:20:00.000',NULL,1423750392679763968,'fndSPP3BlPhQzA',0,0,0,'JPS','JPS','"email:user_a@example.com,email:user_b@example.com,tel:+1234567891,tel:+1234567892"');

/* user_a is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (7,'2025-08-01 00:21:00.000','2025-08-01 00:21:00.000',NULL,1423750392084172800,'grpT6Mt5tURQGg',0,22,22,'JRWPS','JRWPS','{"comment": ""}');

/* user_a and user_b are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (10,'2025-08-01 00:22:00.000','2025-08-01 00:22:00.000',NULL,1423750392084172800,'p2pBschiht3BwqUROhvOeY5ZA',0,17,17,'JRWPA','JRWPA','{"comment": "Private message between user_a and user_b"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (11,'2025-08-01 00:23:00.000','2025-08-01 00:23:00.000',NULL,1423750392411328512,'p2pBschiht3BwqUROhvOeY5ZA',0,19,19,'JRWPA','JRWPA','{"comment": "Private message between user_a and user_b"}');

/* user_a and user_c are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (12,'2025-08-01 00:24:00.000','2025-08-01 00:24:00.000',NULL,1423750392084172800,'p2pBschiht3BwpI8_cGU-FDMA',0,12,12,'JRWPA','JRWPA','{"comment": "Private message between user_a and user_c"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (13,'2025-08-01 00:25:00.000','2025-08-01 00:25:00.000',NULL,1423750392679763968,'p2pBschiht3BwpI8_cGU-FDMA',0,13,13,'JRWPA','JRWPA','{"comment": "Private message between user_a and user_c"}');

/* user_b and user_c are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (14,'2025-08-01 00:26:00.000','2025-08-01 00:26:00.000',NULL,1423750392411328512,'p2pSPP3BlPhQzCUROhvOeY5ZA',0,17,17,'JRWPA','JRWPA','{"comment": "Private message between user_b and user_c"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (15,'2025-08-01 00:27:00.000','2025-08-01 00:27:00.000',NULL,1423750392679763968,'p2pSPP3BlPhQzCUROhvOeY5ZA',0,19,19,'JRWPA','JRWPA','{"comment": "Private message between user_b and user_c"}');

/* user_b is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (17,'2025-08-01 00:28:00.000','2025-08-01 00:28:00.000',NULL,1423750392411328512,'grpT6Mt5tURQGg',0,21,21,'JRWPS','JRWPS','{"comment": "user_b is subscribed to Group Chat ABC"}');

/* user_c is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (18,'2025-08-01 00:29:00.000','2025-08-01 00:29:00.000',NULL,1423750392679763968,'grpT6Mt5tURQGg',0,19,19,'JRWPS','JRWPS','{"comment": "user_c is subscribed to Group Chat ABC"}');

/* user_b is subscribed to the Group Chat BC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (19,'2025-08-01 00:30:00.000','2025-08-01 00:30:00.000',NULL,1423750392411328512,'grpvpbyckgyGrQ',0,15,15,'JRWPS','JRWPS','{"comment": "user_b is subscribed to Group Chat BC"}');

/* user_c is subscribed to the Group Chat BC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (8,'2025-08-01 00:31:00.000','2025-08-01 00:31:00.000',NULL,1423750392679763968,'grpvpbyckgyGrQ',0,19,19,'JRWPS','JRWPS','{"comment": "user_c is subscribed to Group Chat BC"}');

/* user_c is subscribed to the Group Chat C topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (9,'2025-08-01 00:32:00.000','2025-08-01 00:32:00.000',NULL,1423750392679763968,'grpX2rL0ki6_B4',0,4,4,'JRWPS','JRWPS','{"comment": ""}');
/*!40000 ALTER TABLE `subscriptions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Fill the `messages` table (depends on topics table)
--

LOCK TABLES `messages` WRITE;
/*!40000 ALTER TABLE `messages` DISABLE KEYS */;
/* Message from user_a to Private chat between user_a and user_b: user_a says "hello from agent to user_b" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (1,'2025-08-01 00:00:00.000','2025-08-01 00:00:00.000',NULL,0,1,'p2pBschiht3BwqUROhvOeY5ZA',1423750392084172800,'null','"hello from agent to user_b"');
/* Message from user_b to Private chat between user_a and user_b: user_b says "hello from user_b to agent" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (2,'2025-08-01 00:01:02.100','2025-08-01 00:01:02.100',NULL,0,2,'p2pBschiht3BwqUROhvOeY5ZA',1423750392411328512,'null','"hello from user_b to agent"');
/* Message from user_a to Private chat between user_a and user_c: user_a says "hello from agent to user_c" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (3,'2025-08-01 00:02:04.200','2025-08-01 00:02:04.200',NULL,0,1,'p2pBschiht3BwpI8_cGU-FDMA',1423750392084172800,'null','"hello from agent to user_c"');
/* Message from user_c to Private chat between user_a and user_c: user_c says "hello from user_c to agent" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (4,'2025-08-01 00:03:06.300','2025-08-01 00:03:06.300',NULL,0,2,'p2pBschiht3BwpI8_cGU-FDMA',1423750392679763968,'null','"hello from user_c to agent"');
/* Message from user_b to Private chat between user_b and user_c: user_b says "bear to camel" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (5,'2025-08-01 00:04:08.400','2025-08-01 00:04:08.400',NULL,0,1,'p2pSPP3BlPhQzCUROhvOeY5ZA',1423750392411328512,'null','"bear to camel"');
/* Message from user_c to Private chat between user_b and user_c: user_c says "camel to bear" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (6,'2025-08-01 00:05:10.500','2025-08-01 00:05:10.500',NULL,0,2,'p2pSPP3BlPhQzCUROhvOeY5ZA',1423750392679763968,'null','"camel to bear"');
/* Message from user_a to Group Chat ABC: user_a says "hello from agent!" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (7,'2025-08-01 00:06:12.600','2025-08-01 00:06:12.600',NULL,0,1,'grpT6Mt5tURQGg',1423750392084172800,'null','"hello from agent!"');
/* Message from user_b to Group Chat ABC: user_b says "hello from user_b!" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (8,'2025-08-01 00:07:14.700','2025-08-01 00:07:14.700',NULL,0,2,'grpT6Mt5tURQGg',1423750392411328512,'null','"hello from user_b!"');
/* Message from user_c to Group Chat ABC: user_c says "hello from user_c!" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (9,'2025-08-01 00:08:16.800','2025-08-01 00:08:16.800',NULL,0,3,'grpT6Mt5tURQGg',1423750392679763968,'null','"hello from user_c!"');
/* Message from user_b to Group Chat BC: user_b says "hello from bear to group chat bc" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (10,'2025-08-01 00:09:18.900','2025-08-01 00:09:18.900',NULL,0,1,'grpvpbyckgyGrQ',1423750392411328512,'null','"hello from bear to group chat bc"');
/* Message from user_c to Group Chat BC: user_c says "hello from camel to group chat bc" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (11,'2025-08-01 00:10:20.000','2025-08-01 00:10:20.000',NULL,0,2,'grpvpbyckgyGrQ',1423750392679763968,'null','"hello from camel to group chat bc"');
/* Message from user_c to Group Chat C: user_c says "hello from camel to group chat c" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (12,'2025-08-01 00:11:22.100','2025-08-01 00:11:22.100',NULL,0,1,'grpX2rL0ki6_B4',1423750392679763968,'null','"hello from camel to group chat c"');
/*!40000 ALTER TABLE `messages` ENABLE KEYS */;
UNLOCK TABLES;

--
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


def write_flat_secrets_json():
    """
    Write user data as flat keys to secrets.json using shared utilities.

    This function creates a flat key-value structure instead of nested objects:
    - User data: user_b_user_id, user_b_password, user_b_password_hash (for user_b and user_c only)
    - Message data: message_in_<chat_name>_from_<user> format

    This flat structure is compatible with shared utilities and simplifies test access patterns.
    Uses USER_DATA and MESSAGES constants directly. Only writes user_b's and user_c's secrets.
    """
    # Create flat secrets structure
    flat_secrets = {}

    # Iterate over USER_DATA dictionary values
    for user_key, user_data in USER_DATA.items():
        if user_data["username"] == "user_a":
            continue  # skip writing user_a to secrets.json

        flat_secrets[f"{user_data['username']}_user_id"] = user_data["id"]
        flat_secrets[f"{user_data['username']}_password"] = user_data["password"]
        flat_secrets[f"{user_data['username']}_password_hash"] = user_data[
            "password_hash"
        ]

    # Add messages from MESSAGES constant
    for chat_name in MESSAGES:
        members = chat_name.split(":")[1]
        if "a" in members:  # skip writing messages from conversations that user_a is in
            continue
        for msg in MESSAGES[chat_name]:
            flat_secrets[f"message_in_{chat_name}_from_{msg['from']}"] = msg["content"]

    # Add metadata
    flat_secrets["generated_at"] = datetime.now().isoformat()

    # Use shared utility to write JSON
    write_secrets_json(flat_secrets, ".")

    print("Flat user data and messages saved to secrets.json")


def main():
    """Main function to generate passwords and SQL files."""
    print(
        "Generating file to seed MySQL database with fixed USER_DATA and MESSAGES from constants..."
    )

    # Write secrets to JSON file
    write_flat_secrets_json()

    # Write SQL file
    print("\nGenerating seed_db.sql...")
    with open("seed_db.sql", "w") as f:
        f.write(SEED_SQL)

    print("seed_db.sql generated successfully!")
    print("\nFiles created:")
    print(
        "- secrets.json (contains flat key-value pairs for user data, passwords, and fixed messages)"
    )
    print(
        "- seed_db.sql (contains all SQL insert commands with verified users and fixed messages)"
    )


if __name__ == "__main__":
    main()
