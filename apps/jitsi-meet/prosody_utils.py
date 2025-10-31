import base64
import random
import subprocess
import xml.etree.ElementTree as ET

import requests


def send_xml(
    url: str, xml_str: str, headers: dict, verify_ssl: bool, timeout: int = 8
) -> requests.Response:
    resp = requests.post(
        url,
        data=xml_str.encode("utf-8"),
        headers=headers,
        timeout=timeout,
        verify=verify_ssl,
    )
    resp.raise_for_status()
    return resp


def create_bosh_body(rid: int, attrs: dict = None) -> ET.Element:
    attrs = dict(attrs or {})
    base = {
        "rid": str(rid),
        "xmlns": "http://jabber.org/protocol/httpbind",
    }
    base.update(attrs)
    return ET.Element("body", base)


def xml_to_text(elem: ET.Element) -> str:
    return ET.tostring(elem, encoding="unicode")


def parse_sid_and_mechanisms(resp_text: str):
    # parse XML and extract sid and SASL mechanisms (if present)
    root = ET.fromstring(resp_text)
    sid = root.attrib.get("sid")
    # find mechanisms under the SASL namespace
    mech_node = root.find(".//{urn:ietf:params:xml:ns:xmpp-sasl}mechanisms")
    mechs = []
    if mech_node is not None:
        mechs = [
            m.text
            for m in mech_node.findall("{urn:ietf:params:xml:ns:xmpp-sasl}mechanism")
        ]
    return sid, mechs, root


def bosh_plain_login(
    bosh_url: str,
    domain: str,
    username: str,
    password: str,
    use_https: bool = False,
    verify_ssl: bool = False,
) -> bool:
    """
    Attempt BOSH login using SASL PLAIN.
    - bosh_url: full URL to /http-bind (e.g. "http://localhost:5280/http-bind" or "https://localhost:5281/http-bind")
    - domain: the XMPP domain (e.g. "meet.jitsi")
    - username/password: credentials to test
    - use_https / verify_ssl: control verify flag (verify_ssl=False for self-signed certs)
    - host_header: optional HTTP Host header (use "meet.jitsi" when connecting to localhost)
    Returns True on success, False otherwise. Prints debug info.
    """
    headers = {"Content-Type": "text/xml; charset=utf-8"}

    # 1) Start BOSH session (initial <body ... xmpp:version='1.0' xmlns:xmpp='urn:xmpp:xbosh' />)
    rid = random.randint(1000000, 9999999)
    init_attrs = {
        "to": domain,
        "xml:lang": "en",
        "wait": "60",
        "hold": "1",
        "ver": "1.6",
        "xmpp:version": "1.0",
        "xmlns:xmpp": "urn:xmpp:xbosh",
    }
    body = create_bosh_body(rid, attrs=init_attrs)
    xml = xml_to_text(body)
    # print("=== Initial BOSH body ===")
    # print(xml)
    try:
        resp = send_xml(bosh_url, xml, headers, verify_ssl)
    except Exception:
        # print("Initial BOSH request failed:", e)
        return False

    # print("=== Initial BOSH response ===")
    # print(resp.text)
    sid, mechs, root = parse_sid_and_mechanisms(resp.text)
    # print("SID:", sid)
    # print("Mechanisms offered:", mechs)

    # 2) Send SASL PLAIN auth: auth string is \0username\0password base64-encoded
    rid += 1
    auth_str = "\x00{0}\x00{1}".format(username, password)
    auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")

    auth_body = create_bosh_body(rid, attrs={"sid": sid})
    auth_elem = ET.SubElement(auth_body, "auth")
    auth_elem.set("xmlns", "urn:ietf:params:xml:ns:xmpp-sasl")
    auth_elem.set("mechanism", "PLAIN")
    auth_elem.text = auth_b64
    xml_auth = xml_to_text(auth_body)
    # print("=== Auth BOSH body ===")
    # print(xml_auth)

    try:
        resp2 = send_xml(bosh_url, xml_auth, headers, verify_ssl)
    except Exception:
        # print("Auth BOSH request failed:", e)
        return False

    # print("=== Auth response ===")
    # print(resp2.text)

    # success indicated by <success xmlns='urn:ietf:params:xml:ns:xmpp-sasl'/>
    if "<success" in resp2.text:
        # print("AUTH SUCCESS")
        return True
    else:
        # print("AUTH FAILED")
        return False


def check_user_login(user: str, password: str) -> bool:
    bosh_url = "http://localhost:5280/http-bind"
    return bosh_plain_login(
        bosh_url,
        domain="auth.meet.jitsi",
        username=user,
        password=password,
        verify_ssl=False,
    )


def get_prosody_container():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    containers = result.stdout.splitlines()
    for name in containers:
        if "prosody" in name:
            return name
    return None


def check_web_up():
    try:
        r = requests.get("https://localhost:8443", verify=False, timeout=5)
        return r.status_code == 200
    except Exception:
        return False
