-- seed.sql

-- 1. Insert/update users
UPDATE public.users
SET password = '$2b$12$5C9PP9rKxy9pChRGU53KB.85.4Nr3TRggSKxh2GJPDB27bB09IX7u'
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
'$2b$12$Sa6Qh2zEevX41RvQXrJ4fOMhVsKzi4L80he6pXQFaVB1UtXsCsHbe',
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
('notebook-6697',
'Notebook on the Galapagos penguins',
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
('notebook-8589',
'Notebook on Mesopotamian Art',
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
('notebook-5391',
'Notebook on the Decapterus fish',
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

-- Map the notebook to the user in user_items
INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('111',
'userB',
'notebook-6697',
3000,
3000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('100',
'userB',
'notebook-8589',
3000,
3000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('101',
'userB',
'notebook-5391',
3000,
3000);

-- 3. Insert a new note
INSERT INTO public.items
(id, name, mime_type, updated_time, created_time, content, content_size,
 jop_id, jop_parent_id, jop_share_id, jop_type, jop_encryption_applied,
 jop_updated_time, owner_id, content_storage_id)
VALUES 
('note-8726',
'Cool facts about Galapagos penguins',
'text/plain',
4000,
4000,
convert_to('The Galapagos penguins are the only penguin species that live north of the equator', 'UTF8'),
octet_length(convert_to('The Galapagos penguins are the only penguin species that live north of the equator', 'UTF8')),
'',
'notebook-6697',
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
('note-8241',
'Cool stats about Galapagos penguins',
'text/plain',
4000,
4000,
convert_to('As of 2025, the Galapagos penguin population is only around 2000-3000', 'UTF8'),
octet_length(convert_to('As of 2025, the Galapagos penguin population is only around 2000-3000', 'UTF8')),
'',
'notebook-6697',
'',
0,
0,
0,
'userB',
1
);


-- Map the note to the user in user_items
INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('222',
'userB',
'note-8726',
5000,
5000);

INSERT INTO public.user_items
(id, user_id, item_id, updated_time, created_time)
VALUES
('333',
'userB',
'note-8241',
5000,
5000);

-- End of seed.sql
