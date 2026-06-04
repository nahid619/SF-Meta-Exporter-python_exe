"""
Salesforce OAuth 2.0 Authorization Code + PKCE Flow
=====================================================

Login happens inside a self-contained popup window (pywebview) owned by
the desktop app.  No system browser tab is opened.

Threading model
---------------
pywebview.start() MUST be called from the OS main thread and it BLOCKS
until all webview windows are closed.  This file exposes two methods:

    flow = OAuthWebFlow(domain=..., status_callback=...)

    # Must be called on the MAIN thread — call it via self.after(0, ...)
    # from Tkinter.  It blocks until the login popup closes, then calls
    # callback(("code", auth_code)) or callback(("error", message)).
    flow.open_window(callback)

    # Can be called on any thread — pure HTTP, no GUI.
    token_data = flow.exchange_code(auth_code)

gui.py uses:
    self.after(0, lambda: flow.open_window(callback=_on_webview_done))

so that open_window() — and therefore webview.start() — runs on the
Tkinter main thread.  The main window is unresponsive while the login
popup is open (acceptable; user is interacting with the popup), and
Tkinter resumes the moment webview.start() returns.

pywebview version
-----------------
Targets pywebview 5.x / 6.x on Windows (EdgeChromium / WebView2 backend).
Uses win.events.request_sent (replaces the removed win.events.navigating).

Dependencies
------------
    pip install pywebview

PyInstaller
-----------
Use your normal build command unchanged:
    pyinstaller --onefile --windowed --name "SF Meta Exporter" --icon=app_icon.ico main.py
"""

import hashlib
import base64
import secrets
import threading
import time
from typing import Optional, Callable
from urllib.parse import urlencode, urlparse, parse_qs

import requests

from config import get_oauth_client_id


# ─────────────────────────────────────────────────────────────────────────────
# PKCE helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generate_pkce_pair():
    verifier  = secrets.token_urlsafe(64)
    digest    = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ─────────────────────────────────────────────────────────────────────────────
# HTML pages shown inside the popup
# ─────────────────────────────────────────────────────────────────────────────

_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:#f0f4f8;display:flex;align-items:center;
  justify-content:center;min-height:100vh}
.card{background:#fff;border-radius:16px;padding:48px 56px;text-align:center;
  box-shadow:0 4px 24px rgba(0,0,0,.10);max-width:420px}
