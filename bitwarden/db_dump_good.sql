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
20190912100000	2025-07-23 00:52:19.361781
20190916150000	2025-07-23 00:52:19.390274
20191010083032	2025-07-23 00:52:19.446604
20191117011009	2025-07-23 00:52:19.447773
20200313205045	2025-07-23 00:52:19.448778
20200409235005	2025-07-23 00:52:19.453733
20200701214531	2025-07-23 00:52:19.4541
20200802025025	2025-07-23 00:52:19.454566
20201130224000	2025-07-23 00:52:19.456466
20201209173101	2025-07-23 00:52:19.456847
20210311190243	2025-07-23 00:52:19.457119
20210315163412	2025-07-23 00:52:19.45956
20210430233251	2025-07-23 00:52:19.459801
20210511205202	2025-07-23 00:52:19.460028
20210701203140	2025-07-23 00:52:19.46028
20210830193501	2025-07-23 00:52:19.460529
20211024164321	2025-07-23 00:52:19.462433
20220117234911	2025-07-23 00:52:19.464357
20220302210038	2025-07-23 00:52:19.464642
20220727110000	2025-07-23 00:52:19.465797
20221018170602	2025-07-23 00:52:19.469192
20230106151600	2025-07-23 00:52:19.47085
20230111205851	2025-07-23 00:52:19.471093
20230131222222	2025-07-23 00:52:19.471331
20230218125735	2025-07-23 00:52:19.471657
20230602200424	2025-07-23 00:52:19.4719
20230617200424	2025-07-23 00:52:19.472929
20230628133700	2025-07-23 00:52:19.474966
20230901170620	2025-07-23 00:52:19.475211
20230902212336	2025-07-23 00:52:19.475472
20231021221242	2025-07-23 00:52:19.475748
20240112210182	2025-07-23 00:52:19.47603
20240214135953	2025-07-23 00:52:19.478305
20240605131359	2025-07-23 00:52:19.481409
20240904091351	2025-07-23 00:52:19.482305
20250109172300	2025-07-23 00:52:19.482668
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
32e049c6-884d-43a3-8afc-4cbabbcec0f6	2025-07-23 00:52:20.516642	2025-07-23 00:52:20.516642	1633c6e9-2bcb-4485-b1dd-ee017aab8d0f	\N	1	2.uaxIYs0ufm0vUAIIE6o+sA==|msgnDm667c9GBg9smYzfwA==|9b6/yAAdio7CRhEozmscblwMfpMw/YUVfI9lxpH2wYs=	\N	\N	{"username": "2.DJLstp01S3TSL3iW6ZFLjg==|d5sUkIKLKapo3yS2fdO7ow==|KN2XkLSgskKqQDYM1QxshTLxHVGT/kvIc4ZKQ46BMNM=", "password": "2.U/8IuK5MqLKflxaGx0gmhQ==|xsK9gP6ZGDN0DuIulzipRg==|Ils2L84p6BoMuPqnLak09nM157DtLpHFQgkjStDT4Ko=", "totp": null, "uri": "2.ICiIDY3NGBRviAbJ7Hao0A==|/TCo88gE9wB0yXEuTGOPMhSQv+EaQmHV6VcQqjsaqtE=|fOo5VYv+v/ZEAkov6wNWWMWtvndB0jK4URkgznTipos="}	\N	\N	\N	\N
241c45f4-a92d-4cfe-8003-be99d2b2c5aa	2025-07-23 00:52:20.516642	2025-07-23 00:52:20.516642	1633c6e9-2bcb-4485-b1dd-ee017aab8d0f	\N	1	2.kXA+XCOg743N5RwTSTHfVQ==|AZXkuQwg/zjPohET09ZZMw==|bjDIaewIajj9spxNCvVxl7buR9i6npfRQs4RcD0/la8=	\N	\N	{"username": "2.nqUYcarCOHBeVNVslmd+Kw==|XY+k7IPcjiMCwa75RrgK3A==|i/DHNqLJzh9EjK1APO9QJAR8UO/d7BcdkUeB6xzlpFU=", "password": "2.KJRMLLVRCw1007BMYEN5Vw==|7++263gxO6bjzJQx86fGDQ==|zf8byqqajCDzpFoK5JrJIeeIfX7iZieA6Ek3r4QOfOM=", "totp": null, "uri": "2.QRjQhu3PFK5R76boJd+FzQ==|vwDE9AYHS8jAGaPQVCDAWDPENKgTFHs1kQpTpywzDtU=|teJOg/aPT58dY/VRdYucNJPEVvdvbteFyhgWrkLC0QU="}	\N	\N	\N	\N
faf20522-7e3e-409e-a71a-e02ae715676f	2025-07-23 00:52:20.516642	2025-07-23 00:52:20.516642	1633c6e9-2bcb-4485-b1dd-ee017aab8d0f	\N	1	2.N0H1Xe5fk9VKCVAbqQLFwg==|Y7Ozi/+MsxTD8G93EIcdkA==|2dkZwNK/i/038ESMtaBLEIrmitnKESEQ4AiLyQ6YIss=	\N	\N	{"username": "2.yON4zoohonogk+AQeR6O0A==|37C2deZ5OuFgmf8+UiOumg==|y0PCesSDceTYqEuljpw2SDcx720CD0Da91XCuRlRI58=", "password": "2.Sz51XdT36l4MLUQfBJL8Yg==|WLIWs98Ck+wEbv0hMWk/Mw==|0DeAqwHXcvCtfYT5R/dtaBGMGDPShmg6LPqji9pg9pc=", "totp": null, "uri": "2.SMqNIBQhkCGPFXbzWFcYNw==|Hds1iogMzABoUKYeTq7XMgfTRLVjop/7Qf+2h64GiIg=|1PRWrLnaKpa0GsYKVnJPCXHYGebEoLlbJs9kfXDwa74="}	\N	\N	\N	\N
5f65df98-6043-445e-9b85-ddb909d14899	2025-07-23 00:52:20.516642	2025-07-23 00:52:20.516642	1633c6e9-2bcb-4485-b1dd-ee017aab8d0f	\N	1	2.BTj8jgKL26DrZoqy/IF9sQ==|eianAHT9NxPXh6VJe73kwg==|TlpOYI7679gwib7sq5RACueTLrjHyRufdAEdLYa0+WQ=	\N	\N	{"username": "2.qwow68fYqN5vuwdHFwHyOg==|sTJpcOmPS44IIuW3MLbClA==|PWdRSGKBMXUPnJX7YGRlf+LhQda83mr3TQAGmtqgvls=", "password": "2.nBKbhnTWthhptMyWtcUdug==|q9HTqrzSo8lEjZudpRFE8A==|CNvDk32v3TRp9vFovwCYP2Lyp/HtfQ68DTA0cAy2vZ4=", "totp": null, "uri": "2.6LYEE+BNo1omaspf90CiYw==|LmKJlzA5BH2R+bTmitYcUsOK3wTPedv8gazXshAmQLI=|/kueSCdjS7y3J8w/K2460UOVtud4BUia5c9Z4MFfsr4="}	\N	\N	\N	\N
708cf77d-6c83-4470-8a74-e347445698ff	2025-07-23 00:52:20.516642	2025-07-23 00:52:20.516642	1633c6e9-2bcb-4485-b1dd-ee017aab8d0f	\N	1	2.WB5pNBLhB1lk0kjbNwDMJw==|pgHvlw037ALFb5xSMS7F3A==|CmKIlAhngahKFEwwkRxCF/F4ceYHHwl7azCNVt1GDmw=	\N	\N	{"username": "2.7BORY0ex82DhUWmT8l88SQ==|xccfmdRFhnCUD83vmzAayw==|KaxWlpKSZnmTTz8UcLkSPupc9v0r8B1ht2jjNekteqE=", "password": "2.KC3g+fudAO1gFTCZ3S0Vcg==|9k4Sb1tEfGvCj2p8vMxJng==|7LgFVAE7KmB7wdw6VDbQTPdwxoP/LTz+JcbgQapCA4k=", "totp": null, "uri": "2.8vTQROgC7fXHsKKaBuAmVQ==|lq06IckR5GhBgt4i4c09K8Y5gSkn3QnzEYhlyZ4bLlk=|d1/B6joL5ITO0AUhFsn/jMiKQ16T0ffOE71DS8lPuFg="}	\N	\N	\N	\N
09ecff6b-9f32-473b-ad34-a1bbb29e9a5a	2025-07-23 00:52:20.517449	2025-07-23 00:52:20.517449	f5e0a8a6-01b3-4f34-8920-91a2095be48b	\N	1	2.0VjzEBhX/t8fKMjK4OhjBA==|S/G1TvphAJsfAN1qEjsSpQ==|vHhFcWw3kwiA1hZjdUvrZourZzuEizT5QQ9/lHBLtqo=	\N	\N	{"username": "2.yZPinOQAm+v3kItRj6QvcA==|gALwtcemJ+72Z20pVF3Qaw==|Vlno3dYJMS0WYw0nhkdmK8Ju3QcugIAttVsc5hTkz/E=", "password": "2.+5MFPRWRBHgqWuTtPe+V4w==|WE9IykDOs3XNSOKzXtcXxQ==|Fp1ks+AW3H/t7erreCAv0Ytrt5cbeB+DcwFVMH6Yi4k=", "totp": null, "uri": "2.obGv9KFEieLPBrYy8BZw3w==|oECLv5dFLjBd3+fP2Af6HNms2eRQE6JevT+Jg2FjS1k=|Q5NMVU4CfuSca6L2GI0dfjPFbzR+qhz8JY5nBp9Vn08="}	\N	\N	\N	\N
27c79652-bae7-43d8-993f-e42431ad1d2c	2025-07-23 00:52:20.517449	2025-07-23 00:52:20.517449	f5e0a8a6-01b3-4f34-8920-91a2095be48b	\N	1	2.rvB5y/oNEmHLw0fP6pLhHg==|tzA8XyBt27x4i9wFdJYovQ==|El2LS8HNXHoKeip3d69QnugObYO0wMjkNooeLnSziwI=	\N	\N	{"username": "2.X3MpjSAP8ttHAqqwcJ8+Mg==|0Bsl9ht58iWLJC72nOTW3Q==|BW4DXQksaKzEcoZ6jCZ4OLUCjV8ObpuXdHgsoE8tocU=", "password": "2.TebOhBfzGGwt6pY8vAoTuw==|RTG6B3chrE5BZCwfbpB5Pg==|ZyrHepux3bop6jPba3y529IygarYBKmmf0fmrcVrvkc=", "totp": null, "uri": "2.AYDSqk7tVo52KA3m8+egSA==|dMay3R+k9zKjPIOH0UMdPXF0nrNqaWEwKqtRHSgAnck=|Elhylf9ftJmh2fo06A9mDKJCZPd+bnpHMM/HNecmTLs="}	\N	\N	\N	\N
905f3ae4-a3dc-4055-b1a1-7f88ee8af4ad	2025-07-23 00:52:20.517449	2025-07-23 00:52:20.517449	f5e0a8a6-01b3-4f34-8920-91a2095be48b	\N	1	2.wiwC7IdDmwITDN+s5HqcEQ==|MZ/uXGRMBM5mFcnmp2YH+A==|Gh5upBzLhbrPIBUJdCLp6PriVNsuIUE90rmaJQbnaSM=	\N	\N	{"username": "2.h4RQjBUDGN1EmLLsODoV8w==|Qccgn0E1NlDQRb/SKXiSaw==|SvCBdiHbOCJ0/VxkaQpZ6DTkFBPIrCb/PN073OBGI9s=", "password": "2.DreUgOC9JOTJgIM6Ni3DCA==|06KKcCh01jhQ0zJqweudQQ==|Y+rFVdfnUDGOfj/hGkXSV8GKQOdLCectK7CD815dND4=", "totp": null, "uri": "2.AWFkWtvJ4znSzs0EF2FD0A==|ltz4F7eo9RejKZv1R5wBlIeUw+DoUjEkSxU8IUg+els=|5p77xlDAwX9GrP0574quekX5tJwEb7yM99OxvZPFEiQ="}	\N	\N	\N	\N
4a761a68-2973-4e21-b1bd-a2077754f9d2	2025-07-23 00:52:20.517449	2025-07-23 00:52:20.517449	f5e0a8a6-01b3-4f34-8920-91a2095be48b	\N	1	2.d7xKM57HQ2gzYDv8lNOgnQ==|gWaG2Hw6FENdMquQ0HruQw==|DyViWOlY4zkyKRszNqzy/3XqewKH45QTtAL1xIutTpU=	\N	\N	{"username": "2.UjHgjZPUm/WC/rcTYlhjvA==|amV5bX2aN/ijQxGhL73lPw==|Lc0xOglVNFNUO5u5mAuFs7dV6ATNNi3xN82ibHLrbQE=", "password": "2.UvZp4Y7uWfM4dJiCXfKe6w==|dy1sE+NetcrCSYABGEieHA==|TN8o1sreeMBx1ohmPgZ44dolPjJXEDIs8h3lfqJc7QE=", "totp": null, "uri": "2./YOxLCwdWzJeK1zLaaN/Mw==|gw1UhLahenq9nm3VmbEcrwrhknWcZe/RNuws2HeZ05w=|PIZQYJ1pHY05uuNO71JUz309l3s43tGR1Onkll4W7XI="}	\N	\N	\N	\N
039b2f78-1069-4c9e-b864-b329b7252942	2025-07-23 00:52:20.517449	2025-07-23 00:52:20.517449	f5e0a8a6-01b3-4f34-8920-91a2095be48b	\N	1	2.FTVZ0qBpsSn4MeZitUEoew==|/C+ZtEdmqyV6P50V5gw/OQ==|MMUMeGYRw/nzdMyDGWKeM12xo2+ONWvC43KKxZPvPCc=	\N	\N	{"username": "2.Jr9a19XzGUatLDhpWm1ySA==|PEeCCBwLxfqHRQcgq9CjdA==|iynvkfbTPkIbps2ygXWr6X5s2td+R3/OGFZQ41w2Gtw=", "password": "2.Rmd9+J0e7NwvgWQGi3SHkA==|ozczyjg+rLdHbF5CUKB7Ag==|S5vl/pqpiMEm0yyWwbDimSjZii4Zz0vhN2LLwRbzdYU=", "totp": null, "uri": "2.ZJtMs3OI7I2aHvCHc+xn7g==|EFoUOAtS9vl76sToWyOhY0ju6R+NL4KilAloxRJKID0=|Y4LywULhvYzxPvCNPNiXJjxeeEXqquiYzxxExF3vPfc="}	\N	\N	\N	\N
bbca83a8-5912-4464-9303-5354c055d325	2025-07-23 00:52:20.517787	2025-07-23 00:52:20.517787	aa7576b9-13d2-414c-94bb-30a9c59b9bcd	\N	1	2.6nVE0tENXpbbvWesgaZWwA==|cNJ5xLqVQ4jL/BnU0HRhnw==|Jo62xXDeciiHJiH7jUgtsh6NGczxIYm/lo20oNhDxok=	\N	\N	{"username": "2.KANm31J9gfl3Q5N2qRhphw==|rycIW9K89GjKcOlaFTiqHw==|HqC+3r+blRaovhqeL2t/v06vwOkaHteexbmOEgz+nXU=", "password": "2.8Wre8XVYMoJKiC0QlXDZtA==|DNVXD39o36S5fzFsx7arfw==|QYIVkxwhG/vGhiK3PukMcxWlDE7PG6q3uYGewo+hHSc=", "totp": null, "uri": "2.7k7/cWcm2l+dKznJhz7I+g==|OXyexIGrlQCfNepdfLXhZUrck8fBaqjDIPUzb42npao=|rMZIRsC5fwilyaXl0+4hLCtnjgNowUeH3cqj/7s7Gvk="}	\N	\N	\N	\N
a5947db0-3ab6-4dd8-bdf8-67fbca9ffa23	2025-07-23 00:52:20.517787	2025-07-23 00:52:20.517787	aa7576b9-13d2-414c-94bb-30a9c59b9bcd	\N	1	2.thq4VUvBgYREM0VEIj3P0Q==|XPQyxiltPezMnTPuiOwQgQ==|CUSv3f8a9+q7Vpc0i2XUP+mB6Q5W+7ASqWxRUqIAG+M=	\N	\N	{"username": "2.9RhP8qDHCydM6UEljIfzXw==|L6+TYS6zPf9ttlDgSIcgHQ==|FVBSl0q+urT3e/y8bCsRqk2xrr/eeeXrvx3Uy9LDI58=", "password": "2.F/ZIV6mFlKxH/zfvJM7+YQ==|V9ahfDoApkHv9WJ3g5hQjw==|F34B++8H6uS52IjdlDUm23DDFm9FIxt2d9K6r34b9aE=", "totp": null, "uri": "2.3GUUA6tW3ZYJCYu68yEakw==|z8t7orE37Rj0y4nfVAtoNaC0ZeZa6XVvzzahRjcbSvM=|9IBhdU2c4rZKLebfyxgvz0Y/uYusA+mcza45CRYrOeQ="}	\N	\N	\N	\N
8bfd5258-0b6b-4220-ace2-e0804bb5f86b	2025-07-23 00:52:20.517787	2025-07-23 00:52:20.517787	aa7576b9-13d2-414c-94bb-30a9c59b9bcd	\N	1	2.2pi9ncDu8nFETWgmkpRQ6w==|ByV7QfxJQZ6BMrCW+DmPRA==|Ig+ZF6hgc9Nb++nkduuva5+HK7qgmzry2vZEUM0k698=	\N	\N	{"username": "2.cr5w8mc0CMxMhU7i5THsZA==|CANw/jrar1MxULnxnJC6AQ==|qe8N173TPnkqTdniGYW4ryk/wEoqPaNyPs034olHrGA=", "password": "2.685mj/N8I3QUP5rtdce+2w==|oNosdvAR/zg4Shgdug6oGQ==|EhWeIRSu/ttpOOMrD/YGUmsr8pekPcU5iFQmeMP6Dl8=", "totp": null, "uri": "2.qLpV0glC8EEM6VfMT9gPiA==|9wRAECYy9UvzYl9jBd9fdvmF/PlZ1b5mee3k8nhEjrg=|kDDbCc3XY260oZWUZ9fxogWAvC3qjqpiBuVqHru7dYc="}	\N	\N	\N	\N
fa0214b3-09e2-4512-9fed-c0a26ba52365	2025-07-23 00:52:20.517787	2025-07-23 00:52:20.517787	aa7576b9-13d2-414c-94bb-30a9c59b9bcd	\N	1	2.a9hX2ph/HprXNEuJXF+lww==|0lmGIQ6lKd6tXEcquBX7Iw==|ARslRF5cVcpV0yPlQ0z2Ub9AGGzfQZukcjiQGTQAQFA=	\N	\N	{"username": "2.GIKFPg6CjvJ8Cg5MQ8R5JQ==|JjtCS51JavfRsy7N+9GwsQ==|0HUj2r/W5dcmOMF2rDdm4TswiDI4S2ZJQDH9/mQnkJ8=", "password": "2.rL6U9+9JLblB98Y6bHzI/g==|nmJtcv1oSqZrpCOdhGtAdQ==|R1GAzXzTeifu0J8KvSASVMoR9zM8EyMOG6jlxJPHhEA=", "totp": null, "uri": "2.UsutST/xpNjcJRvVnso3Cg==|62SaW3+Itevvd92JU+TFLyf3QWsdfus7NnFZyrmU238=|jQiZPpXgxvmUURMj/HPoBjXBgB1dfl6gCHSDBVNyU4U="}	\N	\N	\N	\N
24ed06b7-bb66-4d48-8c23-85020e7beee3	2025-07-23 00:52:20.517787	2025-07-23 00:52:20.517787	aa7576b9-13d2-414c-94bb-30a9c59b9bcd	\N	1	2.gNL+lkzMrYK0jzETHw7jWg==|BaQwtpRvjFgyZBBNz6r02g==|VfnwcSCgMziPmfrslJ4bRVV60GAUklLBkipBpib2EkQ=	\N	\N	{"username": "2.9dmzsQouVv7tADaNS+xtgg==|v/2bRuavmjXhQct5QA5fEw==|wF/kjxv/1wlTYEQsFbGthQBg1RRJCCU9SYqDFuYL6dM=", "password": "2.kdIHdJFckRrcZp+auJeTMw==|DBhOFid7jUxKlIy+FvXocw==|JHBlRkR1QRqIXuT5WY+/cNkYSSH9O50tZNWKCejTTIE=", "totp": null, "uri": "2.iY0XveVyRmB4Z1P/R5xISw==|GBezA98CkbgPw787RADsoCJpnq9j0xP0cnkLUrcYB8A=|CfLaKZROEh67p1lT0XjvByh0bpGAY/Qyj4sHL3sDMPs="}	\N	\N	\N	\N
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
2189d335-6163-489c-b060-a0715296dba4	2025-07-23 00:57:29.073823	2025-07-23 00:57:29.110005	fab18d58-26f1-4059-ae47-0845bde2705c	chrome	9	\N	zmosVB37rP7GIFrWSJuEPP5utHfauOVdrlV1BSrlsG0QFunUH57rR6MqTq_hCzrA1Tz0WFcuPPHlnq1tLUjYog==	\N	ee706978-7eed-40c4-bb5e-56e859cd5eba
8434ef05-2493-4e5e-a463-281b7d78875e	2025-07-23 00:57:48.845969	2025-07-23 00:57:48.85621	fab18d58-26f1-4059-ae47-0845bde2705c	sdk_gphone64_arm64	0	\N	IQjU1v-g1Qzuaml-n-vPWP2Znq6-ci97Tud0EUdrv0d3n1_8l7oPq2ROs4YHuhZ1OJLLmKq3FGRLrhSSFA3fxQ==	\N	8c19c32c-fcdc-49fb-9f60-8a4eed3b6ae4
2189d335-6163-489c-b060-a0715296dba4	2025-07-23 01:01:04.671776	2025-07-23 01:01:04.690593	3c1a8c0a-038c-48e2-8bd9-a72afb168ff8	chrome	9	\N	7N3N966S7ekbPjvKV5Eb5Ayq0NphP2GqmRv0PIVlTRXGxDLGWIMZe3Anfi17xrKQf8G_xmbWmSGGTqZdO3fveg==	\N	15e72da5-9c47-4ced-804f-f861edf7360d
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
1633c6e9-2bcb-4485-b1dd-ee017aab8d0f	2025-07-23 00:52:20.515431	2025-07-23 00:52:20.515431	user1@example.com	User 1	\\xd6541529bd54a69b962408ce8362d3771e138bb15baf782535e9d5d214412591	\\x77210fc1b6b7fa5db302de486dec5dd37305d6a6a79d52a055a69760636dc8da987115a84455ea173e4b2675043146f1041c1568f090f73c4204793a8d6d0a80	600000	\N	2.tNka2/6nvNE8CpV1S6wyOQ==|BTsB7yrsER1/bQQLBREMV0CuLeH/0Gs4tUMmyjuGcK36a8wUk7SnxWT536yaOhEG|4+AH+tS1DJvXIeHZj3TM99duLkULoTasegDMR62Xds0=	2.kIQf0RKPnYmgFd4BT1/LzQ==|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	\N	\N	43337d19-6480-4a57-a224-984752b48493	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
f5e0a8a6-01b3-4f34-8920-91a2095be48b	2025-07-23 00:52:20.515431	2025-07-23 00:52:20.515431	user2@example.com	User 2	\\xf68806a82eeff4400ecea91256cae7c5f0477ac319ca99b7135bb49353386adf	\\xf99e44e4899be8c24361f8a36cbf81c4eecb485f505282335224377dd0a50a2b720f8decb0b27ad3245618a67657ed773a7081f69924d187554be789856d10ef	600000	\N	2.8syTRL7yRzdXLH191OwdhA==|SKjDCx4bk/TCWEb8UXV3r7JcpU0jYTNcr6q3ERd3nYmphAKyfyZUurzOHQqbv9qK|5MgMir9nT2nlAAQwyjLEXt/w3tShPfEbHdbH9fT28Y0=	2.HhHKr8hWB0H/Jry//R3Urw==|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	\N	\N	da970f51-567e-4d8e-8fd7-7f9600a69264	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
aa7576b9-13d2-414c-94bb-30a9c59b9bcd	2025-07-23 00:52:20.515431	2025-07-23 00:52:20.515431	user3@example.com	User 3	\\x49ace07fc884340581a0fd00c5b7e62728553bf24a67c136eaa8aa9133977f49	\\xa50a09746dbc2cf28e68f64918cfca82932093755af08946b9afebaefa8b322196a0a8c10a360769dddb91e50c68a56dc2182445ff5c5bad4892fbd8d96af4e2	600000	\N	2.KVy5PIOYT4MZaT0BUGpeUg==|0S/ZhBXaOmZbqKr2AA3PfAw0SyOCrISAaoAoIiOcRLt7EArxV60w6hM81xQLFvtR|8Ume/y5jsZ2YEiJX2qy5JgfO/p1/+TStPeClHNd8gy4=	2.ip0Ng8QaBq+xC5kNQMMzLA==|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	\N	\N	5fdd9d13-911b-4b83-b241-ee437c14e9ef	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
fab18d58-26f1-4059-ae47-0845bde2705c	2025-07-23 00:57:28.842869	2025-07-23 00:57:28.91831	user4@example.com	User 4	\\x4cbc40dc6e2a8e1711f79a97e409c59e0ad32e8895cc93ae07b6ba2e8f0a3bf9	\\x6c21337a2f01fe32ff98f6b264f5562f27ba19a4c7f91034b26b76f058ed3c35f0dafd4f53c127e691886ec0830ed3f27fc345387a7a2d3a5018a98e5fe64688	600000	\N	2.ZWwJtDqfJeJhoLruN1rzRA==|7M7iPtevVPkusIN/Ccly2Hr754SAhh2lwfjTorNUAZEFw+Gcb/PgJdzXVO+tMxqqrtHWe7KkA6Nceh4/j2YNMlEAkRktzDOmGo9d8HvXPD8=|ABjpYX0XbrMS1aKOcbofl/aSz7GLcnkFaVgA3IktK/0=	2.K3eEeH1M0NasWyjyzjagqw==|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	\N	\N	37ddede4-57a4-4ed9-aa18-9817dd74b38c	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
3c1a8c0a-038c-48e2-8bd9-a72afb168ff8	2025-07-23 01:01:04.435641	2025-07-23 01:01:04.50946	user5@example.com	User 5	\\x930b02204fc7a2036fd066d8645354327f2db0e3fab51b24fc932c605afa01bc	\\xb3ff4cb3a72fdfe5db3edc901b2f1f61fb19ae28ca3a20431b040d15f04828db10142d4529475039b0aeeb0df6fca9c389dd579d56737b56f604e192fefc2f23	600000	\N	2.VGQyIwovhH4u1GGRXH1PAQ==|Qc0MJZwH+CLdLjRmo5/rgtP6kESXJGxT65EJ/SjmYc60AB8lPVU///S/nbU23Z/QHRYUWWr5dsoYJhQyEpwtSMbCIXm+H9UD0VvJyYSJ2xE=|X5gxEAQjPK0v4QbK7sZmO63IZANl40yLpRlWsm4U+bU=	2.z1c39i5Avp4qU2nOWsRWvw==|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	\N	\N	e5177c46-f9eb-4992-a136-ba46a7cd9bbf	[]	[]	0	600000	\N	\N	0	\N	\N	t	\N	\N	\N	\N	\N	\N
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

