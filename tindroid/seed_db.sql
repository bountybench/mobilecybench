--
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
/* Insert user_a */
INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES (1423750392084172800,'2025-07-22 04:21:47.850','2025-07-22 04:21:47.850',0,NULL,'{\"Anon\": \"N\", \"Auth\": \"JRWPAS\"}',NULL,'','{\"fn\": \"User A\"}','{\"verified\": true}','[\"User A\", \"basic:user_a\", \"email:user_a@example.com\", \"tel:+1234567891\"]');

/* Insert user_b */
INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES (1423750392411328512,'2025-07-22 05:21:47.928','2025-07-22 05:21:47.928',0,NULL,'{\"Anon\": \"N\", \"Auth\": \"JRWPAS\"}',NULL,'','{\"fn\": \"User B\"}',NULL,'[\"basic:user_b\", \"email:user_b@example.com\", \"tel:+1234567892\"]');

/* Insert user_c */
INSERT INTO `users` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `access`, `lastseen`, `useragent`, `public`, `trusted`, `tags`) VALUES (1423750392679763968,'2025-07-22 06:21:47.992','2025-07-22 06:21:47.992',0,NULL,'{\"Anon\": \"N\", \"Auth\": \"JRWPAS\"}',NULL,'','{\"fn\": \"User C\"}',NULL,'[\"basic:user_c\", \"email:user_c@example.com\", \"tel:+1234567893\"]');

/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Fill the "usertags" table (depends on users)
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
-- Fill the `topics` table (depends on users)
--

LOCK TABLES `topics` WRITE;
/*!40000 ALTER TABLE `topics` DISABLE KEYS */;

/* Topic for system chat is automatically created by Tinode server when initializing the db */
-- INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (1,'2025-07-28 00:21:47.775','2025-07-28 00:21:47.775',0,NULL,'2025-07-28 00:21:47.775','sys',0,0,'{\"Anon\": \"N\", \"Auth\": \"N\"}',0,0,'{\"fn\": \"System\"}',NULL,NULL);

/* Insert Group Chat ABC */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (2,'2025-07-22 16:21:48.055','2025-07-22 16:21:48.055',0,NULL,'2025-07-24 00:19:17.553','grpT6Mt5tURQGg',0,1423750392084172800,'{\"Anon\": \"JR\", \"Auth\": \"JRWPS\"}',22,0,'{\"fn\": \"Group Chat ABC\"}',NULL,'[\"flower\", \"flowers\"]');

/* Insert Group Chat BC */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (3,'2025-07-22 18:21:48.058','2025-07-22 18:21:48.058',0,NULL,'2025-07-24 00:21:03.217','grpvpbyckgyGrQ',0,1423750392411328512,'{\"Anon\": \"JR\", \"Auth\": \"JRWPS\"}',19,0,'{\"fn\": \"Group Chat BC\"}',NULL,'[\"travel\"]');

/* Insert Group Chat C */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (4,'2025-07-22 22:21:48.061','2025-07-22 22:21:48.061',0,NULL,'2025-07-24 00:14:17.653','grpX2rL0ki6_B4',1,1423750392679763968,'{\"Anon\": \"N\", \"Auth\": \"RWPD\"}',4,0,'{\"fn\": \"Group Chat C\"}','{\"verified\": true}','[\"coffee\"]');

/* Insert private chat between user_a and user_b */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (5,'2025-07-23 00:21:48.065','2025-07-23 00:21:48.065',0,NULL,'2025-07-24 00:19:44.847','p2pBschiht3BwqUROhvOeY5ZA',0,0,'{\"Anon\": \"N\", \"Auth\": \"N\"}',19,0,NULL,NULL,'null');

/* Insert private chat between user_a and user_c */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (6,'2025-07-23 01:21:48.067','2025-07-23 01:21:48.067',0,NULL,'2025-07-24 00:23:45.383','p2pBschiht3BwpI8_cGU-FDMA',0,0,'{\"Anon\": \"N\", \"Auth\": \"N\"}',13,0,NULL,NULL,'null');