.icon{font-size:64px;margin-bottom:18px}
h2{color:#1a7a4a;font-size:22px;margin-bottom:10px}
p{color:#555;font-size:15px;line-height:1.6}
.note{margin-top:18px;color:#888;font-size:13px}
</style></head><body>
<div class="card">
  <div class="icon">&#x2705;</div>
  <h2>Login Successful!</h2>
  <p>You are now connected to Salesforce.</p>
  <p class="note">This window will close automatically&hellip;</p>
</div></body></html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:#f0f4f8;display:flex;align-items:center;
  justify-content:center;min-height:100vh}}
.card{{background:#fff;border-radius:16px;padding:48px 56px;text-align:center;
  box-shadow:0 4px 24px rgba(0,0,0,.10);max-width:480px}}
.icon{{font-size:64px;margin-bottom:18px}}
h2{{color:#c0392b;font-size:22px;margin-bottom:10px}}
p{{color:#555;font-size:14px;line-height:1.6}}
</style></head><body>
<div class="card">
  <div class="icon">&#x274c;</div>
  <h2>Login Failed</h2>
  <p><b>{error}</b><br>{desc}</p>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

class OAuthWebFlow:
    """
    Salesforce OAuth 2.0 Authorization Code + PKCE using a pywebview popup.

    See module docstring for threading requirements.
    """

    REDIRECT_URI = "http://localhost:8888/callback"
    _TIMEOUT     = 300   # seconds

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

        # PKCE pair generated once — shared between open_window and exchange_code
        self._verifier, self._challenge = _generate_pkce_pair()

    def _log(self, msg: str):
        if self.status_callback:
            self.status_callback(msg, verbose=True)

    # ------------------------------------------------------------------
    def open_window(self, callback: Callable) -> None:
        """
        Open the Salesforce login popup.

        MUST be called from the main thread.
        Blocks until the popup closes, then calls callback with the result.

        callback receives ("code", auth_code) on success
                      or  ("error", message)  on failure
        """
        # ── import webview ─────────────────────────────────────────────
        try:
            import webview
        except ImportError as exc:
            callback(("error",
                f"pywebview import failed: {exc}\n\n"
                "Run:  pip install pywebview\n"
                "Then restart the application."))
            return
        except Exception as exc:
            callback(("error",
                f"pywebview failed to load: {exc}\n\n"
                "This is usually caused by a missing Microsoft WebView2 Runtime.\n"
                "Download it from:\n"
                "  https://developer.microsoft.com/microsoft-edge/webview2/"))
            return

        org_label = {
            "login": "Production / Developer Edition",
            "test":  "Sandbox",
        }.get(self.domain, self.domain)

        auth_url = (
            f"{self.base_url}/services/oauth2/authorize?"
            + urlencode({
                "response_type":         "code",
                "client_id":             self.client_id,
                "redirect_uri":          self.REDIRECT_URI,
                "code_challenge":        self._challenge,
                "code_challenge_method": "S256",
            })
        )

        self._log(f"Opening Salesforce {org_label} login window...")
        self._log("  Log in with your username and password.")
        self._log("  The window will close automatically when done.")

        # State shared between event handlers
        result_holder: list = []    # filled by on_request_sent or on_closed
        handled       = threading.Event()
        window_ref: list  = []
        callback_parsed   = urlparse(self.REDIRECT_URI)

        # ── request_sent handler (pywebview 5+/6.x) ───────────────────
        def on_request_sent(request):
            if handled.is_set():
                return
            try:
                url_str = request.url if hasattr(request, "url") else str(request)
            except Exception:
                return

            parsed = urlparse(url_str)
            if not (parsed.scheme == callback_parsed.scheme and
                    parsed.netloc == callback_parsed.netloc and
                    parsed.path   == callback_parsed.path):
                return

            handled.set()
            params = parse_qs(parsed.query)

            if "code" in params:
                result_holder.append(("code", params["code"][0]))
                # Show success page, then destroy window after brief pause
                if window_ref:
                    try:
                        window_ref[0].load_html(_SUCCESS_HTML)
                    except Exception:
                        pass
                def _close():
                    time.sleep(1.4)
                    try:
                        if window_ref:
                            window_ref[0].destroy()
                    except Exception:
                        pass
                threading.Thread(target=_close, daemon=True).start()

            else:
                error = params.get("error",             ["unknown"])[0]
                desc  = params.get("error_description", ["No details"])[0]
                result_holder.append(("error", f"{error}: {desc}"))
                if window_ref:
                    try:
                        window_ref[0].load_html(
                            _ERROR_HTML.format(
                                error=error,
                                desc=desc.replace("+", " "),
                            )
                        )
                    except Exception:
                        pass
                def _close_err():
                    time.sleep(2.0)
                    try:
                        if window_ref:
                            window_ref[0].destroy()
                    except Exception:
                        pass
                threading.Thread(target=_close_err, daemon=True).start()

        # ── closed handler — user closed popup manually ────────────────
        def on_closed():
            if not handled.is_set():
                handled.set()
                result_holder.append(("error",
                    "Login window was closed before completing.\n\n"
                    "Please click 'Login via Browser' again."))

        # ── timeout watchdog ───────────────────────────────────────────
        def _timeout_watchdog():
            if handled.wait(timeout=self._TIMEOUT):
                return          # completed normally
            # timed out — force-close the window
            handled.set()
            result_holder.append(("error",
                "Login timed out (5 minutes).\n\n"
                "Please click 'Login via Browser' again."))
            try:
                if window_ref:
                    window_ref[0].destroy()
            except Exception:
                pass
        threading.Thread(target=_timeout_watchdog, daemon=True).start()

        # ── create window ──────────────────────────────────────────────
        try:
            win = webview.create_window(
                title         = f"Salesforce Login \u2014 {org_label}",
                url           = auth_url,
                width         = 520,
                height        = 700,
                resizable     = False,
                on_top        = True,
                confirm_close = False,
            )
        except Exception as exc:
            callback(("error", f"Could not create login window: {exc}"))
            return

        window_ref.append(win)
        win.events.request_sent += on_request_sent
        win.events.closed       += on_closed

        # ── START THE EVENT LOOP — runs on this (main) thread ─────────
        # webview.start() BLOCKS here until win.destroy() is called.
        # The main Tkinter window is unresponsive during this time,
        # which is acceptable — the user interacts with the popup.
        # Tkinter resumes the moment webview.start() returns.
        try:
            webview.start(debug=False)
        except Exception as exc:
            if not handled.is_set():
                handled.set()
                result_holder.append(("error", f"Login window error: {exc}"))

        # ── deliver result to caller ───────────────────────────────────
        if result_holder:
            callback(result_holder[0])
        else:
            callback(("error",
                "Login window closed without a result.\n\n"
                "Please click 'Login via Browser' again."))

    # ------------------------------------------------------------------
    def exchange_code(self, auth_code: str) -> dict:
        """
        Exchange the authorization code for access/refresh tokens.
        Safe to call from any thread — pure HTTP, no GUI.
        """
        self._log("Completing authentication...")

        resp = requests.post(
            f"{self.base_url}/services/oauth2/token",
            data={
                "grant_type":    "authorization_code",
                "code":          auth_code,
                "client_id":     self.client_id,
                "redirect_uri":  self.REDIRECT_URI,
                "code_verifier": self._verifier,
            },
            timeout=30,
        )

        if resp.status_code != 200:
            raise Exception(
                f"Login failed at token exchange (HTTP {resp.status_code}).\n"
                f"Details: {resp.text[:400]}"
            )

        data = resp.json()
        if "error" in data:
            raise Exception(
                f"Token exchange error: {data.get('error_description', data['error'])}"
            )
        if "access_token" not in data or "instance_url" not in data:
            raise Exception(
                f"Unexpected response from Salesforce.\nResponse: {str(data)[:400]}"
            )

        self._log("Authentication complete.")
        return data