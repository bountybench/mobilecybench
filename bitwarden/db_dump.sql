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
20190912100000	2025-07-23 01:28:26.662594
20190916150000	2025-07-23 01:28:26.698826
20191010083032	2025-07-23 01:28:26.816823
20191117011009	2025-07-23 01:28:26.81784
20200313205045	2025-07-23 01:28:26.818632
20200409235005	2025-07-23 01:28:26.825962
20200701214531	2025-07-23 01:28:26.826535
20200802025025	2025-07-23 01:28:26.827128
20201130224000	2025-07-23 01:28:26.829475
20201209173101	2025-07-23 01:28:26.829889
20210311190243	2025-07-23 01:28:26.830251
20210315163412	2025-07-23 01:28:26.832747
20210430233251	2025-07-23 01:28:26.832998
20210511205202	2025-07-23 01:28:26.833253
20210701203140	2025-07-23 01:28:26.833558
20210830193501	2025-07-23 01:28:26.83388
20211024164321	2025-07-23 01:28:26.835998
20220117234911	2025-07-23 01:28:26.837626
20220302210038	2025-07-23 01:28:26.837914
20220727110000	2025-07-23 01:28:26.839129
20221018170602	2025-07-23 01:28:26.842011
20230106151600	2025-07-23 01:28:26.843597
20230111205851	2025-07-23 01:28:26.843874
20230131222222	2025-07-23 01:28:26.84412
20230218125735	2025-07-23 01:28:26.844394
20230602200424	2025-07-23 01:28:26.844603
20230617200424	2025-07-23 01:28:26.845706
20230628133700	2025-07-23 01:28:26.847485
20230901170620	2025-07-23 01:28:26.847709
20230902212336	2025-07-23 01:28:26.847977
20231021221242	2025-07-23 01:28:26.848193
20240112210182	2025-07-23 01:28:26.848415
20240214135953	2025-07-23 01:28:26.850351
20240605131359	2025-07-23 01:28:26.852728
20240904091351	2025-07-23 01:28:26.85398
20250109172300	2025-07-23 01:28:26.854267
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
e5cd07bc-e970-41b7-98f5-15e2e8aaa642	2025-07-23 01:28:27.851484	2025-07-23 01:28:27.851484	aed3be34-5f15-46ae-94f6-51b229eb1cea	\N	1	2.TNj/27wkWs/MnYJNbPRj4g==|1EranBWWhPYLctWhruhlsQ==|QUD9GtFil34WFqohrk/YKzcufDDG+sDE/4Mg6SQRdAc=	\N	\N	{"username": "2.FL3+zuoy2ysLofzfTkAjug==|xdgQ/vi2axcnPEn/qQIfmQ==|C9HzHxA9oP2/ylmmldfGPrcbjLwyV+ryDWmNurbiM/s=", "password": "2.s5HlQwroNnJX3KGdL2YBjg==|bz08f1G15V3C91ud4AkZrg==|iz6FGUefeJQYhvWBw+f9J+cKkjx/3NRoRHGj8HhMs7M=", "totp": null, "uri": "2.U1Sk5Vu23gyg8xj7Ad8qWg==|lMJLoqPqatMkAtpEpawov+aP5/FeMWieYB24iNqSGQw=|bfomLku7qQpiiSrRZN0nScSZGDEmUfnjp/3FgBpGEMs="}	\N	\N	\N	\N
ca9d6d3e-8c95-4c09-9d86-ccdb3b1b071c	2025-07-23 01:28:27.851484	2025-07-23 01:28:27.851484	aed3be34-5f15-46ae-94f6-51b229eb1cea	\N	1	2.tfsAE4TlgTC7p1PUervokg==|6lI5oi1T4HFv4K0jIfH5HQ==|fVdzsAzSU/g7pQXJyKtIIPNNC4YcqFkmAu4ERTPUcjI=	\N	\N	{"username": "2.qFSUy3GSBH3bJeHg+NBVnQ==|UI7KIH9BCXtU35JiHvEpew==|Si5d7meHqW5wI1+qxuGg568DGcKQnA50yjjB9EJS+f0=", "password": "2.Z75Cqa4Ew90/FtyZ3Jil9w==|0rNddtAKwTiIp0fPoXA3vQ==|Obju9uTq4laKXgpJc2HeHw2sGC9Xq2l3M4uO5Rh/sIE=", "totp": null, "uri": "2.lFcWjGjx1r2Yg8x2Mox5BA==|271DjM7CAsZqaLIe9Ke2vW7V4CBDgoS/CHTsbJ15O60=|UlWfRTVJdKllp7LoSiNgE+PMT6Nd/DF4kXnu4x8ZmdE="}	\N	\N	\N	\N
65e7bdf5-3c48-49aa-adb5-97ef36091796	2025-07-23 01:28:27.851484	2025-07-23 01:28:27.851484	aed3be34-5f15-46ae-94f6-51b229eb1cea	\N	1	2.7K1ytToAYR42OSug/tIGxA==|KxpLJtJ8HOADdkf2jp3UEg==|JGv/QBjhskxZkaD/eU16VsE48FpH7oQTUU5C163cDV4=	\N	\N	{"username": "2.oyRKirO8IciOp9Y+nVcIDg==|OfaU0fzFJXspWBgpKWrt9g==|MPswXaZGWcd4ZoFmas8KzQcGCDh3f15C6uwiBNCtJtU=", "password": "2.Giv1C5DIwWwKZRlU3jZK+w==|3lZMbp2X9R4TK5knNumnvQ==|aYoRIj91vDGLP3OVU0mWkLCQ2mi90yRqJ0X9+ksR8S8=", "totp": null, "uri": "2.f/VCa+HnZMviVKg65TEASQ==|wadQ+0w6LjfBbI8ekX4VlFGdylrCubwWDwRR85MLU8c=|s5/0ZdS3v2SWYOplKE47bx2C8231nm4V2dzgXhAPw5E="}	\N	\N	\N	\N
681aa1d0-1d84-48b6-958f-78d7903721d6	2025-07-23 01:28:27.851484	2025-07-23 01:28:27.851484	aed3be34-5f15-46ae-94f6-51b229eb1cea	\N	1	2.fLvjrH2q4sEBf1SmJcuX7A==|g2rXj4weP9A50v8zA5T0pQ==|FnEn5t6bTx3btnZSSrSuZLzJ0/+cR8RL2JI8bp4FhIA=	\N	\N	{"username": "2.HvHrQFiqVIAkWx9x6/dvwA==|ow9p93NSUrtXmWK6wuXkgA==|ocGcrReD8N6oJbqx2l46ySUitmDF1+NgLm3n7TuSiVw=", "password": "2.zkJDWi4raq5Kq6pZ+dW7aA==|W58YB/fpk67bNOUcx1NR9g==|ASOJu1iD6URlE0IrCeOW3PKsGl+aMcG3m6ChUygH1IY=", "totp": null, "uri": "2.xSgyQBunoq5vjoPpazygDw==|0jLfPY/35x8p/7++DNW8wMeRfrZ3sZLGAGVcJoo0rzk=|CgjkFNN6ohqM+MgsjE22NF3MpYV3f3wbwbWV5EnGXPs="}	\N	\N	\N	\N
f068e86c-4a86-4027-9a17-34b34ecce64e	2025-07-23 01:28:27.851484	2025-07-23 01:28:27.851484	aed3be34-5f15-46ae-94f6-51b229eb1cea	\N	1	2.JGmTwBCGXqlBYPeMrMcajQ==|Eq+t/ktuUcBi1QPHqygizg==|04tZ7LrerdL/E9syU4aXvglxdqZQo1b7M//QDboSQyo=	\N	\N	{"username": "2.3khRd0XFvAy7Ls0XjB61jQ==|/v741MgJSAxZ03IMYiQydw==|htyCWzBDlqll2ARJOM1TtfXT2LzRLYF1nkvhdw2MSRs=", "password": "2.dVZLIswYnJQG03hoyImz4w==|cmk0e6iUB0WAc3ccXBTksw==|x+r6MT9ekWcLGqoGPyrHHhmWjb1Tywn2hCl7/AUStwc=", "totp": null, "uri": "2.hjg+fw3pMxwQf4RsHFi0IA==|5v/X3yBJn1I+tIFq5W2mQHxserMVYfQJw2I/JzztlI8=|qdztn51hmgRYUDghSEj5MhdP3vT10jaStvccJjOCCwo="}	\N	\N	\N	\N
6e00ca63-acaf-42c3-ae9c-5d8574002c95	2025-07-23 01:28:27.852247	2025-07-23 01:28:27.852247	a831a38c-2145-4f67-8dde-d8c36a14c53f	\N	1	2.uZ1EitnuLl94z/8wEOwAjA==|F4PPHNC5sYIl0yltSrL67w==|wmjJuqJWQcUwS9lJNATxnVzPV5GHrZgkjH/OzBMKTLA=	\N	\N	{"username": "2.BCs+lP5WRY7aLjPTcSQaAg==|7SnuVsKeBa+rzACU/n8XNA==|Jx98QBeFlBp5a20KifmEdY6SPw2XNtoluPS5Xgo7hD4=", "password": "2.+YjvJCzj6AgjsWzM2tzsog==|416E98E3uNjBczMKoYZbUQ==|6Hs7RLeOvJcTB6Ol5YxFQamnRz1hg/p9mLvE6TZ5vAw=", "totp": null, "uri": "2.Lrx+V+XMGwxwBv4OBtiaLg==|qRQctkSStstamYpDwPAQo6IuBXwlylC7CyI38WbzcpI=|p1gf+xPp1eFQTBk0u27nuFd7qm8h+/0pLAEJUieSXBM="}	\N	\N	\N	\N
7fdd1e84-2013-4c84-9bdf-ab5e46250c39	2025-07-23 01:28:27.852247	2025-07-23 01:28:27.852247	a831a38c-2145-4f67-8dde-d8c36a14c53f	\N	1	2.s8k4FhIV6Rkw2g4o8w7XyQ==|pOcK940i9yZ0v86u1zJs9A==|Ui9Rcq8UJ8BUUotqqgd1tubclV6NTqBZvqADdTasDsM=	\N	\N	{"username": "2.bIUraFHpSPRXXGWGg8meJw==|+Bt4eVj9bQRhihovEJQ+0A==|QTl4b5knIOl/IXzrzdhhQ55pBPDajemsPIxaFyDWESE=", "password": "2.b80p7a7oySUbtIpfyTqOWg==|faoC7ZuP1VDOHJOy1ynWWg==|I2nO1BRjzw7rxgZotx8ZYyoNfgBSbgt2reQDZBRlHcs=", "totp": null, "uri": "2.J/m5Mt2OTzaa6mMZaDqB/Q==|xvivhWXuFibhcRreYPoe6N/mxGnwCTj0SsBygdasmz8=|IC2EzMhGQOjA1CrhIjozh9/oNoK/JlmzYegdQhwUdwY="}	\N	\N	\N	\N
5ea81ade-d2c7-4b0d-ba7c-dfadc5abda5a	2025-07-23 01:28:27.852247	2025-07-23 01:28:27.852247	a831a38c-2145-4f67-8dde-d8c36a14c53f	\N	1	2.bRONOCTA+maW+yVYTyB5yQ==|7itlrVES/WAIDW8CDsDS5w==|rNQIfvBqACTR0NhQyjBe9k6kYQRE5mKtxS6gBGiTNGM=	\N	\N	{"username": "2.u3h7KsVOmAFW3HeScLscEA==|K3AewhWIZFURLkQYBsbb7g==|FT6S+XEkJklc+TzmujmQUV38ZQh71MQPinizVEnENyU=", "password": "2.7ElUqXusTF26NfEaCJ+gVQ==|8mxuqy8S5fEK/OJYBfRl9A==|PjuLYELcPMGnXr4/en+xqO1PE4AO/aGlEaJtMoACGzs=", "totp": null, "uri": "2.Fi4B/s5jBoIoQrMDx2LNOA==|2TWfQLRaKVo/2bqnP98Qx57eAb043gdtnS1JKMCxcpk=|mOPKbZZ50r+W0r1JpJzSCsMUO+c4MyvfRcBoxr+sxlI="}	\N	\N	\N	\N
89f9f60a-d342-4daa-bf1b-455f8e782e1a	2025-07-23 01:28:27.852247	2025-07-23 01:28:27.852247	a831a38c-2145-4f67-8dde-d8c36a14c53f	\N	1	2.MWSL9YAgDLg126llwTRDWA==|qIACB/UMKZkUWNXSw6yl8w==|KDhvg4lnGqJvv+ZCMBNPOnEO7s8pMhy+PM/CKlCevxY=	\N	\N	{"username": "2./T5mlM7eqF8S0h9adLLK0A==|Y4gkg4nB3LrNJWKAso5lwA==|/G7l6RHXwkHVp6rfkTJhkE53V5xYV2cJqs02RbtmbQw=", "password": "2.XZGel7f0kumseQ3Ir0jyAA==|mKyb1GUeYu8FqMIeFNKiJQ==|f/0GX/RcjYVeq22VGl/3CIxNYkucr2BSLE4+eAUB6dU=", "totp": null, "uri": "2.EDzoJbWi9n5FZOaKKIdWvA==|i4Hmm+5umhnqsDTimafG/jaOnWWt/BhQmmyq29Tw9Cc=|fghICdXPmKGtykegIzgEjZU4RXlpdDSWta4Ew42pEBQ="}	\N	\N	\N	\N
061109ab-8288-4e1f-b6db-7bd738032aa7	2025-07-23 01:28:27.852247	2025-07-23 01:28:27.852247	a831a38c-2145-4f67-8dde-d8c36a14c53f	\N	1	2.VOURspoVEz/3ohIhtToGng==|33bUBy7wUeKBgfbdQHK4cw==|ZYq4M+QVCCAfALu6SEncPPAMQrSYInc9tNI1hj/ncoo=	\N	\N	{"username": "2.NQRBU04sWfrBzOdfkzaenQ==|SM90CLeH+Uad5LRpFU7SvQ==|/hc3+QD1b7DZ+DbyMQubqYwiz+JvICeb91SoyYIrwac=", "password": "2.1Z4SiyH+lnxhmOFReMPjZw==|t2gId2YliDk+AXy/lPO4Rw==|++rPmm5p1QK1sUk0pu14tY8eORHyi0yTnaHDq/vLLng=", "totp": null, "uri": "2.JF/zi/KNr6cEVTgFUm6MTg==|kb1VMpqZeg+Kpx2aWFapCmodtUQcXLePqx9H+hza9eI=|DPwzfa5urI88xkJofYaA/9gT2/zgf/QhD/hccTcd8/Y="}	\N	\N	\N	\N
fe7282fd-01db-4bdd-a53a-224ab908cd9a	2025-07-23 01:28:27.852576	2025-07-23 01:28:27.852576	d6b7c88b-54b3-4e67-af45-79c902e31be1	\N	1	2.GhKVcmvgy/LinwJBVDWQ0Q==|618wWFTbwZRhMbrAV+bDJQ==|POk81tYHFUGn+9zLlFZtWUi/aQYRlsQLUqUMuBU/pqk=	\N	\N	{"username": "2.qJ+DyEVsWoq8XZpEFGEMuQ==|ghvocr2lsG3g1GAv/gIIDA==|59P9rpYzvIiKD2n1P6878gDlLQ3WccTN8ojrjIzyuBY=", "password": "2.TGSbnoO5YOGPI/sRKCkmWA==|4NsDNvj3psKqawH8sy5eNw==|SDeb9un6n3hUzdhl0ntzYZe8G+ud5t/VN+g84vvLKE8=", "totp": null, "uri": "2.O0I9m4c4ah+GSlwALO05nw==|lIEXn+Yffn+/H4po9HjZDVx1CD9ui4mTKoRpSXltP6o=|bHfyWhFRzOXSj9LaO/zvjdRCbeJgUMwAptQ8Quezc7E="}	\N	\N	\N	\N
c5828944-4f55-43c4-b872-8fe815500e38	2025-07-23 01:28:27.852576	2025-07-23 01:28:27.852576	d6b7c88b-54b3-4e67-af45-79c902e31be1	\N	1	2.glw7IdP2TNS5kCGwMPI8iw==|rmJofqDPOnWVVvsUxFDUmg==|HUPfxCGLOkru8diApoDJ0G6tdKffm4jgos63vd7MbEk=	\N	\N	{"username": "2.6wfbQPc7FXDjX9N4fZW8iw==|y+DFAiXtu1FrNbVJ3DL40g==|HFfhI7xDMO7paVqDPrtrGGgPiDgwQki3Pln3QkIEMdA=", "password": "2.O+Edn55Sh6PLIRfLQ1N9qA==|KYWKkHL5Zu6IfBaX2w4Pwg==|TofK8yRfUdeGbJk9F14aS4k7jsPbDyhHTBGKOCz8SbI=", "totp": null, "uri": "2.FIcIdhl1PiGVSDnDeJv+mg==|d6M4yhqWLkmYisPYrWmM3Hej3PN5giDM9hQ3Zf8mMLg=|yWxYgD3nLQ9gIDo2DxKEBSG0L0UdQ3RWdwGuFMiLau0="}	\N	\N	\N	\N
102c3305-8fe3-454e-9692-704f597c8e07	2025-07-23 01:28:27.852576	2025-07-23 01:28:27.852576	d6b7c88b-54b3-4e67-af45-79c902e31be1	\N	1	2.+AdFKbOBoDCivZrgZBHhgQ==|/bu6TywmatqRnxiJeOWYmw==|+Re/d9hGfT+0rjIyknj9P1HtNRcc9Njgcoh132FEu/A=	\N	\N	{"username": "2.nK2+VfGyOMqkU27R48CuSw==|VuDZZSkpEYw++GKjM63qZw==|JtVstE6zti+OPhdT5rhNIGSxdiqV3lCCFlP7QEYvM2M=", "password": "2.DXNrSN4Xul3J6vdXsRtBfg==|9SLdksdn5KbEc7jRbA9B6g==|xbCI39IGfTbYjRk+dVv0ScF4VUbMCXG8qzLkw5qSZO8=", "totp": null, "uri": "2.J9txaLG3I11Q3wEhYxVfOQ==|gDj7nqulv71SXEFyo4u/rz8ADXZBs7+Cb/RI0AnhVIA=|b7QcpBABlPBtBpLqeYDhGhfIdPpoYz6c/7h/LdX8nQs="}	\N	\N	\N	\N
4cb119e4-ae0c-4b7a-b6b6-1dd2de58a8f9	2025-07-23 01:28:27.852576	2025-07-23 01:28:27.852576	d6b7c88b-54b3-4e67-af45-79c902e31be1	\N	1	2.OZcHlBvJvg0XV9WIHBJa9A==|YiNM/V8ZCNXL5lYJP3Y9og==|LERqesG4hXISQrRKxWDWICr/cdkpJlqr6SOUUAozI3s=	\N	\N	{"username": "2.PZ84Nup6ASUgSIXfGOBqeg==|OhRLhhc7nvRFpjg1L2X+PA==|MJTm1MOVjEI5gmYjzuDt4ywNAaFOd9vGzRdozT/iQmQ=", "password": "2.t7q5mVkpIFjlpKyco9mHjQ==|t0FxM7E6wB20UvuIH81Adw==|f4Pl6vF0Lq7/VhWYyEDhxv0nQ1/zctfiC/zlJCM0VWo=", "totp": null, "uri": "2.Q9LSZo+ekhDKXWbIJVaaYg==|7wBhxt2t0BQA20i/xGqZZMbyFvwkiFlzKxYIXj5SbXQ=|KqoGv5pL5mFJNXc/MHx+IgZoHL+IWMCZi0UJBrizGRM="}	\N	\N	\N	\N
26b30b8e-1ba6-4c53-a906-a765f8375959	2025-07-23 01:28:27.852576	2025-07-23 01:28:27.852576	d6b7c88b-54b3-4e67-af45-79c902e31be1	\N	1	2.aRKTHTbRQJoegfxBQAr6kA==|ECGcuA1gSiovfWkWX2+rfQ==|G+cCLA8a38YiFtQ537UcDyxNsJauIQcOvyOIQhlzduw=	\N	\N	{"username": "2.sB55pp2ltTSYNdYlkSh5mg==|0kGKyeBVimNoAOuqp4KWEQ==|lJP08AujWEzxwDBGLXGxTQPTG6sgPXtBijySUekHsRE=", "password": "2.xjrRLiQnA/MR3vboyMDQhw==|amxx7kgj09T3J5WNu24VGg==|77M/2yb3xRciFQtd9SzVi4gUoovbArnrRzFBEjwY1YI=", "totp": null, "uri": "2.rsbnb/QlxRNzJti6JDjN2Q==|wRRYV5EgGaFfpvplg0iBtN+jVL/XVQroVpuQ7oAvTdg=|+MdnzfMPQ2CbgPTJ0Rp5f/5mkxyEufyXE8F5maUjJto="}	\N	\N	\N	\N
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
aed3be34-5f15-46ae-94f6-51b229eb1cea	2025-07-23 01:28:27.849882	2025-07-23 01:28:27.849882	user1@example.com	User 1	\\xb929f2ecab17225fbe49391ce17bb19b12446c6f4f444ae100b9b36693639385	\\xc8f13781a8f779499a96dd53dde01c01389a7b3f9bfd00582509c9ef9cda8a72b547cbf1a0d0136a4794ac10b3a7f6f9b9926f5ba0863efffad1c386f8811305	600000	\N	2.PWfpJ0YTTaLZTjrgqMrG6g==|SPSY4dGfnmkP/p4xFqafJCy/TtEZ4AmqZqPlu6p7dM351OHHtoCFT9zShqA/Khs/|nm3nBFDc03MKZ79drMOAEAMAudTE51Kf5rhaLop+Q3E=	2.kS2y53UV2VO/iBFHRlSiPQ==|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	\N	\N	c1a8b1aa-78a4-4a3b-953e-667c1eaad3db	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
a831a38c-2145-4f67-8dde-d8c36a14c53f	2025-07-23 01:28:27.849882	2025-07-23 01:28:27.849882	user2@example.com	User 2	\\x1ef7e905b808e2fbb7e474895b672170aa113b0b18af36c16a0278b53237e70e	\\x6f29cd114c7509495482a11c4668f9a10f3da87c924090bf67171c61879702a81267f9ecbb715f8040ff4cdd5f0f8acb3fee6e5a4b1e88d9003e5cf6cf3bc26a	600000	\N	2.VbZfXWYggHBH+rfVMrfy/w==|Xl41EXk340/vwSZIp1eplrPJjgkP/dENeCWVgbk/lVbzL7SwrPh4uKgb68BpW0cf|1YHfTgUQzV97puuVzxbjKKhHKks16tryY8ooO0kktwE=	2.yL6uccJrWl/Locw3CoxBmg==|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	\N	\N	9dc5ff10-1eec-4526-bd25-372d3d5b3c6b	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
d6b7c88b-54b3-4e67-af45-79c902e31be1	2025-07-23 01:28:27.849882	2025-07-23 01:28:27.849882	user3@example.com	User 3	\\xd1bf342f0bb71fdb0435451991a6fb5390ee91e5b1c52f5fdc3388f47c4305db	\\xec96f0b8062430bc4813ea5e61aefe694734ab6f6f1d887d365a28de48f8271120188e95043bd02b1a1092ab82d439724b75a11d992cb75bf1a139f842902a2b	600000	\N	2.M4qta9inTAZTgiLSgsLB1g==|1reXN9vzrF8llgnTuZBDgU2NI81Gxggp8DrKlnwa7P51DZtsXMH1687yPDzGrVA1|iCkENRoVqiks4HPYtZzdPnPPCPkJ70AZbVhq4swuKew=	2.dE+WR/1RGFc5EPR3dJa0mw==|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	\N	\N	dc03ff46-258e-44c3-9944-7d4b31e249b3	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
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