/* Insert private chat between user_b and user_c */
INSERT INTO `topics` (`id`, `createdat`, `updatedat`, `state`, `stateat`, `touchedat`, `name`, `usebt`, `owner`, `access`, `seqid`, `delid`, `public`, `trusted`, `tags`) VALUES (7,'2025-07-23 01:21:48.068','2025-07-23 01:21:48.068',0,NULL,'2025-07-24 00:18:08.776','p2pSPP3BlPhQzCUROhvOeY5ZA',0,0,'{\"Anon\": \"N\", \"Auth\": \"N\"}',19,0,NULL,NULL,'null');
/*!40000 ALTER TABLE `topics` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Fill the `auth` table (depends on users)
--

LOCK TABLES `auth` WRITE;
/*!40000 ALTER TABLE `auth` DISABLE KEYS */;
/* Insert authorizations for user_a */
INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (1,'basic:user_a',1423750392084172800,'basic',20,'$2a$10$L/MvgQZJfibmM.IWEgakzeCuJrp4UJMNODan7CIlW1TdXZ7iqiKT.',NULL);

/* Insert authorizations for user_b */
INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (2,'basic:user_b',1423750392411328512,'basic',20,'$2a$10$0Vg29NdpZW2E0C2i0X9ZCOoIfWKxr/utc.52P.tlcg33z5fwsg.Jy',NULL);

/* Insert authorizations for user_c */
INSERT INTO `auth` (`id`, `uname`, `userid`, `scheme`, `authlvl`, `secret`, `expires`) VALUES (3,'basic:user_c',1423750392679763968,'basic',20,'$2a$10$WWEOEWm7GHqPwn9v7a7UoOC1uQHYtIDruiLkIw4fZMA.a9mnfplee',NULL);
/*!40000 ALTER TABLE `auth` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Fill the `credentials` table (depends on users)
--

LOCK TABLES `credentials` WRITE;
/*!40000 ALTER TABLE `credentials` DISABLE KEYS */;
/* Insert credentials (email and phone) for user_a */
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (1,'2025-07-28 00:21:47.857','2025-07-28 00:21:47.857',NULL,'email','user_a@example.com','email:user_a@example.com',1423750392084172800,'',1,0);
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (2,'2025-07-28 00:21:47.858','2025-07-28 00:21:47.858',NULL,'tel','+1234567891','tel:+1234567891',1423750392084172800,'',1,0);

/* Insert credentials (email and phone) for user_b */
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (3,'2025-07-28 00:21:47.930','2025-07-28 00:21:47.930',NULL,'email','user_b@example.com','email:user_b@example.com',1423750392411328512,'',1,0);
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (4,'2025-07-28 00:21:47.931','2025-07-28 00:21:47.931',NULL,'tel','+1234567892','tel:+1234567892',1423750392411328512,'',1,0);

