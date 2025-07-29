-- seed.sql

-- 1. Insert/update users
UPDATE public.users
SET password = '$2b$12$PyTm2sr4xLpOtgk2KYSOdek6bAIIdJEVd/SRo2qGZq.JhaF5RgUAa'
WHERE email = 'admin@localhost';

UPDATE public.users
SET password = '2b$12$GFeZgYXgnFhPoEr7nTBLFuuttObm4yhS09VxHimYau6wSfoqiCa0G'
WHERE email = 'userb@localhost';

UPDATE public.users
SET is_admin = 1
WHERE email = 'usera@localhost';

INSERT INTO public.users
(id, email, password, full_name, is_admin, updated_time, created_time, email_confirmed, must_set_password, account_type, can_upload, max_item_size, can_share_folder, can_share_note, max_total_item_size, total_item_size, enabled, disabled_time, can_receive_folder)
VALUES
('bob',
'bob@localhost',
'$2b$12$uXKuxW6r0Xk3h1qQZu77ZeRRGB1CWtms7mi/D8JEBTI.6ubykGMU2',
'bob',
0,
8000,
8000,
0,
0,
0,
1,
0,
1,
0,
0,
0,
1,
0,
0); 


-- 2. Insert a new notebook 
INSERT INTO public.items
(id, name, mime_type, updated_time, created_time, content, content_size,
 jop_id, jop_parent_id, jop_share_id, jop_type, jop_encryption_applied,
 jop_updated_time, owner_id, content_storage_id)
VALUES
(645722,
'userB-Added-Test-Notebook',
'application/octet-stream',
2000,
2000,
'\x',
0,
'',
'',
'',
1,
0,
0,
'userB',
 1);

   INSERT INTO public.items
(id, name, mime_type, updated_time, created_time, content, content_size,
 jop_id, jop_parent_id, jop_share_id, jop_type, jop_encryption_applied,
 jop_updated_time, owner_id, content_storage_id)
VALUES
(202949,
'bob-Added-Test-Notebook',
'application/octet-stream',
7000,
7000,
'\x',
0,
'',
'',
'',
1,
0,
0,
'bob',
 1);

-- Map the notebook to the user in user_items
INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
(688626,
'userB',
645722,
3000,
3000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
(811225,
'bob',
202949,
3000,
3000);

-- 3. Insert a new note

INSERT INTO public.items
(id, name, mime_type, updated_time, created_time, content, content_size,
 jop_id, jop_parent_id, jop_share_id, jop_type, jop_encryption_applied,
 jop_updated_time, owner_id, content_storage_id)
VALUES 
(096453,
'userB-Added-Test-Note-2',
'text/plain',
4000,
4000,
convert_to('This is a test note.', 'UTF8'),
octet_length(convert_to('This is a test note.', 'UTF8')),
'',
645722,
'',
0,
0,
0,
'userB',
1
);

INSERT INTO public.items
(id, name, mime_type, updated_time, created_time, content, content_size,
 jop_id, jop_parent_id, jop_share_id, jop_type, jop_encryption_applied,
 jop_updated_time, owner_id, content_storage_id)
VALUES 
(649559,
'bob-Added-Test-Note',
'text/plain',
4000,
4000,
convert_to('This is a test note.', 'UTF8'),
octet_length(convert_to('This is a test note.', 'UTF8')),
'',
202949,
'',
0,
0,
0,
'bob',
1
);

-- Map the note to the user in user_items
INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
(064319,
'userB',
096453,
5000,
5000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
(047991,
'bob',
649559,
5000,
5000);

-- End of seed.sql
