import ssl, smtplib, email.utils

HOST, PORT = "127.0.0.1", 465  # SMTPS
USERS = [
    ("usera@test.com","userAPW123"),
    ("alex@test.com","alexpass"),
    ("bob@test.com","bobpass"),
]

def send(to_addr, auth):
    from_addr = "noreply@test.com"
    msg = f"""From: Test Seeder <{from_addr}>
To: <{to_addr}>
Subject: Welcome {to_addr.split('@')[0]}
Message-ID: <seed-{to_addr}-1@test.com>
Date: {email.utils.formatdate(localtime=True)}

Hello {to_addr}, this is a seeded message.
Token: TKN-{to_addr.split('@')[0].upper()}-001
"""
    ctx = ssl.create_default_context()
    # For self-signed local CA: uncomment and point to your CA
    # ctx.load_verify_locations("dms-ssl/ssl/demoCA/cacert.pem")
    with smtplib.SMTP_SSL(HOST, PORT, context=ctx) as s:
        s.login(*auth)
        s.sendmail(from_addr, [to_addr], msg)

for user, pw in USERS:
    send(user, (user, pw))
print("Seeded messages via SMTP.")