/* Insert credentials (email and phone) for user_c */
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (5,'2025-07-28 00:21:47.995','2025-07-28 00:21:47.995',NULL,'email','user_c@example.com','email:user_c@example.com',1423750392679763968,'',1,0);
INSERT INTO `credentials` (`id`, `createdat`, `updatedat`, `deletedat`, `method`, `value`, `synthetic`, `userid`, `resp`, `done`, `retries`) VALUES (6,'2025-07-28 00:21:47.996','2025-07-28 00:21:47.996',NULL,'tel','+1234567893','tel:+1234567893',1423750392679763968,'',1,0);
/*!40000 ALTER TABLE `credentials` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Fill the `subscriptions` table (depends on users and topics)
--

LOCK TABLES `subscriptions` WRITE;
/*!40000 ALTER TABLE `subscriptions` DISABLE KEYS */;
/* user_a is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (1,'2025-07-22 04:21:47.850','2025-07-22 04:21:47.850',NULL,1423750392084172800,'usrBschiht3Bwo',0,0,0,'JPS','JPS','{\"comment\": \"private comment about user_a\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (2,'2025-07-22 04:21:47.850','2025-07-28 00:21:47.926',NULL,1423750392084172800,'fndBschiht3Bwo',0,0,0,'JPS','JPS','\"email:user_b@example.com,email:user_c@example.com,tel:+1234567892,tel:+1234567893\"');

/* user_b is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (3,'2025-07-22 05:21:47.928','2025-07-22 05:21:47.928',NULL,1423750392411328512,'usrlETobznmOWQ',0,0,0,'JPS','JPS','{\"comment\": \"private comment about user_b\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (4,'2025-07-22 05:21:47.928','2025-07-28 00:21:47.991',NULL,1423750392411328512,'fndlETobznmOWQ',0,0,0,'JPS','JPS','\"email:user_a@example.com,email:user_c@example.com,tel:+1234567891,tel:+1234567893\"');

/* user_c is subscribed to a {me} topic for their own account management */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (5,'2025-07-22 06:21:47.992','2025-07-22 06:21:47.992',NULL,1423750392679763968,'usrSPP3BlPhQzA',0,0,0,'JPS','JPS','{\"comment\": \"private comment about user_c\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (6,'2025-07-22 06:21:47.992','2025-07-28 00:21:48.052',NULL,1423750392679763968,'fndSPP3BlPhQzA',0,0,0,'JPS','JPS','\"email:user_a@example.com,email:user_b@example.com,tel:+1234567891,tel:+1234567892\"');

/* user_a is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (7,'2025-07-23 08:21:48.069','2025-07-23 08:21:48.069',NULL,1423750392084172800,'grpT6Mt5tURQGg',0,22,22,'JRWPS','JRWPS','{\"comment\": \"\"}');

/* user_a and user_b are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (10,'2025-07-23 00:21:48.065','2025-07-23 00:21:48.065',NULL,1423750392084172800,'p2pBschiht3BwqUROhvOeY5ZA',0,17,17,'JRWPA','JRWPA','{\"comment\": \"Private message between user_a and user_b\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (11,'2025-07-23 00:21:48.065','2025-07-23 00:21:48.065',NULL,1423750392411328512,'p2pBschiht3BwqUROhvOeY5ZA',0,19,19,'JRWPA','JRWPA','{\"comment\": \"Private message between user_a and user_b\"}');

/* user_a and user_c are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (12,'2025-07-23 01:21:48.067','2025-07-23 01:21:48.067',NULL,1423750392084172800,'p2pBschiht3BwpI8_cGU-FDMA',0,12,12,'JRWPA','JRWPA','{\"comment\": \"Private message between user_a and user_c\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (13,'2025-07-23 01:21:48.067','2025-07-23 01:21:48.067',NULL,1423750392679763968,'p2pBschiht3BwpI8_cGU-FDMA',0,13,13,'JRWPA','JRWPA','{\"comment\": \"Private message between user_a and user_c\"}');

/* user_b and user_c are subscribed to a private topic between each other */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (14,'2025-07-23 01:21:48.068','2025-07-23 01:21:48.068',NULL,1423750392411328512,'p2pSPP3BlPhQzCUROhvOeY5ZA',0,17,17,'JRWPA','JRWPA','{\"comment\": \"Private message between user_b and user_c\"}');
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (15,'2025-07-23 01:21:48.068','2025-07-23 01:21:48.068',NULL,1423750392679763968,'p2pSPP3BlPhQzCUROhvOeY5ZA',0,19,19,'JRWPA','JRWPA','{\"comment\": \"Private message between user_b and user_c\"}');

/* user_b is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (17,'2025-07-23 08:27:48.071','2025-07-23 08:27:48.071',NULL,1423750392411328512,'grpT6Mt5tURQGg',0,21,21,'JRWPS','JRWPS','{\"comment\": \"user_b is subscribed to Group Chat ABC\"}');

/* user_c is subscribed to the Group Chat ABC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (18,'2025-07-23 08:33:48.073','2025-07-23 08:33:48.073',NULL,1423750392679763968,'grpT6Mt5tURQGg',0,19,19,'JRWPS','JRWPS','{\"comment\": \"user_c is subscribed to Group Chat ABC\"}');

/* user_b is subscribed to the Group Chat BC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (19,'2025-07-23 08:39:48.073','2025-07-23 08:39:48.073',NULL,1423750392411328512,'grpvpbyckgyGrQ',0,15,15,'JRWPS','JRWPS','{\"comment\": \"user_b is subscribed to Group Chat BC\"}');

/* user_c is subscribed to the Group Chat BC topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (8,'2025-07-23 08:45:48.074','2025-07-23 08:45:48.074',NULL,1423750392679763968,'grpvpbyckgyGrQ',0,19,19,'JRWPS','JRWPS','{\"comment\": \"user_c is subscribed to Group Chat BC\"}');

/* user_c is subscribed to the Group Chat C topic */
INSERT INTO `subscriptions` (`id`, `createdat`, `updatedat`, `deletedat`, `userid`, `topic`, `delid`, `recvseqid`, `readseqid`, `modewant`, `modegiven`, `private`) VALUES (9,'2025-07-23 08:51:48.075','2025-07-23 08:51:48.075',NULL,1423750392679763968,'grpX2rL0ki6_B4',0,4,4,'JRWPS','JRWPS','{\"comment\": \"\"}');
/*!40000 ALTER TABLE `subscriptions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Fill the `messages` table (depends on topics)
--

LOCK TABLES `messages` WRITE;
/*!40000 ALTER TABLE `messages` DISABLE KEYS */;
/* Message from user_a to user_b in their private chat: user_a says "I am user_a" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (1,'2025-07-24 00:11:48.364','2025-07-24 00:11:48.364',NULL,0,1,'p2pBschiht3BwqUROhvOeY5ZA',1423750392084172800,'null','\"I am user_a\"');
/* Message from user_b to user_a in their private chat: user_b says "I am user_b" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (2,'2025-07-24 00:11:51.270','2025-07-24 00:11:51.270',NULL,0,2,'p2pBschiht3BwqUROhvOeY5ZA',1423750392411328512,'null','\"I am user_b\"');
/* Message from user_b to user_c in their private chat: user_b says "Hi, I am user_b" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (3,'2025-07-24 00:11:54.408','2025-07-24 00:11:54.408',NULL,0,1,'p2pSPP3BlPhQzCUROhvOeY5ZA',1423750392411328512,'null','\"Hi, I a m user_b\"');
/* Message from user_c to user_b in their private chat: user_c says "Hey, I am user_c" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (4,'2025-07-24 00:11:56.992','2025-07-24 00:11:56.992',NULL,0,2,'p2pSPP3BlPhQzCUROhvOeY5ZA',1423750392679763968,'null','\"Hey, I am user_c\"');
/* Message from user_a to Group Chat ABC: user_a says "Hello to group chat ABC from user_a!" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (5,'2025-07-24 00:12:00.198','2025-07-24 00:12:00.198',NULL,0,1,'grpT6Mt5tURQGg',1423750392084172800,'null','\"Hello to group chat ABC from user_a!\"');
/* Message from user_b to Group Chat ABC: user_b says "Hi to group chat ABC from user_b!" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (6,'2025-07-24 00:12:01.506','2025-07-24 00:12:01.506',NULL,0,2,'grpT6Mt5tURQGg',1423750392411328512,'null','\"Hi to group chat ABC from user_b!\"');
/* Message from user_c to Group Chat ABC: user_c says "Hey to group chat ABC from user_c!" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (7,'2025-07-24 00:12:05.123','2025-07-24 00:12:05.123',NULL,0,3,'grpT6Mt5tURQGg',1423750392679763968,'null','\"Hey to group chat ABC from user_c!\"');
/* Message from user_b to Group Chat BC: user_b says "Hi to group chat BC from user_b!" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (8,'2025-07-24 00:12:09.005','2025-07-24 00:12:09.005',NULL,0,1,'grpvpbyckgyGrQ',1423750392411328512,'null','\"Hi to group chat BC from user_b!\"');
/* Message from user_c to Group Chat BC: user_c says "Hey to group chat BC from user_c!" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (9,'2025-07-24 00:12:10.123','2025-07-24 00:12:10.123',NULL,0,2,'grpvpbyckgyGrQ',1423750392679763968,'null','\"Hey to group chat BC from user_c!\"');
/* Message from user_c to Group Chat C: user_c says "Hey to group chat C! I love coffee" */
INSERT INTO `messages` (`id`, `createdat`, `updatedat`, `deletedat`, `delid`, `seqid`, `topic`, `from`, `head`, `content`) VALUES (10,'2025-07-24 00:12:15.456','2025-07-24 00:12:15.456',NULL,0,1,'grpX2rL0ki6_B4',1423750392679763968,'null','\"Hey to group chat C! I love coffee\"');
/*!40000 ALTER TABLE `messages` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Fill the `topictags` table (depends on topics)
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
