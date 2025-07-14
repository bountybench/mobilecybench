--
-- PostgreSQL database dump
--

-- Dumped from database version 14.18 (Debian 14.18-1.pgdg120+1)
-- Dumped by pg_dump version 14.18 (Debian 14.18-1.pgdg120+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: __diesel_schema_migrations; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.__diesel_schema_migrations (
    version character varying(50) NOT NULL,
    run_on timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.__diesel_schema_migrations OWNER TO bitwarden;

--
-- Name: attachments; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.attachments (
    id text NOT NULL,
    cipher_uuid character varying(40) NOT NULL,
    file_name text NOT NULL,
    file_size bigint NOT NULL,
    akey text
);


ALTER TABLE public.attachments OWNER TO bitwarden;

--
-- Name: auth_requests; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.auth_requests (
    uuid character(36) NOT NULL,
    user_uuid character(36) NOT NULL,
    organization_uuid character(36),
    request_device_identifier character(36) NOT NULL,
    device_type integer NOT NULL,
    request_ip text NOT NULL,
    response_device_id character(36),
    access_code text NOT NULL,
    public_key text NOT NULL,
    enc_key text,
    master_password_hash text,
    approved boolean,
    creation_date timestamp without time zone NOT NULL,
    response_date timestamp without time zone,
    authentication_date timestamp without time zone
);


ALTER TABLE public.auth_requests OWNER TO bitwarden;

--
-- Name: ciphers; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.ciphers (
    uuid character varying(40) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    user_uuid character varying(40),
    organization_uuid character varying(40),
    atype integer NOT NULL,
    name text NOT NULL,
    notes text,
    fields text,
    data text NOT NULL,
    password_history text,
    deleted_at timestamp without time zone,
    reprompt integer,
    key text
);


ALTER TABLE public.ciphers OWNER TO bitwarden;

--
-- Name: ciphers_collections; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.ciphers_collections (
    cipher_uuid character varying(40) NOT NULL,
    collection_uuid character varying(40) NOT NULL
);


ALTER TABLE public.ciphers_collections OWNER TO bitwarden;

--
-- Name: collections; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.collections (
    uuid character varying(40) NOT NULL,
    org_uuid character varying(40) NOT NULL,
    name text NOT NULL,
    external_id text
);


ALTER TABLE public.collections OWNER TO bitwarden;

--
-- Name: collections_groups; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.collections_groups (
    collections_uuid character varying(40) NOT NULL,
    groups_uuid character(36) NOT NULL,
    read_only boolean NOT NULL,
    hide_passwords boolean NOT NULL,
    manage boolean DEFAULT false NOT NULL
);


ALTER TABLE public.collections_groups OWNER TO bitwarden;

--
-- Name: devices; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.devices (
    uuid character varying(40) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    user_uuid character varying(40) NOT NULL,
    name text NOT NULL,
    atype integer NOT NULL,
    push_token text,
    refresh_token text NOT NULL,
    twofactor_remember text,
    push_uuid text
);


ALTER TABLE public.devices OWNER TO bitwarden;

--
-- Name: emergency_access; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.emergency_access (
    uuid character(36) NOT NULL,
    grantor_uuid character(36),
    grantee_uuid character(36),
    email character varying(255),
    key_encrypted text,
    atype integer NOT NULL,
    status integer NOT NULL,
    wait_time_days integer NOT NULL,
    recovery_initiated_at timestamp without time zone,
    last_notification_at timestamp without time zone,
    updated_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.emergency_access OWNER TO bitwarden;

--
-- Name: event; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.event (
    uuid character(36) NOT NULL,
    event_type integer NOT NULL,
    user_uuid character(36),
    org_uuid character(36),
    cipher_uuid character(36),
    collection_uuid character(36),
    group_uuid character(36),
    org_user_uuid character(36),
    act_user_uuid character(36),
    device_type integer,
    ip_address text,
    event_date timestamp without time zone NOT NULL,
    policy_uuid character(36),
    provider_uuid character(36),
    provider_user_uuid character(36),
    provider_org_uuid character(36)
);


ALTER TABLE public.event OWNER TO bitwarden;

--
-- Name: favorites; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.favorites (
    user_uuid character varying(40) NOT NULL,
    cipher_uuid character varying(40) NOT NULL
);


ALTER TABLE public.favorites OWNER TO bitwarden;

--
-- Name: folders; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.folders (
    uuid character varying(40) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    user_uuid character varying(40) NOT NULL,
    name text NOT NULL
);


ALTER TABLE public.folders OWNER TO bitwarden;

--
-- Name: folders_ciphers; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.folders_ciphers (
    cipher_uuid character varying(40) NOT NULL,
    folder_uuid character varying(40) NOT NULL
);


ALTER TABLE public.folders_ciphers OWNER TO bitwarden;

--
-- Name: groups; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.groups (
    uuid character(36) NOT NULL,
    organizations_uuid character varying(40) NOT NULL,
    name character varying(100) NOT NULL,
    access_all boolean NOT NULL,
    external_id character varying(300),
    creation_date timestamp without time zone NOT NULL,
    revision_date timestamp without time zone NOT NULL
);


ALTER TABLE public.groups OWNER TO bitwarden;

--
-- Name: groups_users; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.groups_users (
    groups_uuid character(36) NOT NULL,
    users_organizations_uuid character varying(36) NOT NULL
);


ALTER TABLE public.groups_users OWNER TO bitwarden;

--
-- Name: invitations; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.invitations (
    email text NOT NULL
);


ALTER TABLE public.invitations OWNER TO bitwarden;

--
-- Name: org_policies; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.org_policies (
    uuid character(36) NOT NULL,
    org_uuid character(36) NOT NULL,
    atype integer NOT NULL,
    enabled boolean NOT NULL,
    data text NOT NULL
);


ALTER TABLE public.org_policies OWNER TO bitwarden;

--
-- Name: organization_api_key; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.organization_api_key (
    uuid character(36) NOT NULL,
    org_uuid character(36) NOT NULL,
    atype integer NOT NULL,
    api_key character varying(255),
    revision_date timestamp without time zone NOT NULL
);


ALTER TABLE public.organization_api_key OWNER TO bitwarden;

--
-- Name: organizations; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.organizations (
    uuid character varying(40) NOT NULL,
    name text NOT NULL,
    billing_email text NOT NULL,
    private_key text,
    public_key text
);


ALTER TABLE public.organizations OWNER TO bitwarden;

--
-- Name: sends; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.sends (
    uuid character(36) NOT NULL,
    user_uuid character(36),
    organization_uuid character(36),
    name text NOT NULL,
    notes text,
    atype integer NOT NULL,
    data text NOT NULL,
    akey text NOT NULL,
    password_hash bytea,
    password_salt bytea,
    password_iter integer,
    max_access_count integer,
    access_count integer NOT NULL,
    creation_date timestamp without time zone NOT NULL,
    revision_date timestamp without time zone NOT NULL,
    expiration_date timestamp without time zone,
    deletion_date timestamp without time zone NOT NULL,
    disabled boolean NOT NULL,
    hide_email boolean
);


ALTER TABLE public.sends OWNER TO bitwarden;

--
-- Name: twofactor; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.twofactor (
    uuid character varying(40) NOT NULL,
    user_uuid character varying(40) NOT NULL,
    atype integer NOT NULL,
    enabled boolean NOT NULL,
    data text NOT NULL,
    last_used bigint DEFAULT 0 NOT NULL
);


ALTER TABLE public.twofactor OWNER TO bitwarden;

--
-- Name: twofactor_duo_ctx; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.twofactor_duo_ctx (
    state character varying(64) NOT NULL,
    user_email character varying(255) NOT NULL,
    nonce character varying(64) NOT NULL,
    exp bigint NOT NULL
);


ALTER TABLE public.twofactor_duo_ctx OWNER TO bitwarden;

--
-- Name: twofactor_incomplete; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.twofactor_incomplete (
    user_uuid character varying(40) NOT NULL,
    device_uuid character varying(40) NOT NULL,
    device_name text NOT NULL,
    login_time timestamp without time zone NOT NULL,
    ip_address text NOT NULL,
    device_type integer DEFAULT 14 NOT NULL
);


ALTER TABLE public.twofactor_incomplete OWNER TO bitwarden;

--
-- Name: users; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.users (
    uuid character varying(40) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    email text NOT NULL,
    name text NOT NULL,
    password_hash bytea NOT NULL,
    salt bytea NOT NULL,
    password_iterations integer NOT NULL,
    password_hint text,
    akey text NOT NULL,
    private_key text,
    public_key text,
    totp_secret text,
    totp_recover text,
    security_stamp text NOT NULL,
    equivalent_domains text NOT NULL,
    excluded_globals text NOT NULL,
    client_kdf_type integer DEFAULT 0 NOT NULL,
    client_kdf_iter integer DEFAULT 100000 NOT NULL,
    verified_at timestamp without time zone,
    last_verifying_at timestamp without time zone,
    login_verify_count integer DEFAULT 0 NOT NULL,
    email_new character varying(255) DEFAULT NULL::character varying,
    email_new_token character varying(16) DEFAULT NULL::character varying,
    enabled boolean DEFAULT true NOT NULL,
    stamp_exception text,
    api_key text,
    avatar_color text,
    client_kdf_memory integer,
    client_kdf_parallelism integer,
    external_id text
);


ALTER TABLE public.users OWNER TO bitwarden;

--
-- Name: users_collections; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.users_collections (
    user_uuid character varying(40) NOT NULL,
    collection_uuid character varying(40) NOT NULL,
    read_only boolean DEFAULT false NOT NULL,
    hide_passwords boolean DEFAULT false NOT NULL,
    manage boolean DEFAULT false NOT NULL
);


ALTER TABLE public.users_collections OWNER TO bitwarden;

--
-- Name: users_organizations; Type: TABLE; Schema: public; Owner: bitwarden
--

CREATE TABLE public.users_organizations (
    uuid character varying(40) NOT NULL,
    user_uuid character varying(40) NOT NULL,
    org_uuid character varying(40) NOT NULL,
    access_all boolean NOT NULL,
    akey text NOT NULL,
    status integer NOT NULL,
    atype integer NOT NULL,
    reset_password_key text,
    external_id text
);


ALTER TABLE public.users_organizations OWNER TO bitwarden;

--
-- Data for Name: __diesel_schema_migrations; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.__diesel_schema_migrations (version, run_on) FROM stdin;
20190912100000	2025-07-11 00:32:04.001861
20190916150000	2025-07-11 00:32:04.023222
20191010083032	2025-07-11 00:32:04.081421
20191117011009	2025-07-11 00:32:04.082037
20200313205045	2025-07-11 00:32:04.082529
20200409235005	2025-07-11 00:32:04.086057
20200701214531	2025-07-11 00:32:04.086312
20200802025025	2025-07-11 00:32:04.086565
20201130224000	2025-07-11 00:32:04.087989
20201209173101	2025-07-11 00:32:04.088284
20210311190243	2025-07-11 00:32:04.088539
20210315163412	2025-07-11 00:32:04.090938
20210430233251	2025-07-11 00:32:04.091182
20210511205202	2025-07-11 00:32:04.09141
20210701203140	2025-07-11 00:32:04.091625
20210830193501	2025-07-11 00:32:04.091869
20211024164321	2025-07-11 00:32:04.093939
20220117234911	2025-07-11 00:32:04.095817
20220302210038	2025-07-11 00:32:04.096106
20220727110000	2025-07-11 00:32:04.097103
20221018170602	2025-07-11 00:32:04.099865
20230106151600	2025-07-11 00:32:04.101623
20230111205851	2025-07-11 00:32:04.101889
20230131222222	2025-07-11 00:32:04.102138
20230218125735	2025-07-11 00:32:04.102402
20230602200424	2025-07-11 00:32:04.102616
20230617200424	2025-07-11 00:32:04.103473
20230628133700	2025-07-11 00:32:04.105696
20230901170620	2025-07-11 00:32:04.105925
20230902212336	2025-07-11 00:32:04.106181
20231021221242	2025-07-11 00:32:04.106398
20240112210182	2025-07-11 00:32:04.106604
20240214135953	2025-07-11 00:32:04.108338
20240605131359	2025-07-11 00:32:04.110723
20240904091351	2025-07-11 00:32:04.112393
20250109172300	2025-07-11 00:32:04.112813
\.


--
-- Data for Name: attachments; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.attachments (id, cipher_uuid, file_name, file_size, akey) FROM stdin;
\.


--
-- Data for Name: auth_requests; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.auth_requests (uuid, user_uuid, organization_uuid, request_device_identifier, device_type, request_ip, response_device_id, access_code, public_key, enc_key, master_password_hash, approved, creation_date, response_date, authentication_date) FROM stdin;
\.


--
-- Data for Name: ciphers; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.ciphers (uuid, created_at, updated_at, user_uuid, organization_uuid, atype, name, notes, fields, data, password_history, deleted_at, reprompt, key) FROM stdin;
6b5e4974-4a65-4057-a730-183b4c9ea6ea	2025-07-11 00:50:14.338537	2025-07-11 00:50:14.369647	d5aaae15-c2cc-4079-86fa-7abeaf8c106a	\N	1	2.e1xA3JyyxQN4kEe08pGgoQ==|5JLpS34GGr//x6Ai68cSUQ==|h+D1ob6W5gJigxdkrqBIc941nMKPvlclRZADNnfYVzM=	\N	[]	{"password":"2.RVlc/JL3gL+4IIIgb22vlQ==|b1+Lwl3OTE7bTxiZ55bF/BN6hAeSeGa+188GVwLqgjg=|JOsNeO9vGm0fvK14j7t6+M5+ftPcxAY4fZqr/DSsb4k=","username":"2.NWxYNsrNTZUZSzOs5v6w8w==|HKi5m4CnpyeWvkERCwYwuw==|1CMHt37neY6bqnWOjTrsFPvKep+DRBu0GFP+j9xT7xs="}	\N	\N	0	\N
7de973fa-fbab-45d3-8d2f-78cd6cfc736f	2025-07-11 00:50:55.53531	2025-07-11 00:50:55.542728	d5aaae15-c2cc-4079-86fa-7abeaf8c106a	\N	1	2.1f5CY6+ErG+s6rEk/oPWVA==|SXGKdbkWldc0NDEbJOJ8Vw==|D/NNzK8jBqplWord8KTUGTwhLWYsvMdwcGNgdEy8JkU=	\N	[]	{"password":"2.idiHnie1JdMucq7Imsz7SA==|whLs6GOaBw+5jm4HMdQMf+HS/hYj/QxM8BTXKnh79yg=|LyhtBWpfH06pJCeigNboYwaMGRhCkS3/rsH37jVs1sg=","username":"2.GdGT+V/3t/8MFNC1WiOtRA==|whxYsuVWG0moKFQvAZkHgQ==|oE06MTOQ6FuUAJyfMz6A6mM+sPQLQWa24TO192h13pA="}	\N	\N	0	\N
46dbb39d-7467-4e5d-9c03-c15388167d28	2025-07-11 00:51:17.873158	2025-07-11 00:51:17.876658	d5aaae15-c2cc-4079-86fa-7abeaf8c106a	\N	1	2.O0zVaRlHBhWgMVjfJ64lLg==|FnN3x6lNFz/x+qFV+Xe82w==|fMTDOXp4gB/mcirXSrB0rCREry3YhDIaviB7Bq2KbkA=	\N	[]	{"password":"2.8mOJhE7gE86D7eg8YMqL9w==|ObWL4JhY880+TiYcnjY/tornbnRcl8DUlc7GIXTSyBI=|nE2NdQXxnf1uXcZNZuYoUhKAm5InasLiJIqdh0LWlTE=","username":"2.RaPUNGrvotA0HVf5PGYing==|n91lJw+c0YEPc/oqc/ob0w==|MaaTlFrwQBmZTLwzYb8T8XYNJ253jjdZrd1XZ1e9cLw="}	\N	\N	0	\N
44eb9057-2c3c-485a-a285-b5a678f581b3	2025-07-11 00:51:37.671061	2025-07-11 00:51:37.679928	d5aaae15-c2cc-4079-86fa-7abeaf8c106a	\N	1	2.0MIWy4E/vGOcjoUg8aBbTQ==|+m3pJ3PUzvBbEBGDO07M+Q==|baxaoS+5Er0fEh8e3H7g7kUMhhlXJ1XyR5XEXYRRcG8=	\N	[]	{"password":"2.rL49JPHnibEBOdWb0/r1wQ==|r5YZmyvR9jN4CtzpQc/ttjBlCaUrNSwsYJv4jSzdC/4=|nVnrj0zTTrXKHCl6adjhROhAR14bLJOFeGvVkMW2b0o=","username":"2.Wx86Lox4FecTmtB7rRppzw==|N1PY3CoR6JmMjnJWKjALHw==|nsZ+ysy1Hy5jH/sZarj2maLLRGDIpY2bZXBpUniuPlw="}	\N	\N	0	\N
185cdccb-54b6-45ea-ae93-4ed03b0e17e8	2025-07-11 00:52:04.142655	2025-07-11 00:52:04.160558	d5aaae15-c2cc-4079-86fa-7abeaf8c106a	\N	1	2.VYaSaLf4z7VJ5JFKWQGKPw==|++GERvoo7oz7M+w2I4MgDQ==|bRxLlil8C8B6ZUo+sErsM0U7q7NSj7UAyvYGgddLFQM=	\N	[]	{"password":"2.24Jme3fconWY02pTE7sV5Q==|IU3LhcK0C4GmxkmammT1wzlanVKu+C5k9OXvvhP89jE=|MbNzvXavYBLhON4NMjp4Ckm4ovn7LCw/2gqgwk9ZvEc=","username":"2.5sItO5odHNSzLIrWTlvStQ==|87mo065zZWpoH/q64OAf4w==|b0aEMSFSscSriAR1B45h9rULiJ7fufaZWGV/E7cFZvE="}	\N	\N	0	\N
899820d2-e856-4896-a825-5291ac3568d1	2025-07-11 00:53:38.909952	2025-07-11 00:53:38.922251	be536446-4638-40d9-9b93-9e5396f11958	\N	1	2./8SjW6gLVhn4tKt3crWEzg==|XNeREd1ymZ17yioUIAsrGQ==|TaSV8CJ0MzEJyFl3m/rCem/FQveE+radynRYs1oSM3Y=	\N	[]	{"password":"2.1yP8u02hwfOSAPVMIZre1g==|fJQF3m+E6zZsCiia21wMhFvqod5zLhat5zfFi7jYooY=|gctGGDHwWXFWJkVR/TZLR1QyHuTtmQMDmPAagmh3MYI=","username":"2.ClX+NS0c1a149tUt97W19A==|0tUBpcTsMh9EirCie6Wrfw==|NqKYPhg7sZbto1+euqhJAcalRqge+E4ogRYqH0QBmhk="}	\N	\N	0	\N
3b9a6cda-dbe4-492b-a052-9727072aeb58	2025-07-11 00:53:55.167994	2025-07-11 00:53:55.174426	be536446-4638-40d9-9b93-9e5396f11958	\N	1	2.fiMxiXDPm3wfN0WK9hVpZA==|xPKdkBtTnBOP3fxXrKO/bg==|tA1uxgthpk/l8azYJpf1r9LNJlJzIS9b0GZHoYTrcYo=	\N	[]	{"password":"2.XlkK8lDGTx2fIAuySPYT9w==|eMmMyE+/qAYhzT+jeJ0r2uHvN+/lo+ce/M3AMqMs7J4=|TskklnWf8g2X6AOiWFR9o58zddwID1u+GHiGIUlJCsQ=","username":"2.7B2pZrpW4mQEHgxbHe47Ug==|iObKu38mg2LcE0hY8DZjGA==|pPlmLD3w4iljYt8noaAfJXIUhZ33m6JvzjP4tsDcsGg="}	\N	\N	0	\N
fa546962-0923-490f-b4ea-110c7ce4430a	2025-07-11 00:54:12.092536	2025-07-11 00:54:12.09882	be536446-4638-40d9-9b93-9e5396f11958	\N	1	2.I1LiMjQxOfujUY+1+0xmhQ==|+CeiTBmSgfhuEWIuvTD+dQ==|XXhJ296zEpXYkLvyVT8T1mrVUxu1HG146qhSf6BTOc4=	\N	[]	{"password":"2.Xfmmj3b1UaoDBDc8KSjsAQ==|Kiz/N8cRK7neKiufv0mucGhcSBjQs2QpMs84+rzesJ4=|autvzHSnfZIn8wY5tKxdRz/WU4kaRcBFBolTzLVAr20=","username":"2.NBqdePiYTyzqfpE3ZbDOYQ==|nBnucMk2Wzgetv3L7zUSCw==|b5QyFT0JFa7qlRiodcwdGWYs4pB6lT35XXsAo+QmzXA="}	\N	\N	0	\N
5a99d6cd-fb9a-40d3-9407-4e55762a5582	2025-07-11 00:54:36.605442	2025-07-11 00:54:36.618711	be536446-4638-40d9-9b93-9e5396f11958	\N	1	2.Zn/IPIVnWmW+ELzqK4cjbw==|jSdYZs10p1rNzK3ps84p5g==|475uRMB+hXFA/mgaq+7KgY1SEV8IJJDEEopPKFScASE=	\N	[]	{"password":"2.Gx0EQhMsnkCeTyYFCLsspg==|NmUHc2tiZEq/kQ6IToe2X9MAmyMV/4c8sOEl6GUxyNg=|mQqDhXj5iEcfgcUSJi3gQyXZjrjbq5bPuVfhxSrA0E4=","username":"2.06B3t3BGwEfOjkPWI2EB9w==|po2DTaycomBF6x+pt+m50w==|r4rUCrUZU2F0394M+rYQeWBMq4VuUz7IJWqIWzB2t6M="}	\N	\N	0	\N
af6696ad-9a5c-432f-ab63-34ea3e44e2a1	2025-07-11 00:54:58.728824	2025-07-11 00:54:58.737152	be536446-4638-40d9-9b93-9e5396f11958	\N	1	2.eI04ArXVaxfMgVtgMc1Tpw==|E0q9YGe7SZ3S2k0ukPD7mA==|a8yhD4jCtKPVPgyUphbBRqt5gJK2AbgCncKVJ5m4wYI=	\N	[]	{"password":"2.lIud9W02WSfcZF8Wik8plQ==|gaweTsvyYdYNQAhUjR555Py07jyW5+sCE29If6sUZqo=|BOmKBNudl8YFkaXJ+RTychgXeOxm1sfpHpkI8T2D+n0=","username":"2.XDA7nidRIaUD/dnn9RX1GQ==|H180TqJNEJMf7P8P46m3RQ==|O4EwpqW8sbpcRYvhkTrrH9zlMFi6JRGjBNHByyLBcig="}	\N	\N	0	\N
ace98388-f2ad-42a3-a9b7-50f916dd0870	2025-07-11 00:55:53.566187	2025-07-11 00:55:53.578411	f04f4c42-015e-4b51-a794-1d2891601ba5	\N	1	2.v98kS+01m+RcF3Yxj4zKow==|vxCJ7NbGbEJQwPwRYR+rfQ==|wESMStaXnzlwtqD3Y+3bNcmZrfUVERziQVOgZEPm/5Q=	\N	[]	{"password":"2.XVFAYCuHuuCz6jHHhaiXPA==|PdZwR2ozvi1CAv7T0tOBC1zxmvamurR5y2lNdihLH1A=|38qQo1TVH1m7uFr75YKthElGCs22PzNKWvZWnv6x7fw=","username":"2.MyzGz69Wh+4a4a/5ZPMAjA==|zLg5jkgeB0W54BEiRwl4Ow==|86ryB+jSFZ1ldUXV0+EXn5tY+GjoZe5QeuA0UngL5zg="}	\N	\N	0	\N
2c6a0535-5b1e-4c6f-b523-60b831765e5c	2025-07-11 00:56:09.257667	2025-07-11 00:56:09.260556	f04f4c42-015e-4b51-a794-1d2891601ba5	\N	1	2.7jq5jm0b86nVBAJFBcSO9A==|ss5IZ12e0couTVo2JCK7gQ==|V4xiQAhIs/CsPMgnRbbH6G/NZ/gkH/QWD8FQeLGEAac=	\N	[]	{"password":"2.3+JmTslrX/caUi8SnMdsDQ==|NOG+sBewmCbVg1Fvt8DUzNHgdzEEFof45n4MsnLDq+s=|c6CVCYntjs25N24eIlRJgMiR6WBbjoHzkKcK5EVrYgU=","username":"2.PtzHylipUeK6bYNncqDygQ==|WGwTpfWEw/IW/XDGOIo4Xw==|QRWc8T7HOQo+/Q+0MJq/6qB+OTEb2msU+Y8Z6ezHzPo="}	\N	\N	0	\N
cdf0f680-b1d2-474e-b2fe-b43e4a269cc1	2025-07-11 00:56:27.660417	2025-07-11 00:56:27.6643	f04f4c42-015e-4b51-a794-1d2891601ba5	\N	1	2.EkUCGgI+0cTGh3h3zNbqMQ==|myvQBt+R57ytdpRk6+Aaug==|J3Kespa06HPHmSFd/dW0Wi/pIk3e2753QYq4bDLLfmk=	\N	[]	{"password":"2.ByFkweYsPYZ1feRj2VeOgw==|h5YVfHPBRdSpi0plBH0pxt65R0mzXBQisPhNQjdJxOo=|tSHg34sla5xqsjFqlc2SevFyOewHwST4BGaVhkDEzVk=","username":"2.3R2DifJTrM0c/WmuFPdcYg==|C45Lt7A5J5SqTYNfzBEaSA==|IWtOjbI3ePtHzhW8t063bakLPSe3qa5hU1Rre3dgzXM="}	\N	\N	0	\N
156efa4d-241a-4911-bbcb-203641945b19	2025-07-11 00:56:45.374128	2025-07-11 00:56:45.378128	f04f4c42-015e-4b51-a794-1d2891601ba5	\N	1	2.pODLdQ8GUraPSpuvUoue7w==|2hdI8J8jdlUZq6Ll7GUpnw==|cP+6ven/u0sExMPS4hCEtByV+p6G9QCu72Mo9fAsrI4=	\N	[]	{"password":"2.Qraw9KhqtkOp9SnrBkNqaA==|rPH/+e3YmkbOA4ejpfmcfcTQIWsD8QMNMMy2mEwvK44=|DVCJeiopdm/Po9dbqNmV8tL7bPdQT9oETOMhaqHCmbg=","username":"2.2BQiJt/EQDiTTwsRSutABg==|qWzqahqEapo8Du/SJ2RGoQ==|ruc2hriy9o3WxGD2wOt81M5WivX01sQXD1zg8au8XI0="}	\N	\N	0	\N
71e464cc-4382-4d28-ad64-84b58450ddea	2025-07-11 00:57:01.663125	2025-07-11 00:57:01.668729	f04f4c42-015e-4b51-a794-1d2891601ba5	\N	1	2.7hY5XTJpUuFUX5Tk/6vfSg==|YdeDcq4UahSDEh7lsTiI5Q==|tdW6N2Yowqdrk8RUrK6FqapbRqx8BUpXMpRyqd0dRs8=	\N	[]	{"password":"2.5RRQzFqTFTtxiUi/xnWh+A==|xrGDG7aC/DXL4OYc96rkbtQgwDXffPfyrVb0Iw5jJ0w=|RyISfc6RE2GcPSAIZh0nVfLBs5q+w7zxRt08LiTLUAU=","username":"2.RKR40OIzWeC7J0znEx6xwA==|3QeP9yVPsKI/7c9zbOGFHg==|OJ1V3KnEGXgYmCXqoiOX6q8I0GQ269dzGqoDDhVQYFc="}	\N	\N	0	\N
\.


--
-- Data for Name: ciphers_collections; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.ciphers_collections (cipher_uuid, collection_uuid) FROM stdin;
\.


--
-- Data for Name: collections; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.collections (uuid, org_uuid, name, external_id) FROM stdin;
\.


--
-- Data for Name: collections_groups; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.collections_groups (collections_uuid, groups_uuid, read_only, hide_passwords, manage) FROM stdin;
\.


--
-- Data for Name: devices; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.devices (uuid, created_at, updated_at, user_uuid, name, atype, push_token, refresh_token, twofactor_remember, push_uuid) FROM stdin;
b2e025df-845d-445f-ba60-5f041cc4e2b2	2025-07-11 00:49:41.627946	2025-07-11 00:49:41.638726	d5aaae15-c2cc-4079-86fa-7abeaf8c106a	sdk_gphone64_arm64	0	\N	Ns-KfiheOyR9H4BmOmpzoLXCc1dSCDCBtr6rIaWtZfxV_CU9iHfcA_zgPj1mQydt6rczxRgPrcIueR6mBj4mWw==	\N	764201a2-7825-4ac9-9ea8-931c8ea6cb26
b2e025df-845d-445f-ba60-5f041cc4e2b2	2025-07-11 00:53:05.241495	2025-07-11 00:53:05.247357	be536446-4638-40d9-9b93-9e5396f11958	sdk_gphone64_arm64	0	\N	7aUJeoeVZU5G51uGttUGbdXNcZe80WQuDh4-pgenlGR4AJ39XXhO6O9WGGd_yO7Ydw6pT_ZlSXlFAToHLGuozQ==	\N	cc4726c1-9199-4c86-aa9b-c132595d1f91
b2e025df-845d-445f-ba60-5f041cc4e2b2	2025-07-11 00:55:31.419245	2025-07-11 00:55:31.438481	f04f4c42-015e-4b51-a794-1d2891601ba5	sdk_gphone64_arm64	0	\N	11Dzk8xo1x5k4iXMPEa87kQfgEdqVQqs_5QcqBoNT-7TnhDmf6b0js1RdoMUkpBXM-T5xHqPbVGdV6b1FLlZtg==	\N	18ea9c83-4f94-4d62-861b-3f9570b0e41d
\.


--
-- Data for Name: emergency_access; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.emergency_access (uuid, grantor_uuid, grantee_uuid, email, key_encrypted, atype, status, wait_time_days, recovery_initiated_at, last_notification_at, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: event; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.event (uuid, event_type, user_uuid, org_uuid, cipher_uuid, collection_uuid, group_uuid, org_user_uuid, act_user_uuid, device_type, ip_address, event_date, policy_uuid, provider_uuid, provider_user_uuid, provider_org_uuid) FROM stdin;
\.


--
-- Data for Name: favorites; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.favorites (user_uuid, cipher_uuid) FROM stdin;
\.


--
-- Data for Name: folders; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.folders (uuid, created_at, updated_at, user_uuid, name) FROM stdin;
\.


--
-- Data for Name: folders_ciphers; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.folders_ciphers (cipher_uuid, folder_uuid) FROM stdin;
\.


--
-- Data for Name: groups; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.groups (uuid, organizations_uuid, name, access_all, external_id, creation_date, revision_date) FROM stdin;
\.


--
-- Data for Name: groups_users; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.groups_users (groups_uuid, users_organizations_uuid) FROM stdin;
\.


--
-- Data for Name: invitations; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.invitations (email) FROM stdin;
\.


--
-- Data for Name: org_policies; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.org_policies (uuid, org_uuid, atype, enabled, data) FROM stdin;
\.


--
-- Data for Name: organization_api_key; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.organization_api_key (uuid, org_uuid, atype, api_key, revision_date) FROM stdin;
\.


--
-- Data for Name: organizations; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.organizations (uuid, name, billing_email, private_key, public_key) FROM stdin;
\.


--
-- Data for Name: sends; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.sends (uuid, user_uuid, organization_uuid, name, notes, atype, data, akey, password_hash, password_salt, password_iter, max_access_count, access_count, creation_date, revision_date, expiration_date, deletion_date, disabled, hide_email) FROM stdin;
\.


--
-- Data for Name: twofactor; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.twofactor (uuid, user_uuid, atype, enabled, data, last_used) FROM stdin;
\.


--
-- Data for Name: twofactor_duo_ctx; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.twofactor_duo_ctx (state, user_email, nonce, exp) FROM stdin;
\.


--
-- Data for Name: twofactor_incomplete; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.twofactor_incomplete (user_uuid, device_uuid, device_name, login_time, ip_address, device_type) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.users (uuid, created_at, updated_at, email, name, password_hash, salt, password_iterations, password_hint, akey, private_key, public_key, totp_secret, totp_recover, security_stamp, equivalent_domains, excluded_globals, client_kdf_type, client_kdf_iter, verified_at, last_verifying_at, login_verify_count, email_new, email_new_token, enabled, stamp_exception, api_key, avatar_color, client_kdf_memory, client_kdf_parallelism, external_id) FROM stdin;
be536446-4638-40d9-9b93-9e5396f11958	2025-07-11 00:53:04.75118	2025-07-11 00:54:58.739733	user2@test.com	User 2	\\xdc3294db58d5a6f501212adc028ce517a373b22681fb474ee1ee9904651f60b7	\\x7d400dd09d108edabec15e61cca2fa4f38d123dc6f571c848a51301d6b6462cac8640166bf1e5cb103eae660a5198dcb1aa1e0a35aef591e941a20c3c871825b	600000	master password 2	2.X5jXYVugRS1GqxDHC/9kGw==|gYYWqsBqdHTUDROyaYG7S8hLD6PlBcUS4qD6H/sPpvItmXGIhw3G9HVv6d78FHkAi2A8h34U2lNlpG1zRVffVqRaLy+U1dAE7OepNbhi8kM=|BigkWKI09blKxXVJfFcPNVNV3MBsGB3J0uyplpMnfx4=	2.mONb/oaZ1Mom3j6HLpeAPA==|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	\N	\N	a01b6c96-10e2-43e2-acd0-02fa20c7f9d7	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
d5aaae15-c2cc-4079-86fa-7abeaf8c106a	2025-07-11 00:49:41.149642	2025-07-11 00:52:04.163835	user1@test.com	User 1	\\x0865c5276c1ee4427ce360d8081f2adcd4d8ff73c42e93201ac329e7dd2398dd	\\xbabce103cc273b3aa82066d7c7343221c66d338c5187266c26b6821aace6a4c4536bfb90fbed2c1f74d883a96f81453d3ebb88233ce08c47b0749bf20d970f8d	600000	master password 1	2.hXPoSOzzT1HM0XX8CtI1sg==|VDFYfz1y1V7n3pnOqU9LtLQOfz16Y3dZVE1KRbIAlq974v2+ZShjO7MxJ+EftmnLyD53DtS9rteP+CuLxduNpJnTT4mnbbMnWYLrZfNog4w=|Uv3Z/bI/G7kwtriwLQ9eXqtGg1cPRApGOyuQ3MretfE=	2.q4SpDuOvcFJ97dxTiD3FaA==|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	\N	\N	03d05086-d3a0-4d06-9ed9-4dba5c2af982	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
f04f4c42-015e-4b51-a794-1d2891601ba5	2025-07-11 00:55:30.996838	2025-07-11 00:57:01.670668	user3@test.com	User 3	\\xdd7eb8aca2748f971bfda244105868b2d296cbf84425bfd50c05d289af98dcc3	\\x2092742a77e68651cef45699d7b363218a41514f282812e038f7d453632782f9f6a9d50325a43406f30501d1a00c24b400990e52017ae0639a8a430e46a5dbf5	600000	master password 3	2.SzSE1btRMeIbP3M+iQU0IA==|ac1GQS3XlEAOVRCTg3Wng1o31FH9AX+4i/z4v77OfuEGHUm9110FMqnpm4bhLu4GqDsXlfYCwahDzDQZLXwMeO5yQIVJizT3cL7t8kVLlS0=|wBOZu6IpdWDc6o8iYryiARVtjBih75tu6cLOhGhZNm8=	2.1ReqQ1z8M+jzXfg4Xql6zA==|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	\N	\N	f58b99b5-bc65-40ee-a4a5-65a963dd34fc	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
\.


--
-- Data for Name: users_collections; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.users_collections (user_uuid, collection_uuid, read_only, hide_passwords, manage) FROM stdin;
\.


--
-- Data for Name: users_organizations; Type: TABLE DATA; Schema: public; Owner: bitwarden
--

COPY public.users_organizations (uuid, user_uuid, org_uuid, access_all, akey, status, atype, reset_password_key, external_id) FROM stdin;
\.


--
-- Name: __diesel_schema_migrations __diesel_schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.__diesel_schema_migrations
    ADD CONSTRAINT __diesel_schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: attachments attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_pkey PRIMARY KEY (id);


--
-- Name: auth_requests auth_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.auth_requests
    ADD CONSTRAINT auth_requests_pkey PRIMARY KEY (uuid);


--
-- Name: ciphers_collections ciphers_collections_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.ciphers_collections
    ADD CONSTRAINT ciphers_collections_pkey PRIMARY KEY (cipher_uuid, collection_uuid);


--
-- Name: ciphers ciphers_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.ciphers
    ADD CONSTRAINT ciphers_pkey PRIMARY KEY (uuid);


--
-- Name: collections_groups collections_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.collections_groups
    ADD CONSTRAINT collections_groups_pkey PRIMARY KEY (collections_uuid, groups_uuid);


--
-- Name: collections collections_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.collections
    ADD CONSTRAINT collections_pkey PRIMARY KEY (uuid);


--
-- Name: devices devices_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_pkey PRIMARY KEY (uuid, user_uuid);


--
-- Name: emergency_access emergency_access_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.emergency_access
    ADD CONSTRAINT emergency_access_pkey PRIMARY KEY (uuid);


--
-- Name: event event_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_pkey PRIMARY KEY (uuid);


--
-- Name: favorites favorites_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.favorites
    ADD CONSTRAINT favorites_pkey PRIMARY KEY (user_uuid, cipher_uuid);


--
-- Name: folders_ciphers folders_ciphers_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.folders_ciphers
    ADD CONSTRAINT folders_ciphers_pkey PRIMARY KEY (cipher_uuid, folder_uuid);


--
-- Name: folders folders_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.folders
    ADD CONSTRAINT folders_pkey PRIMARY KEY (uuid);


--
-- Name: groups groups_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.groups
    ADD CONSTRAINT groups_pkey PRIMARY KEY (uuid);


--
-- Name: groups_users groups_users_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.groups_users
    ADD CONSTRAINT groups_users_pkey PRIMARY KEY (groups_uuid, users_organizations_uuid);


--
-- Name: invitations invitations_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.invitations
    ADD CONSTRAINT invitations_pkey PRIMARY KEY (email);


--
-- Name: org_policies org_policies_org_uuid_atype_key; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.org_policies
    ADD CONSTRAINT org_policies_org_uuid_atype_key UNIQUE (org_uuid, atype);


--
-- Name: org_policies org_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.org_policies
    ADD CONSTRAINT org_policies_pkey PRIMARY KEY (uuid);


--
-- Name: organization_api_key organization_api_key_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.organization_api_key
    ADD CONSTRAINT organization_api_key_pkey PRIMARY KEY (uuid, org_uuid);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (uuid);


--
-- Name: sends sends_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.sends
    ADD CONSTRAINT sends_pkey PRIMARY KEY (uuid);


--
-- Name: twofactor_duo_ctx twofactor_duo_ctx_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.twofactor_duo_ctx
    ADD CONSTRAINT twofactor_duo_ctx_pkey PRIMARY KEY (state);


--
-- Name: twofactor_incomplete twofactor_incomplete_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.twofactor_incomplete
    ADD CONSTRAINT twofactor_incomplete_pkey PRIMARY KEY (user_uuid, device_uuid);


--
-- Name: twofactor twofactor_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.twofactor
    ADD CONSTRAINT twofactor_pkey PRIMARY KEY (uuid);


--
-- Name: twofactor twofactor_user_uuid_atype_key; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.twofactor
    ADD CONSTRAINT twofactor_user_uuid_atype_key UNIQUE (user_uuid, atype);


--
-- Name: users_collections users_collections_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users_collections
    ADD CONSTRAINT users_collections_pkey PRIMARY KEY (user_uuid, collection_uuid);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users_organizations users_organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users_organizations
    ADD CONSTRAINT users_organizations_pkey PRIMARY KEY (uuid);


--
-- Name: users_organizations users_organizations_user_uuid_org_uuid_key; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users_organizations
    ADD CONSTRAINT users_organizations_user_uuid_org_uuid_key UNIQUE (user_uuid, org_uuid);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (uuid);


--
-- Name: attachments attachments_cipher_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_cipher_uuid_fkey FOREIGN KEY (cipher_uuid) REFERENCES public.ciphers(uuid);


--
-- Name: auth_requests auth_requests_organization_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.auth_requests
    ADD CONSTRAINT auth_requests_organization_uuid_fkey FOREIGN KEY (organization_uuid) REFERENCES public.organizations(uuid);


--
-- Name: auth_requests auth_requests_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.auth_requests
    ADD CONSTRAINT auth_requests_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: ciphers_collections ciphers_collections_cipher_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.ciphers_collections
    ADD CONSTRAINT ciphers_collections_cipher_uuid_fkey FOREIGN KEY (cipher_uuid) REFERENCES public.ciphers(uuid);


--
-- Name: ciphers_collections ciphers_collections_collection_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.ciphers_collections
    ADD CONSTRAINT ciphers_collections_collection_uuid_fkey FOREIGN KEY (collection_uuid) REFERENCES public.collections(uuid);


--
-- Name: ciphers ciphers_organization_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.ciphers
    ADD CONSTRAINT ciphers_organization_uuid_fkey FOREIGN KEY (organization_uuid) REFERENCES public.organizations(uuid);


--
-- Name: ciphers ciphers_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.ciphers
    ADD CONSTRAINT ciphers_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: collections_groups collections_groups_collections_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.collections_groups
    ADD CONSTRAINT collections_groups_collections_uuid_fkey FOREIGN KEY (collections_uuid) REFERENCES public.collections(uuid);


--
-- Name: collections_groups collections_groups_groups_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.collections_groups
    ADD CONSTRAINT collections_groups_groups_uuid_fkey FOREIGN KEY (groups_uuid) REFERENCES public.groups(uuid);


--
-- Name: collections collections_org_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.collections
    ADD CONSTRAINT collections_org_uuid_fkey FOREIGN KEY (org_uuid) REFERENCES public.organizations(uuid);


--
-- Name: devices devices_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: emergency_access emergency_access_grantee_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.emergency_access
    ADD CONSTRAINT emergency_access_grantee_uuid_fkey FOREIGN KEY (grantee_uuid) REFERENCES public.users(uuid);


--
-- Name: emergency_access emergency_access_grantor_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.emergency_access
    ADD CONSTRAINT emergency_access_grantor_uuid_fkey FOREIGN KEY (grantor_uuid) REFERENCES public.users(uuid);


--
-- Name: favorites favorites_cipher_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.favorites
    ADD CONSTRAINT favorites_cipher_uuid_fkey FOREIGN KEY (cipher_uuid) REFERENCES public.ciphers(uuid);


--
-- Name: favorites favorites_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.favorites
    ADD CONSTRAINT favorites_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: folders_ciphers folders_ciphers_cipher_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.folders_ciphers
    ADD CONSTRAINT folders_ciphers_cipher_uuid_fkey FOREIGN KEY (cipher_uuid) REFERENCES public.ciphers(uuid);


--
-- Name: folders_ciphers folders_ciphers_folder_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.folders_ciphers
    ADD CONSTRAINT folders_ciphers_folder_uuid_fkey FOREIGN KEY (folder_uuid) REFERENCES public.folders(uuid);


--
-- Name: folders folders_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.folders
    ADD CONSTRAINT folders_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: groups groups_organizations_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.groups
    ADD CONSTRAINT groups_organizations_uuid_fkey FOREIGN KEY (organizations_uuid) REFERENCES public.organizations(uuid);


--
-- Name: groups_users groups_users_groups_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.groups_users
    ADD CONSTRAINT groups_users_groups_uuid_fkey FOREIGN KEY (groups_uuid) REFERENCES public.groups(uuid);


--
-- Name: groups_users groups_users_users_organizations_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.groups_users
    ADD CONSTRAINT groups_users_users_organizations_uuid_fkey FOREIGN KEY (users_organizations_uuid) REFERENCES public.users_organizations(uuid);


--
-- Name: org_policies org_policies_org_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.org_policies
    ADD CONSTRAINT org_policies_org_uuid_fkey FOREIGN KEY (org_uuid) REFERENCES public.organizations(uuid);


--
-- Name: organization_api_key organization_api_key_org_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.organization_api_key
    ADD CONSTRAINT organization_api_key_org_uuid_fkey FOREIGN KEY (org_uuid) REFERENCES public.organizations(uuid);


--
-- Name: sends sends_organization_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.sends
    ADD CONSTRAINT sends_organization_uuid_fkey FOREIGN KEY (organization_uuid) REFERENCES public.organizations(uuid);


--
-- Name: sends sends_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.sends
    ADD CONSTRAINT sends_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: twofactor_incomplete twofactor_incomplete_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.twofactor_incomplete
    ADD CONSTRAINT twofactor_incomplete_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: twofactor twofactor_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.twofactor
    ADD CONSTRAINT twofactor_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: users_collections users_collections_collection_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users_collections
    ADD CONSTRAINT users_collections_collection_uuid_fkey FOREIGN KEY (collection_uuid) REFERENCES public.collections(uuid);


--
-- Name: users_collections users_collections_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users_collections
    ADD CONSTRAINT users_collections_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- Name: users_organizations users_organizations_org_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users_organizations
    ADD CONSTRAINT users_organizations_org_uuid_fkey FOREIGN KEY (org_uuid) REFERENCES public.organizations(uuid);


--
-- Name: users_organizations users_organizations_user_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bitwarden
--

ALTER TABLE ONLY public.users_organizations
    ADD CONSTRAINT users_organizations_user_uuid_fkey FOREIGN KEY (user_uuid) REFERENCES public.users(uuid);


--
-- PostgreSQL database dump complete
--

