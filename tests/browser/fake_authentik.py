"""Loopback-only OAuth provider for the portal browser test."""

import base64
import hashlib
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit


class FakeAuthentik(HTTPServer):
    def __init__(self, email):
        super().__init__(("127.0.0.1", 0), ProviderHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.issuer = self.origin + "/application/o/bulsca/"
        self.callback = None
        self.email = email
        self.subject = secrets.token_hex(16)
        self.client_id = "portal-browser-test"
        self.secret = secrets.token_urlsafe(24)
        self.codes = {}
        self.active_tokens = set()
        self.revoked = False


class ProviderHandler(BaseHTTPRequestHandler):
    # Never log authorization parameters or bearer tokens.
    def log_message(self, *_):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        provider = self.server
        url = urlsplit(self.path)
        params = dict(parse_qsl(url.query))
        if url.path == "/application/o/authorize/":
            valid = (
                params.get("client_id") == provider.client_id
                and params.get("redirect_uri") == provider.callback
                and params.get("response_type") == "code"
                and set(params.get("scope", "").split()) >= {"openid", "profile", "email"}
                and params.get("code_challenge_method") == "S256"
                and params.get("code_challenge")
                and params.get("state")
            )
            if not valid:
                return self.reply(400, {"error": "invalid_request"})
            code = secrets.token_urlsafe(32)
            provider.codes[code] = params["code_challenge"]
            self.send_response(302)
            self.send_header("Location", provider.callback + "?" + urlencode({
                "code": code, "state": params["state"], "iss": provider.issuer,
            }))
            self.end_headers()
        elif url.path == "/application/o/userinfo/":
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] not in provider.active_tokens:
                return self.reply(401, {"error": "invalid_token"})
            self.reply(200, {"sub": provider.subject, "email": provider.email,
                             "name": "Browser Manager", "email_verified": True})
        else:
            self.reply(404, {})

    def do_POST(self):
        provider = self.server
        form = dict(parse_qsl(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()))
        basic = base64.b64encode(f"{provider.client_id}:{provider.secret}".encode()).decode()
        if not ((form.get("client_id"), form.get("client_secret")) == (provider.client_id, provider.secret)
                or self.headers.get("Authorization") == "Basic " + basic):
            return self.reply(401, {"error": "invalid_client"})
        if self.path == "/application/o/token/":
            verifier = form.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if (form.get("grant_type") != "authorization_code" or form.get("redirect_uri") != provider.callback
                    or not verifier or provider.codes.pop(form.get("code"), None) != challenge):
                return self.reply(400, {"error": "invalid_grant"})
            token = secrets.token_urlsafe(32)
            provider.active_tokens.add(token)
            self.reply(200, {"access_token": token, "token_type": "Bearer", "expires_in": 3600})
        elif self.path == "/application/o/revoke/" and form.get("token") in provider.active_tokens:
            provider.active_tokens.remove(form["token"])
            provider.revoked = True
            self.reply(200, {})
        else:
            self.reply(404, {})
