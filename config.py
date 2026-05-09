"""
Configuration constants for Salesforce Metadata Exporter
"""
import os
import json

# ── API ───────────────────────────────────────────────────────────────────────
# v65+ permanently disables SOAP login() — must stay at 64
API_VERSION = '64.0'

# ── OAuth port range ──────────────────────────────────────────────────────────
# Tries each port in order until one is free.
# All three must be registered as Callback URLs in the External Client App.
OAUTH_REDIRECT_PORT_RANGE = range(8888, 8908)

# ── Local settings file ───────────────────────────────────────────────────────
# Stores the user's Consumer Key after first-time setup.
# Saved as sfmetaexporter_settings.json next to the .exe on the user's machine.
# ── Resolve the correct directory whether running as .py or .exe ─────────────
# When PyInstaller bundles the app, sys.frozen is True and sys.executable
# is the path to the .exe. Using __file__ would point to the temp extraction
# folder PyInstaller uses internally — the user would never find the JSON there.
import sys as _sys
if getattr(_sys, 'frozen', False):
    # Running as a PyInstaller .exe — put the JSON next to the .exe
    SCRIPT_DIR = os.path.dirname(_sys.executable)
else:
    # Running as a plain .py script — put the JSON next to main.py / config.py
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(SCRIPT_DIR, "sfmetaexporter_settings.json")


def load_settings() -> dict:
    """Load saved settings from disk. Returns empty dict if file doesn't exist."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_settings(data: dict):
    """Merge and persist settings to disk."""
    try:
        existing = load_settings()
        existing.update(data)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        print(f"Warning: could not save settings: {e}")


def get_oauth_client_id() -> str:
    """Return the saved Consumer Key, or empty string if not set yet."""
    return load_settings().get("oauth_client_id", "")


def set_oauth_client_id(key: str):
    """Save a Consumer Key to disk."""
    save_settings({"oauth_client_id": key.strip()})


# ── Window ────────────────────────────────────────────────────────────────────
# Computed at runtime as 70% of primary monitor — see SalesforceExporterGUI.__init__
WINDOW_TITLE    = "Salesforce Metadata Exporter"
APPEARANCE_MODE = "System"
COLOR_THEME     = "blue"

# ── Paths ─────────────────────────────────────────────────────────────────────

# ── Export filenames ──────────────────────────────────────────────────────────
DEFAULT_PICKLIST_FILENAME        = 'Picklist_Export_{timestamp}.xlsx'
DEFAULT_METADATA_FILENAME        = 'Object_Metadata_{timestamp}.csv'
DEFAULT_CONTENTDOCUMENT_FILENAME = 'ContentDocument_Export_{timestamp}.csv'
