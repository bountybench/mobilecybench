-- seed.sql

\i secrets.sql

-- 1. Insert/update users
UPDATE public.users
SET password = :admin_password_hash
WHERE email = 'admin@localhost';

INSERT INTO public.users
(id, email, password, full_name, is_admin, updated_time, created_time, email_confirmed, must_set_password, account_type, can_upload, max_item_size, can_share_folder, can_share_note, max_total_item_size, total_item_size, enabled, disabled_time, can_receive_folder)
VALUES
('userA',
'usera@localhost',
'$2b$12$A2KDsIx5zwqR/YlNdrZUF.NacuBvghvWaXpV.DLPw8x5BSectAIdK',
'userA',
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

INSERT INTO public.users
(id, email, password, full_name, is_admin, updated_time, created_time, email_confirmed, must_set_password, account_type, can_upload, max_item_size, can_share_folder, can_share_note, max_total_item_size, total_item_size, enabled, disabled_time, can_receive_folder)
VALUES
('userB',
'userb@localhost',
:userb_password_hash,
'userB',
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
(:notebook1_id,
:notebook1_name,
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
(:notebook2_id,
:notebook2_name,
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
(:notebook3_id,
:notebook3_name,
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
(:notebook4_id,
:notebook4_name,
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
(SELECT id FROM public.users WHERE email = 'admin@localhost'),
 1);

-- Map the notebook to the user in user_items
INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('111',
'userB',
:notebook1_id,
3000,
3000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('100',
'userB',
:notebook2_id,
3000,
3000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('101',
'userB',
:notebook3_id,
3000,
3000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('110',
(SELECT id FROM public.users WHERE email = 'admin@localhost'),
:notebook4_id,
3000,
3000);

-- 3. Insert a new note
INSERT INTO public.items
(id, name, mime_type, updated_time, created_time, content, content_size,
 jop_id, jop_parent_id, jop_share_id, jop_type, jop_encryption_applied,
 jop_updated_time, owner_id, content_storage_id)
VALUES 
(:note1_id,
:note1_name,
'text/plain',
4000,
4000,
convert_to(:note1_content, 'UTF8'),
octet_length(convert_to(:note1_content, 'UTF8')),
'',
:notebook1_id,
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
(:note2_id,
:note2_name,
'text/plain',
4000,
4000,
convert_to(:note2_content, 'UTF8'),
octet_length(convert_to(:note2_content, 'UTF8')),
'',
:notebook1_id,
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
(:note3_id,
:note3_name,
'text/plain',
4000,
4000,
convert_to(:note3_content, 'UTF8'),
octet_length(convert_to(:note3_content, 'UTF8')),
'',
:notebook4_id,
'',
0,
0,
0,
(SELECT id FROM public.users WHERE email = 'admin@localhost'),
1
);

-- Map the note to the user in user_items
INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('222',
'userB',
:note1_id,
5000,
5000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('333',
'userB',
:note2_id,
5000,
5000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('999',
(SELECT id FROM public.users WHERE email = 'admin@localhost'),
:note3_id,
5000,
5000);

-- End of seed.sql
