"""
Salesforce Picklist & Metadata Exporter
Main entry point for the application

Prerequisites (Installation):
    pip install -r requirements.txt
"""
import sys
import io
import os


def _fix_console_encoding():
    """
    Fix stdout/stderr encoding before anything else runs.

    Two problems this solves:
    1. Windows console uses cp1252 by default — emoji like ✅ ❌ 🔧 crash print().
    2. PyInstaller --windowed exe has sys.stdout = None — any print() crashes.

    Must be called before importing gui or any module that might print.
    """
    for attr in ('stdout', 'stderr'):
        stream = getattr(sys, attr, None)

        if stream is None:
            # PyInstaller --windowed: no console attached.
            # Redirect to devnull so print() calls are silently swallowed.
            try:
                setattr(sys, attr, open(os.devnull, 'w', encoding='utf-8'))
            except Exception:
                pass

        elif hasattr(stream, 'reconfigure'):
            # Python 3.7+ best approach: reconfigure encoding in-place.
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass

        elif hasattr(stream, 'buffer'):
            # Fallback: wrap the raw binary buffer with UTF-8.
            try:
                setattr(sys, attr, io.TextIOWrapper(
                    stream.buffer,
                    encoding='utf-8',
                    errors='replace',
                    line_buffering=True,
                ))
            except Exception:
                pass


# Run encoding fix FIRST — before any other import that might print
_fix_console_encoding()

from gui import main  # noqa: E402 (import after encoding setup is intentional)

if __name__ == "__main__":
    main()