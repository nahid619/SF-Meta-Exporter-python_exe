"""
Main GUI application for Salesforce Picklist & Metadata Exporter
"""
import os
import time
import tkinter as tk
from datetime import datetime
from typing import Optional, Set, List
from tkinter import messagebox, filedialog, END
from threading_helper import ThreadHelper
import customtkinter as ctk

from config import WINDOW_TITLE, APPEARANCE_MODE, COLOR_THEME, get_oauth_client_id, set_oauth_client_id
from config import DEFAULT_PICKLIST_FILENAME, DEFAULT_METADATA_FILENAME, DEFAULT_CONTENTDOCUMENT_FILENAME, DEFAULT_ATTACHMENT_FILENAME
from salesforce_client import SalesforceClient
from oauth_handler import OAuthWebFlow
from picklist_exporter import PicklistExporter
from metadata_exporter import MetadataExporter
from content_document_exporter import ContentDocumentExporter
from attachment_exporter import AttachmentExporter
from utils import format_runtime, print_picklist_statistics, print_metadata_statistics, print_content_document_statistics

from soql_runner import SOQLRunner
from soql_query_frame import SOQLQueryFrame

from metadata_switch_manager import MetadataSwitchManager
from salesforce_switch_frame import SalesforceSwitchFrame

# ✅ NEW - Report Exporter Module
from report_exporter.main_app import SalesforceExporterApp


# Set appearance mode and default color theme
ctk.set_appearance_mode(APPEARANCE_MODE)
ctk.set_default_color_theme(COLOR_THEME)


# gui.py - ADD THIS RIGHT AFTER IMPORTS
class ButtonStateManager:
    """
    Centralized manager for all operation buttons.
    Ensures only one operation can run at a time.
    """
    
    def __init__(self, gui_instance):
        self.gui = gui_instance
        self.operation_running = False
        self.current_operation = None
        self._buttons = {}
    
    def register_buttons(self, buttons_dict):
        """
        Register all operation buttons.
        
        Args:
            buttons_dict: {'picklist': btn, 'metadata': btn, ...}
        """
        self._buttons = buttons_dict
    
    def start_operation(self, operation_name: str) -> bool:
        """
        Start an operation. Returns False if another operation is running.
        """
        if self.operation_running:
            messagebox.showwarning(
                "Operation in Progress",
                f"Cannot start {operation_name}.\n\n"
                f"{self.current_operation} is currently running.\n"
                f"Please wait for it to complete."
            )
            return False
        
        self.operation_running = True
        self.current_operation = operation_name
        
        # Disable ALL buttons
        self._set_all_buttons_state("disabled")
        
        return True
    
    def end_operation(self):
        """End current operation and re-enable all buttons."""
        self.operation_running = False
        self.current_operation = None
        
        # Re-enable ALL buttons
        self._set_all_buttons_state("normal")
    
    def _set_all_buttons_state(self, state: str):
        """Set state for all registered buttons."""
        for button_name, button_widget in self._buttons.items():
            try:
                if button_widget and button_widget.winfo_exists():
                    button_widget.configure(state=state)
            except Exception as e:
                print(f"⚠️ Button state error ({button_name}): {e}")





