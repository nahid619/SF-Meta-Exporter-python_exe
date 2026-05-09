"""
Salesforce OAuth 2.0 Authorization Code + PKCE Flow — Approach 2
=================================================================

In this approach each user creates their own External Client App (ECA)
in THEIR Salesforce org once, then pastes the Consumer Key into the app's
settings dialog. The key is saved to sfmetaexporter_settings.json next to
the .exe and reused on every subsequent login.

Flow per user (one-time setup):
  1. User clicks ⚙️ next to "Login via Browser"
  2. Dialog shows 10-step instructions to create an ECA in their org
  3. User creates the ECA, copies the Consumer Key, pastes it, clicks Save
  4. From now on: click "Login via Browser" → browser opens → log in → done

Works for Production, Developer Edition, Sandbox, and Custom Domain.
No client secret needed (PKCE handles security without one).
"""

import hashlib
import base64
import socket
import secrets
import webbrowser
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from typing import Optional, Callable

from config import get_oauth_client_id, OAUTH_REDIRECT_PORT_RANGE


# ─────────────────────────────────────────────────────────────────────────────
# PKCE helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generate_pkce_pair():
    verifier  = secrets.token_urlsafe(64)
    digest    = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ─────────────────────────────────────────────────────────────────────────────
# Local callback HTTP handler
# ─────────────────────────────────────────────────────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            self.server.auth_code  = params["code"][0]
            self.server.auth_error = None
            body = (
                "<html><body style='font-family:-apple-system,sans-serif;"
                "text-align:center;padding:80px;background:#f4f6f9'>"
                "<div style='background:#fff;border-radius:12px;padding:48px;"
                "box-shadow:0 2px 16px rgba(0,0,0,.1);display:inline-block'>"
                "<div style='font-size:64px'>&#x2705;</div>"
                "<h2 style='color:#1a7a4a;margin:16px 0 8px'>Login Successful!</h2>"
                "<p style='color:#555;font-size:16px'>"
                "You can close this tab and return to "
                "<strong>SFMetaExporter</strong>.</p>"
                "</div></body></html>"
            ).encode()
            self._respond(200, body)
        else:
            error = params.get("error",             ["unknown"])[0]
            desc  = params.get("error_description", ["No details"])[0]
            self.server.auth_code  = None
            self.server.auth_error = f"{error}: {desc}"
            body = (
                "<html><body style='font-family:-apple-system,sans-serif;"
                "text-align:center;padding:80px;background:#f4f6f9'>"
                "<div style='background:#fff;border-radius:12px;padding:48px;"
                "box-shadow:0 2px 16px rgba(0,0,0,.1);display:inline-block'>"
                "<div style='font-size:64px'>&#x274c;</div>"
                f"<h2 style='color:#c0392b'>Login Failed</h2>"
                f"<p style='color:#555'><b>{error}</b><br>{desc}</p>"
                "<p style='color:#888'>Close this tab and try again.</p>"
                "</div></body></html>"
            ).encode()
            self._respond(400, body)

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

class OAuthWebFlow:
    """
    Salesforce OAuth 2.0 Authorization Code + PKCE flow.

    Reads Consumer Key from the local settings file via get_oauth_client_id().

    Parameters
    ----------
    domain : str
        "login"  -> Production / Developer Edition
        "test"   -> Sandbox
        custom   -> e.g. "mycompany.my.salesforce.com"

    status_callback : callable(message: str, verbose: bool), optional
    """

    _TIMEOUT = 300

    def __init__(self, domain: str = "login",
                 status_callback: Optional[Callable] = None):
        self.domain          = domain.strip()
        self.status_callback = status_callback
        self.client_id       = get_oauth_client_id()

        if not self.client_id:
            raise Exception(
                "No Consumer Key found.\n\n"
                "Please complete the one-time setup:\n"
                "Click the \u2699 icon next to 'Login via Browser'\n"
                "and follow the steps to create an External Client App\n"
                "in your Salesforce org."
            )

        if self.domain in ("login", "test"):
            self.base_url = f"https://{self.domain}.salesforce.com"
        else:
            host = self.domain
            if not (host.endswith(".salesforce.com") or host.endswith(".force.com")):
                host = f"{host}.salesforce.com"
            self.base_url = f"https://{host}"

    def _log(self, msg: str):
        if self.status_callback:
            self.status_callback(msg, verbose=True)

    @staticmethod
    def _free_port() -> int:
        for port in OAUTH_REDIRECT_PORT_RANGE:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("localhost", port))
                    return port
                except OSError:
                    continue
        raise RuntimeError(
            f"No free local port in range "
            f"{OAUTH_REDIRECT_PORT_RANGE.start}-{OAUTH_REDIRECT_PORT_RANGE.stop - 1}.\n"
            "Close other applications and try again."
        )

    def authenticate(self) -> dict:
        verifier, challenge = _generate_pkce_pair()
        port         = self._free_port()
        redirect_uri = f"http://localhost:{port}/callback"

        auth_url = (
            f"{self.base_url}/services/oauth2/authorize?"
            + urlencode({
                "response_type":         "code",
                "client_id":             self.client_id,
                "redirect_uri":          redirect_uri,
                "code_challenge":        challenge,
                "code_challenge_method": "S256",
            })
        )

        server            = HTTPServer(("localhost", port), _CallbackHandler)
        server.auth_code  = None
        server.auth_error = None
        server.timeout    = self._TIMEOUT

        org_label = {
            "login": "Production / Developer Edition",
            "test":  "Sandbox",
        }.get(self.domain, self.domain)

        self._log(f"Opening Salesforce {org_label} login in your browser...")
        self._log("  Log in with your username and password.")
        self._log("  First time: Salesforce will ask you to allow access — click Allow.")
        self._log("  If MFA is required, complete it — won't be asked again next time.")
        webbrowser.open(auth_url)

        self._log("Waiting for browser login (up to 5 minutes)...")
        server.handle_request()

        if server.auth_error:
            raise Exception(
                f"Salesforce rejected the login:\n{server.auth_error}\n\n"
                "Common causes:\n"
                "• Wrong org type selected (Production vs Sandbox)\n"
                "• Consumer Key does not match this org's External Client App\n"
                "• Callback URL http://localhost:8888/callback not registered in the ECA"
            )
        if not server.auth_code:
            raise Exception(
                "Browser login timed out or was closed before completing.\n"
                "Please try again."
            )

        self._log("Completing login...")
        resp = requests.post(
            f"{self.base_url}/services/oauth2/token",
            data={
                "grant_type":    "authorization_code",
                "code":          server.auth_code,
                "client_id":     self.client_id,
                "redirect_uri":  redirect_uri,
                "code_verifier": verifier,
            },
            timeout=30,
        )

        if resp.status_code != 200:
            raise Exception(
                f"Login failed at final step (HTTP {resp.status_code}).\n"
                f"Details: {resp.text[:400]}"
            )

        data = resp.json()
        if "error" in data:
            raise Exception(
                f"Login error: {data.get('error_description', data['error'])}"
            )
        if "access_token" not in data or "instance_url" not in data:
            raise Exception(
                f"Unexpected response from Salesforce.\n"
                f"Response: {str(data)[:400]}"
            )

        self._log("Browser login complete.")
        return data