class SalesforceExporterGUI(ctk.CTk):
    """Main GUI application class"""

    def __init__(self):
        super().__init__()

        self.title(WINDOW_TITLE)

        # ── Compute screen dimensions (used for both login and main window) ──
        self.screen_w = self.winfo_screenwidth()
        self.screen_h = self.winfo_screenheight()

        # ── Login window: fixed 780 wide, up to 90% screen height, centred ──
        login_w = min(780, int(self.screen_w * 0.80))
        login_h = int(self.screen_h * 0.70)
        pos_x   = (self.screen_w - login_w) // 2
        pos_y   = (self.screen_h - login_h) // 2
        self.minsize(780, 500)
        self.geometry(f"{login_w}x{login_h}+{pos_x}+{pos_y}")
        self.resizable(False, False)
        
        # ✅ CRITICAL: Initialize button_manager FIRST (before _setup_ui)
        self.button_manager = ButtonStateManager(self)

        self.sf_client: Optional[SalesforceClient] = None
        self.picklist_exporter: Optional[PicklistExporter] = None
        self.metadata_exporter: Optional[MetadataExporter] = None
        self.content_document_exporter: Optional[ContentDocumentExporter] = None
        self.attachment_exporter: Optional[AttachmentExporter] = None
        self.all_org_objects: List[str] = []
        self.selected_objects: Set[str] = set()
        
        # âœ… NEW: Export mode selection variable
        self.export_mode_var = ctk.StringVar(value="single_tab")
        self._logged_in_user = ""   # set after OAuth login succeeds
        # Stores active filters for the Download Files operation.
        # Keys: created_from, created_to, modified_from, modified_to,
        #       file_type, file_extension, title, is_archived
        self.download_file_filters: dict = {}
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Create frames
        self.login_frame = ctk.CTkFrame(self)
        self.export_frame = ctk.CTkFrame(self)

        self.login_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        self.export_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)

        self._setup_login_frame()
        self._setup_export_frame()

        # Initially show login frame
        self.export_frame.grid_forget()

        # Create SOQL frame
        self.soql_frame = None  # Will be created after login
        
        self.metadata_switch_manager: Optional[MetadataSwitchManager] = None
        self.switch_frame = None  # Will be created after login
        
        # ✅ NEW - Report Exporter frame
        self.report_exporter_frame = None  # Will be created after login
        


    # ==================================
    # Screen 1: Login & Authentication
    # ==================================

    def _setup_login_frame(self):

        login_frame = self.login_frame
        login_frame.grid_rowconfigure(0, weight=1)
        login_frame.grid_columnconfigure(0, weight=1)

        # Scrollable container
        scroll = ctk.CTkScrollableFrame(login_frame, fg_color="transparent", corner_radius=0)
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        # Card
        card = ctk.CTkFrame(scroll, corner_radius=18)
        card.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        card.grid_columnconfigure(0, weight=1)

        # ── HEADER ───────────────────────────────────────────────────────────
        header = ctk.CTkFrame(card, fg_color="#009EDB", corner_radius=16, height=96)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        header.grid_propagate(False)

        logo_box = ctk.CTkFrame(header, fg_color="#ffffff", width=52, height=52, corner_radius=10)
        logo_box.grid(row=0, column=0, padx=(20, 14), pady=16)
        logo_box.grid_propagate(False)
        ctk.CTkLabel(logo_box, text="SF", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#009EDB").place(relx=0.5, rely=0.5, anchor="center")

        hdr_text = ctk.CTkFrame(header, fg_color="transparent")
        hdr_text.grid(row=0, column=1, sticky="w", pady=12)
        ctk.CTkLabel(hdr_text, text="Salesforce Metadata Exporter",
                    font=ctk.CTkFont(size=21, weight="bold"),
                     text_color="#ffffff").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(hdr_text,
                    text="Sign in to your Salesforce org to export metadata, picklists, and reports",
                    font=ctk.CTkFont(size=13), text_color="#cce8f4"
                    ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        # ── TAB PANELS ───────────────────────────────────────────────────────
        self._panel_browser = ctk.CTkFrame(card, fg_color="transparent")
        self._panel_browser.grid(row=1, column=0, sticky="nsew", padx=28, pady=(22, 20))
        self._panel_browser.grid_columnconfigure(0, weight=1)

        LABEL_FONT = ctk.CTkFont(size=13, weight="bold")
        HINT_FONT  = ctk.CTkFont(size=11)
        ENTRY_H    = 36
        PAD        = (0, 5)

        # ── helpers ──────────────────────────────────────────────────────────
        def _lbl(parent, text, row):
            ctk.CTkLabel(parent, text=text, font=LABEL_FONT, anchor="w"
                         ).grid(row=row, column=0, sticky="w", pady=(0, 3))

        def _hint(parent, text, row):
            ctk.CTkLabel(parent, text=text, font=HINT_FONT,
                         text_color=("gray45", "gray60"), anchor="w", wraplength=600
                         ).grid(row=row, column=0, sticky="w", pady=(2, 0))

        def _spacer(parent, row, h=3):
            ctk.CTkFrame(parent, height=h, fg_color="transparent").grid(row=row, column=0)

        def _org_dropdown(parent, var_attr, row):
            setattr(self, var_attr, ctk.StringVar(value="Production / Developer Edition"))
            m = ctk.CTkOptionMenu(
                parent, variable=getattr(self, var_attr),
                values=["Production / Developer Edition", "Sandbox"],
                height=ENTRY_H, font=ctk.CTkFont(size=13, weight="bold"))
            m.grid(row=row, column=0, sticky="ew", pady=PAD)
            return m

        def _custom_domain_block(parent, var_attr, check_attr, entry_attr,
                                 cd_frame_attr, cd_slot_attr, row_start):
            """Build custom domain checkbox + hidden entry, return next row."""
            r = row_start
            setattr(self, var_attr, ctk.BooleanVar(value=False))

            def _toggle():
                on = getattr(self, var_attr).get()
                fr = getattr(self, cd_frame_attr)
                slot = getattr(self, cd_slot_attr)
                en = getattr(self, entry_attr)
                if on:
                    fr.grid(row=slot, column=0, sticky="ew", pady=(0, 8), in_=fr.master)
                    en.configure(state="normal")
                    en.focus()
                else:
                    fr.grid_remove()
                    en.configure(state="disabled")
                en.update_idletasks()

            chk = ctk.CTkCheckBox(
                parent,
                text="Use a custom domain   (e.g. mycompany.my.salesforce.com)",
                variable=getattr(self, var_attr),
                command=_toggle,
                font=ctk.CTkFont(size=13))
            chk.grid(row=r, column=0, sticky="w", pady=(0, 5))
            setattr(self, check_attr, chk)
            r += 1

            # Hidden frame
            setattr(self, cd_slot_attr, r)
            fr = ctk.CTkFrame(parent, fg_color=("gray93", "gray17"), corner_radius=8)
            fr.grid_columnconfigure(0, weight=1)
            setattr(self, cd_frame_attr, fr)

            ctk.CTkLabel(fr, text="Custom domain URL", font=LABEL_FONT, anchor="w"
                         ).grid(row=0, column=0, sticky="w", padx=14, pady=(8, 3))
            en = ctk.CTkEntry(fr, placeholder_text="mycompany.my.salesforce.com",
                              height=ENTRY_H, font=ctk.CTkFont(size=13), state="disabled")
            en.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 3))
            ctk.CTkLabel(fr, text="Do not include https:// — domain only",
                         font=HINT_FONT, text_color=("gray50", "gray55"), anchor="w"
                         ).grid(row=2, column=0, sticky="w", padx=14, pady=(0, 8))
            setattr(self, entry_attr, en)
            r += 1
            return r

        def _activity_log(parent, textbox_attr, row):
            ctk.CTkLabel(parent, text="ACTIVITY LOG", font=ctk.CTkFont(size=10),
                         text_color=("gray55", "gray50"), anchor="w"
                         ).grid(row=row, column=0, sticky="w", pady=(0, 2))
            tb = ctk.CTkTextbox(parent, height=140,
                                font=ctk.CTkFont(family="Courier", size=11),
                                wrap="word", state="normal")
            tb.grid(row=row + 1, column=0, sticky="ew")
            tb.insert("end", "[ready] Waiting for login...")
            tb.configure(state="disabled")
            setattr(self, textbox_attr, tb)

        # ════════════════════════════════════════════════════════════════════
        # BROWSER TAB
        # ════════════════════════════════════════════════════════════════════
        bp = self._panel_browser
        br = 0

        _lbl(bp, "Org type", br);  br += 1
        self.org_type_var = ctk.StringVar(value="Production / Developer Edition")
        self.org_type_menu = ctk.CTkOptionMenu(
            bp, variable=self.org_type_var,
            values=["Production / Developer Edition", "Sandbox"],
            height=ENTRY_H, font=ctk.CTkFont(size=13, weight="bold"))
        self.org_type_menu.grid(row=br, column=0, sticky="ew", pady=PAD);  br += 1

        br = _custom_domain_block(bp, "custom_domain_var", "custom_domain_check",
                                  "custom_domain_entry", "_cd_frame", "_cd_slot", br)

        # Browser login button row
        brow = ctk.CTkFrame(bp, fg_color="transparent")
        brow.grid(row=br, column=0, sticky="ew", pady=(3, 3));  br += 1
        brow.grid_columnconfigure(0, weight=1)

        self.oauth_button = ctk.CTkButton(
            brow, text="🌐  Login via Browser",
            command=self._oauth_login_action,
            height=42, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=("#1a7a4a", "#1a7a4a"), hover_color=("#145c37", "#145c37"))
        self.oauth_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.oauth_setup_btn = ctk.CTkButton(
            brow, text="⚙",
            command=self._open_oauth_setup_dialog,
            width=42, height=42,
            font=ctk.CTkFont(size=20),
            fg_color=("gray85", "gray25"), hover_color=("gray75", "gray35"),
            text_color=("gray20", "gray80"), corner_radius=6)
        self.oauth_setup_btn.grid(row=0, column=1)

        ctk.CTkLabel(bp,
                     text="Opens a secure login window — supports any org, MFA, and SSO. No token needed.",
                     font=HINT_FONT, text_color=("gray45", "gray60"),
                     anchor="center", wraplength=600
                     ).grid(row=br, column=0, pady=(0, 6));  br += 1

        # ── Reset button — sits directly below the login button row ──────────
        # Immediately visible when the login button gets stuck in the
        # "⏳ Waiting..." state after a failed or cancelled login attempt.
        # Does NOT wipe the Consumer Key — only unsticks the button and clears
        # the activity log so the user can retry without re-entering their key.
        # To change the Consumer Key, use the ⚙ gear dialog instead.
        self.reset_session_btn = ctk.CTkButton(
            bp,
            text="↻  Stuck? Reset Login Button",
            command=self._reset_session_action,
            height=30,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "gray35"),
            hover_color=("gray65", "gray25"),
            border_width=1,
            border_color=("gray70", "gray40"),
            text_color=("gray15", "gray85"),
            corner_radius=6,
        )
        self.reset_session_btn.grid(row=br, column=0, sticky="ew", pady=(0, 10));  br += 1

        _activity_log(bp, "login_status_textbox", br)


    def _on_custom_domain_toggle(self):
        """Show / hide the custom-domain entry when the checkbox changes."""
        if self.custom_domain_var.get():
            self._cd_frame.grid(row=self._cd_slot, column=0, sticky="ew",
                                pady=(0, 12), in_=self._cd_frame.master)
            self.custom_domain_entry.configure(state="normal")
            self.custom_domain_entry.focus()
        else:
            self._cd_frame.grid_remove()
            self.custom_domain_entry.configure(state="disabled")
        self.custom_domain_entry.update_idletasks()

        
    def _oauth_login_action(self):
        """
        Handle the 'Login via Browser' button click (Approach 2).
        Reads Consumer Key from the local settings file.
        If not set, prompts the user to open the setup dialog.
        """
        client_id = get_oauth_client_id()
        if not client_id:
            answer = messagebox.askyesno(
                "One-Time Setup Required",
                "Browser login needs a one-time setup.\n\n"
                "You need to create an External Client App in your\n"
                "Salesforce org and paste the Consumer Key here.\n\n"
                "This takes about 5 minutes and only needs to be done once.\n\n"
                "Open the setup guide now?"
            )
            if answer:
                self._open_oauth_setup_dialog()
            return

        # Determine domain from BROWSER tab UI selection
        if self.custom_domain_var.get():
            domain_raw = self.custom_domain_entry.get().strip().lower()

            if not domain_raw:
                messagebox.showerror(
                    "Custom Domain Required",
                    "You checked 'Use a custom domain' but left the field empty.\n\n"
                    "Please enter your Salesforce domain, for example:\n"
                    "  mycompany.my.salesforce.com\n\n"
                    "Or uncheck 'Use a custom domain' to use Production/Sandbox."
                )
                self.custom_domain_entry.focus()
                return

            for prefix in ("https://", "http://"):
                if domain_raw.startswith(prefix):
                    domain_raw = domain_raw[len(prefix):]
            domain = domain_raw.rstrip("/")
        else:
            domain = "test" if self.org_type_var.get() == "Sandbox" else "login"

        # Disable both buttons while waiting
        self.oauth_button.configure(state="disabled", text="⏳  Waiting for login window...")
        try:
            self.oauth_setup_btn.configure(state="disabled")
        except Exception:
            pass
        self.reset_session_btn.configure(state="normal")   # keep reset always accessible
        self.update_status("Opening Salesforce login window...")

        # ── Why "Not Responding" happens with a visible frozen window ─────────
        # webview.start() must run on threading.current_thread().name=='MainThread'
        # (pywebview checks the thread NAME literally — cannot be worked around).
        # While it blocks, Tkinter cannot process Windows messages (WM_PAINT,
        # WM_NCHITTEST, etc.).  After ~5 s Windows marks any VISIBLE window
        # "Not Responding" and grays it out.  Double-clicking makes it worse.
        #
        # ── The correct fix: withdraw() before webview.start() ────────────────
        # A withdrawn (hidden) window receives NO Windows messages at all, so
        # Windows has nothing to flag.  webview.start() still runs on MainThread
        # as required.  We restore the window with deiconify() the instant the
        # popup closes — the user sees it disappear briefly, then reappear.
        #
        # Steps:
        #   1. withdraw() — hide the main window.
        #   2. after(0) — yield one event-loop tick so withdraw() is rendered,
        #      THEN call flow.open_window() on this same MainThread.
        #      webview.start() blocks here; hidden window = no OS complaint.
        #   3. Popup closes → open_window() returns → callback fires on MainThread.
        #   4. deiconify() restores the window; token exchange runs in background.

        try:
            flow = OAuthWebFlow(domain=domain, status_callback=self.update_status)
        except Exception as e:
            self._on_oauth_login_error(str(e))
            return

        def _on_webview_done(result):
            """Called on the MainThread the moment the webview popup closes."""
            kind, value = result
            if kind == "error":
                self._on_oauth_login_error(value)
                return
            auth_code = value

            def do_exchange():
                try:
                    token_data = flow.exchange_code(auth_code)
                    self.sf_client = SalesforceClient.from_session(
                        session_id=token_data["access_token"],
                        instance_url=token_data["instance_url"],
                        status_callback=self.update_status,
                    )
                    self.after(0, self._on_oauth_login_success)
                except Exception as e:
                    err_msg = str(e)
                    self.after(0, lambda m=err_msg: self._on_oauth_login_error(m))

            from threading_helper import ThreadHelper
            ThreadHelper.run_in_thread(do_exchange)

            # ✅ NEW: Show "Connecting..." popup NOW.
            # Safe because do_exchange() is in a background thread —
            # the main thread is free and this Toplevel is fully responsive.
            self._show_processing_overlay()
        
         # ✅ THESE TWO LINES WERE MISSING — add them here:
        self.withdraw()   # Hide main window → no "Not Responding" while webview blocks
        self.after(0, lambda: flow.open_window(callback=_on_webview_done))

    def _open_oauth_setup_dialog(self):
        """
        One-time setup dialog: walks the user through creating an External
        Client App in their Salesforce org and saving the Consumer Key.
        """
        dialog = ctk.CTkToplevel(self)
        dialog.title("Browser Login Setup")
        dialog.geometry("680x660")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()

        # ── Title ────────────────────────────────────────────────────────────
        ctk.CTkLabel(
            dialog,
            text="One-Time Browser Login Setup",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(pady=(22, 2), padx=28, anchor="w")

        ctk.CTkLabel(
            dialog,
            text="Follow these steps once. After saving, Login via Browser works forever for your org.",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
            wraplength=600,
            justify="left",
        ).pack(padx=28, pady=(0, 12), anchor="w")

        # ── Instructions textbox ─────────────────────────────────────────────
        instructions = (
            "STEP-BY-STEP GUIDE\n"
            "\n"
            "1.  Log in to your Salesforce org in a browser\n"
            "2.  Click the gear icon (top right) → Setup\n"
            "3.  In the Quick Find box on the left, type: External Client App Manager\n"
            "4.  Click ‘External Client App Manager’ from the results\n"
            "5.  Click ‘New External Client App’ (top right)\n"
            "\n"
            "6.  Fill in Basic Information:\n"
            "       • External Client App Name:  SFMetaExporter\n"
            "       • Contact Email:             your email address\n"
            "       • Distribution State:        Local\n"
            "\n"
            "7.  Click ‘Enable OAuth’ and fill in:\n"
            "       • Callback URL:  http://localhost:8888/callback\n"
            "         (Only ONE URL needed — the login popup intercepts the\n"
            "          redirect internally, no local server required)\n"
            "       • OAuth Scopes: add ‘Full access (full)’\n"
            "                        add ‘Perform requests at any time (refresh_token)’\n"
            
            "       • Flow Enablement: check 'Enable Authorization Code and Credentials Flow'\n"
            "                          ⚠ Leave 'Require user credentials in POST body' UNCHECKED\n"
            "       • Security: check 'Require Proof Key for Code Exchange (PKCE)'\n"
            "       • Security: UNCHECK 'Require secret for Web Server Flow'\n"
            
            "\n"
            "8.  Click ‘Create’ at the bottom\n"
            "\n"
            "9.  On the Policies tab → click Edit:\n"
            "       • Permitted Users:  All users may self-authorize\n"
            "       • IP Relaxation:    Relax IP restrictions\n"
            "       • Refresh Token:    Refresh token is valid until revoked\n"
            "    Click Save\n"
            "\n"
            "10. On the Settings tab → scroll to OAuth Settings →\n"
            "    click ‘Consumer Key and Secret’ → verify your email code\n"
            "    Copy the Consumer Key and paste it in the field below"
        )

        instr_box = ctk.CTkTextbox(
            dialog,
            height=290,
            font=ctk.CTkFont(family="Courier", size=11),
            wrap="word",
            state="normal",
        )
        instr_box.pack(padx=28, pady=(0, 12), fill="x")
        instr_box.insert("end", instructions)
        instr_box.configure(state="disabled")

        # ── Consumer Key entry ───────────────────────────────────────────────
        ctk.CTkLabel(
            dialog,
            text="Consumer Key  (paste here after step 10):",
            font=ctk.CTkFont(size=13),
            anchor="w",
        ).pack(padx=28, pady=(0, 5), anchor="w")

        key_entry = ctk.CTkEntry(
            dialog,
            placeholder_text="3MVG9... paste your Consumer Key here ...",
            height=40,
            font=ctk.CTkFont(size=12),
        )
        existing = get_oauth_client_id()
        if existing:
            key_entry.insert(0, existing)
        key_entry.pack(padx=28, fill="x")

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(padx=28, pady=(16, 24), fill="x")
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        def _cancel():
            dialog.destroy()

        def _save():
            key = key_entry.get().strip()
            if not key:
                messagebox.showerror(
                    "Consumer Key Required",
                    "Please paste your Consumer Key before saving.\n\n"
                    "Follow step 10 above to copy it from Salesforce.",
                    parent=dialog,
                )
                return
            set_oauth_client_id(key)
            dialog.destroy()
            messagebox.showinfo(
                "Setup Complete",
                "Consumer Key saved successfully!\n\n"
                "You can now click \'Login via Browser\' to sign in.\n"
                "You will not need to do this setup again."
            )

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            fg_color=("gray75", "gray30"),
            hover_color=("gray65", "gray40"),
            text_color=("gray10", "gray90"),
            command=_cancel,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            btn_frame,
            text="Save Consumer Key",
            fg_color="#009EDB",
            hover_color="#007db8",
            command=_save,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self.wait_window(dialog)

    def _on_oauth_login_success(self):
        """Called on the main thread after a successful OAuth browser login."""
        self._hide_processing_overlay()   # ✅ hides popup + deiconifies main window
        self.oauth_button.configure(state="normal", text="🌐  Login via Browser")
        try:
            self.oauth_setup_btn.configure(state="normal")
        except Exception:
            pass
        self._on_login_success()

    def _on_oauth_login_error(self, error_msg: str):
        """Called on the main thread when OAuth browser login fails."""
        self._hide_processing_overlay()
        self.oauth_button.configure(state="normal", text="🌐  Login via Browser")
        try:
            self.oauth_setup_btn.configure(state="normal")
        except Exception:
            pass

        err_lower = error_msg.lower()

        if any(x in err_lower for x in ["app_not_found", "oauth_ec_app_not_found"]):
            detail = (
                "❌ Consumer Key Does Not Match This Org\n\n"
                "The Consumer Key saved in settings belongs to a different Salesforce org.\n\n"
                "Fix:\n"
                "1. Click the ⚙ gear button\n"
                "2. Create a new External Client App in THIS org\n"
                "3. Paste the new Consumer Key and click Save\n\n"
                f"Technical detail: {error_msg}"
            )
        elif "no consumer key" in err_lower or "no_consumer_key" in err_lower:
            detail = (
                "⚙️ One-Time Setup Not Completed\n\n"
                "Click the ⚙ gear button next to 'Login via Browser'\n"
                "and follow the steps to create an External Client App.\n\n"
                "This only needs to be done once per org."
            )
        elif "timed out" in err_lower or "closed before" in err_lower:
            detail = (
                "⏱ Browser Login Timed Out\n\n"
                "The browser window was closed or login took longer than 5 minutes.\n\n"
                "Please click 'Login via Browser' again and complete the login promptly.\n\n"
                f"Technical detail: {error_msg}"
            )
        elif "rejected" in err_lower or "access_denied" in err_lower:
            detail = (
                "🚫 Access Denied\n\n"
                "Salesforce rejected the login request.\n\n"
                "Common causes:\n"
                "• You clicked 'Deny' instead of 'Allow' in the browser\n"
                "• Your profile does not have API access enabled\n"
                "• The External Client App's Permitted Users is set too restrictively\n"
                "  (Fix: ECA → Policies → Permitted Users → All users may self-authorize)\n\n"
                f"Technical detail: {error_msg}"
            )
        elif "callback" in err_lower or "redirect" in err_lower:
            detail = (
                "🔗 Callback URL Mismatch\n\n"
                "The redirect URL is not registered in your External Client App.\n\n"
                "Fix: Click ⚙ and verify this callback URL is in your ECA:\n"
                "  http://localhost:8888/callback\n\n"
                f"Technical detail: {error_msg}"
            )
        elif "no module named" in err_lower and "webview" in err_lower:
            detail = (
                "📦 Missing Dependency: pywebview\n\n"
                "The login window requires the pywebview library.\n\n"
                "Fix:\n"
                "  pip install pywebview\n\n"
                "Then restart the application."
            )
        elif "webview2" in err_lower or ("pywebview" in err_lower and "import" in err_lower):
            detail = (
                "📦 WebView2 Runtime Missing\n\n"
                "pywebview is installed but the Microsoft WebView2 Runtime is missing.\n\n"
                "Fix:\n"
                "  1. Download and install the WebView2 Runtime from:\n"
                "     https://developer.microsoft.com/microsoft-edge/webview2/\n"
                "  2. Restart the application.\n\n"
                f"Technical detail: {error_msg}"
            )
        elif any(x in err_lower for x in ["nameresolutionerror", "getaddrinfo", "connection"]):
            detail = (
                "🌐 Connection Failed\n\n"
                "Could not reach Salesforce. Please check:\n"
                "• Internet connection is working\n"
                "• VPN or firewall is not blocking salesforce.com\n"
                "• The org domain is correct\n\n"
                f"Technical detail: {error_msg}"
            )
        else:
            detail = (
                f"❌ Browser Login Failed\n\n"
                f"Error: {error_msg}\n\n"
                "Common causes:\n"
                "• Wrong org type selected (Production vs Sandbox)\n"
                "• Browser was closed before finishing\n"
                "• Callback URL not registered in the External Client App\n"
                "• Consumer Key belongs to a different org\n\n"
                "Check the Activity Log below for full details.\n"
                "Click ⚙ to verify your External Client App setup."
            )

        messagebox.showerror("Browser Login Failed", detail)
        self.update_status(f"❌ Browser login failed: {error_msg}")


    def _reset_session_action(self):
        """
        Full reset: unstick the login button, clear the activity log, remove
        the saved Consumer Key from the JSON settings file, and restore the
        main window if it was hidden.

        Use this when the login button is stuck OR you want to start the
        one-time setup from scratch.  After reset the user must re-enter
        their Consumer Key via the ⚙ gear dialog.
        """
        # ── 1. Restore the main window in case withdraw() left it hidden ──
        try:
            self.deiconify()
        except Exception:
            pass

        # ── 2. Destroy the processing overlay if it is still showing ──────
        try:
            if getattr(self, "_processing_overlay", None):
                self._processing_overlay.destroy()
                self._processing_overlay = None
        except Exception:
            pass

        # ── 3. Re-enable the login buttons ────────────────────────────────
        try:
            self.oauth_button.configure(
                state="normal",
                text="🌐  Login via Browser",
            )
        except Exception:
            pass
        try:
            self.oauth_setup_btn.configure(state="normal")
        except Exception:
            pass

        # ── 4. Wipe the saved Consumer Key from the JSON settings file ─────
        try:
            set_oauth_client_id("")
        except Exception:
            pass

        # ── 5. Clear the activity log ──────────────────────────────────────
        try:
            self.login_status_textbox.configure(state="normal")
            self.login_status_textbox.delete("1.0", "end")
            self.login_status_textbox.insert(
                "end",
                "[ready] Reset complete. Consumer Key cleared.\n"
                "        Click ⚙ to enter your Consumer Key, then log in again.\n"
            )
            self.login_status_textbox.configure(state="disabled")
        except Exception:
            pass

        self.update_status("↻ Reset complete — Consumer Key removed. Use ⚙ to set it up again.")

    def _show_login_status(self, message: str, color: str = "gray"):
        """Show status message during login — writes to login_status_textbox."""
        try:
            timestamp = datetime.now().strftime("[%H:%M:%S]")
            log_msg = f"{timestamp} {message}\n"
            self.login_status_textbox.configure(state="normal")
            self.login_status_textbox.insert("end", log_msg)
            self.login_status_textbox.see("end")
            self.login_status_textbox.configure(state="disabled")
            print(log_msg.strip())
        except Exception as e:
            print(f"Status update error: {e}")
        



    def _hide_login_overlay(self):
        """Restore the main window after login completes."""
        self._webview_running = False
        try:
            self.deiconify()   # Bring window back — login is done
        except Exception:
            pass




    def _on_login_success(self):
        """Called after successful login - ENHANCED with object validation"""
        
        # ✅ FIX 1: Get objects from sf_client, not from self
        if self.sf_client and hasattr(self.sf_client, 'all_org_objects'):
            try:
                result = self.sf_client.sf.query("SELECT Username FROM User WHERE Id = UserInfo.getUserId()")
                self._logged_in_user = result['records'][0]['Username'] if result.get('records') else ""
            except Exception:
                self._logged_in_user = ""
            self.all_org_objects = self.sf_client.all_org_objects  # ✅ Copy to GUI
            object_count = len(self.all_org_objects)
        else:
            self.all_org_objects = []
            object_count = 0
        
        # ✅ FIX 2: Initialize exporters IMMEDIATELY (before checking object count) WITH ERROR HANDLING
        try:
            self.update_status("🔧 Initializing Picklist Exporter...")
            self.picklist_exporter = PicklistExporter(self.sf_client)
            self.update_status("✅ Picklist Exporter initialized")
        except Exception as e:
            self.update_status(f"❌ ERROR initializing Picklist Exporter: {str(e)}")
            import traceback
            self.update_status(f"🔍 Stack trace:\n{traceback.format_exc()}")
            self.picklist_exporter = None
        
        try:
            self.update_status("🔧 Initializing Metadata Exporter...")
            self.metadata_exporter = MetadataExporter(self.sf_client)
            self.update_status("✅ Metadata Exporter initialized")
        except Exception as e:
            self.update_status(f"❌ ERROR initializing Metadata Exporter: {str(e)}")
            import traceback
            self.update_status(f"🔍 Stack trace:\n{traceback.format_exc()}")
            self.metadata_exporter = None
        
        try:
            self.update_status("🔧 Initializing ContentDocument Exporter...")
            self.content_document_exporter = ContentDocumentExporter(self.sf_client)
            self.update_status("✅ ContentDocument Exporter initialized")
        except Exception as e:
            self.update_status(f"❌ ERROR initializing ContentDocument Exporter: {str(e)}")
            import traceback
            self.update_status(f"🔍 Stack trace:\n{traceback.format_exc()}")
            self.content_document_exporter = None
        
        try:
            self.update_status("🔧 Initializing Attachment Exporter...")
            self.attachment_exporter = AttachmentExporter(self.sf_client)
            self.update_status("✅ Attachment Exporter initialized")
        except Exception as e:
            self.update_status(f"❌ ERROR initializing Attachment Exporter: {str(e)}")
            import traceback
            self.update_status(f"🔍 Stack trace:\n{traceback.format_exc()}")
            self.attachment_exporter = None

        # Determine connection type
        if self.custom_domain_var.get():
            connection_type = "Custom Domain"
            domain_used = self.custom_domain_entry.get().strip()
        else:
            connection_type = self.org_type_var.get()
            domain_used = 'test.salesforce.com' if connection_type == 'Sandbox' else 'login.salesforce.com'
        
        # Check if token was used
        token_status = "Browser OAuth (PKCE)"
        
        # ✅ FIX 3: Show appropriate message based on object count
        if object_count == 0:
            # ⚠️ No objects found - show warning but allow login
            error_msg = (
                f"⚠️ Connected to Salesforce successfully, but no objects were found.\n\n"
                f"Connection Details:\n"
                f"• Type: {connection_type}\n"
                f"• Domain: {domain_used}\n"
                f"• Instance: {self.sf_client.base_url}\n"
                f"• API Version: v{self.sf_client.api_version}\n"
                f"• Authentication: {token_status}\n\n"
                f"Possible causes:\n"
                f"✓ Insufficient permissions (no 'View All Data' or object access)\n"
                f"✓ API access disabled for your user\n"
                f"✓ Network/proxy blocking API calls\n\n"
                f"💡 You can still use Report Exporter and SOQL Runner.\n"
                f"   Contact your Salesforce administrator to access objects."
            )
            
            messagebox.showwarning("No Objects Found", error_msg)
            
            # Log detailed error
            self.update_status("=" * 60)
            self.update_status("⚠️ LOGIN SUCCESSFUL BUT NO OBJECTS FOUND")
            self.update_status(f"📊 Connection Type: {connection_type}")
            self.update_status(f"🌐 Domain: {domain_used}")
            self.update_status(f"🔗 Instance: {self.sf_client.base_url}")
            self.update_status(f"📡 API Version: v{self.sf_client.api_version}")
            self.update_status(f"🔐 Authentication: {token_status}")
            self.update_status(f"❌ Objects Found: 0")
            self.update_status("=" * 60)
            self.update_status("")
            self.update_status("💡 Possible solutions:")
            self.update_status("  • Ask admin to grant 'View All Data' permission")
            self.update_status("  • Check if API access is enabled for your user")
            self.update_status("  • Verify profile has object-level read permissions")
            self.update_status("=" * 60)
            
        else:
            # ✅ SUCCESS: We have objects
            success_msg = (
                f"Successfully connected to Salesforce!\n\n"
                f"Connection Details:\n"
                f"• Type: {connection_type}\n"
                f"• Domain: {domain_used}\n"
                f"• Instance: {self.sf_client.base_url}\n"
                f"• API Version: v{self.sf_client.api_version}\n"
                f"• Authentication: {token_status}\n"
                f"• Objects Found: {object_count}"
            )
            
            messagebox.showinfo("Success", success_msg)
            
            # Log detailed connection info
            self.update_status("=" * 60)
            self.update_status(f"✅ CONNECTED TO SALESFORCE")
            self.update_status(f"📊 Connection Type: {connection_type}")
            self.update_status(f"🌐 Domain: {domain_used}")
            self.update_status(f"🔗 Instance: {self.sf_client.base_url}")
            self.update_status(f"📡 API Version: v{self.sf_client.api_version}")
            self.update_status(f"🔐 Authentication: {token_status}")
            self.update_status(f"📦 Objects Found: {object_count}")
            self.update_status("=" * 60)
        
        # ✅ FIX 4: Switch to Export Frame — expand window to 70% of screen
        self.login_frame.grid_forget()
        main_w = min(int(self.screen_w * 0.70), int(self.screen_w * 0.80))
        main_h = min(int(self.screen_h * 0.70), int(self.screen_h * 0.80))
        pos_x  = (self.screen_w - main_w) // 2
        pos_y  = (self.screen_h - main_h) // 2
        self.geometry(f"{main_w}x{main_h}+{pos_x}+{pos_y}")
        self.resizable(True, True)
        self.minsize(900, 600)
        self.export_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        
        # ✅ FIX 5: Populate objects (will show empty state if no objects)
        self.populate_available_objects(self.all_org_objects)
        self.populate_selected_objects()
        
        # Reset login button
        
        # ✅ FIX 6: Initialize SOQL Runner (works even without objects)
        self.soql_runner = SOQLRunner(self.sf_client)
        
        # ✅ FIX 7: Initialize Metadata Switch Manager (works even without objects)
        self.metadata_switch_manager = MetadataSwitchManager(
            self.sf_client.sf,
            status_callback=self.update_status
        )
        
        # ✅ ADD THIS AT THE VERY END:
        self._verify_exporters()  # Debug check 
 
 
 
        
        


    def _verify_exporters(self):
        """Debug method to verify exporters are initialized"""
        print("\n" + "="*60)
        print("🔍 EXPORTER VERIFICATION:")
        print(f"  sf_client: {self.sf_client is not None}")
        print(f"  picklist_exporter: {self.picklist_exporter is not None}")
        print(f"  metadata_exporter: {self.metadata_exporter is not None}")
        print(f"  content_document_exporter: {self.content_document_exporter is not None}")
        print(f"  attachment_exporter: {self.attachment_exporter is not None}")
        
        if self.sf_client:
            print(f"  sf_client.sf: {self.sf_client.sf is not None}")
            print(f"  sf_client.session_id: {self.sf_client.session_id[:20] if self.sf_client.session_id else 'None'}...")
            print(f"  sf_client.all_org_objects: {len(self.sf_client.all_org_objects)} objects")
        
        print("="*60 + "\n")



    # ==================================
    # Screen 2: Object Selection & Export
    # ==================================

    def _setup_export_frame(self):
        """Setup the export screen UI"""
        export_frame = self.export_frame
        export_frame.grid_rowconfigure(2, weight=1)
        export_frame.grid_columnconfigure(0, weight=1)

        # Header with logout button
        header_frame = ctk.CTkFrame(export_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, pady=(10, 5), sticky="ew")
        header_frame.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header_frame,
            text="Object Selection & Export",
            font=ctk.CTkFont(size=30, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        self.logout_button = ctk.CTkButton(
            header_frame,
            text="Logout",
            command=self.logout_action,
            width=100,
            fg_color="#CC3333"
        )
        self.logout_button.grid(row=0, column=1, sticky="e", padx=10)

        # Selection frame with three columns
        selection_frame = ctk.CTkFrame(export_frame)
        selection_frame.grid(row=1, column=0, pady=10, sticky="nsew")
        selection_frame.grid_columnconfigure(0, weight=3)
        selection_frame.grid_columnconfigure(1, weight=1)
        selection_frame.grid_columnconfigure(2, weight=2)
        selection_frame.grid_rowconfigure(0, weight=1)

        # Available Objects (Left)
        self._setup_available_objects_panel(selection_frame)

        # Action Buttons (Middle)
        self._setup_action_buttons_panel(selection_frame)

        # Selected Objects (Right)
        self._setup_selected_objects_panel(selection_frame)

        # Status textbox
        self.status_textbox = ctk.CTkTextbox(export_frame, height=150)
        self.status_textbox.grid(row=2, column=0, padx=20, pady=(10, 10), sticky="ew")
        self.status_textbox.insert("end", "Status: Ready to select objects and export.")
        self.status_textbox.configure(state="disabled")

        # âœ… NEW: Export Mode Selection Frame (THE RED BOX AREA)
        self._setup_export_mode_frame(export_frame)

        # Export buttons frame (6 BUTTONS)
        export_buttons_frame = ctk.CTkFrame(export_frame, fg_color="transparent")
        export_buttons_frame.grid(row=4, column=0, pady=(10, 20), sticky="ew", padx=20)  # âœ… Changed from row=3 to row=4
        export_buttons_frame.grid_columnconfigure(0, weight=1)
        export_buttons_frame.grid_columnconfigure(1, weight=1)
        export_buttons_frame.grid_columnconfigure(2, weight=1)
        export_buttons_frame.grid_columnconfigure(3, weight=1)

        # Configure 8 columns — 7 action buttons + 1 narrow filter button
        for i in range(8):
            export_buttons_frame.grid_columnconfigure(i, weight=1)
        # Filter button column is narrower; it doesn't expand like the others
        export_buttons_frame.grid_columnconfigure(3, weight=0, minsize=110)
        
        self.export_picklist_button = ctk.CTkButton(
            export_buttons_frame,
            text="Export Picklist Data",
            command=self.export_picklist_action,
            height=50,
            fg_color="#2D7BD4",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.export_picklist_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        self.export_metadata_button = ctk.CTkButton(
            export_buttons_frame,
            text="Export Metadata",
            command=self.export_metadata_action,
            height=50,
            fg_color="#2D7BD4",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.export_metadata_button.grid(row=0, column=1, sticky="ew", padx=(5, 5))
        
        self.download_files_button = ctk.CTkButton(
            export_buttons_frame,
            text="Download Files",
            command=self.download_files_action,
            height=50,
            fg_color="#2D7BD4",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.download_files_button.grid(row=0, column=2, sticky="ew", padx=(5, 2))

        # ── Filter button (narrow, sits right beside Download Files) ─────────
        self.download_filter_button = ctk.CTkButton(
            export_buttons_frame,
            text="🔍 Filter",
            command=self.open_download_filter_modal,
            height=50,
            fg_color="#555E6B",
            hover_color="#3A4250",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.download_filter_button.grid(row=0, column=3, sticky="ew", padx=(2, 5))

        self.run_soql_button = ctk.CTkButton(
            export_buttons_frame,
            text="Run SOQL",
            command=self.run_soql_action,
            height=50,
            fg_color="#2D7BD4",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.run_soql_button.grid(row=0, column=4, sticky="ew", padx=(5, 5))
        
        self.salesforce_switch_button = ctk.CTkButton(
            export_buttons_frame,
            text="Salesforce Switch",
            command=self.salesforce_switch_action,
            height=50,
            fg_color="#2D7BD4",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.salesforce_switch_button.grid(row=0, column=5, sticky="ew", padx=(5, 5))
        
        self.report_exporter_button = ctk.CTkButton(
            export_buttons_frame,
            text="📊 Report Export",
            command=self.report_exporter_action,
            height=50,
            fg_color="#2D7BD4",
            hover_color="#2D7BD4",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.report_exporter_button.grid(row=0, column=6, sticky="ew", padx=(5, 5))

        self.download_attachments_button = ctk.CTkButton(
            export_buttons_frame,
            text="🗂 Download Attachments",
            command=self.download_attachments_action,
            height=50,
            fg_color="#2D7BD4",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.download_attachments_button.grid(row=0, column=7, sticky="ew", padx=(5, 0))

        # Register all buttons with state manager
        self.button_manager.register_buttons({
            'picklist':        self.export_picklist_button,
            'metadata':        self.export_metadata_button,
            'download':        self.download_files_button,
            'download_filter': self.download_filter_button,
            'soql':            self.run_soql_button,
            'switch':          self.salesforce_switch_button,
            'report':          self.report_exporter_button,
            'attachments':     self.download_attachments_button,
        })


    def _setup_available_objects_panel(self, parent):
        """Setup the available objects panel"""
        available_frame = ctk.CTkFrame(parent)
        available_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        available_frame.grid_rowconfigure(2, weight=1)
        available_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            available_frame,
            text="Available Objects (Org)",
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, pady=(5, 5))

        self.search_entry = ctk.CTkEntry(
            available_frame,
            placeholder_text="Search Object API Name...",
            height=35
        )
        self.search_entry.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.search_entry.bind("<KeyRelease>", self.filter_available_objects)

        self.available_listbox = tk.Listbox(
            available_frame,
            selectmode="extended",
            height=15,
            exportselection=False,
            font=("Arial", 12),
            borderwidth=0,
            highlightthickness=0,
            selectbackground="#1F538D",
            fg="white",
            background="#242424"
        )
        self.available_listbox.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="nsew")

    def _setup_action_buttons_panel(self, parent):
        """Setup the action buttons panel"""
        action_frame = ctk.CTkFrame(parent, fg_color="transparent")
        action_frame.grid(row=0, column=1, padx=5, pady=10, sticky="n")

        ctk.CTkLabel(
            action_frame,
            text="Actions",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=5)

        ctk.CTkButton(
            action_frame,
            text=">> Add Selected >>",
            command=self.add_selected_to_export,
            height=35
        ).pack(pady=5, padx=5, fill="x")

        ctk.CTkButton(
            action_frame,
            text="<< Remove Selected <<",
            command=self.remove_selected_from_export,
            height=35
        ).pack(pady=5, padx=5, fill="x")

        ctk.CTkButton(
            action_frame,
            text="Select All",
            command=self.select_all_available,
            height=35
        ).pack(pady=(20, 5), padx=5, fill="x")

        ctk.CTkButton(
            action_frame,
            text="Deselect All",
            command=self.deselect_all_available,
            height=35
        ).pack(pady=5, padx=5, fill="x")


    def _setup_selected_objects_panel(self, parent):
        """Setup the selected objects panel with Clear All button"""
        selected_frame = ctk.CTkFrame(parent)
        selected_frame.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
        selected_frame.grid_rowconfigure(2, weight=1)  # ✅ Changed from row 1 to row 2 (listbox now in row 2)
        selected_frame.grid_columnconfigure(0, weight=1)

        # Header label
        ctk.CTkLabel(
            selected_frame,
            text="Selected for Export",
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, pady=(5, 5))

        # ✅ NEW: Clear All button (row 1)
        self.clear_all_button = ctk.CTkButton(
            selected_frame,
            text="🗑️ Clear All",
            command=self.clear_all_selected_action,
            height=35,
            fg_color="#DC3545",  # Red color for destructive action
            hover_color="#C82333",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.clear_all_button.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="ew")

        # Listbox (row 2)
        self.selected_listbox = tk.Listbox(
            selected_frame,
            selectmode="extended",
            height=15,
            exportselection=False,
            font=("Arial", 12),
            borderwidth=0,
            highlightthickness=0,
            selectbackground="#3366CC",
            fg="white",
            background="#242424"
        )
        self.selected_listbox.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="nsew")


    def _setup_export_mode_frame(self, parent):
        """Setup export mode selection frame (Radio buttons for export options)"""
        
        # Main frame for export mode selection (THE RED BOX AREA)
        # ✅ Use theme-aware colors: (light_mode_color, dark_mode_color)
        export_mode_frame = ctk.CTkFrame(parent, fg_color=("#E0E0E0", "#2B2B2B"))
        export_mode_frame.grid(row=3, column=0, padx=20, pady=(10, 10), sticky="ew")
        export_mode_frame.grid_columnconfigure(0, weight=0)  # Label
        export_mode_frame.grid_columnconfigure(1, weight=1)  # Radio buttons container
        
        # Label on the left
        mode_label = ctk.CTkLabel(
            export_mode_frame,
            text="📑 Excel Export Mode:",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
            text_color=("#2c3e50", "#ecf0f1")  # ✅ Dark gray (light), Light gray (dark)
        )
        mode_label.grid(row=0, column=0, padx=(15, 20), pady=15, sticky="w")
        
        # Radio buttons container (horizontal layout)
        radio_container = ctk.CTkFrame(export_mode_frame, fg_color="transparent")
        radio_container.grid(row=0, column=1, padx=(0, 15), pady=15, sticky="w")
        
        # Radio Button 1: Single Tab (Default)
        self.radio_single_tab = ctk.CTkRadioButton(
            radio_container,
            text="📄 Single Tab (All objects in one sheet)",
            variable=self.export_mode_var,
            value="single_tab",
            font=ctk.CTkFont(size=12),
            command=self._on_export_mode_changed,
            text_color=("#2c3e50", "#ecf0f1")  # ✅ Theme-aware text color
        )
        self.radio_single_tab.grid(row=0, column=0, padx=(0, 25), sticky="w")
        
        # Radio Button 2: Multiple Tabs
        self.radio_multi_tab = ctk.CTkRadioButton(
            radio_container,
            text="📑 Multiple Tabs (One sheet per object)",
            variable=self.export_mode_var,
            value="multi_tab",
            font=ctk.CTkFont(size=12),
            command=self._on_export_mode_changed,
            text_color=("#2c3e50", "#ecf0f1")  # ✅ Theme-aware text color
        )
        self.radio_multi_tab.grid(row=0, column=1, padx=(0, 25), sticky="w")
        
        # Radio Button 3: Individual Files
        self.radio_individual_files = ctk.CTkRadioButton(
            radio_container,
            text="📦 Individual Files (Separate .xlsx per object, auto-zipped)",
            variable=self.export_mode_var,
            value="individual_files",
            font=ctk.CTkFont(size=12),
            command=self._on_export_mode_changed,
            text_color=("#2c3e50", "#ecf0f1")  # ✅ Theme-aware text color
        )
        self.radio_individual_files.grid(row=0, column=2, padx=(0, 0), sticky="w")



    def _on_export_mode_changed(self):
        """Called when user changes export mode radio button"""
        selected_mode = self.export_mode_var.get()
        
        mode_descriptions = {
            "single_tab": "All selected objects will be exported to a single Excel sheet",
            "multi_tab": "Each object will have its own tab in one Excel file",
            "individual_files": "Each object will be saved as a separate Excel file (auto-zipped if multiple objects)"
        }
        
        description = mode_descriptions.get(selected_mode, "")
        self.update_status(f"📑 Export mode changed: {description}")


    # ==================================
    # Object List Management Methods
    # ==================================

    def populate_available_objects(self, objects: List[str]):
        """Populates the Left ListBox based on the current search filter"""
        self.available_listbox.delete(0, END)
        for obj in objects:
            self.available_listbox.insert(END, obj)
            if obj in self.selected_objects:
                idx = self.available_listbox.get(0, END).index(obj)
                self.available_listbox.itemconfig(idx, {'fg': '#87CEEB'})

    def populate_selected_objects(self):
        """Populates the Right ListBox from the internal selected_objects set"""
        self.selected_listbox.delete(0, END)
        for obj in sorted(list(self.selected_objects)):
            self.selected_listbox.insert(END, obj)

    def filter_available_objects(self, event):
        """Filters the Available ListBox based on the search entry content"""
        search_term = self.search_entry.get().lower()
        filtered_objects = [
            obj for obj in self.all_org_objects
            if search_term in obj.lower()
        ]
        self.populate_available_objects(filtered_objects)

    def add_selected_to_export(self):
        """Adds selected objects from the Available List to the Export Set"""
        selected_indices = self.available_listbox.curselection()

        if not selected_indices:
            messagebox.showwarning(
                "Selection",
                "Please select one or more objects from the 'Available Objects' list to add."
            )
            return

        added_count = 0
        for i in selected_indices:
            obj_name = self.available_listbox.get(i)
            if obj_name not in self.selected_objects:
                self.selected_objects.add(obj_name)
                added_count += 1

        if added_count > 0:
            self.populate_selected_objects()
            self.filter_available_objects(None)
            self.update_status(f"Added {added_count} object(s) to export list.")

    def remove_selected_from_export(self):
        """Removes selected objects from the Selected List"""
        selected_indices = self.selected_listbox.curselection()

        if not selected_indices:
            messagebox.showwarning(
                "Selection",
                "Please select one or more objects from the 'Selected for Export' list to remove."
            )
            return

        removed_objects = []
        for i in reversed(selected_indices):
            obj_name = self.selected_listbox.get(i)
            removed_objects.append(obj_name)

        for obj_name in removed_objects:
            self.selected_objects.discard(obj_name)

        if removed_objects:
            self.populate_selected_objects()
            self.filter_available_objects(None)
            self.update_status(f"Removed {len(removed_objects)} object(s) from export list.")
            
            
    def clear_all_selected_action(self):
        """
        Clear all objects from the Selected for Export list
        
        ✅ Uses confirmation dialog for safety (100+ objects scenario)
        ✅ Updates UI immediately
        ✅ Provides feedback via status log
        """
        # Check if there are objects to clear
        if not self.selected_objects:
            messagebox.showinfo(
                "Nothing to Clear",
                "The 'Selected for Export' list is already empty."
            )
            return
        
        # Get count for confirmation message
        count = len(self.selected_objects)
        
        # ✅ Confirmation dialog (especially important for large selections)
        if count > 10:
            # Show detailed confirmation for large selections
            confirm = messagebox.askyesno(
                "Confirm Clear All",
                f"Are you sure you want to remove all {count} objects from the export list?\n\n"
                f"This action cannot be undone.",
                icon='warning'
            )
        else:
            # Simple confirmation for small selections
            confirm = messagebox.askyesno(
                "Confirm Clear All",
                f"Remove all {count} object(s) from the export list?",
                icon='question'
            )
        
        if not confirm:
            # User cancelled
            return
        
        # ✅ Clear the selected objects set
        self.selected_objects.clear()
        
        # ✅ Update the Selected listbox UI
        self.populate_selected_objects()
        
        # ✅ Refresh the Available listbox to remove blue highlighting
        self.filter_available_objects(None)
        
        # ✅ Log the action
        self.update_status(f"🗑️ Cleared {count} object(s) from export list.")
        
        # ✅ Optional: Show success message for large clears
        if count > 50:
            messagebox.showinfo(
                "Cleared Successfully",
                f"Removed {count} objects from the export list."
            )
            


    def select_all_available(self):
        """Selects all objects currently visible in the Available ListBox"""
        self.available_listbox.select_set(0, END)

    def deselect_all_available(self):
        """Deselects all objects currently visible in the Available ListBox"""
        self.available_listbox.select_clear(0, END)

    # ==================================
    # Run SOQL Action Methods
    # ==================================
    
    def run_soql_action(self):
        """Handle Run SOQL button click"""
        if not self.sf_client or not self.soql_runner:
            messagebox.showerror("Error", "Not logged in. Please log in first.")
            return
        
        # ✅ NEW: Check if another operation is running
        if self.button_manager.operation_running:
            messagebox.showwarning(
                "Operation in Progress",
                f"{self.button_manager.current_operation} is currently running.\n\n"
                f"Please wait for it to complete before opening SOQL runner."
            )
            return
        
        # Create SOQL frame if it doesn't exist
        if self.soql_frame is None:
            self.soql_frame = SOQLQueryFrame(
                self,
                self.soql_runner,
                status_callback=self.update_status
            )
            self.soql_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
            
            # Connect back button
            self.soql_frame.back_button.configure(command=self.show_export_frame)
        
        # Hide export frame and show SOQL frame
        self.export_frame.grid_forget()
        self.soql_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
    
    def show_export_frame(self):
        """Show the export frame and hide SOQL frame"""
        if self.soql_frame:
            self.soql_frame.grid_forget()
        self.export_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        
        
    # ============================================
    # salesforce_switch_action
    # ============================================

    def salesforce_switch_action(self):
        """Handle Salesforce Switch button click"""
        if not self.sf_client or not self.metadata_switch_manager:
            messagebox.showerror("Error", "Not logged in. Please log in first.")
            return
        
        # ✅ NEW: Check if another operation is running
        if self.button_manager.operation_running:
            messagebox.showwarning(
                "Operation in Progress",
                f"{self.button_manager.current_operation} is currently running.\n\n"
                f"Please wait for it to complete before opening Salesforce Switch."
            )
            return
        
        # Create switch frame if it doesn't exist
        if self.switch_frame is None:
            self.switch_frame = SalesforceSwitchFrame(
                self,
                self.metadata_switch_manager,
                username=self._logged_in_user,
                status_callback=self.update_status
            )
            self.switch_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
            
            # Connect back button
            self.switch_frame.back_button.configure(command=self.show_export_frame_from_switch)
        
        # Hide export frame and show switch frame
        self.export_frame.grid_forget()
        self.switch_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        
        # Load components
        self.switch_frame.load_components()


    # ============================================
    # show_export_frame_from_switch
    # ============================================



    def show_export_frame_from_switch(self):
        """Show the export frame and hide switch frame"""
        if self.switch_frame:
            self.switch_frame.grid_forget()
        self.export_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        
    def _get_window_monitor_geometry(self) -> tuple:
        """
        Get the geometry of the monitor where this window is currently displayed.
        
        Returns:
            (x, y, width, height) of the monitor containing this window
        """
        try:
            # Get main window position and size
            window_x = self.winfo_x()
            window_y = self.winfo_y()
            window_width = self.winfo_width()
            window_height = self.winfo_height()
            
            # Calculate window center point
            window_center_x = window_x + (window_width // 2)
            window_center_y = window_y + (window_height // 2)
            
            # Get screen dimensions
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            
            # Detect which monitor the window is on
            if window_center_x > screen_width:
                # Window is on RIGHT monitor (extended display)
                monitor_x = screen_width
                monitor_y = 0
                monitor_width = screen_width
                monitor_height = screen_height
            elif window_center_x < 0:
                # Window is on LEFT monitor
                monitor_x = -screen_width
                monitor_y = 0
                monitor_width = screen_width
                monitor_height = screen_height
            elif window_center_y < 0:
                # Window is on TOP monitor (stacked setup)
                monitor_x = 0
                monitor_y = -screen_height
                monitor_width = screen_width
                monitor_height = screen_height
            elif window_center_y > screen_height:
                # Window is on BOTTOM monitor
                monitor_x = 0
                monitor_y = screen_height
                monitor_width = screen_width
                monitor_height = screen_height
            else:
                # Window is on PRIMARY monitor
                monitor_x = 0
                monitor_y = 0
                monitor_width = screen_width
                monitor_height = screen_height
            
            return (monitor_x, monitor_y, monitor_width, monitor_height)
            
        except Exception as e:
            print(f"⚠️ Error detecting monitor: {e}")
            # Fallback to primary monitor
            return (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())

    def _get_window_state_info(self) -> dict:
        """
        Get current window state and geometry information.
        
        Returns:
            Dictionary with window state info
        """
        try:
            # Get window state
            state = self.state()
            
            # Check if zoomed (maximized)
            is_zoomed = (state == 'zoomed')
            
            # Check if fullscreen
            try:
                is_fullscreen = self.attributes('-fullscreen')
            except:
                is_fullscreen = False
            
            # Determine state string
            if is_fullscreen:
                state_str = 'fullscreen'
            elif is_zoomed:
                state_str = 'zoomed'
            else:
                state_str = 'normal'
            
            # Get window geometry
            width = self.winfo_width()
            height = self.winfo_height()
            x = self.winfo_x()
            y = self.winfo_y()
            
            # Get monitor geometry
            monitor_x, monitor_y, monitor_width, monitor_height = self._get_window_monitor_geometry()
            
            return {
                'state': state_str,
                'width': width,
                'height': height,
                'x': x,
                'y': y,
                'monitor_x': monitor_x,
                'monitor_y': monitor_y,
                'monitor_width': monitor_width,
                'monitor_height': monitor_height
            }
            
        except Exception as e:
            print(f"⚠️ Error getting window state: {e}")
            # Fallback to defaults
            return {
                'state': 'normal',
                'width': 1200,
                'height': 800,
                'x': 100,
                'y': 100,
                'monitor_x': 0,
                'monitor_y': 0,
                'monitor_width': self.winfo_screenwidth(),
                'monitor_height': self.winfo_screenheight()
            }

    def _center_window_on_monitor(self, window, window_width: int, window_height: int, 
                                monitor_x: int, monitor_y: int, 
                                monitor_width: int, monitor_height: int):
        """
        Center a window on a specific monitor.
        
        Args:
            window: The window to center
            window_width: Desired window width
            window_height: Desired window height
            monitor_x: Monitor X offset
            monitor_y: Monitor Y offset
            monitor_width: Monitor width
            monitor_height: Monitor height
        """
        try:
            # Calculate center position on the monitor
            center_x = monitor_x + (monitor_width - window_width) // 2
            center_y = monitor_y + (monitor_height - window_height) // 2
            
            # Set geometry
            window.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
            
        except Exception as e:
            print(f"⚠️ Error centering window: {e}")
            # Fallback to default positioning
            window.geometry(f"{window_width}x{window_height}")

    def _apply_parent_state_to_child(self, child_window, parent_state: dict):
        """
        Apply parent window's state (position, size, fullscreen) to child window.
        
        Args:
            child_window: The child Toplevel window
            parent_state: Dictionary from _get_window_state_info()
        """
        try:
            state = parent_state['state']
            
            if state == 'fullscreen':
                # Parent is fullscreen - make child fullscreen too
                try:
                    child_window.attributes('-fullscreen', True)
                    print("🖥️ Report Exporter: Fullscreen mode")
                except:
                    pass
                
            elif state == 'zoomed':
                # Parent is maximized - maximize child
                try:
                    child_window.state('zoomed')
                    print("🖥️ Report Exporter: Maximized mode")
                except:
                    pass
                
            else:
                # Parent is normal - match parent's size and center on same monitor
                width = parent_state['width']
                height = parent_state['height']
                monitor_x = parent_state['monitor_x']
                monitor_y = parent_state['monitor_y']
                monitor_width = parent_state['monitor_width']
                monitor_height = parent_state['monitor_height']
                
                # Use 90% of parent size (looks better than exact match)
                child_width = int(width * 0.9)
                child_height = int(height * 0.9)
                
                # Ensure minimum size
                child_width = max(child_width, 1000)
                child_height = max(child_height, 700)
                
                # Center on same monitor as parent
                self._center_window_on_monitor(
                    child_window,
                    child_width,
                    child_height,
                    monitor_x,
                    monitor_y,
                    monitor_width,
                    monitor_height
                )
                
                print(f"🖥️ Report Exporter: Normal mode ({child_width}x{child_height})")
            
            # Force window to update
            child_window.update_idletasks()
            
        except Exception as e:
            print(f"⚠️ Error applying parent state to child: {e}")
            # Fallback to default size and position
            try:
                child_window.geometry("1200x740")
            except:
                pass     


    # ✅ NEW METHOD 1 - Report Exporter Action
    # gui.py - REPLACE the report_exporter_action method

    def report_exporter_action(self):
        """Handle Report Exporter button click (6th button)"""
        if not self.sf_client:
            messagebox.showerror("Error", "Not logged in. Please log in first.")
            return
        
        # ✅ NEW: Get current appearance mode
        current_appearance = ctk.get_appearance_mode()  # Returns "Light" or "Dark"
        
        # Build session info for Report Exporter
        session_info = {
            "session_id": self.sf_client.session_id,
            "instance_url": self.sf_client.base_url,
            "api_version": self.sf_client.api_version,
            "user_name": self._logged_in_user,
            "appearance_mode": current_appearance  # ✅ NEW: Pass theme to child
        }
        
        # ✅ CRITICAL FIX: Check if window exists and is alive
        window_exists = (
            self.report_exporter_frame is not None and 
            hasattr(self.report_exporter_frame, 'winfo_exists') and
            self.report_exporter_frame.winfo_exists()
        )
        
        if window_exists:
            # Window already exists - just show it
            try:
                self.report_exporter_frame.deiconify()
                self.report_exporter_frame.lift()
                self.report_exporter_frame.focus_force()
                
                # Hide main window
                self.withdraw()
                
                print("✅ Report Exporter: Restored existing window")
                return
                
            except Exception as e:
                print(f"⚠️ Error showing existing window: {e}")
                # Window is broken, recreate it
                self.report_exporter_frame = None
        
        # Create new window
        try:
            print("🔨 Creating new Report Exporter window...")
            
            self.report_exporter_frame = SalesforceExporterApp(
                master=self,
                session_info=session_info,
                on_logout=self.show_export_frame_from_report_exporter
            )
            
            # ✅ CRITICAL: Don't hide parent yet - let child initialize first
            print("⏳ Window created, initializing...")
            
            # ✅ Get parent window state AFTER child is created
            parent_state = self._get_window_state_info()
            
            # ✅ Apply parent state with delay (let child finish _setup_ui first)
            self.after(100, lambda: self._finalize_report_exporter_window(parent_state))
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            
            print(f"❌ Failed to create Report Exporter:")
            print(error_details)
            
            messagebox.showerror(
                "Error",
                f"Failed to open Report Exporter:\n\n{str(e)}"
            )
            
            self.report_exporter_frame = None
            return
    
    # gui.py - ADD this new method

    def _finalize_report_exporter_window(self, parent_state):
        """
        Finalize report exporter window after initialization.
        """
        try:
            # Check if window still exists
            if not self.report_exporter_frame or not self.report_exporter_frame.winfo_exists():
                print("⚠️ Report Exporter window destroyed during initialization")
                self.deiconify()  # Show parent again
                return
            
            # Apply parent state to child
            print("🎨 Applying window state...")
            self._apply_parent_state_to_child(self.report_exporter_frame, parent_state)
            
            # NOW hide parent window
            print("👁️ Hiding parent window...")
            self.withdraw()
            
            # Ensure child is visible and focused
            self.report_exporter_frame.deiconify()
            self.report_exporter_frame.lift()
            self.report_exporter_frame.focus_force()
            
            print("✅ Report Exporter window finalized successfully")
            
            # Log action
            try:
                self.update_status("📊 Opened Report Exporter")
            except:
                pass
                
        except Exception as e:
            print(f"❌ Error finalizing Report Exporter window: {e}")
            import traceback
            traceback.print_exc()
            
            # Recovery: show parent window again
            try:
                self.deiconify()
            except:
                pass    
    
    
    
    
    # ✅ NEW METHOD 2 - Back from Report Exporter
    def show_export_frame_from_report_exporter(self):
        """Show the export frame and hide report exporter frame"""
        if self.report_exporter_frame:
            try:
                # ✅ FIXED: Toplevel windows use withdraw(), not grid_forget()
                self.report_exporter_frame.withdraw()
                
                
            except Exception as e:
                print(f"⚠️ Error hiding report exporter: {e}")
        
        # Show main export frame
        self.export_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        
        # Bring main window to front
        self.deiconify()
        self.lift()
        self.focus_force()
        
        self._log("⬅️ Returned from Report Exporter")


    # ==================================
    # Export Action Methods
    # ==================================

    def export_picklist_action(self):
        """Handle export picklist button click"""
        if not self.sf_client or not self.picklist_exporter:
            messagebox.showerror("Error", "Not logged in. Please log in first.")
            return

        selected_objects_list = sorted(list(self.selected_objects))

        if not selected_objects_list:
            messagebox.showwarning(
                "Warning",
                "The 'Selected for Export' list is empty. Please add objects."
            )
            return

        # ✅ NEW: Check if another operation is running
        if not self.button_manager.start_operation("Picklist Export"):
            return

        # ✅ Get selected export mode
        export_mode = self.export_mode_var.get()
        
        # ✅ Determine file extension and filter based on mode
        if export_mode == "individual_files":
            # Individual files mode - will create .zip (or single .xlsx)
            file_types = [("ZIP files", "*.zip"), ("Excel files", "*.xlsx")]
            default_ext = ".zip"
        else:
            # Single tab or multi-tab - always .xlsx
            file_types = [("Excel files", "*.xlsx")]
            default_ext = ".xlsx"
        
        # ✅ Generate default filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if export_mode == "individual_files":
            default_filename = f"Salesforce_Picklist_Export_{timestamp}.zip"
        else:
            default_filename = f"Picklist_Export_{timestamp}.xlsx"
        
        # ✅ Ask user for save location
        output_file_path = filedialog.asksaveasfilename(
            defaultextension=default_ext,
            initialfile=default_filename,
            filetypes=file_types
        )

        if not output_file_path:
            # User cancelled, end operation
            self.button_manager.end_operation()
            return

        # ✅ Log export details
        mode_descriptions = {
            "single_tab": "Single Tab (all objects in one sheet)",
            "multi_tab": "Multiple Tabs (one sheet per object)",
            "individual_files": "Individual Files (separate .xlsx per object, auto-zipped)"
        }
        
        mode_desc = mode_descriptions.get(export_mode, export_mode)
        
        self.update_status(
            f"Starting picklist export for {len(selected_objects_list)} objects..."
        )
        self.update_status(f"📑 Export Mode: {mode_desc}")
        self.update_status(f"💾 Output: {output_file_path}")
        
        start_time = time.time()

        # ✅ Run export in background thread
        def do_export():
            try:
                # ✅ NEW: Use export_picklists_excel with mode parameter
                output_path, stats = self.picklist_exporter.export_picklists_excel(
                    selected_objects_list,
                    output_file_path,
                    export_mode=export_mode
                )

                end_time = time.time()
                runtime_seconds = end_time - start_time
                runtime_formatted = format_runtime(runtime_seconds)

                # Update UI on main thread
                self.after(0, lambda: self._on_picklist_export_success(
                    output_path, stats, runtime_formatted
                ))

            except Exception as e:
                # Handle error on main thread
                self.after(0, lambda: self._on_picklist_export_error(str(e)))

        ThreadHelper.run_in_thread(do_export)



    def _on_picklist_export_success(self, output_path, stats, runtime_formatted):
        """Called after successful picklist export"""
        
        # ✅ Get export mode for messaging
        export_mode = stats.get('export_mode', 'unknown')
        
        mode_descriptions = {
            "single_tab": "Single Tab Mode",
            "multi_tab": "Multiple Tabs Mode",
            "individual_files": "Individual Files Mode"
        }
        
        mode_desc = mode_descriptions.get(export_mode, export_mode)
        
        self.update_status(f"Export Complete! Total Runtime: {runtime_formatted}")
        
        # ✅ Determine file type for message
        file_ext = os.path.splitext(output_path)[1].lower()
        
        if file_ext == ".zip":
            message = (
                f"Picklist data successfully exported!\n\n"
                f"Mode: {mode_desc}\n"
                f"ZIP Archive: {output_path}\n\n"
                f"📦 The ZIP contains individual Excel files for each object."
            )
        else:
            message = (
                f"Picklist data successfully exported!\n\n"
                f"Mode: {mode_desc}\n"
                f"Excel File: {output_path}"
            )
        
        messagebox.showinfo("Export Done", message)

        print_picklist_statistics(stats, runtime_formatted, output_path)

        # ✅ Re-enable all buttons
        self.button_manager.end_operation()

    def _on_picklist_export_error(self, error_message):
        """Called when picklist export fails"""
        self.update_status(f"❌ FATAL EXPORT ERROR: {error_message}")
        messagebox.showerror("Export Error", f"A fatal error occurred during export: {error_message}")

        # ✅ NEW: Re-enable all buttons
        self.button_manager.end_operation()


    def export_metadata_action(self):
        """Handle export metadata button click"""
        if not self.sf_client or not self.metadata_exporter:
            messagebox.showerror("Error", "Not logged in. Please log in first.")
            return

        selected_objects_list = sorted(list(self.selected_objects))

        if not selected_objects_list:
            messagebox.showwarning(
                "Warning",
                "The 'Selected for Export' list is empty. Please add objects."
            )
            return

        # ✅ NEW: Check if another operation is running
        if not self.button_manager.start_operation("Metadata Export"):
            return

        # ✅ Get selected export mode
        export_mode = self.export_mode_var.get()
        
        # ✅ Determine file extension and filter based on mode
        if export_mode == "individual_files":
            # Individual files mode - will create .zip (or single .xlsx)
            file_types = [("ZIP files", "*.zip"), ("Excel files", "*.xlsx")]
            default_ext = ".zip"
        else:
            # Single tab or multi-tab - always .xlsx
            file_types = [("Excel files", "*.xlsx")]
            default_ext = ".xlsx"
        
        # ✅ Generate default filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if export_mode == "individual_files":
            default_filename = f"Salesforce_Metadata_Export_{timestamp}.zip"
        else:
            default_filename = f"Object_Metadata_{timestamp}.xlsx"
        
        # ✅ Ask user for save location
        output_file_path = filedialog.asksaveasfilename(
            defaultextension=default_ext,
            initialfile=default_filename,
            filetypes=file_types
        )

        if not output_file_path:
            # User cancelled, end operation
            self.button_manager.end_operation()
            return

        # ✅ Log export details
        mode_descriptions = {
            "single_tab": "Single Tab (all objects in one sheet)",
            "multi_tab": "Multiple Tabs (one sheet per object)",
            "individual_files": "Individual Files (separate .xlsx per object, auto-zipped)"
        }
        
        mode_desc = mode_descriptions.get(export_mode, export_mode)
        
        self.update_status(
            f"Starting metadata export for {len(selected_objects_list)} objects..."
        )
        self.update_status(f"📑 Export Mode: {mode_desc}")
        self.update_status(f"💾 Output: {output_file_path}")
        
        start_time = time.time()

        # ✅ Run export in background thread
        def do_export():
            try:
                # ✅ NEW: Use export_metadata_excel with mode parameter
                output_path, stats = self.metadata_exporter.export_metadata_excel(
                    selected_objects_list,
                    output_file_path,
                    export_mode=export_mode
                )

                end_time = time.time()
                runtime_seconds = end_time - start_time
                runtime_formatted = format_runtime(runtime_seconds)

                # Update UI on main thread
                self.after(0, lambda: self._on_metadata_export_success(
                    output_path, stats, runtime_formatted
                ))

            except Exception as e:
                # Handle error on main thread
                self.after(0, lambda: self._on_metadata_export_error(str(e)))

        ThreadHelper.run_in_thread(do_export)


    def _on_metadata_export_success(self, output_path, stats, runtime_formatted):
        """Called after successful metadata export"""
        
        # ✅ Get export mode for messaging
        export_mode = stats.get('export_mode', 'unknown')
        
        mode_descriptions = {
            "single_tab": "Single Tab Mode",
            "multi_tab": "Multiple Tabs Mode",
            "individual_files": "Individual Files Mode"
        }
        
        mode_desc = mode_descriptions.get(export_mode, export_mode)
        
        self.update_status(f"Export Complete! Total Runtime: {runtime_formatted}")
        
        # ✅ Determine file type for message
        file_ext = os.path.splitext(output_path)[1].lower()
        
        if file_ext == ".zip":
            message = (
                f"Metadata successfully exported!\n\n"
                f"Mode: {mode_desc}\n"
                f"ZIP Archive: {output_path}\n\n"
                f"📦 The ZIP contains individual Excel files for each object."
            )
        else:
            message = (
                f"Metadata successfully exported!\n\n"
                f"Mode: {mode_desc}\n"
                f"Excel File: {output_path}"
            )
        
        messagebox.showinfo("Export Done", message)

        print_metadata_statistics(stats, runtime_formatted, output_path)

        # ✅ Re-enable all buttons
        self.button_manager.end_operation()




    def _on_metadata_export_error(self, error_message):
        """Called when metadata export fails"""
        self.update_status(f"❌ FATAL EXPORT ERROR: {error_message}")
        messagebox.showerror("Export Error", f"A fatal error occurred during export: {error_message}")

        # ✅ NEW: Re-enable all buttons
        self.button_manager.end_operation()
        
    # ──────────────────────────────────────────────────────────────────────────
    # Download Files — Filter modal
    # ──────────────────────────────────────────────────────────────────────────

    def open_download_filter_modal(self):
        """Open the filter configuration modal for Download Files."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Download Files — Filters")
        dialog.geometry("500x620")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()

        f = self.download_file_filters  # shorthand for pre-filling

        # ── Header ───────────────────────────────────────────────────────────
        ctk.CTkLabel(
            dialog,
            text="Download Files Filter",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(pady=(18, 2), padx=24, anchor="w")

        ctk.CTkLabel(
            dialog,
            text="Narrows the SOQL query before downloading. Leave fields blank to skip a filter.",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
            wraplength=450,
            justify="left",
        ).pack(padx=24, pady=(0, 10), anchor="w")

        # ── Helper: section heading ───────────────────────────────────────────
        def section(text):
            ctk.CTkLabel(
                dialog,
                text=text,
                font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(padx=24, pady=(10, 2), anchor="w")

        # ── Helper: labelled entry row ────────────────────────────────────────
        def labeled_entry(label: str, default: str = "", placeholder: str = "") -> ctk.CTkEntry:
            fr = ctk.CTkFrame(dialog, fg_color="transparent")
            fr.pack(fill="x", padx=24, pady=3)
            ctk.CTkLabel(fr, text=label, width=160, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(fr, width=260, placeholder_text=placeholder)
            entry.pack(side="left", padx=(6, 0))
            if default:
                entry.insert(0, default)
            return entry

        # ── Created Date ──────────────────────────────────────────────────────
        section("Created Date Range")
        created_from_entry = labeled_entry(
            "From (YYYY-MM-DD)", f.get("created_from", ""), "e.g. 2024-01-01"
        )
        created_to_entry = labeled_entry(
            "To   (YYYY-MM-DD)", f.get("created_to", ""),   "e.g. 2024-12-31"
        )

        # ── Last Modified Date ────────────────────────────────────────────────
        section("Last Modified Date Range")
        modified_from_entry = labeled_entry(
            "From (YYYY-MM-DD)", f.get("modified_from", ""), "e.g. 2024-01-01"
        )
        modified_to_entry = labeled_entry(
            "To   (YYYY-MM-DD)", f.get("modified_to", ""),   "e.g. 2024-12-31"
        )

        # ── Text LIKE filters ─────────────────────────────────────────────────
        section("Text Filters  (partial match, case-insensitive)")
        file_type_entry  = labeled_entry("FileType",      f.get("file_type", ""),      "e.g. PDF")
        file_ext_entry   = labeled_entry("FileExtension", f.get("file_extension", ""), "e.g. pdf")
        title_entry      = labeled_entry("Title",         f.get("title", ""),          "e.g. Invoice")

        # ── IsArchived ────────────────────────────────────────────────────────
        section("Archived Status")
        archived_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        archived_frame.pack(fill="x", padx=24, pady=3)
        ctk.CTkLabel(archived_frame, text="IsArchived", width=160, anchor="w").pack(side="left")
        archived_var = ctk.StringVar(value=f.get("is_archived", "Any"))
        ctk.CTkOptionMenu(
            archived_frame,
            values=["Any", "True", "False"],
            variable=archived_var,
            width=120,
        ).pack(side="left", padx=(6, 0))

        # ── Active filter count indicator ─────────────────────────────────────
        indicator_var = ctk.StringVar(value=self._filter_indicator_text())
        ctk.CTkLabel(
            dialog,
            textvariable=indicator_var,
            text_color="#F0A500",
            font=ctk.CTkFont(size=11),
        ).pack(pady=(10, 0), padx=24, anchor="w")

        # ── Date validation helper ────────────────────────────────────────────
        def validate_date(val: str, field_name: str) -> bool:
            import re
            if val and not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                messagebox.showerror(
                    "Invalid Date",
                    f'"{field_name}" must be in YYYY-MM-DD format.\nExample: 2024-06-15',
                    parent=dialog,
                )
                return False
            return True

        # ── Apply ─────────────────────────────────────────────────────────────
        def apply_filters():
            cf = created_from_entry.get().strip()
            ct = created_to_entry.get().strip()
            mf = modified_from_entry.get().strip()
            mt = modified_to_entry.get().strip()

            for val, name in [
                (cf, "Created From"),
                (ct, "Created To"),
                (mf, "Modified From"),
                (mt, "Modified To"),
            ]:
                if not validate_date(val, name):
                    return

            raw = {
                "created_from":   cf,
                "created_to":     ct,
                "modified_from":  mf,
                "modified_to":    mt,
                "file_type":      file_type_entry.get().strip(),
                "file_extension": file_ext_entry.get().strip(),
                "title":          title_entry.get().strip(),
                "is_archived":    archived_var.get(),
            }
            # Drop empty / "Any" values — cleaner dict, easier SOQL building
            self.download_file_filters = {
                k: v for k, v in raw.items() if v and v != "Any"
            }
            self._update_filter_button()
            dialog.destroy()

        # ── Clear ─────────────────────────────────────────────────────────────
        def clear_filters():
            self.download_file_filters = {}
            self._update_filter_button()
            dialog.destroy()

        # ── Button row ────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=(14, 20))

        ctk.CTkButton(
            btn_frame, text="✅ Apply Filter",
            command=apply_filters, fg_color="#2D7BD4", width=150,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="🗑 Clear All",
            command=clear_filters, fg_color="#C0392B", width=130,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="Cancel",
            command=dialog.destroy, fg_color=("gray70", "gray30"), width=100,
        ).pack(side="left")

    def _filter_indicator_text(self) -> str:
        """Return a short status string for the filter indicator label."""
        count = len(self.download_file_filters)
        return f"⚡ {count} active filter(s) applied" if count else ""

    def _update_filter_button(self):
        """
        Update the Filter button's label and colour to reflect whether
        any filters are currently active.
        """
        count = len(self.download_file_filters)
        if count > 0:
            self.download_filter_button.configure(
                text=f"🔍 Filter ({count})",
                fg_color="#E67E22",       # orange = filters active
                hover_color="#CA6F1E",
            )
        else:
            self.download_filter_button.configure(
                text="🔍 Filter",
                fg_color="#555E6B",       # default muted grey-blue
                hover_color="#3A4250",
            )    

    def download_files_action(self):
        """Handle download files button click"""
        if not self.sf_client or not self.content_document_exporter:
            messagebox.showerror("Error", "Not logged in. Please log in first.")
            return

        # ✅ NEW: Check if another operation is running
        if not self.button_manager.start_operation("File Download"):
            return

        default_filename = DEFAULT_CONTENTDOCUMENT_FILENAME.format(
            timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        output_file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=default_filename,
            filetypes=[("CSV files", "*.csv")]
        )

        if not output_file_path:
            # ✅ NEW: User cancelled, end operation
            self.button_manager.end_operation()
            return


        self.update_status("Starting ContentDocument export and file downloads...")
        start_time = time.time()

        # Run export in background thread
        def do_export():
            try:
                output_path, stats = self.content_document_exporter.export_content_documents(
                    output_file_path,
                    filters=self.download_file_filters or None,
                )

                end_time = time.time()
                runtime_seconds = end_time - start_time
                runtime_formatted = format_runtime(runtime_seconds)

                # Update UI on main thread
                self.after(0, lambda: self._on_download_files_success(
                    output_path, stats, runtime_formatted
                ))

            except Exception as e:
                # Handle error on main thread
                self.after(0, lambda: self._on_download_files_error(str(e)))

        ThreadHelper.run_in_thread(do_export)


    def _on_download_files_success(self, output_path, stats, runtime_formatted):
        """Called after successful file downloads"""
        self.update_status(f"Export Complete! Total Runtime: {runtime_formatted}")

        # Get documents folder path
        csv_dir = os.path.dirname(output_path)
        documents_folder = os.path.join(csv_dir, "Documents")

        # Build success message
        message = (
            f"ContentDocument export completed!\n\n"
            f"Documents Found: {stats['total_documents']}\n"
            f"Total Versions: {stats['total_versions']}\n"
            f"Successfully Downloaded: {stats['successful_downloads']}\n"
            f"Failed: {stats['failed_downloads']}\n\n"
            f"CSV File: {output_path}\n"
            f"Files Folder: {documents_folder}\n\n"
            f"💡 CSV is DataLoader-ready for migration!"
        )

        messagebox.showinfo("Export Done", message)

        print_content_document_statistics(stats, runtime_formatted, output_path, documents_folder)

        # ✅ Re-enable all buttons
        self.button_manager.end_operation()

    def _on_download_files_error(self, error_message):
        """Called when file download fails"""
        self.update_status(f"❌ FATAL EXPORT ERROR: {error_message}")
        messagebox.showerror("Export Error", f"A fatal error occurred during export: {error_message}")

        # ✅ NEW: Re-enable all buttons
        self.button_manager.end_operation()


    # ==================================
    # Attachment Download Action Methods
    # ==================================

    def download_attachments_action(self):
        """Handle Download Attachments button click (7th button)."""
        if not self.sf_client or not self.attachment_exporter:
            messagebox.showerror("Error", "Not logged in. Please log in first.")
            return

        if not self.selected_objects:
            messagebox.showwarning(
                "No Objects Selected",
                "Please select at least one object from the \'Available Objects\' list\n"
                "before downloading attachments.\n\n"
                "The attachment download is filtered by parent object type.\n"
                "For example, select \'Account\' to download only attachments\n"
                "attached to Account records."
            )
            return

        if not self.button_manager.start_operation("Attachment Download"):
            return

        selected_objects_list = sorted(list(self.selected_objects))

        default_filename = DEFAULT_ATTACHMENT_FILENAME.format(
            timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        output_file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=default_filename,
            filetypes=[("CSV files", "*.csv")]
        )

        if not output_file_path:
            self.button_manager.end_operation()
            return

        self.update_status(
            f"Starting Attachment download for: {', '.join(selected_objects_list)}…"
        )
        start_time = time.time()

        def do_export():
            try:
                output_path, stats = self.attachment_exporter.export_attachments(
                    output_file_path,
                    selected_objects=selected_objects_list,
                    status_callback=lambda msg: self.after(
                        0, lambda m=msg: self.update_status(m, verbose=True)
                    ),
                )
                end_time          = time.time()
                runtime_formatted = format_runtime(end_time - start_time)
                self.after(0, lambda: self._on_download_attachments_success(
                    output_path, stats, runtime_formatted
                ))
            except Exception as e:
                self.after(0, lambda: self._on_download_attachments_error(str(e)))

        ThreadHelper.run_in_thread(do_export)


    def _on_download_attachments_success(self, output_path, stats, runtime_formatted):
        """Called after successful attachment download."""
        self.update_status(f"Attachment Download Complete! Runtime: {runtime_formatted}")

        attachments_folder = os.path.join(os.path.dirname(output_path), "Attachments")

        obj_lines = ""
        for obj in stats.get("objects_processed", []):
            obj_lines += (
                f"  • {obj['object']}: "
                f"{obj['downloaded']} downloaded, {obj['failed']} failed\n"
            )

        total_mb = stats["total_size_bytes"] / (1024 * 1024)
        message = (
            f"Attachment download completed!\n\n"
            f"Total Attachments Found:   {stats['total_attachments']}\n"
            f"Successfully Downloaded:   {stats['successful_downloads']}\n"
            f"Failed:                    {stats['failed_downloads']}\n"
            f"Total Size:                {total_mb:.2f} MB\n\n"
            f"Per-object breakdown:\n{obj_lines}\n"
            f"CSV File:     {output_path}\n"
            f"Files Folder: {attachments_folder}\n\n"
            f"💡 CSV is DataLoader-ready for migration!"
        )
        messagebox.showinfo("Download Done", message)

        print("\n" + "=" * 70)
        print("✅ ATTACHMENT EXPORT COMPLETED")
        print("=" * 70)
        print(f"Runtime:                   {runtime_formatted}")
        print(f"Total Attachments Found:   {stats['total_attachments']}")
        print(f"✅ Successfully Downloaded: {stats['successful_downloads']}")
        print(f"❌ Failed:                  {stats['failed_downloads']}")
        print(f"Total Size:                {total_mb:.2f} MB")
        for obj in stats.get("objects_processed", []):
            print(f"  • {obj['object']}: {obj['downloaded']} ok, {obj['failed']} failed")
        if stats.get("failed_files"):
            print("\n❌ FAILED FILES:")
            for ff in stats["failed_files"]:
                print(f"   • {ff['filename']} (ID: {ff['id']}): {ff['reason']}")
        print("=" * 70)

        self.button_manager.end_operation()


    def _on_download_attachments_error(self, error_message):
        """Called when attachment download fails."""
        self.update_status(f"❌ ATTACHMENT DOWNLOAD ERROR: {error_message}")
        messagebox.showerror(
            "Download Error",
            f"A fatal error occurred during attachment download:\n\n{error_message}"
        )
        self.button_manager.end_operation()


    # ==================================
    # Utility Methods
    # ==================================

    def _log(self, message: str):
        """Alias for update_status — used by sub-frames."""
        self.update_status(message)

    def update_status(self, message: str, verbose: bool = False):
        """Updates the status text box. Also mirrors to the login activity log when visible."""
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        display_message = f"{timestamp} {message}"

        # Main export-screen log
        try:
            self.status_textbox.configure(state="normal")
            self.status_textbox.insert("end", "\n" + display_message)
            self.status_textbox.see("end")
            self.status_textbox.configure(state="disabled")
        except Exception:
            pass

        # Login-screen activity logs (both tabs)
        for _tb_attr in ("login_status_textbox",): 
            try:
                _tb = getattr(self, _tb_attr, None)
                if _tb and _tb.winfo_exists():
                    _tb.configure(state="normal")
                    _tb.insert("end", "\n" + display_message)
                    _tb.see("end")
                    _tb.configure(state="disabled")
            except Exception:
                pass

        if not verbose:
            # Double-layered safety:
            # Layer 1 — try normal print (works if main.py fixed encoding)
            # Layer 2 — fall back to ASCII-safe version
            # Layer 3 — silently swallow if stdout is None (windowed exe)
            try:
                print(display_message)
            except Exception:
                try:
                    import sys as _sys
                    if _sys.stdout is not None:
                        safe = display_message.encode('ascii', errors='replace').decode('ascii')
                        print(safe)
                except Exception:
                    pass  # windowed exe with no console — give up silently

        self.update_idletasks()

    def logout_action(self):
        """Clears connection, resets state, and returns to the login screen"""
        confirm = messagebox.askyesno("Logout", "Are you sure you want to log out?")
        if confirm:
            self.sf_client = None
            self.picklist_exporter = None
            self.metadata_exporter = None
            self.content_document_exporter = None
            self.attachment_exporter = None
            self.selected_objects.clear()
            self.all_org_objects.clear()
            self.soql_runner = None
            
            # Clear SOQL frame (existing)
            if self.soql_frame:
                try:
                    self.soql_frame.destroy()
                except:
                    pass
                self.soql_frame = None
            
            # Clear switch frame and manager (existing)
            if self.switch_frame:
                try:
                    self.switch_frame.destroy()
                except:
                    pass
                self.switch_frame = None
            self.metadata_switch_manager = None
            
            # Clear report exporter frame
            if self.report_exporter_frame:
                try:
                    if self.report_exporter_frame.winfo_exists():
                        try:
                            self.report_exporter_frame._is_being_destroyed = True
                        except:
                            pass
                        try:
                            self.report_exporter_frame.export_cancel_event.set()
                        except:
                            pass
                        self.after(100, lambda: self._destroy_report_frame())
                    else:
                        self.report_exporter_frame = None
                except Exception as e:
                    print(f"⚠️ Error closing report exporter: {e}")
                    self.report_exporter_frame = None
            

            try:
                self.update_status("Logged out successfully. Please log in again.")
            except:
                print("Logged out successfully. Please log in again.")
            
            # Switch back to Login Frame — shrink window back to login size
            self.export_frame.grid_forget()
            login_w = min(780, int(self.screen_w * 0.80))
            login_h = int(self.screen_h * 0.70)
            pos_x   = (self.screen_w - login_w) // 2
            pos_y   = (self.screen_h - login_h) // 2
            self.minsize(780, 500)   # reset before geometry to fix width-after-logout bug
            self.geometry(f"{login_w}x{login_h}+{pos_x}+{pos_y}")
            self.resizable(False, False)
            self.login_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
            
            # Show main window if it was hidden
            self.deiconify()

    def _destroy_report_frame(self):
        """Helper method to destroy report exporter frame safely"""
        if self.report_exporter_frame:
            try:
                if self.report_exporter_frame.winfo_exists():
                    self.report_exporter_frame.destroy()
            except Exception as e:
                print(f"⚠️ Error destroying report frame: {e}")
            finally:
                self.report_exporter_frame = None
                
                
                
    def _show_processing_overlay(self):
        try:
            self._processing_overlay = ctk.CTkToplevel(self)
            self._processing_overlay.overrideredirect(True)
            self._processing_overlay.attributes("-topmost", True)
            self._processing_overlay.resizable(False, False)

            # ✅ THE WINDOW ITSELF IS THE BLUE BORDER
            # padx=8, pady=8 on the card = equal 8px blue gap on all 4 sides
            self._processing_overlay.configure(fg_color="#009EDB")

            # Card sits inside with equal padding — that padding IS the blue border
            card = ctk.CTkFrame(
                self._processing_overlay,
                fg_color=("#ffffff", "#1e1e1e"),
                corner_radius=14
            )
            card.pack(padx=8, pady=8)

            # Icon
            ctk.CTkLabel(
                card,
                text="🔐",
                font=ctk.CTkFont(size=38),
            ).pack(pady=(22, 4))

            # Heading
            ctk.CTkLabel(
                card,
                text="Connecting to Salesforce...",
                font=ctk.CTkFont(size=15, weight="bold"),
            ).pack(padx=36)

            # Sub-text
            ctk.CTkLabel(
                card,
                text="Login successful. Verifying your session,\nthis takes just a moment.",
                font=ctk.CTkFont(size=12),
                text_color=("gray45", "gray60"),
                justify="center",
            ).pack(padx=36, pady=(8, 6))

            # Divider
            ctk.CTkFrame(card, height=1, fg_color=("gray80", "gray30")).pack(
                fill="x", padx=24, pady=(0, 10)
            )

            # Footer
            ctk.CTkLabel(
                card,
                text="Please wait — do not close the application.",
                font=ctk.CTkFont(size=10),
                text_color=("gray55", "gray50"),
            ).pack(pady=(0, 20))

            # Centre on screen
            self._processing_overlay.update_idletasks()
            w = self._processing_overlay.winfo_reqwidth()
            h = self._processing_overlay.winfo_reqheight()
            sx = self.winfo_screenwidth()
            sy = self.winfo_screenheight()
            self._processing_overlay.geometry(
                f"{w}x{h}+{(sx - w) // 2}+{(sy - h) // 2}"
            )
            self._processing_overlay.update()

        except Exception as e:
            print(f"⚠️ Could not show processing overlay: {e}")
            self._processing_overlay = None

    def _hide_processing_overlay(self):
        """Destroy the 'Connecting...' popup and restore the main window."""
        self._webview_running = False
        try:
            if getattr(self, "_processing_overlay", None):
                self._processing_overlay.destroy()
                self._processing_overlay = None
        except Exception:
            pass
        try:
            self.deiconify()   # Bring main window back
        except Exception:
            pass



def main():
    """Main entry point"""
    try:
        app = SalesforceExporterGUI()
        app.mainloop()
    except Exception as e:
        print(f"\n❌ GUI Application Failed: {str(e)}")
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()