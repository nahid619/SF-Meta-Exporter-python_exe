# main_app.py - REDESIGNED VERSION
# Salesforce Report Exporter with Tree View and Dual-Panel Selection

import customtkinter as ctk
import threading
import queue
import os
import subprocess
import platform
import datetime
import time
from tkinter import filedialog, messagebox, ttk
from typing import Optional, List, Dict, Any, Callable

# ✅ UPDATED: Use relative imports for module files
from .exporter import SalesforceReportExporter
from .virtual_tree import VirtualTreeView

class ExportProgressTracker:
    """
    Track export progress with ETA and speed calculation.
    """
    
    def __init__(self):
        self.start_time = None
        self.completed = 0
        self.total = 0
        self.last_update_time = None
        self.last_completed = 0
        self.speed_samples = []  # Rolling average of speed
        self.max_samples = 10
    
    def start(self, total: int):
        """Start tracking progress"""
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.completed = 0
        self.total = total
        self.last_completed = 0
        self.speed_samples = []
    
    def update(self, completed: int):
        """Update progress"""
        current_time = time.time()
        
        if self.last_update_time:
            time_delta = current_time - self.last_update_time
            if time_delta > 0:
                # Calculate instant speed
                items_delta = completed - self.last_completed
                instant_speed = items_delta / time_delta
                
                # Add to rolling average
                self.speed_samples.append(instant_speed)
                if len(self.speed_samples) > self.max_samples:
                    self.speed_samples.pop(0)
        
        self.completed = completed
        self.last_update_time = current_time
        self.last_completed = completed
    
    def get_speed(self) -> float:
        """Get current speed (reports/second)"""
        if not self.speed_samples:
            return 0.0
        return sum(self.speed_samples) / len(self.speed_samples)
    
    def get_eta_seconds(self) -> float:
        """Get estimated time remaining in seconds"""
        speed = self.get_speed()
        if speed <= 0:
            return 0.0
        
        remaining = self.total - self.completed
        return remaining / speed
    
    def get_elapsed_seconds(self) -> float:
        """Get elapsed time in seconds"""
        if not self.start_time:
            return 0.0
        return time.time() - self.start_time
    
    def format_time(self, seconds: float) -> str:
        """Format seconds into human-readable time"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
    
    def get_progress_text(self) -> str:
        """Get formatted progress text with ETA and speed"""
        if self.total == 0:
            return "Ready to export"
        
        percentage = int((self.completed / self.total) * 100)
        speed = self.get_speed()
        eta_seconds = self.get_eta_seconds()
        
        text = f"Exporting: {self.completed}/{self.total} reports ({percentage}%)"
        
        if speed > 0:
            text += f" • {speed:.1f} reports/sec"
        
        if eta_seconds > 0 and self.completed < self.total:
            eta_formatted = self.format_time(eta_seconds)
            text += f" • ETA: {eta_formatted}"
        
        return text
    
    def get_completion_text(self) -> str:
        """Get formatted completion text with statistics"""
        elapsed = self.get_elapsed_seconds()
        elapsed_formatted = self.format_time(elapsed)
        
        avg_speed = self.completed / elapsed if elapsed > 0 else 0
        
        text = f"✅ Completed {self.completed}/{self.total} reports in {elapsed_formatted}"
        
        if avg_speed > 0:
            text += f" (avg: {avg_speed:.1f} reports/sec)"
        
        return text

class SalesforceExporterApp(ctk.CTkToplevel):
    """
    Main application window for Salesforce Report Exporter.
    Redesigned with folder/report tree view and dual-panel selection.
    """
    
    def __init__(self, master, session_info: Dict, on_logout: Optional[Callable] = None):
        """Initialize with improved state management"""
        super().__init__(master)
        
        # ✅ CRITICAL: Initialize _log method FIRST (before anything else)
        self._log_buffer = []  # Buffer for early log messages
        
        # ✅ NEW: Store theme colors for UI elements
        self.theme_colors = self._get_theme_colors()
        
        # Store session info and logout callback
        self.session_info = session_info
        self.on_logout_callback = on_logout
        
        # This prevents AttributeError when window configure events fire early
        self.is_exporting = False  
        self.is_loading = False    
        self._export_state = "idle" 
        self._showing_dialog = False 
        
        # ✅ NEW: Search results cache
        self.search_cache: Dict[str, Dict] = {}  
        self.search_cache_max_size = 10
        
        # Thread Safety - Initialize locks early
        self.data_lock = threading.RLock()
        self.ui_lock = threading.RLock()
        self.state_lock = threading.RLock() 
        
        # Export control
        self.export_cancel_event = threading.Event()
        
        # ✅ NEW: Prevent double-initialization
        self._initialized = False
        
        # Window setup (after basic state init)
        self.title("Salesforce Report Exporter")
        self.geometry("1200x740")
        
        if master and master.winfo_exists():
            try:
                master.withdraw()
            except:
                pass
        
        # ✅ NEW: Apply parent's appearance mode instead of hardcoding
        parent_appearance = session_info.get("appearance_mode", "Dark")
        ctk.set_appearance_mode(parent_appearance)
        ctk.set_default_color_theme("blue")

        #self._log(f"🎨 Theme: {parent_appearance} mode")
        
        # UI State Management
        self.ui_state = "idle"
        self.pending_ui_operations = []
        
        # Session data
        self.output_zip_path: Optional[str] = None
        self.available_folders: List[Dict] = []
        self.available_reports: List[Dict] = []
        self.reports_by_folder: Dict[str, List[Dict]] = {}
        
        # Selection tracking
        self.selected_items: Dict[str, Dict] = {}
        self.search_timer = None
        
        self.last_search_keyword: Optional[str] = None
        
        # ✅ NEW: Virtual tree view instance
        self.virtual_tree: Optional[VirtualTreeView] = None
        self.tree_items: Dict[str, Dict] = {}
        
        # Progress tracker
        self.progress_tracker = ExportProgressTracker()
        
        # Queue for thread-safe UI updates
        self.update_queue = queue.Queue()
        
        # Window configuration tracking
        self._configure_timer = None
        self._last_window_geometry = None
        self._last_export_state = None
        
        # ✅ NEW: Destruction flag
        self._is_being_destroyed = False
        
        # ✅ IMPORTANT: Setup UI BEFORE starting queue processor
        self._setup_ui()
        
        # ✅ NOW the log textbox exists, flush buffered messages
        self._flush_log_buffer()
        
        parent_appearance = self.session_info.get("appearance_mode", "Dark")
        self._log(f"🎨 Theme: {parent_appearance} mode")
        
        # Center window on screen
        self.after(100, self._center_window)
       
        
        # Start queue processor
        self._process_queue()
        
        # Bind window close event
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # Keyboard shortcuts
        self.unbind('<Control-e>')
        self.unbind('<Escape>')
        self.unbind('<F5>')
        self.bind('<Control-e>', lambda e: self._start_export_safe())
        self.bind('<Escape>', lambda e: self._cancel_export_safe())
        self.bind('<F5>', lambda e: self._on_refresh_clicked())
        
        # Window configuration tracking
        self.bind('<Configure>', self._on_window_configure)
        
        # ✅ Mark as initialized
        self._initialized = True
        
        # Auto-load data after UI is ready
        self.after(500, self._show_welcome_message)
    
    def _log(self, message: str):
        """
        Add message to log.
        ✅ FIXED: Safe to call even before UI is ready.
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}\n"
        
        # ✅ Check if log textbox exists yet
        if not hasattr(self, 'log_textbox') or not self.log_textbox.winfo_exists():
            # Buffer the message for later
            if hasattr(self, '_log_buffer'):
                self._log_buffer.append(log_msg)
            return
        
        try:
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", log_msg)
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        except Exception as e:
            print(f"⚠️ Log error: {e}")
            # Fallback to console
            print(log_msg.strip())
            

    def _get_theme_colors(self) -> dict:
        """
        Get theme-appropriate colors based on current appearance mode.
        
        Returns:
            Dictionary with color values for current theme
        """
        appearance = ctk.get_appearance_mode()
        
        if appearance == "Light":
            return {
                # Light mode colors
                "bg_primary": "#F0F0F0",        # Light gray background
                "bg_secondary": "#FFFFFF",      # White secondary
                "bg_container": "#E8E8E8",      # Light container
                "fg_text": "#000000",           # Black text
                "fg_text_dim": "#666666",       # Dark gray for secondary text
                "border": "#CCCCCC",            # Light border
                "selection_bg": "#0078D4",      # Blue selection
                "selection_fg": "#FFFFFF",      # White text on selection
                "hover": "#DADADA",            # Hover effect
                "error": "#D32F2F",             # Red (same in both)
                "success": "#2E7D32",           # Green (same in both)
                "warning": "#F57C00"            # Orange (same in both)
            }
        else:
            return {
                # Dark mode colors (original)
                "bg_primary": "#2b2b2b",
                "bg_secondary": "#1a1a1a",
                "bg_container": "#333333",
                "fg_text": "#FFFFFF",
                "fg_text_dim": "gray",
                "border": "#444444",
                "selection_bg": "#1f6aa5",
                "selection_fg": "#FFFFFF",
                "hover": "#3a3a3a",
                "error": "#d32f2f",
                "success": "#2e7d32",
                "warning": "#f57c00"
            }            



    def _flush_log_buffer(self):
        """
        Flush buffered log messages to the textbox.
        ✅ NEW: Called after UI is ready.
        """
        if not hasattr(self, '_log_buffer'):
            return
        
        if not self._log_buffer:
            return
        
        if not hasattr(self, 'log_textbox') or not self.log_textbox.winfo_exists():
            return
        
        try:
            self.log_textbox.configure(state="normal")
            for msg in self._log_buffer:
                self.log_textbox.insert("end", msg)
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
            
            # Clear buffer
            self._log_buffer.clear()
            
            print(f"✅ Flushed {len(self._log_buffer)} buffered log messages")
        except Exception as e:
            print(f"⚠️ Error flushing log buffer: {e}")    
    
    
        
    
    def _cancel_export_safe(self):
        """
        Safe wrapper for ESC key binding.
        Only cancels if actually exporting.
        """
        export_state = self._get_export_state()
        
        if export_state == "running":
            self._cancel_export()
        else:
            print(f"ℹ️ ESC pressed but export state is '{export_state}' - ignoring")
            
    def _setup_ui(self):
        """Setup the main UI layout"""
        
        # Configure grid layout (3 rows)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Header (fixed height)
        self.grid_rowconfigure(1, weight=1)  # Main content (expandable)
        self.grid_rowconfigure(2, weight=0)  # Bottom section (fixed height)
        
        # Header
        self._create_header()
        
        # Main content area (3-panel layout)
        self._create_main_content()
        
        # Bottom section (file naming, progress, export button, log)
        self._create_bottom_section()
        
    def _center_window(self):
        """Center the main window on screen"""
        # Force window to update and calculate its actual size
        self.update_idletasks()
        
        # Explicitly set the geometry again to ensure it's correct
        self.geometry("1200x740")
        
        # Wait a tiny bit for the geometry to apply
        self.update_idletasks()
        
        # Now calculate center position
        width = 1200
        height = 740
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        
        # Apply the centered geometry
        self.geometry(f'{width}x{height}+{x}+{y}')
    
    # ===== NEW: UI STATE MANAGEMENT METHODS =====
    # ✅ NEW: Atomic state management methods
    def _get_export_state(self) -> str:
        """Get current export state (thread-safe)"""
        with self.state_lock:
            return self._export_state
        
    def _set_export_state(self, new_state: str):
        """
        Set export state atomically (thread-safe).
        Valid states: "idle", "running", "cancelling"
        """
        with self.state_lock:
            old_state = self._export_state
            self._export_state = new_state
            
            # Auto-sync is_exporting for backward compatibility
            self.is_exporting = (new_state in ("running", "cancelling"))
            
            # Log state transitions for debugging
            if old_state != new_state:
                print(f"🔄 Export state: {old_state} → {new_state}")


    def _is_export_busy(self) -> bool:
        """Check if export is currently running or cancelling"""
        state = self._get_export_state()
        return state in ("running", "cancelling")


    def _reset_export_state(self):
        """Reset export state to idle and clear all flags"""
        with self.state_lock:
            self._export_state = "idle"
            self.is_exporting = False
            self._showing_dialog = False
            self.export_cancel_event.clear()
            
            print("🔄 Export state reset to IDLE")        
        
    def _set_ui_state(self, state: str):
        """
        Set UI state and update UI accordingly.
        States: 'idle', 'loading', 'exporting'
        """
        with self.ui_lock:
            self.ui_state = state
            
            if state == "idle":
                self.is_loading = False
                self.is_exporting = False
                
            elif state == "loading":
                self.is_loading = True
                self.is_exporting = False
                
            elif state == "exporting":
                self.is_loading = False
                self.is_exporting = True
    
    def _is_ui_busy(self) -> bool:
        """Check if UI is currently busy with an operation"""
        with self.ui_lock:
            return self.ui_state != "idle"
    
    def _safe_ui_update(self, callback, *args, **kwargs):
        """
        Execute UI update safely on main thread.
        Prevents race conditions and ensures thread safety.
        
        IMPROVED: Better error handling and thread detection.
        """
        def wrapper():
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"⚠️ UI update error in callback: {str(e)}")
        
        # Check if we're on main thread
        try:
            import threading
            if threading.current_thread() is threading.main_thread():
                # Already on main thread - execute immediately
                wrapper()
            else:
                # Schedule on main thread
                self.after(0, wrapper)
        except Exception:
            # Fallback: always schedule
            try:
                self.after(0, wrapper)
            except:
                # Last resort: use queue
                self.update_queue.put(("ui_update", (callback, args, kwargs)))
    
    def _prevent_double_click(self, button: ctk.CTkButton, duration: float = 2.0):
        """
        Disable button temporarily to prevent double-clicks.
        Re-enables after duration seconds.
        """
        button.configure(state="disabled")
        
        def re_enable():
            try:
                button.configure(state="normal")
            except:
                pass  # Button might be destroyed
        
        self.after(int(duration * 1000), re_enable)
    
    def _on_closing(self):
        """
        Handle window close event.
        
        ✅ FIXED: Now behaves like Back button (return to parent, no logout)
        """
        if self._is_ui_busy():
            result = messagebox.askyesno(
                "Operation in Progress",
                "An operation is in progress. Are you sure you want to exit?\n\n"
                "This will cancel the current operation.",
                icon='warning'
            )
            
            if not result:
                return
            
            # Cancel ongoing operations
            self.export_cancel_event.set()
            self._log("🛑 Cancelling operations...")
            
            # Give threads time to cleanup, then close
            self.after(500, self._force_close)
        else:
            # No operations running - can close immediately
            self._force_close()
    
    def _force_close(self):
        """
        Force close the window and return to parent.
        
        ✅ FIXED: Same behavior as Back button (no logout)
        """
        try:
            self.grab_release()
        except:
            pass
        
        # If we have a back callback, use it (proper flow)
        if self.on_logout_callback:
            try:
                self.on_logout_callback()
                return
            except:
                pass
        
        # Fallback: destroy directly
        try:
            self.destroy()
        except:
            pass
    
    
    def _on_window_configure(self, event=None):
        """
        Handle window move/resize events with debouncing.
        Fixes button visibility issues when moving between monitors.
        
        ✅ IMPROVED: Better safety checks and early bailout
        """
        # ✅ SAFETY: Ignore if being destroyed
        if hasattr(self, '_is_being_destroyed') and self._is_being_destroyed:
            return
        
        # ✅ SAFETY: Ignore if not initialized
        if not hasattr(self, '_initialized') or not self._initialized:
            return
        
        # Only process events for the main window (not child widgets)
        if event and event.widget != self:
            return
        
        # ✅ SAFETY: Check if attributes exist
        required_attrs = ['is_exporting', '_configure_timer', 'ui_lock']
        for attr in required_attrs:
            if not hasattr(self, attr):
                return
        
        # ✅ Cancel any pending configure updates (debouncing)
        if self._configure_timer:
            try:
                self.after_cancel(self._configure_timer)
            except:
                pass
        
        # ✅ Adaptive delay based on current state
        try:
            with self.ui_lock:
                delay = 400 if self.is_exporting else 100
        except:
            delay = 100  # Fallback if lock fails
        
        self._configure_timer = self.after(delay, self._apply_window_configure)

    def _apply_window_configure(self):
        """
        Apply window configuration changes after debounce delay.
        
        ✅ IMPROVED: More safety checks
        """
        # ✅ SAFETY: Ignore if being destroyed
        if hasattr(self, '_is_being_destroyed') and self._is_being_destroyed:
            return
        
        try:
            # ✅ SAFETY: Check attributes exist
            if not hasattr(self, 'is_exporting') or not hasattr(self, '_initialized'):
                return
            
            if not self._initialized:
                return
            
            # Refresh buttons with current state
            self._refresh_button_visibility()
            
        except Exception as e:
            # Log errors for debugging
            try:
                print(f"⚠️ Window configure error: {e}")
            except:
                pass
        finally:
            # Clear timer reference
            self._configure_timer = None


    def _refresh_button_visibility(self):
        """
        Refresh export/cancel button visibility based on ACTUAL current state.
        
        This is the SINGLE SOURCE OF TRUTH for button visibility.
        Thread-safe and handles all edge cases.
        
        ✅ IMPROVED: Better error handling and existence checks.
        """
        # ✅ SAFETY: Check if widgets exist
        if not hasattr(self, 'export_button') or not hasattr(self, 'cancel_button'):
            print("⚠️ Export/Cancel buttons not initialized yet")
            return
        
        try:
            if not self.export_button.winfo_exists() or not self.cancel_button.winfo_exists():
                print("⚠️ Export/Cancel buttons destroyed")
                return
        except:
            print("⚠️ Cannot check button existence")
            return
        
        # ✅ CRITICAL: Read state atomically
        export_state = self._get_export_state()
        is_cancelling = self.export_cancel_event.is_set()
        
        # Debug logging
        print(f"🔄 Refreshing buttons: state={export_state}, cancelling={is_cancelling}")
        
        try:
            if export_state == "running":
                # ===== EXPORTING: Show CANCEL button =====
                
                if is_cancelling:
                    # User clicked cancel - button should be disabled
                    self.cancel_button.configure(
                        state="disabled",
                        text="🛑 Cancelling..."
                    )
                else:
                    # Export is running - button should be ENABLED and clickable
                    self.cancel_button.configure(
                        state="normal",
                        text="🛑 Cancel Export"
                    )
                
                # Show cancel button
                self.cancel_button.grid(row=0, column=0, sticky="ew")
                self.cancel_button.lift()
                
                # Hide export button
                self.export_button.grid_remove()
                
            else:
                # ===== IDLE or CANCELLING: Show EXPORT button =====
                
                # Show export button FIRST (no gap)
                self.export_button.grid(row=0, column=0, sticky="ew")
                self.export_button.lift()
                
                # Hide cancel button
                self.cancel_button.grid_remove()
                self.cancel_button.configure(state="disabled", text="🛑 Cancel Export")
                self.cancel_button.lower()
                
                # Update export button enabled/disabled state
                self._update_export_button_state()
            
            # Force UI update
            self.update_idletasks()
            
            print(f"✅ Buttons refreshed successfully")
            
        except Exception as e:
            print(f"⚠️ Button visibility error: {e}")
            import traceback
            traceback.print_exc()
            
    def _create_header(self):
        """Create header section with title and login status"""
        header_frame = ctk.CTkFrame(self, height=70, corner_radius=0)
        header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        header_frame.grid_propagate(False)
        
        # Left side - Back button + Title
        left_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True, padx=20, pady=10)
        
        # ✅ NEW - Back button container
        back_container = ctk.CTkFrame(left_frame, fg_color="transparent")
        back_container.pack(side="left", padx=(0, 15))
        
        # ✅ NEW - Back button
        self.back_button = ctk.CTkButton(
            back_container,
            text="← Back",
            command=self._on_back_clicked,
            width=100,
            height=32,
            fg_color="#666666",
            hover_color="#555555",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.back_button.pack()
        
        # Title
        title_label = ctk.CTkLabel(
            left_frame,
            text="📊 Salesforce Report Exporter",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        title_label.pack(side="left", anchor="w")
        
        self.subtitle_label = ctk.CTkLabel(
            left_frame,
            text="Select folders and reports to export • F5 to refresh • Ctrl+E to export • ESC to cancel",
            font=ctk.CTkFont(size=11),
            text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
            justify="center"
        )
        self.subtitle_label.pack(anchor="w", pady=(3, 0))
        
        # Right side - Login status and refresh button (NO LOGOUT)
        right_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_frame.pack(side="right", padx=20, pady=10)

        # Status based on session_info
        instance = self.session_info.get("instance_url", "").replace('https://', '')
        api_version = self.session_info.get("api_version", "")
        user_name = self.session_info.get("user_name", "")

        status_text = f"🟢 {instance}"
        if api_version:
            status_text += f" (API v{api_version})"

        self.status_label = ctk.CTkLabel(
            right_frame,
            text=status_text,
            font=ctk.CTkFont(size=12),
            text_color="green"
        )
        self.status_label.pack(pady=(0, 5))

        # ✅ ONLY Refresh button (logout button REMOVED)
        self.refresh_button = ctk.CTkButton(
            right_frame,
            text="🔄 Refresh",
            command=self._on_refresh_clicked,
            width=120,
            height=32,
            fg_color="#1f6aa5",
            hover_color="#144870",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.refresh_button.pack()
        self.refresh_button.configure(state="disabled")


    
    def _create_main_content(self):
        """Create main content area with 3 panels: Available | Actions | Selected"""
        
        # Main content container
        content_frame = ctk.CTkFrame(self, corner_radius=0)
        content_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=1)  # Left panel
        content_frame.grid_columnconfigure(1, weight=1)  # Right panel (removed middle)
        
        # LEFT PANEL - Available Items
        self._create_left_panel(content_frame)
        
        # RIGHT PANEL - Selected Items (changed column from 2 to 1)
        self._create_right_panel(content_frame)
    
    def _create_left_panel(self, parent):
        """Create left panel - Clean, compact layout with search button"""
        
        left_panel = ctk.CTkFrame(parent)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        
        # ✅ SIMPLIFIED: Only 2 rows now (search + tree)
        left_panel.grid_rowconfigure(0, weight=0)  # Search section (fixed)
        left_panel.grid_rowconfigure(1, weight=1)  # Tree view (expands)
        left_panel.grid_columnconfigure(0, weight=1)
        
        # ========== ROW 0: Search Section ==========
        search_container = ctk.CTkFrame(left_panel, fg_color="transparent")
        search_container.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 10))
        search_container.grid_columnconfigure(0, weight=1)
        
        # Header label (compact)
        header_label = ctk.CTkLabel(
            search_container,
            text="Available Reports/Folders",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w"
        )
        header_label.grid(row=0, column=0, sticky="w", pady=(0, 8))
        
        # Search box + button in one row
        search_frame = ctk.CTkFrame(search_container, fg_color="transparent")
        search_frame.grid(row=1, column=0, sticky="ew")
        search_frame.grid_columnconfigure(0, weight=1)  # Entry expands
        search_frame.grid_columnconfigure(1, weight=0)  # Button fixed
        
        # Search entry
        self.left_search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="🔍 Search folders and reports...",
            height=34
        )
        self.left_search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        
        # Search button
        self.search_button = ctk.CTkButton(
            search_frame,
            text="🔍 Search",
            command=self._on_search_button_clicked,
            width=95,
            height=34,
            fg_color="#1f6aa5",
            hover_color="#144870",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.search_button.grid(row=0, column=1)
        
        # Bind Enter key to search
        self.left_search_entry.bind("<Return>", lambda e: self._on_search_button_clicked())
        
        # ========== ROW 1: Tree View Container (expands fully) ==========
        self.tree_container = ctk.CTkScrollableFrame(
            left_panel,
            fg_color=self.theme_colors["bg_container"],  # ✅ Theme-aware
            corner_radius=5
        )
        self.tree_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.tree_container.grid_columnconfigure(0, weight=1)
        
        # Show helpful empty state (no auto-load)
        self._show_empty_search_state()
        
        # Initialize virtual tree (will be populated after search)
        self.virtual_tree = None
        self.tree_items: Dict[str, Dict] = {}
    
    
    def _create_right_panel(self, parent):
        """Create right panel - Compact layout"""
        
        right_panel = ctk.CTkFrame(parent)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10) 
        
        # Configure rows (Row 2 gets the expansion)
        right_panel.grid_rowconfigure(0, weight=0)
        right_panel.grid_rowconfigure(1, weight=0)
        right_panel.grid_rowconfigure(2, weight=1) # List expands
        right_panel.grid_rowconfigure(3, weight=0)
        right_panel.grid_columnconfigure(0, weight=1)
        
        # Header - REDUCED PADDING
        header_label = ctk.CTkLabel(
            right_panel,
            text="Selected for Export",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))  # ✅ REDUCED from pady=(10, 5)
        
        # Selection count - REDUCED PADDING
        self.selection_count_label = ctk.CTkLabel(
            right_panel,
            text="0 reports selected",
            font=ctk.CTkFont(size=12),
            text_color=self.theme_colors["fg_text_dim"]  # ✅ Theme-aware
        )
        self.selection_count_label.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 3))  # ✅ REDUCED from pady=(0, 5)
        
        # Selected items list (Scrollable, expands)
        self.selected_container = ctk.CTkScrollableFrame(
            right_panel,
            fg_color=self.theme_colors["bg_container"],  # ✅ Theme-aware
            corner_radius=5
        )
        self.selected_container.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 5))  # ✅ REDUCED from pady=(0, 10)
        self.selected_container.grid_columnconfigure(0, weight=1)
        
        # Placeholder
        self.selected_placeholder = ctk.CTkLabel(
            self.selected_container,
            text="No reports selected.\nSelect from left panel.",
            text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
            font=ctk.CTkFont(size=12),
            justify="center"
        )
        self.selected_placeholder.grid(row=0, column=0, pady=30)
        
        # Actions section - REDUCED PADDING
        actions_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        actions_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))  # ✅ REDUCED from pady=(0, 10)
        actions_frame.grid_columnconfigure(0, weight=1)
        
        actions_label = ctk.CTkLabel(
            actions_frame,
            text="Actions",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        actions_label.grid(row=0, column=0, sticky="w", pady=(0, 2))
        
        # Quick remove all button - SMALLER HEIGHT
        self.clear_selected_button = ctk.CTkButton(
            actions_frame,
            text="Clear All Selected",
            command=self._clear_all_selected,
            height=28,  # ✅ REDUCED from 30
            fg_color="#d32f2f",
            hover_color="#9a2222",
            state="disabled"
        )
        self.clear_selected_button.grid(row=1, column=0, sticky="ew", pady=(0, 3))  # ✅ REDUCED from pady=(0, 5)
    
    def _create_bottom_section(self):
        """Create bottom section with optimized 2-column layout"""
        
        bottom_frame = ctk.CTkFrame(self, corner_radius=0)
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        bottom_frame.grid_columnconfigure(0, weight=1)  # Left column expands
        bottom_frame.grid_columnconfigure(1, weight=1)  # Right column expands
        
        # ========== TOP ROW: 2-Column Layout ==========
        # ✅ UPDATED: Uniform padding between columns (10px each side = 20px gap)
        
        # LEFT COLUMN: File naming
        left_column = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        left_column.grid(row=0, column=0, sticky="nsew", padx=(10, 10), pady=(8, 5))  # ✅ Changed from (10, 5)
        left_column.grid_columnconfigure(1, weight=1)  # Entry expands
        
        # RIGHT COLUMN: Export format and button
        right_column = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        right_column.grid(row=0, column=1, sticky="nsew", padx=(10, 10), pady=(8, 5))  # ✅ Changed from (5, 10)
        right_column.grid_columnconfigure(1, weight=1)  # Format container expands
        
        # ========== LEFT COLUMN - ROW 0: ZIP Filename ==========
        zip_label = ctk.CTkLabel(
            left_column,
            text="ZIP Filename:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=120
        )
        zip_label.grid(row=0, column=0, padx=(15, 10), pady=(0, 5), sticky="w")
        
        self.filename_entry = ctk.CTkEntry(
            left_column,
            placeholder_text="salesforce_reports_20251201.zip",
            height=35
        )
        self.filename_entry.grid(row=0, column=1, sticky="ew", padx=(0, 15), pady=(0, 5))
        
        # Auto-generate timestamp filename
        self._generate_default_filename()
        
        # ========== LEFT COLUMN - ROW 1: Save Location ==========
        # ✅ UPDATED: Increased top padding from 0 to 10 for better row separation
        location_label = ctk.CTkLabel(
            left_column,
            text="Save Location:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=120
        )
        location_label.grid(row=1, column=0, padx=(15, 10), pady=(10, 5), sticky="w")  # ✅ Changed from (0, 5)
        
        # Container for entry + browse button
        location_container = ctk.CTkFrame(left_column, fg_color="transparent")
        location_container.grid(row=1, column=1, sticky="ew", padx=(0, 15), pady=(10, 5))  # ✅ Changed from (0, 5)
        location_container.grid_columnconfigure(0, weight=1)
        
        self.location_entry = ctk.CTkEntry(
            location_container,
            placeholder_text="Click Browse to select save location...",
            height=35,
            state="readonly"
        )
        self.location_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        self.browse_button = ctk.CTkButton(
            location_container,
            text="Browse...",
            command=self._browse_save_location,
            width=100,
            height=35
        )
        self.browse_button.grid(row=0, column=1)

    # ========== RIGHT COLUMN - ROW 0: Export Format ==========
        format_label = ctk.CTkLabel(
            right_column,
            text="Export Format:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=120
        )
        format_label.grid(row=0, column=0, padx=(15, 10), pady=(0, 5), sticky="w")
        
        # Radio button container
        radio_container = ctk.CTkFrame(right_column, fg_color="transparent")
        radio_container.grid(row=0, column=1, sticky="w", padx=(0, 15), pady=(0, 5))
        
        # Export format variable (default: CSV)
        self.export_format = ctk.StringVar(value="csv")
        
        # CSV Radio Button
        self.csv_radio = ctk.CTkRadioButton(
            radio_container,
            text="CSV Format (.csv)",
            variable=self.export_format,
            value="csv",
            font=ctk.CTkFont(size=12),
            command=self._on_format_changed
        )
        self.csv_radio.pack(side="left", padx=(0, 20))
        
        # Excel Radio Button
        # Excel Radio Button
        self.excel_radio = ctk.CTkRadioButton(
            radio_container,
            text="Excel Format (.xlsx) ",
            variable=self.export_format,
            value="xlsx",
            font=ctk.CTkFont(size=12),
            command=self._on_format_changed
        )
        self.excel_radio.pack(side="left")

        # ✅ NEW: Add helpful note about Excel format
        # ✅ Excel format explanation
        excel_note = ctk.CTkLabel(
            right_column,
            text="💡 Excel: Uses Salesforce's NATIVE exporter (same file as UI download). Preserves ALL formatting, groupings, and subtotals.",
            font=ctk.CTkFont(size=10),
            text_color=self.theme_colors["fg_text_dim"],
            wraplength=400,
            justify="left"
        )
        excel_note.grid(row=1, column=1, sticky="w", padx=(15, 15), pady=(0, 5))
        
        # ========== RIGHT COLUMN - ROW 1: Export/Cancel Button ==========
        # ✅ UPDATED: Increased top padding from 0 to 10 to match left column row separation
        button_container = ctk.CTkFrame(right_column, fg_color="transparent")
        button_container.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(15, 15), pady=(10, 5))  # ✅ Changed from (0, 5)
        button_container.grid_columnconfigure(0, weight=1)
        
        # Export button
        self.export_button = ctk.CTkButton(
            button_container,
            text="🚀 Export Reports",
            command=self._start_export_safe,
            height=45,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#1f6aa5",
            hover_color="#144870",
            state="disabled"
        )
        self.export_button.grid(row=0, column=0, sticky="ew")
        
        # Cancel button (hidden by default, overlays export button)
        self.cancel_button = ctk.CTkButton(
            button_container,
            text="🛑 Cancel Export",
            command=self._cancel_export,
            height=45,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#d32f2f",
            hover_color="#9a2222",
            state="disabled"
        )
        self.cancel_button.grid(row=0, column=0, sticky="ew")
        self.cancel_button.grid_remove()  # Hide initially
        self.cancel_button.lower()
        
        # ========== MIDDLE ROW: Progress Bar (Full Width) ==========
        progress_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        progress_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(3, 3))
        progress_frame.grid_columnconfigure(0, weight=1)

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(progress_frame, height=20)
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.progress_bar.set(0)
        
        # ✅ FIX: Progress label with better positioning
        self.progress_label = ctk.CTkLabel(
            progress_frame,
            text="Ready to export",
            font=ctk.CTkFont(size=11),
            text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
            anchor="w"
        )
        self.progress_label.grid(row=1, column=0, sticky="w", pady=(0, 0))
        
        # ========== BOTTOM ROW: Activity Log - UNCHANGED ==========
        log_frame = ctk.CTkFrame(bottom_frame, height=120)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 5))
        log_frame.grid_propagate(False)
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        # Log header
        log_header_frame = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 3))
        
        log_header_label = ctk.CTkLabel(
            log_header_frame,
            text="📋 Activity Log",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        log_header_label.pack(side="left")
        
        clear_log_btn = ctk.CTkButton(
            log_header_frame,
            text="Clear Log",
            command=self._clear_log,
            width=80,
            height=25,
            font=ctk.CTkFont(size=11)
        )
        clear_log_btn.pack(side="right")
        
        # Log textbox
        self.log_textbox = ctk.CTkTextbox(
            log_frame,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=10),
            fg_color=self.theme_colors["bg_secondary"]  # ✅ Theme-aware
        )
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_textbox.configure(state="disabled")   



    def _on_format_changed(self):
        """
        Handle export format radio button change.
        Updates filename extension.
        
        ✅ UPDATED: Now supports native Excel export from Salesforce API
        """
        selected_format = self.export_format.get()
        
        # Get current filename
        current_filename = self.filename_entry.get().strip()
        
        # Update filename extension
        if selected_format == "csv":
            # Change to .zip (CSV exports are zipped)
            if current_filename.endswith('.xlsx.zip'):
                new_filename = current_filename.replace('.xlsx.zip', '.zip')
            elif current_filename.endswith('.xls.zip'):
                new_filename = current_filename.replace('.xls.zip', '.zip')
            elif not current_filename.endswith('.zip'):
                # Remove any extension and add .zip
                base_name = current_filename.rsplit('.', 1)[0] if '.' in current_filename else current_filename
                new_filename = f"{base_name}.zip"
            else:
                new_filename = current_filename
            
            self._log("📄 Export format: CSV (zipped)")
            
        else:  # xlsx
            # Change to .xlsx.zip (Native Salesforce Excel)
            if current_filename.endswith('.zip') and not current_filename.endswith('.xlsx.zip'):
                new_filename = current_filename.replace('.zip', '.xlsx.zip')
            elif not current_filename.endswith('.xlsx.zip'):
                # Remove any extension and add .xlsx.zip
                base_name = current_filename.rsplit('.', 1)[0] if '.' in current_filename else current_filename
                new_filename = f"{base_name}.xlsx.zip"
            else:
                new_filename = current_filename
            
            self._log("📊 Export format: Native Salesforce Excel (.xlsx, preserves ALL formatting)")
        
        # Update filename entry
        self.filename_entry.delete(0, "end")
        self.filename_entry.insert(0, new_filename)
        
        # Update export button state
        self._update_export_button_state()    

    
    def _generate_default_filename(self):
        """
        Generate default filename with timestamp.
        
        ✅ UPDATED: Now uses .xls.zip for native Excel format
        """
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        
        # Check current format selection (if initialized)
        try:
            selected_format = self.export_format.get()
        except:
            # Not initialized yet, default to CSV
            selected_format = "csv"
        
        if selected_format == "xlsx":
            default_name = f"salesforce_reports_{timestamp}.xlsx.zip"
        else:
            default_name = f"salesforce_reports_{timestamp}.zip"
        
        self.filename_entry.delete(0, "end")
        self.filename_entry.insert(0, default_name)


    def _validate_export_ready(self) -> tuple[bool, str]:
        """
        Validate if export is ready to start.
        
        ✅ NEW: Centralized validation logic
        
        Returns:
            (is_valid, error_message) tuple
        """
        if not self.session_info:
            return (False, "Not logged in. Please login first.")
        
        if not self.output_zip_path:
            return (False, "No save location selected. Click Browse to select a location.")
        
        if not self.selected_items:
            return (False, "No reports selected. Please select at least one report to export.")
        
        filename = self.filename_entry.get().strip()
        if not filename:
            return (False, "Please enter a filename.")
        
        # Validate filename has correct extension
        selected_format = self.export_format.get()

        if selected_format == "xlsx":
            if not filename.endswith('.xlsx.zip'):
                return (False, "Filename must end with .xlsx.zip for Excel format")
        else:
            if not filename.endswith('.zip'):
                return (False, "Filename must end with .zip for CSV format")
        
        return (True, "")

   
    
    # ===== LOGGING =====
    
    def _log(self, message: str):
        """Add message to log"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}\n"
        
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", log_msg)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")
    
    def _clear_log(self):
        """Clear the log"""
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
    

    # ===== LOAD FOLDERS AND REPORTS =====
    
    def _show_welcome_message(self):
        """
        Show welcome message and search instructions on startup.
        No data is loaded until user performs a search.
        """
        if not self.session_info:
            self._log("⚠️ No session info available")
            return
        
        # Extract session info
        instance = self.session_info.get("instance_url", "").replace("https://", "")
        api_version = self.session_info.get("api_version", "")
        user_name = self.session_info.get("user_name", "")
        
        # Log welcome message
        self._log("=" * 50)
        self._log("✅ CONNECTED TO SALESFORCE")
        self._log(f"🌐 Instance: {instance}")
        self._log(f"🔌 API Version: v{api_version}")
        if user_name:
            self._log(f"👤 User: {user_name}")
        self._log("=" * 50)
        self._log("")
        self._log("🔍 Ready to search!")
        self._log("💡 Enter keywords like 'Sales', 'Account', 'Q4 2024', etc.")
        self._log("💡 Press Enter or click Search button to find reports")
        self._log("💡 Use the 🔄 Refresh button to get latest data from Salesforce")
        self._log("")
        
        # Show empty search state in tree
        self._show_empty_search_state()
        
    def _search_worker(self, keyword: str):
        """
        Background worker to search Salesforce by keyword.
        
        ✅ OPTIMIZED: Progress updates + memory-efficient result handling for 10,000+ reports.
        
        Uses the new search_by_keyword() method from exporter which:
        1. Searches folders matching keyword
        2. Searches reports matching keyword
        3. Fetches parent folders of matching reports
        4. Groups reports by folder
        5. Returns organized data ready for tree view
        
        Args:
            keyword: Search term entered by user
        """
        try:
            # ✅ SAFETY: Check if we still have session
            if not self.session_info:
                self.update_queue.put(("log", "❌ No session - please login again"))
                self.update_queue.put(("search_error", "Session expired"))
                return
            
            session_id = self.session_info.get("session_id")
            instance_url = self.session_info.get("instance_url")
            
            if not session_id or not instance_url:
                self.update_queue.put(("log", "❌ Invalid session data"))
                self.update_queue.put(("search_error", "Invalid session"))
                return
            
            # Create exporter instance
            try:
                exporter = SalesforceReportExporter(session_id, instance_url)
            except Exception as e:
                self.update_queue.put(("log", f"❌ Failed to create exporter: {str(e)}"))
                self.update_queue.put(("search_error", f"Connection error: {str(e)}"))
                return
            
            # Log search start
            self.update_queue.put(("log", f"🔍 Searching for: '{keyword}'"))
            self.update_queue.put(("log", "⏳ This may take a moment for large orgs..."))
            
            # ✅ Check cancellation before search
            if self.export_cancel_event.is_set():
                self.update_queue.put(("search_cancelled", None))
                return
            
            # ✅ MAIN SEARCH: This does all the heavy lifting
            try:
                result = exporter.search_by_keyword(
                    keyword=keyword,
                    cancel_event=self.export_cancel_event
                )
            except Exception as e:
                # Catch search-specific errors
                error_msg = str(e)
                
                # Check if it's a cancellation
                if "cancel" in error_msg.lower():
                    self.update_queue.put(("search_cancelled", None))
                    return
                
                # Real error
                self.update_queue.put(("log", f"❌ Search API error: {error_msg}"))
                self.update_queue.put(("search_error", error_msg))
                return
            
            # ✅ Check cancellation after search
            if self.export_cancel_event.is_set():
                self.update_queue.put(("search_cancelled", None))
                return
            
            # ✅ Validate result structure
            if not isinstance(result, dict):
                self.update_queue.put(("log", f"❌ Invalid search result type: {type(result)}"))
                self.update_queue.put(("search_error", "Invalid response from Salesforce"))
                return
            
            # Extract results with defaults
            folders = result.get("folders", [])
            reports_by_folder = result.get("reports_by_folder", {})
            
            # ✅ Validate folders
            if not isinstance(folders, list):
                folders = []
            
            # ✅ Validate reports_by_folder
            if not isinstance(reports_by_folder, dict):
                reports_by_folder = {}
            
            # Calculate statistics
            total_folders = len(folders)
            total_reports = sum(len(reports) for reports in reports_by_folder.values())
            
            # ✅ NEW: Log memory-friendly statistics
            self.update_queue.put(("log", f"✅ Search complete: {total_folders} folders, {total_reports} reports"))
            
            # ✅ NEW: Warn if result set is very large
            if total_reports > 5000:
                self.update_queue.put(("log", f"⚠️ Large result set ({total_reports} reports) - tree view may take a moment to render"))
            
            # ✅ Final cancellation check before sending results
            if self.export_cancel_event.is_set():
                self.update_queue.put(("search_cancelled", None))
                return
            
            # Send organized data to UI
            self.update_queue.put(("search_complete", {
                "folders": folders,
                "reports_by_folder": reports_by_folder,
                "keyword": keyword
            }))
            
        except Exception as e:
            # ✅ Catch ANY unhandled exception
            import traceback
            error_details = traceback.format_exc()
            
            print(f"❌ SEARCH WORKER ERROR:")
            print(error_details)
            
            self.update_queue.put(("log", f"❌ Search error: {str(e)}"))
            self.update_queue.put(("search_error", str(e)))


    def _on_search_complete(self, result: Dict):
        """
        Handle search completion and populate tree with results.
        
        ✅ FIXED: Thread-safe cache access + removed unnecessary after_idle().
        """
        try:
            # ✅ CRITICAL: Reset loading state FIRST
            with self.state_lock:
                self.is_loading = False
                self._set_ui_state("idle")
            
            # Extract data with validation
            if not isinstance(result, dict):
                self._log(f"❌ Invalid result type: {type(result)}")
                self._on_search_error("Invalid search result")
                return
            
            folders = result.get("folders", [])
            reports_by_folder = result.get("reports_by_folder", {})
            keyword = result.get("keyword", "")
            
            # Validate types
            if not isinstance(folders, list):
                folders = []
            if not isinstance(reports_by_folder, dict):
                reports_by_folder = {}
            
            # ✅ FIXED: Thread-safe cache operations
            if keyword:
                keyword_lower = keyword.lower()
                
                # Only cache if result set is reasonable size
                total_reports = sum(len(reports) for reports in reports_by_folder.values())
                
                if total_reports <= 5000:
                    with self.data_lock:  # ✅ FIXED: Thread-safe cache write
                        self.search_cache[keyword_lower] = {
                            "folders": folders,
                            "reports_by_folder": reports_by_folder,
                            "keyword": keyword
                        }
                        
                        # Limit cache size (LRU-style)
                        if len(self.search_cache) > self.search_cache_max_size:
                            oldest_key = next(iter(self.search_cache))
                            del self.search_cache[oldest_key]
                            self._log(f"🗑️ Removed oldest search from cache")
                else:
                    self._log(f"⚠️ Result set too large ({total_reports} reports) - skipping cache")
            
            # Update data storage
            with self.data_lock:
                self.available_folders = folders
                self.reports_by_folder = reports_by_folder
            
            # Calculate statistics
            total_folders = len(folders)
            total_reports = sum(len(reports) for reports in reports_by_folder.values())
            
            # Clear search loading state
            try:
                for widget in self.tree_container.winfo_children():
                    widget.destroy()
            except Exception as e:
                print(f"⚠️ Error clearing tree: {e}")
            
            # Check if we got results
            if total_folders == 0 and total_reports == 0:
                # No results found
                self._show_no_results_state(keyword)
                self._reset_search_ui()
                self._log(f"ℹ️ No results found for '{keyword}'")
                return
            
            # ✅ NEW: Show progress for large result sets
            if total_reports > 1000:
                self._log(f"📊 Rendering {total_folders} folders with {total_reports} reports...")
                self._log(f"⏳ Please wait, this may take a moment...")
            
            # Populate tree with results
            try:
                # ✅ FIXED: Direct call (we're already on main thread)
                self._populate_tree("")
            except Exception as e:
                self._log(f"❌ Error populating tree: {str(e)}")
                import traceback
                traceback.print_exc()
            
            # Re-enable search
            self._reset_search_ui()
            
            # Log summary
            self._log("=" * 50)
            self._log(f"✅ SEARCH COMPLETE")
            self._log(f"🔍 Keyword: '{keyword}'")
            self._log(f"📁 Folders: {total_folders}")
            self._log(f"📄 Reports: {total_reports}")
            
            # ✅ NEW: Show folder breakdown only for reasonable sizes
            if total_folders > 0 and total_folders <= 20:
                for folder in folders[:20]:
                    folder_id = folder.get("id")
                    folder_name = folder.get("name")
                    report_count = len(reports_by_folder.get(folder_id, []))
                    self._log(f"  • {folder_name}: {report_count} reports")
            elif total_folders > 20:
                self._log(f"  • Top folders shown in tree view")
            
            self._log("=" * 50)
            
            # ✅ NEW: Performance tip for large result sets
            if total_reports > 3000:
                self._log(f"💡 Tip: Use virtual scrolling - only visible items are rendered")
            
            # Update export button state
            self._update_export_button_state()
            
            try:
                instance = self.session_info.get("instance_url", "").replace('https://', '')
                api_version = self.session_info.get("api_version", "")
                status_text = f"🟢 {instance}"
                if api_version:
                    status_text += f" (API v{api_version})"
                self.status_label.configure(text=status_text, text_color="green")
            except:
                pass
            
        except Exception as e:
            # ✅ Catch any error in completion handler
            import traceback
            error_details = traceback.format_exc()
            
            print(f"❌ SEARCH COMPLETE HANDLER ERROR:")
            print(error_details)
            
            self._log(f"❌ Error handling search results: {str(e)}")
            self._on_search_error(str(e))

    def _on_search_error(self, error_msg: str):
        """
        Handle search error with user-friendly messages.
        
        ✅ FIXED: Always resets state and UI, even on errors
        
        Args:
            error_msg: Error message from search worker
        """
        # ✅ CRITICAL: Reset loading state FIRST
        with self.state_lock:
            self.is_loading = False
            self._set_ui_state("idle")
        
        # Clear search loading state
        try:
            for widget in self.tree_container.winfo_children():
                widget.destroy()
        except Exception as e:
            print(f"⚠️ Error clearing tree: {e}")
        
        # Show error state in tree
        try:
            error_frame = ctk.CTkFrame(self.tree_container, fg_color="transparent")
            error_frame.grid(row=0, column=0, pady=30)
            
            icon_label = ctk.CTkLabel(
                error_frame,
                text="❌",
                font=ctk.CTkFont(size=48)
            )
            icon_label.pack(pady=(0, 10))
            
            title_label = ctk.CTkLabel(
                error_frame,
                text="Search Failed",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="red"
            )
            title_label.pack(pady=(0, 5))
            
            # Truncate long error messages
            display_error = error_msg[:200] + "..." if len(error_msg) > 200 else error_msg
            
            error_label = ctk.CTkLabel(
                error_frame,
                text=display_error,
                font=ctk.CTkFont(size=11),
                text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
                wraplength=400,
                justify="center"
            )
            error_label.pack(pady=(0, 15))

            # Helpful suggestion
            suggestion = self._get_search_error_suggestion(error_msg)
            if suggestion:
                suggestion_label = ctk.CTkLabel(
                    error_frame,
                    text=f"💡 {suggestion}",
                    font=ctk.CTkFont(size=10),
                    text_color=self.theme_colors["selection_bg"],  # ✅ Theme-aware blue
                    wraplength=400,
                    justify="center"
                )
                suggestion_label.pack()
        except Exception as e:
            print(f"⚠️ Error showing error UI: {e}")
        
        # Re-enable search
        self._reset_search_ui()
        
        # Log error
        self._log(f"❌ Search failed: {error_msg}")
        
        # Show error dialog (non-blocking)
        try:
            self.after(100, lambda: messagebox.showerror(
                "Search Failed",
                f"Failed to search Salesforce:\n\n{error_msg}\n\n{suggestion if suggestion else ''}"
            ))
        except Exception as e:
            print(f"⚠️ Error showing error dialog: {e}")

    def _get_search_error_suggestion(self, error_msg: str) -> str:
        """
        Get helpful suggestion based on search error message.
        
        Args:
            error_msg: Error message from search
            
        Returns:
            Helpful suggestion string
        """
        error_lower = error_msg.lower()
        
        if "session" in error_lower or "authentication" in error_lower or "invalid" in error_lower:
            return "Your session may have expired. Try logging out and back in."
        
        elif "network" in error_lower or "connection" in error_lower or "timeout" in error_lower:
            return "Check your internet connection and try again."
        
        elif "permission" in error_lower or "access" in error_lower:
            return "You may not have permission to search reports. Contact your Salesforce admin."
        
        elif "limit" in error_lower or "exceeded" in error_lower:
            return "Salesforce API limits reached. Try a more specific search keyword or wait a few minutes."
        
        elif "syntax" in error_lower or "query" in error_lower:
            return "Try a simpler search keyword (e.g., 'Sales' instead of special characters)."
        
        else:
            return "Try a different search keyword or check your connection."

    def _show_no_results_state(self, keyword: str):
        """
        Show friendly message when search returns no results.
        
        Args:
            keyword: The search keyword that returned no results
        """
        # Clear tree
        for widget in self.tree_container.winfo_children():
            widget.destroy()
        
        # Create no results frame
        no_results_frame = ctk.CTkFrame(self.tree_container, fg_color="transparent")
        no_results_frame.grid(row=0, column=0, pady=50)
        
        # Icon
        icon_label = ctk.CTkLabel(
            no_results_frame,
            text="🔍",
            font=ctk.CTkFont(size=48)
        )
        icon_label.pack(pady=(0, 10))
        
        # Title
        title_label = ctk.CTkLabel(
            no_results_frame,
            text="No Results Found",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        title_label.pack(pady=(0, 5))
        
        # Message
        message_label = ctk.CTkLabel(
            no_results_frame,
            text=f"No folders or reports match '{keyword}'",
            font=ctk.CTkFont(size=12),
            text_color=self.theme_colors["fg_text_dim"]  # ✅ Theme-aware
        )
        message_label.pack(pady=(0, 15))

        # Suggestions
        suggestions_label = ctk.CTkLabel(
            no_results_frame,
            text="💡 Try:\n• Different keywords (e.g., 'Account', 'Sales', 'Q4')\n• Shorter search terms\n• Check spelling",
            font=ctk.CTkFont(size=11),
            text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
            justify="left"
        )
        suggestions_label.pack()
    
    def _on_search_cancelled(self):
        """
        Handle search cancellation (e.g., user logged out during search).
        
        ✅ FIXED: Proper state cleanup
        """
        # ✅ CRITICAL: Reset loading state
        with self.state_lock:
            self.is_loading = False
            self._set_ui_state("idle")
        
        # Clear search loading state
        try:
            for widget in self.tree_container.winfo_children():
                widget.destroy()
        except Exception as e:
            print(f"⚠️ Error clearing tree: {e}")
        
        # Show cancellation message
        try:
            placeholder = ctk.CTkLabel(
                self.tree_container,
                text="Search cancelled",
                text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
                font=ctk.CTkFont(size=12)
            )
            placeholder.grid(row=0, column=0, pady=30)
        except Exception as e:
            print(f"⚠️ Error showing cancelled UI: {e}")
        
        # Re-enable search UI
        self._reset_search_ui()
        
        self._log("⚠️ Search cancelled")
    
    def _show_empty_search_state(self):
        """
        Show helpful empty state when no search has been performed yet.
        """
        # Clear tree
        for widget in self.tree_container.winfo_children():
            widget.destroy()
        
        # Create empty state message
        empty_frame = ctk.CTkFrame(self.tree_container, fg_color="transparent")
        empty_frame.grid(row=0, column=0, pady=50)
        
        icon_label = ctk.CTkLabel(
            empty_frame,
            text="🔍",
            font=ctk.CTkFont(size=48)
        )
        icon_label.pack(pady=(0, 10))
        
        title_label = ctk.CTkLabel(
            empty_frame,
            text="Search to Get Started",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        title_label.pack(pady=(0, 5))
        
        subtitle_label = ctk.CTkLabel(
            empty_frame,
            text="Enter keywords to search folders and reports\nExample: 'Sales', 'Account', 'Q4 2024'",
            font=ctk.CTkFont(size=11),
            text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
            justify="center"
        )
        subtitle_label.pack()
    
    def _on_search_button_clicked(self):
        """
        Handle search button click with caching.
        ✅ FIXED: Thread-safe cache read
        """
        # Get search keyword
        keyword = self.left_search_entry.get().strip()
        
        # Validate input
        if not keyword:
            self._log("⚠️ Please enter a search keyword")
            messagebox.showwarning("No Keyword", "Please enter a search keyword.")
            return
        
        if len(keyword) < 2:
            self._log("⚠️ Search keyword must be at least 2 characters")
            messagebox.showwarning("Keyword Too Short", "Please enter at least 2 characters.")
            return
        
        # ✅ CRITICAL: Check if already searching
        if self.is_loading:
            self._log("⚠️ Search already in progress, please wait...")
            messagebox.showinfo("Search In Progress", "Please wait for the current search to complete.")
            return
        
        # ✅ CRITICAL: Check if exporting
        if self._is_export_busy():
            self._log("⚠️ Cannot search while export is running")
            messagebox.showinfo("Export In Progress", "Please wait for export to complete before searching.")
            return
        
        # Check if session is valid
        if not self.session_info:
            self._log("⚠️ No active session")
            messagebox.showerror("Not Logged In", "Please login first.")
            return
        
        # ✅ FIXED: Thread-safe cache check
        keyword_lower = keyword.lower()
        cached_result = None
        
        with self.data_lock:  # ✅ Thread-safe read
            if keyword_lower in self.search_cache:
                # ✅ Copy to avoid mutation outside lock
                cached_result = {
                    "folders": self.search_cache[keyword_lower]["folders"].copy(),
                    "reports_by_folder": self.search_cache[keyword_lower]["reports_by_folder"].copy(),
                    "keyword": keyword
                }
        
        if cached_result:
            self._log(f"⚡ Using cached results for: '{keyword}'")
            self._on_search_complete(cached_result)
            return
        
        # Not in cache - perform search
        self._log(f"🔍 Searching for: '{keyword}'")
        self.last_search_keyword = keyword
        self._start_search(keyword)
        
    def _on_refresh_clicked(self):
            """
            Handle refresh button click - re-runs the last search OR searches current entry.
            
            ✅ FIXED: Now checks search entry FIRST before using last_search_keyword
            """
            # ✅ GUARD: Check if busy
            if self.is_loading:
                self._log("⚠️ Search already in progress, please wait...")
                messagebox.showinfo("Search In Progress", "Please wait for the current search to complete.")
                return
            
            if self._is_export_busy():
                self._log("⚠️ Cannot refresh while export is running")
                messagebox.showinfo("Export In Progress", "Please wait for export to complete before refreshing.")
                return
            
            # ✅ CRITICAL FIX: Check what's currently in the search box
            current_entry_text = self.left_search_entry.get().strip()
            
            # Decide which keyword to use:
            # 1. If user typed something new → use that (treat as new search)
            # 2. If search box is empty but we have last_search_keyword → use last (refresh)
            # 3. If both empty → show error
            
            if current_entry_text:
                # User has typed something in search box
                keyword_to_search = current_entry_text
                
                # Check if it's different from last search
                if self.last_search_keyword and keyword_to_search.lower() == self.last_search_keyword.lower():
                    # Same keyword → this is a REFRESH
                    self._log(f"🔄 Refreshing search: '{keyword_to_search}'")
                    self._log("💡 Fetching latest data from Salesforce...")
                    
                    # Clear cache to force fresh data
                    keyword_lower = keyword_to_search.lower()
                    with self.data_lock:
                        if keyword_lower in self.search_cache:
                            del self.search_cache[keyword_lower]
                            self._log(f"🗑️ Cleared cache for '{keyword_to_search}'")
                else:
                    # Different keyword → this is a NEW SEARCH
                    self._log(f"🔍 New search: '{keyword_to_search}'")
            
            elif self.last_search_keyword:
                # Search box is empty, but we have a previous search → use that
                keyword_to_search = self.last_search_keyword
                self._log(f"🔄 Refreshing last search: '{keyword_to_search}'")
                self._log("💡 Fetching latest data from Salesforce...")
                
                # Clear cache to force fresh data
                keyword_lower = keyword_to_search.lower()
                with self.data_lock:
                    if keyword_lower in self.search_cache:
                        del self.search_cache[keyword_lower]
                        self._log(f"🗑️ Cleared cache for '{keyword_to_search}'")
                
                # Update search entry to show what we're searching
                self.left_search_entry.delete(0, "end")
                self.left_search_entry.insert(0, keyword_to_search)
            
            else:
                # No keyword in box and no previous search
                self._log("ℹ️ No search keyword provided")
                messagebox.showinfo(
                    "No Keyword",
                    "Please enter a search keyword first, then click Search or Refresh."
                )
                return
            
            # ✅ NEW: Show visual feedback in status label
            try:
                self.status_label.configure(
                    text=f"🔄 Refreshing: {keyword_to_search}...",
                    text_color="#1f6aa5"
                )
            except:
                pass

            # Start search with the determined keyword
            self._start_search(keyword_to_search)


    def _start_search(self, keyword: str):
        """
        Start search in background thread.
        
        Shows loading state and calls _search_worker() in separate thread
        to prevent UI freezing during Salesforce API calls.
        
        ✅ FIXED: Better state management and error handling
        
        Args:
            keyword: Search term to find folders/reports
        """
        # ✅ CRITICAL: Set loading state atomically
        with self.state_lock:
            if self.is_loading:
                self._log("⚠️ Search already in progress")
                return
            
            if self._is_export_busy():
                self._log("⚠️ Cannot search while exporting")
                return
            
            # Set loading state
            self.is_loading = True
            self._set_ui_state("loading")
        
        # Clear cancel event (fresh start)
        self.export_cancel_event.clear()
        
        # Disable search controls during search
        try:
            self.search_button.configure(state="disabled", text="🔄 Searching...")
            self.left_search_entry.configure(state="disabled")
            
            # ✅ NEW: Also disable refresh button during search
            self.refresh_button.configure(state="disabled")
        except Exception as e:
            print(f"⚠️ Error disabling search UI: {e}")
        
        # Show loading indicator in tree
        try:
            for widget in self.tree_container.winfo_children():
                widget.destroy()
        except Exception as e:
            print(f"⚠️ Error clearing tree: {e}")
        
        try:
            loading_frame = ctk.CTkFrame(self.tree_container, fg_color="transparent")
            loading_frame.grid(row=0, column=0, pady=50)
            
            # Loading spinner icon
            loading_icon = ctk.CTkLabel(
                loading_frame,
                text="🔄",
                font=ctk.CTkFont(size=48)
            )
            loading_icon.pack(pady=(0, 10))
            
            # Loading message
            loading_label = ctk.CTkLabel(
                loading_frame,
                text="Searching Salesforce...",
                text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
                font=ctk.CTkFont(size=14, weight="bold")
            )
            loading_label.pack(pady=(0, 5))

            # Keyword display
            keyword_label = ctk.CTkLabel(
                loading_frame,
                text=f"Looking for: '{keyword}'",
                text_color=self.theme_colors["selection_bg"],  # ✅ Theme-aware blue
                font=ctk.CTkFont(size=12)
            )
            keyword_label.pack()
        except Exception as e:
            print(f"⚠️ Error showing loading UI: {e}")
        
        # ✅ CRITICAL: Force UI update before starting thread
        try:
            self.update_idletasks()
        except:
            pass
        
        # Start search in background thread (prevents UI freeze)
        thread = threading.Thread(
            target=self._search_worker_safe,  # ✅ NEW: Use safe wrapper
            args=(keyword,),
            daemon=True,
            name=f"SearchThread-{keyword}"
        )
        thread.start()
        
        self._log(f"✅ Search thread started for: '{keyword}'")
    
    def _search_worker_safe(self, keyword: str):
        """
        Safe wrapper for _search_worker that catches ALL exceptions.
        
        ✅ NEW: Prevents thread crashes from freezing the UI
        """
        try:
            self._search_worker(keyword)
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            
            # Log full error
            print(f"❌ SEARCH WORKER CRASH:")
            print(error_details)
            
            # Queue error message to UI
            self.update_queue.put(("log", f"❌ Search crashed: {str(e)}"))
            self.update_queue.put(("search_error", f"Search failed: {str(e)}"))
        finally:
            # ✅ CRITICAL: Always reset loading state, even on crash
            with self.state_lock:
                self.is_loading = False
                self._set_ui_state("idle")
            
            # Re-enable search UI
            try:
                self.after(0, self._reset_search_ui)
            except:
                pass
            
    def _reset_search_ui(self):
        """
        Reset search UI to normal state.
        
        ✅ NEW: Centralized UI reset after search completes/fails
        """
        try:
            self.search_button.configure(state="normal", text="🔍 Search")
            self.left_search_entry.configure(state="normal")
            
            # ✅ NEW: Re-enable refresh button (only if user has searched before)
            if self.last_search_keyword:
                self.refresh_button.configure(state="normal")
            else:
                # No previous search yet, keep refresh disabled
                self.refresh_button.configure(state="disabled")
        except Exception as e:
            print(f"⚠️ Error resetting search UI: {e}")

    def _populate_tree_with_data(self, filtered_folders, total_reports_in_folders):
        """
        Populate tree after loading completes.
        ✅ NEW: Helper method to populate virtual tree.
        """
        # Remove temp message
        for widget in self.tree_container.winfo_children():
            widget.destroy()
        
        # Populate tree (virtual scrolling makes this instant!)
        self._populate_tree("")
        
        # Log results with statistics
        self._log("=" * 50)
        self._log(f"✅ DATA LOADING COMPLETE")
        self._log(f"📁 Folders Loaded: {len(filtered_folders)}")
        self._log(f"📄 Total Reports: {total_reports_in_folders}")
        
        if total_reports_in_folders > 0:
            avg_reports_per_folder = total_reports_in_folders / len(filtered_folders) if len(filtered_folders) > 0 else 0
            self._log(f"📊 Average Reports/Folder: {avg_reports_per_folder:.1f}")
        
        if total_reports_in_folders == 0:
            self._log("⚠️ WARNING: No reports found. Check folder permissions.")
        
        self._log("=" * 50)
        
    
    # ===== TREE VIEW POPULATION =====
    
    def _populate_tree(self, search_term: str = ""):
        """
        Populate the tree view with folders and reports.
        
        ✅ OPTIMIZED: Lazy loading + virtual scrolling for 10,000+ reports (no UI freeze!).
        """
        
        # Clear existing tree
        if self.virtual_tree:
            self.virtual_tree.clear()
        
        for widget in self.tree_container.winfo_children():
            widget.destroy()
        
        self.tree_items.clear()
        
        if not self.available_folders:
            placeholder = ctk.CTkLabel(
                self.tree_container,
                text="No folders found",
                text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
                font=ctk.CTkFont(size=12)
            )
            placeholder.grid(row=0, column=0, pady=30)
            return
        
        # ✅ NEW: Show loading message for large datasets
        total_folders = len(self.available_folders)
        total_reports = sum(len(self.reports_by_folder.get(f.get("id"), [])) for f in self.available_folders)
        
        if total_reports > 1000:
            loading_label = ctk.CTkLabel(
                self.tree_container,
                text=f"⏳ Loading {total_folders} folders with {total_reports} reports...",
                text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
                font=ctk.CTkFont(size=12)
            )
            loading_label.grid(row=0, column=0, pady=30)
            self.update_idletasks()  # Force UI update
        
        # Filter folders and reports by search term
        filtered_folders_data = []
        
        with self.data_lock:
            if search_term:
                search_lower = search_term.lower()
                
                for folder in self.available_folders:
                    folder_id = folder.get("id")
                    folder_name = folder.get("name", "")
                    
                    all_reports = self.reports_by_folder.get(folder_id, [])
                    
                    folder_matches = search_lower in folder_name.lower()
                    
                    if folder_matches:
                        filtered_folders_data.append({
                            "folder": folder,
                            "reports": all_reports
                        })
                    else:
                        matching_reports = [
                            r for r in all_reports
                            if search_lower in r.get("name", "").lower()
                        ]
                        
                        if matching_reports:
                            filtered_folders_data.append({
                                "folder": folder,
                                "reports": matching_reports
                            })
            else:
                # ✅ OPTIMIZED: Build filtered data in single pass
                for folder in self.available_folders:
                    folder_id = folder.get("id")
                    filtered_folders_data.append({
                        "folder": folder,
                        "reports": self.reports_by_folder.get(folder_id, [])
                    })
        
        # Remove loading message if shown
        if total_reports > 1000:
            for widget in self.tree_container.winfo_children():
                widget.destroy()
        
        if not filtered_folders_data and search_term:
            placeholder = ctk.CTkLabel(
                self.tree_container,
                text=f"No results found for '{search_term}'",
                text_color=self.theme_colors["fg_text_dim"],  # ✅ Theme-aware
                font=ctk.CTkFont(size=12)
            )
            placeholder.grid(row=0, column=0, pady=30)
            return
        
        # ✅ CRITICAL: Create virtual tree with proper configuration
        if not self.virtual_tree:
            self.virtual_tree = VirtualTreeView(
                parent_frame=self.tree_container,
                item_height=50,
                buffer_items=5,
                theme_colors=self.theme_colors  # ✅ Pass theme colors to virtual tree
            )
            
            # Setup callbacks
            self.virtual_tree.on_folder_checkbox = self._on_folder_checkbox_changed_virtual
            self.virtual_tree.on_report_checkbox = self._on_report_checkbox_changed_virtual
            self.virtual_tree.on_folder_expand = self._on_folder_expand_virtual

        # ✅ NEW: Pass current selection state to virtual tree
        selected_report_ids = set(self.selected_items.keys())
        
        # ✅ OPTIMIZED: Set items with progress logging
        if total_reports > 2000:
            self._log(f"📊 Virtual tree rendering {len(filtered_folders_data)} folders...")
        
        self.virtual_tree.set_items(filtered_folders_data, selected_report_ids)
        
        # Store tree_items for compatibility with existing code
        for idx, folder_data in enumerate(filtered_folders_data):
            folder_id = folder_data["folder"].get("id")
            self.tree_items[folder_id] = {
                "folder": folder_data["folder"],
                "folder_name": folder_data["folder"].get("name", "Unknown"),
                "reports": folder_data["reports"],
                "row_index": idx,
                "report_checkboxes": {}
            }
        
        # ✅ NEW: Log completion for large datasets
        if total_reports > 2000:
            self._log(f"✅ Tree rendering complete - scroll to explore reports")
        
    def _on_folder_checkbox_changed_virtual(self, folder_id: str, checkbox_var: ctk.BooleanVar):
        """
        Handle folder checkbox change from virtual tree.
        ✅ FIXED: Now syncs selection state back to virtual tree.
        """
        if folder_id not in self.tree_items:
            self._log(f"ERROR: Folder {folder_id} not found in tree_items")
            return
        
        is_checked = checkbox_var.get()
        tree_item = self.tree_items[folder_id]
        reports = tree_item.get("reports", [])
        folder_name = tree_item.get("folder_name", "Unknown")
        
        if not reports:
            self._log(f"⚠️ No reports in folder: {folder_name}")
            checkbox_var.set(False)
            return
        
        if is_checked:
            # Select all reports in this folder
            for report in reports:
                report_id = report.get("id")
                report_name = report.get("name", "Unnamed Report")
                
                self.selected_items[report_id] = {
                    "type": "report",
                    "name": report_name,
                    "folder_id": folder_id,
                    "folder_name": folder_name
                }
            
            self._log(f"✅ Selected folder: {folder_name} ({len(reports)} reports)")
        else:
            # Deselect all reports in this folder
            for report in reports:
                report_id = report.get("id")
                
                if report_id in self.selected_items:
                    del self.selected_items[report_id]
            
            self._log(f"❌ Deselected folder: {folder_name}")
        
        # ✅ Update virtual tree selection state
        if self.virtual_tree:
            selected_report_ids = set(self.selected_items.keys())
            self.virtual_tree.update_selection_state(selected_report_ids)
        
        # Update selected panel
        self._refresh_selected_panel()
        
        # Update export button state
        self._update_export_button_state()
    
    

    
    
    def _on_report_checkbox_changed_virtual(self, report_id: str, report_name: str, folder_id: str, checkbox_var: ctk.BooleanVar):
        """
        Handle individual report checkbox change from virtual tree.
        ✅ FIXED: Now syncs selection state back to virtual tree.
        """
        is_checked = checkbox_var.get()
        folder_name = self.tree_items.get(folder_id, {}).get("folder_name", "Unknown")
        
        if is_checked:
            # Add to selection
            self.selected_items[report_id] = {
                "type": "report",
                "name": report_name,
                "folder_id": folder_id,
                "folder_name": folder_name
            }
            self._log(f"✅ Selected: {report_name}")
        else:
            # Remove from selection
            if report_id in self.selected_items:
                del self.selected_items[report_id]
            self._log(f"❌ Deselected: {report_name}")
        
        # ✅ Update virtual tree selection state (updates folder checkbox too)
        if self.virtual_tree:
            selected_report_ids = set(self.selected_items.keys())
            self.virtual_tree.update_selection_state(selected_report_ids)
        
        # Update selected panel
        self._refresh_selected_panel()
        
        # Update export button state
        self._update_export_button_state()


    def _on_report_checkbox_changed(self, report_id: str, report_name: str, folder_id: str, checkbox_var: ctk.BooleanVar):
        """
        Handle individual report checkbox change - LEGACY METHOD.
        
        ✅ FIXED: Always redirects to virtual tree handler (no legacy code).
        This method exists only for backward compatibility.
        """
        # Always use virtual tree handler
        if self.virtual_tree:
            return self._on_report_checkbox_changed_virtual(report_id, report_name, folder_id, checkbox_var)
        
        # Fallback if virtual tree doesn't exist (should never happen)
        self._log("⚠️ Warning: Virtual tree not initialized")


    def _on_folder_expand_virtual(self, folder_id: str):
        """
        Handle folder expand/collapse from virtual tree.
        ✅ Callback for virtual tree view.
        """
        # Virtual tree handles the UI, we just log it
        if folder_id in self.tree_items:
            folder_name = self.tree_items[folder_id].get("folder_name", "Unknown")
            is_expanded = self.virtual_tree and folder_id in self.virtual_tree.expanded_folders
            
            if is_expanded:
                self._log(f"📂 Expanded: {folder_name}")
            else:
                self._log(f"📁 Collapsed: {folder_name}")
        
    
    def _on_folder_checkbox_changed(self, folder_id: str, checkbox_var: ctk.BooleanVar):
        """
        Handle folder checkbox change - LEGACY METHOD.
        
        ✅ FIXED: Always redirects to virtual tree handler (no legacy code).
        This method exists only for backward compatibility.
        """
        # Always use virtual tree handler
        if self.virtual_tree:
            return self._on_folder_checkbox_changed_virtual(folder_id, checkbox_var)
        
        # Fallback if virtual tree doesn't exist (should never happen)
        self._log("⚠️ Warning: Virtual tree not initialized")
    
    def _on_report_checkbox_changed(self, report_id: str, report_name: str, folder_id: str, checkbox_var: ctk.BooleanVar):
        """
        Handle individual report checkbox change - LEGACY METHOD.
        ✅ UPDATED: Redirects to virtual tree handler if using virtual tree.
        """
        # If using virtual tree, redirect to new handler
        if self.virtual_tree:
            return self._on_report_checkbox_changed_virtual(report_id, report_name, folder_id, checkbox_var)
        
        # Old implementation (kept for compatibility)
        is_checked = checkbox_var.get()
        folder_name = self.tree_items.get(folder_id, {}).get("folder_name", "Unknown")
        
        if is_checked:
            self.selected_items[report_id] = {
                "type": "report",
                "name": report_name,
                "folder_id": folder_id,
                "folder_name": folder_name
            }
            self._log(f"✅ Selected: {report_name}")
        else:
            if report_id in self.selected_items:
                del self.selected_items[report_id]
            self._log(f"❌ Deselected: {report_name}")
            
            if folder_id in self.tree_items:
                self.tree_items[folder_id]["checkbox_var"].set(False)
        
        self._refresh_selected_panel()
    
    
    # ===== SELECTED PANEL MANAGEMENT =====
    
    def _refresh_selected_panel(self):
        """Refresh the selected items panel - COMPACT VERSION"""
        
        # Clear existing widgets
        for widget in self.selected_container.winfo_children():
            widget.destroy()
        
        if not self.selected_items:
            # Show placeholder
            self.selected_placeholder = ctk.CTkLabel(
                self.selected_container,
                text="No reports selected.\nSelect from left panel.",
                text_color="gray",
                font=ctk.CTkFont(size=11),
                justify="center"
            )
            self.selected_placeholder.grid(row=0, column=0, pady=20)
            
            # Update count
            self.selection_count_label.configure(text="0 reports selected", text_color="gray")
            
            # Disable buttons
            self.clear_selected_button.configure(state="disabled")
            self._update_export_button_state()
            return
        
        # Group items by folder
        items_by_folder = {}
        for item_id, item_data in self.selected_items.items():
            folder_name = item_data.get("folder_name", "Unknown")
            if folder_name not in items_by_folder:
                items_by_folder[folder_name] = []
            items_by_folder[folder_name].append({
                "id": item_id,
                "name": item_data.get("name", "Unnamed")
            })
        
        # Create items grouped by folder
        row = 0
        for folder_name, items in sorted(items_by_folder.items()):
            # Folder header - ULTRA COMPACT
            folder_header = ctk.CTkFrame(
                self.selected_container, 
                fg_color=self.theme_colors["bg_container"],  # ✅ Theme-aware
                corner_radius=2
            )
            folder_header.grid(row=row, column=0, sticky="ew", padx=3, pady=(0, 0))  # ✅ MINIMAL padding
            folder_header.grid_columnconfigure(0, weight=1)
            
            folder_label = ctk.CTkLabel(
                folder_header,
                text=f"📁 {folder_name} ({len(items)})",
                font=ctk.CTkFont(size=10, weight="bold"),  # ✅ SMALLER font
                anchor="w"
            )
            folder_label.grid(row=0, column=0, sticky="ew", padx=6, pady=2)  # ✅ TIGHT padding
            
            row += 1
            
            # Report items - ULTRA COMPACT
            for item in sorted(items, key=lambda x: x["name"]):
                item_frame = ctk.CTkFrame(
                    self.selected_container, 
                    fg_color=self.theme_colors["bg_primary"],  # ✅ Theme-aware
                    corner_radius=2
                )
                item_frame.grid(row=row, column=0, sticky="ew", padx=(8, 3), pady=0)  # ✅ NO vertical gap!
                item_frame.grid_columnconfigure(0, weight=1)
                
                item_label = ctk.CTkLabel(
                    item_frame,
                    text=f" 📄 {item['name'][:50]}{'...' if len(item['name']) > 50 else ''}",  # ✅ TRUNCATE long names
                    font=ctk.CTkFont(size=9),  # ✅ SMALLER font
                    anchor="w"
                )
                item_label.grid(row=0, column=0, sticky="ew", padx=6, pady=1)  # ✅ MINIMAL padding
                
                # Remove button - TINY
                remove_btn = ctk.CTkButton(
                    item_frame,
                    text="×",  # ✅ Single character
                    width=18,  # ✅ TINY
                    height=16,  # ✅ TINY
                    fg_color="transparent",
                    hover_color=self.theme_colors["error"],  # ✅ Theme-aware hover
                    text_color=self.theme_colors["fg_text"],  # ✅ Theme-aware text (× visible now!)
                    font=ctk.CTkFont(size=12),
                    command=lambda item_id=item['id']: self._remove_item_from_selected(item_id)
                )
                remove_btn.grid(row=0, column=1, padx=2, pady=1)  # ✅ MINIMAL padding
                
                row += 1
        
        # Update count
        count = len(self.selected_items)
        self.selection_count_label.configure(
            text=f"{count} report{'s' if count != 1 else ''} selected",
            text_color=self.theme_colors["selection_bg"]  # ✅ Theme-aware blue
        )
        
        # Enable buttons
        self.clear_selected_button.configure(state="normal")
        self._update_export_button_state()
            
    def _remove_item_from_selected(self, item_id: str):
        """
        Remove a single item from selected panel.
        
        ✅ FIXED: Now properly updates both report AND folder checkboxes in virtual tree.
        """
        if item_id not in self.selected_items:
            return
        
        item_data = self.selected_items[item_id]
        item_name = item_data.get("name", "Unknown")
        folder_id = item_data.get("folder_id")
        
        # Remove from selected items
        del self.selected_items[item_id]
        
        self._log(f"❌ Removed: {item_name}")
        
        # ✅ This now triggers the re-render via update_selection_state()
        if self.virtual_tree:
            selected_report_ids = set(self.selected_items.keys())
            self.virtual_tree.update_selection_state(selected_report_ids)
        
        # Refresh selected panel
        self._refresh_selected_panel()
        
        # Update export button state
        self._update_export_button_state()
    
    # ===== ACTION BUTTONS =====
    
    def _clear_all_selected(self):
        """
        Clear all selected items.
        
        ✅ FIXED: Works with virtual tree view (no direct checkbox access).
        """
        if not self.selected_items:
            return
        
        count = len(self.selected_items)
        
        # Clear selected items dictionary
        self.selected_items.clear()
        
        self._log(f"🗑️ Cleared all selections ({count} reports)")
        
        # ✅ Update virtual tree selection state (this will uncheck all checkboxes)
        if self.virtual_tree:
            self.virtual_tree.update_selection_state(set())  # Empty set = nothing selected
        
        # Refresh selected panel
        self._refresh_selected_panel()
        
        # Update export button state
        self._update_export_button_state()
    
    def _reset_all_selections(self):
        """Reset all selections - same as clear all"""
        if not self.selected_items:
            messagebox.showinfo("No Selection", "No reports are currently selected.")
            return
        
        result = messagebox.askyesno(
            "Reset Selection",
            f"Reset all selections? This will clear {len(self.selected_items)} selected report(s)."
        )
        
        if result:
            self._clear_all_selected()
    
    # ===== BROWSE SAVE LOCATION =====
    
    def _browse_save_location(self):
        """
        Browse for save location.
        
        ✅ UPDATED: Handles both CSV and Excel formats
        """
        
        # Get filename from entry
        filename = self.filename_entry.get().strip()
        if not filename:
            # Generate default based on format
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M')
            selected_format = self.export_format.get()
            
            if selected_format == "xlsx":
                filename = f"salesforce_reports_{timestamp}.xlsx.zip"
            else:
                filename = f"salesforce_reports_{timestamp}.zip"
        
        # Ensure correct extension based on format
        selected_format = self.export_format.get()
        
        if selected_format == "xlsx":
            if not filename.endswith('.xls.zip'):
                # Fix extension
                base_name = filename.replace('.xlsx.zip', '').replace('.xls.zip', '').replace('.zip', '')
                filename = f"{base_name}.xls.zip"
        else:
            if not filename.endswith('.zip') or filename.endswith('.xls.zip') or filename.endswith('.xlsx.zip'):
                # Fix extension
                base_name = filename.replace('.xlsx.zip', '').replace('.xls.zip', '').replace('.zip', '')
                filename = f"{base_name}.zip"
        
        # Open directory dialog
        directory = filedialog.askdirectory(
            title="Select Save Location"
        )
        
        if directory:
            # Build full path
            full_path = os.path.join(directory, filename)
            self.output_zip_path = full_path
            
            # Update location entry
            self.location_entry.configure(state="normal")
            self.location_entry.delete(0, "end")
            self.location_entry.insert(0, directory)
            self.location_entry.configure(state="readonly")
            
            # Update filename entry with corrected name
            self.filename_entry.delete(0, "end")
            self.filename_entry.insert(0, filename)
            
            format_name = "Excel" if selected_format == "xlsx" else "CSV"
            self._log(f"💾 Save location: {directory}")
            self._log(f"📦 Full path: {full_path}")
            self._log(f"📋 Format: {format_name}")
            
            self._update_export_button_state()
    
    def _update_export_button_state(self):
        """
        Enable/disable export button based on conditions.
        
        IMPROVED: Uses atomic state checks and better error handling.
        """
        # ✅ IMPROVED: Atomic state checks
        with self.data_lock:
            has_session = self.session_info is not None
            has_path = self.output_zip_path is not None
            has_selection = len(self.selected_items) > 0
        
        # ✅ IMPROVED: Use atomic state getter
        export_state = self._get_export_state()
        is_busy = self._is_ui_busy() or self._is_export_busy()
        
        # Debug logging
        print(f"🔍 Export Button State Check:")
        print(f"   Session: {has_session}")
        print(f"   Path: {has_path}")
        print(f"   Selection: {has_selection} ({len(self.selected_items)} items)")
        print(f"   Export State: {export_state}")
        print(f"   Busy: {is_busy}")
        
        # Can only export if ALL conditions met AND not busy
        can_export = has_session and has_path and has_selection and not is_busy
        
        print(f"   ✅ Can Export: {can_export}")
        
        # Update button state on main thread
        def update_btn():
            try:
                # ✅ SAFETY: Double-check state hasn't changed
                current_state = self._get_export_state()
                if current_state != "idle":
                    # State changed while scheduling - button should stay disabled
                    self.export_button.configure(state="disabled")
                    print(f"   🔴 Export button DISABLED (state changed to {current_state})")
                    return
                
                if can_export:
                    self.export_button.configure(state="normal")
                    print(f"   🟢 Export button ENABLED")
                else:
                    self.export_button.configure(state="disabled")
                    print(f"   🔴 Export button DISABLED")
            except Exception as e:
                print(f"   ⚠️ Button update error: {e}")
        
        # Execute on main thread
        self._safe_ui_update(update_btn)
        
    # ===== EXPORT OPERATIONS =====
    
    def _cancel_export(self):
        """
        Cancel the ongoing export operation.
        
        IMPROVED: Proper state transition with atomic operations.
        """
        # ✅ IMPROVED: Check actual state
        export_state = self._get_export_state()
        
        if export_state != "running":
            print(f"⚠️ Cannot cancel - export state is '{export_state}'")
            return
        
        # ✅ IMPROVED: Check if already cancelling
        if self.export_cancel_event.is_set():
            print("⚠️ Export already cancelling")
            return
        
        # Show confirmation dialog
        result = messagebox.askyesno(
            "Cancel Export",
            "Cancel the export?\n\n"
            "You can choose to save the reports that have already been exported.",
            icon='warning'
        )
        
        if not result:
            print("ℹ️ Cancel operation aborted by user")
            return
        
        # ✅ CRITICAL: Transition to "cancelling" state atomically
        self._set_export_state("cancelling")
        
        # Set cancel event (background thread will see this)
        self.export_cancel_event.set()
        
        self._log("🛑 Cancelling export...")
        
        # ✅ Update button to show "Cancelling..." state
        self._refresh_button_visibility()
        
        self.progress_label.configure(text="Cancelling export...", text_color="orange")
        
        print("✅ Cancel event set - background thread will stop gracefully")
    
    
    def _start_export(self):
        """
        Start the export process.
        
        ✅ FIXED: Properly manages _showing_dialog flag to prevent button lockup
        
        IMPROVED: Proper state management with atomic transitions.
        """
        # ✅ CRITICAL: Check dialog flag FIRST
        with self.state_lock:
            if self._showing_dialog:
                print("⚠️ Dialog already showing - ignoring export trigger")
                return
            
            if self._is_export_busy():
                print("⚠️ Export already busy")
                return
            
            # ✅ Mark that we're about to show dialog
            self._showing_dialog = True
        
        try:
            # ✅ NEW: Use centralized validation
            is_valid, error_msg = self._validate_export_ready()
            
            if not is_valid:
                with self.state_lock:
                    self._showing_dialog = False
                messagebox.showwarning("Cannot Export", error_msg)
                return
            
            # Get filename from entry
            filename = self.filename_entry.get().strip()
            
            # Get selected format
            selected_format = self.export_format.get()
            
            format_name = "Excel (.xlsx)" if selected_format == "xlsx" else "CSV"
            
            # Validate and fix filename extension if needed
            if selected_format == "xlsx":
                if not filename.endswith('.xls.zip'):
                    base_name = filename.replace('.xlsx.zip', '').replace('.xls.zip', '').replace('.zip', '')
                    filename = f"{base_name}.xls.zip"
            else:
                if not filename.endswith('.zip') or filename.endswith('.xls.zip') or filename.endswith('.xlsx.zip'):
                    base_name = filename.replace('.xlsx.zip', '').replace('.xls.zip', '').replace('.zip', '')
                    filename = f"{base_name}.zip"
            
            # ✅ NEW: Check for filename conflicts and auto-resolve
            directory = os.path.dirname(self.output_zip_path)
            unique_filename = self._get_unique_filename(directory, filename)

            # Update full path with unique filename
            self.output_zip_path = os.path.join(directory, unique_filename)

            # ✅ NEW: If filename was changed due to conflict, update the entry field
            if unique_filename != filename:
                self.filename_entry.delete(0, "end")
                self.filename_entry.insert(0, unique_filename)
                self._log(f"⚠️ File already exists - renamed to: {unique_filename}")
            
            # Confirm export with format information
            count = len(self.selected_items)
            result = messagebox.askyesno(
                "Confirm Export",
                f"Export {count} report(s) in {format_name} format to:\n\n"
                f"{self.output_zip_path}\n\n"
                f"Continue?"
            )
            
            # ✅ NEW: Auto-regenerate filename for next export
            try:
                self._generate_default_filename()
                self._log("🔄 Filename reset for next export")
            except Exception as e:
                print(f"⚠️ Error regenerating filename: {e}")

            # ✅ CRITICAL: Clear dialog flag IMMEDIATELY after user interaction
            with self.state_lock:
                self._showing_dialog = False
            
            if not result:
                print("ℹ️ Export cancelled by user (dialog)")
                return
            
            # ✅ CRITICAL: Transition to "running" state atomically
            self._set_export_state("running")
            
            # Clear cancel event (fresh start)
            self.export_cancel_event.clear()
            
            # Update UI
            self._set_export_ui_state(False)
            
            
            
            
            
            self._log(f"🚀 Starting export of {count} selected reports...")
            self._log(f"📋 Format: {format_name}")
            self._log(f"📦 Destination: {self.output_zip_path}")

            # ✅ Format-specific information
            if selected_format == "xlsx":
                self._log("✅ Excel: Using Salesforce's native exporter (same as UI)")
                self._log("📊 Preserves: Groupings, subtotals, formatting, merged cells")
                self._log("⚡ Fallback: CSV if native Excel fails for any report")
            else:
                self._log("💡 CSV format: Fast export, suitable for large datasets")
                self._log("📄 Note: CSV preserves data but not formatting")
            
            # Get list of report IDs
            report_ids = list(self.selected_items.keys())
            
            # Initialize progress tracker
            self.progress_tracker.start(len(report_ids))
            
            # ✅ Update buttons to show cancel button
            self._refresh_button_visibility()
            
            # Force update
            self.update_idletasks()
            
            # ✅ Start export in BACKGROUND THREAD (UI stays responsive)
            thread = threading.Thread(
                target=self._export_worker_safe,
                args=(report_ids, selected_format),
                daemon=True,
                name=f"ExportThread-{selected_format}"
            )
            thread.start()
            
            print(f"✅ Export thread started (format: {selected_format})")
        
        except Exception as e:
            # ✅ CRITICAL: Always reset dialog flag on ANY error
            with self.state_lock:
                self._showing_dialog = False
            
            print(f"❌ Error in _start_export: {e}")
            import traceback
            traceback.print_exc()
            
            messagebox.showerror("Export Error", f"Failed to start export:\n\n{str(e)}")


    def _start_export_safe(self):
        """
        Safe wrapper for _start_export() to prevent double-triggering.
        Called by keyboard shortcuts and button clicks.
        
        IMPROVED: Uses atomic state checks.
        """
        # ✅ IMPROVED: Check if already busy or showing dialog
        if self._is_export_busy():
            print("⚠️ Export already running, ignoring duplicate trigger")
            return
        
        if self._is_ui_busy():
            print("⚠️ UI is busy, ignoring export trigger")
            return
        
        with self.state_lock:
            if self._showing_dialog:
                print("⚠️ Dialog already open, ignoring export trigger")
                return
        
        # All checks passed - proceed with export
        self._start_export()

    # main_app.py - REPLACE _export_worker_safe method
    
    def _export_worker_safe(self, report_ids: List[str], export_format: str = "csv"):
        """
        Safe wrapper for _export_worker that prevents crashes.
        
        ✅ FIXED: Does NOT reset state (let _on_export_complete do it)
        """
        try:
            self._export_worker(report_ids, export_format)
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            
            # Log full error
            print(f"❌ EXPORT WORKER CRASH:")
            print(error_details)
            
            # Queue error message to UI
            self.update_queue.put(("log", f"❌ Export crashed: {str(e)}"))
            self.update_queue.put(("export_error", f"Export failed: {str(e)}"))
            
            # ✅ IMPORTANT: Reset state only on ERROR, not on success
            with self.state_lock:
                if self._export_state == "running":
                    self._set_export_state("idle")
        

         
    def _export_worker(self, report_ids: List[str], export_format: str = "csv"):
        """
        Background worker for export with concurrent downloads.
        
        ✅ FIXED: Ensures ALL selected reports have metadata with proper names
        
        Args:
            report_ids: List of report IDs to export
            export_format: Either "csv" or "xlsx"
        """
        try:
            session_id = self.session_info.get("session_id")
            instance_url = self.session_info.get("instance_url")
            
            # ✅ BUILD METADATA DICT - IMPROVED VERSION
            reports_metadata = {}
            
            # Track which reports we couldn't find
            missing_reports = []

            with self.data_lock:
                # Extract metadata from reports_by_folder
                for folder_id, reports in self.reports_by_folder.items():
                    for report in reports:
                        report_id = report.get("id")
                        if report_id in report_ids:
                            # Get name from the report data
                            report_name = report.get("name")
                            
                            # ✅ CRITICAL FIX: Verify name is valid
                            if not report_name or report_name == report_id or len(report_name.strip()) == 0:
                                # Name is missing or is the ID - use DeveloperName as fallback
                                report_name = report.get("developerName")
                                
                                # If still bad, create readable name from ID
                                if not report_name or report_name == report_id:
                                    report_name = f"Report_{report_id[-8:]}"
                                    self.update_queue.put(("log", f"⚠️  Report {report_id[-8:]} missing name, using fallback"))
                            
                            reports_metadata[report_id] = {
                                "id": report_id,
                                "name": report_name,
                                "reportFormat": report.get("reportFormat", "TABULAR")
                            }
                
                # ✅ CRITICAL CHECK: Find reports that weren't in reports_by_folder
                for report_id in report_ids:
                    if report_id not in reports_metadata:
                        missing_reports.append(report_id)
                        
                        # Try to get name from selected_items
                        if report_id in self.selected_items:
                            fallback_name = self.selected_items[report_id].get("name", f"Report_{report_id[-8:]}")
                            
                            reports_metadata[report_id] = {
                                "id": report_id,
                                "name": fallback_name,
                                "reportFormat": "TABULAR"
                            }
                            
                            self.update_queue.put(("log", f"⚠️  Using name from selection: {fallback_name}"))
                        else:
                            # Last resort: use ID with readable suffix
                            reports_metadata[report_id] = {
                                "id": report_id,
                                "name": f"Report_{report_id[-8:]}",
                                "reportFormat": "TABULAR"
                            }
                            
                            self.update_queue.put(("log", f"❌ Report {report_id[-8:]} not found in search results"))
            
            # ✅ Log summary
            if missing_reports:
                self.update_queue.put(("log", f"⚠️  {len(missing_reports)} reports not found in reports_by_folder"))
                self.update_queue.put(("log", f"💡 Using fallback names from selected_items"))
            
            # ✅ DIAGNOSTIC: Print final metadata
            print(f"\n{'='*60}")
            print(f"📦 FINAL METADATA FOR EXPORT:")
            print(f"{'='*60}")
            for report_id, metadata in reports_metadata.items():
                print(f"   ID: {report_id}")
                print(f"   Name: {metadata['name']}")
                print(f"   Name == ID?: {metadata['name'] == report_id}")
            print(f"{'='*60}\n")
            
            # ✅ Define progress callback
            def progress_callback(done, total, report_name=None):
                """Progress callback - called when report starts/completes"""
                if report_name:
                    self.update_queue.put(("progress_with_name", (done, total, report_name)))
                    format_icon = "📊" if export_format == "xlsx" else "📄"
                    self.update_queue.put(("log", f"  {format_icon} Downloading: {report_name}"))
                    return
                
                self.update_queue.put(("progress", (done, total)))
                
                if done > 0 and done <= total:
                    percentage = int((done / total) * 100)
                    speed = self.progress_tracker.get_speed()
                    
                    if speed > 0.5:
                        self.update_queue.put(("log", f"  ✅ Completed: {done}/{total} ({percentage}%) • {speed:.1f} reports/sec"))
                    else:
                        self.update_queue.put(("log", f"  ✅ Completed: {done}/{total} ({percentage}%)"))
            
            # ✅ Create exporter instance
            exporter = SalesforceReportExporter(
                session_id,
                instance_url,
                progress_callback=progress_callback
            )
            
            # Log export start
            format_name = "Excel (.xlsx)" if export_format == "xlsx" else "CSV"
            self.update_queue.put(("log", f"🚀 Starting concurrent export of {len(report_ids)} reports in {format_name} format..."))
            
            # Check cancellation before export
            if self.export_cancel_event.is_set():
                self.update_queue.put(("export_cancelled", None))
                return
            
            # ✅ Call different export method based on format
            if export_format == "xlsx":
                # Excel export
                result = exporter.export_selected_reports_to_zip_concurrent_excel(
                    self.output_zip_path,
                    report_ids,
                    max_workers=10,
                    cancel_event=self.export_cancel_event,
                    retry_attempts=3,
                    reports_metadata=reports_metadata
                )
            else:
                # CSV export
                result = exporter.export_selected_reports_to_zip_concurrent(
                    self.output_zip_path,
                    report_ids,
                    max_workers=10,
                    cancel_event=self.export_cancel_event,
                    retry_attempts=3,
                    reports_metadata=reports_metadata
                )
            
            self.update_queue.put(("export_complete", result))
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self.update_queue.put(("log", f"❌ Export error:\n{error_details}"))
            self.update_queue.put(("export_error", str(e)))

    
    
    
    def _on_export_progress(self, progress_data):
        """Handle export progress update - updates after EACH report"""
        done, total = progress_data
        
        # Always update tracker (for speed calculations)
        self.progress_tracker.update(done)
        
        # Update UI for EVERY report
        if total > 0:
            progress = done / total
            self.progress_bar.set(progress)
            
            # Get enhanced progress text with ETA and speed
            progress_text = self.progress_tracker.get_progress_text()
            self.progress_label.configure(
                text=progress_text,
                text_color=self.theme_colors["selection_bg"]  # ✅ Theme-aware blue
            )
    
    
    def _on_export_progress_with_name(self, progress_data):
        """
        Handle progress update with report name (download starting).
        Shows which report is currently being downloaded.
        """
        done, total, report_name = progress_data
        
        # ✅ Show current report in progress label
        if total > 0:
            progress = done / total
            percentage = int(progress * 100)
            
            # Truncate long report names
            display_name = report_name[:40] + "..." if len(report_name) > 40 else report_name
            
            # Update progress label with current report
            self.progress_label.configure(
                text=f"📥 Downloading: {display_name} ({done}/{total} - {percentage}%)",
                text_color=self.theme_colors["selection_bg"]  # ✅ Theme-aware blue
            )
    
    # main_app.py - REPLACE _on_export_complete method

 
    def _on_export_complete(self, result: Dict):
        """
        Handle export completion (including cancellation).
        
        ✅ FIXED: Dialog flag is managed ONLY during dialog display, not blocking future exports
        """
        print("\n" + "=" * 70)
        print("📥 _ON_EXPORT_COMPLETE CALLED!")
        print("=" * 70)
        print(f"📦 Result received: {result}")
        print(f"📦 Type: {type(result)}")
        
        # Check state
        with self.state_lock:
            current_state = self._export_state
            
            print(f"🔒 State check:")
            print(f"   _export_state: {current_state}")
            print(f"   is_exporting: {self.is_exporting}")
            
            # ✅ CRITICAL: Reset state NOW (before dialogs)
            self._export_state = "idle"
            self.is_exporting = False
        
        print("=" * 70 + "\n")
        print("✅ State reset to IDLE, proceeding with completion...")
        
        # Extract result data
        total = result.get("total", 0)
        failed = result.get("failed", [])
        successful = result.get("successful", [])
        zip_path = result.get("zip", "")
        was_cancelled = result.get("cancelled", False)
        completed = result.get("completed", len(successful))
        
        print(f"📊 Export summary: {completed}/{total} reports, cancelled={was_cancelled}")

        
        # Update progress tracker
        elapsed = self.progress_tracker.get_elapsed_seconds()
        elapsed_formatted = self.progress_tracker.format_time(elapsed)
        avg_speed = completed / elapsed if elapsed > 0 else 0
        
        if was_cancelled:
            progress_value = completed / total if total > 0 else 0
            self.progress_bar.set(progress_value)
            
            self.progress_label.configure(
                text=f"⚠️ Export cancelled - saved {completed}/{total} reports ({elapsed_formatted})",
                text_color=self.theme_colors["warning"]
            )
        else:
            self.progress_bar.set(1.0)
            
            self.progress_label.configure(
                text=f"✅ Export Complete: {completed}/{total} reports in {elapsed_formatted} ({avg_speed:.1f} reports/sec)",
                text_color=self.theme_colors["success"]
            )
        
        # Log summary with statistics
        self._log("=" * 50)
        
        if was_cancelled:
            self._log(f"⚠️ EXPORT CANCELLED BY USER")
            self._log(f"📊 Completed: {completed}/{total} reports")
        else:
            self._log(f"✅ EXPORT COMPLETED SUCCESSFULLY")
            self._log(f"📊 Total: {total} reports")
        
        self._log(f"⏱️ Duration: {elapsed_formatted}")
        if avg_speed > 0:
            self._log(f"⚡ Average Speed: {avg_speed:.2f} reports/sec")
        
        self._log(f"✔️ Successful: {len(successful)}")
        self._log(f"❌ Failed: {len(failed)}")
        
        if len(failed) > 0:
            success_rate = (len(successful) / total * 100) if total > 0 else 0
            self._log(f"📈 Success Rate: {success_rate:.1f}%")
        
        self._log(f"💾 Saved to: {zip_path}")
        self._log("=" * 50)
        
        if failed:
            self._log("⚠️ Failed reports:")
            for f in failed[:5]:
                error_msg = f.get('error', 'Unknown error')
                self._log(f"  • {f.get('name')}: {error_msg[:50]}")
            if len(failed) > 5:
                self._log(f"  ... and {len(failed) - 5} more (see summary file)")
        
        # ✅ Update UI state
        self._set_export_ui_state(True)
        
        # ✅ Refresh button visibility
        self._refresh_button_visibility()
        
        # Force UI update BEFORE dialogs
        self.update_idletasks()
        
        print("🎬 About to show completion dialogs...")
        
        # ✅ Show dialogs on main thread with slight delay (ensure UI is stable)
        self.after(100, lambda: self._show_completion_dialogs(
            was_cancelled, completed, total, successful, failed, 
            elapsed_formatted, avg_speed, zip_path, result  # ✅ ADD result parameter
        ))
    
 
    # main_app.py - ADD this new method
    def _show_completion_dialogs(self, was_cancelled, completed, total, successful, 
                                failed, elapsed_formatted, avg_speed, zip_path, result):
        """
        Show completion dialogs (separated from state management).
        
        """
        print("📢 Showing completion dialogs...")
        
        # ✅ CRITICAL: Set dialog flag ONLY while showing dialogs
        with self.state_lock:
            if self._showing_dialog:
                print("⚠️ Dialogs already showing, aborting")
                return
            self._showing_dialog = True
        
        try:
            # Ensure window has focus
            self.lift()
            self.focus_force()
            self.attributes('-topmost', True)
            self.update_idletasks()
            self.attributes('-topmost', False)
            
            print("✅ Window focused, showing messagebox...")
            
            if was_cancelled:
                # Cancellation dialog
                success_rate = (len(successful) / total * 100) if total > 0 else 0
                
                # ✅ NEW: Show export method breakdown if available
                csv_count = 0
                excel_count = 0
                if isinstance(result, dict) and "method_used" in result:
                    csv_count = result["method_used"].get("csv", 0)
                    excel_count = result["method_used"].get("excel_fallback", 0)
                
                message = f"Export was cancelled.\n\n"
                message += f"📊 Statistics:\n"
                message += f"  • Completed: {completed}/{total} reports\n"
                message += f"  • Successful: {len(successful)}\n"
                message += f"  • Failed: {len(failed)}\n"
                message += f"  • Success Rate: {success_rate:.1f}%\n"

                # ✅ NEW: Show method breakdown if available
                if csv_count > 0 or excel_count > 0:
                    message += f"\n📈 Export Methods:\n"
                    message += f"  • CSV Exports: {csv_count}\n"
                    message += f"  • Excel Fallbacks: {excel_count}\n"
                
                message += f"  • Duration: {elapsed_formatted}\n"
                if avg_speed > 0:
                    message += f"  • Average Speed: {avg_speed:.1f} reports/sec\n"
                
                message += f"\n💾 Partial export saved to:\n{zip_path}\n\n"
                message += f"Do you want to keep this partial export?"
                
                print("📋 Showing cancellation dialog...")
                keep_result = messagebox.askyesnocancel(
                    "Export Cancelled",
                    message,
                    icon='warning',
                    parent=self
                )
                
                print(f"   User choice: {keep_result}")
                
                if keep_result is False:  # Delete
                    try:
                        import os
                        os.remove(zip_path)
                        self._log(f"🗑️ Partial export deleted")
                        messagebox.showinfo("Deleted", "Partial export has been deleted.", parent=self)
                    except Exception as e:
                        self._log(f"❌ Failed to delete: {str(e)}")
                        messagebox.showerror("Error", f"Could not delete file:\n{str(e)}", parent=self)
                
                elif keep_result is True:  # Keep and ask about opening folder
                    self._ask_open_folder(zip_path)
            
            else:
                # Success dialog
                success_rate = (len(successful) / total * 100) if total > 0 else 0
                
                # ✅ NEW: Show export method breakdown
                csv_count = 0
                excel_count = 0
                if isinstance(result, dict) and "method_used" in result:
                    csv_count = result["method_used"].get("csv", 0)
                    excel_count = result["method_used"].get("excel_fallback", 0)
                
                message = f"Export completed successfully!\n\n"
                message += f"📊 Statistics:\n"
                message += f"  • Total Reports: {total}\n"
                message += f"  • Successful: {len(successful)}\n"
                message += f"  • Failed: {len(failed)}\n"
                message += f"  • Success Rate: {success_rate:.1f}%\n"
                
                # ✅ NEW: Show method breakdown if available
                if csv_count > 0 or excel_count > 0:
                    message += f"\n📈 Export Methods:\n"
                    message += f"  • CSV Exports: {csv_count}\n"
                    message += f"  • Excel Fallbacks: {excel_count}\n"
                    if excel_count > 0:
                        message += f"    (for Joined/Matrix reports)\n"
                
                message += f"  • Duration: {elapsed_formatted}\n"
                if avg_speed > 0:
                    message += f"  • Average Speed: {avg_speed:.1f} reports/sec\n"
                
                message += f"\n💾 ZIP saved to:\n{zip_path}"
                
                print("📋 Showing success dialog...")
                messagebox.showinfo("Export Complete", message, parent=self)
                print("✅ Success dialog closed")
                
                # Ask about opening folder
                print("📂 Asking about opening folder...")
                self._ask_open_folder(zip_path)
            
            print("✅ All completion dialogs finished")
            
        except Exception as e:
            print(f"❌ Error showing dialogs: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # ✅ CRITICAL: ALWAYS reset dialog flag when done
            with self.state_lock:
                self._showing_dialog = False
            
            print("✅ Dialog flag cleared - ready for next export")        

    # main_app.py - ADD this new method before _handle_cancelled_export

    def _ensure_window_focus(self):
        """
        Ensure this window has focus before showing dialogs.
        Prevents dialogs from appearing behind other windows.
        """
        try:
            # Bring window to front
            self.lift()
            self.attributes('-topmost', True)
            self.update_idletasks()
            self.attributes('-topmost', False)
            self.focus_force()
        except Exception as e:
            print(f"⚠️ Could not ensure window focus: {e}")


    
    # main_app.py - REPLACE _handle_cancelled_export method

    def _handle_cancelled_export(self, completed, total, successful, failed, elapsed_formatted, avg_speed, zip_path):
        """
        Handle UI flow when export was cancelled.
        
        IMPROVED: Ensures dialogs appear on top.
        """
        # Build cancellation message
        message = f"Export was cancelled.\n\n"
        message += f"📊 Statistics:\n"
        message += f"  • Completed: {completed}/{total} reports\n"
        message += f"  • Successful: {len(successful)}\n"
        message += f"  • Failed: {len(failed)}\n"
        message += f"  • Duration: {elapsed_formatted}\n"
        if avg_speed > 0:
            message += f"  • Average Speed: {avg_speed:.1f} reports/sec\n"
        message += f"\nPartial export saved to:\n{zip_path}\n\n"
        message += f"Do you want to keep this partial export?"
        
        # ✅ Ensure window focus before dialog
        self._ensure_window_focus()
        
        # Ask user about partial export
        keep_result = messagebox.askyesnocancel(
            "Export Cancelled",
            message,
            icon='warning',
            parent=self
        )
        
        if keep_result is False:  # User chose "No" - delete
            try:
                import os
                os.remove(zip_path)
                self._log(f"🗑️ Partial export deleted")
                messagebox.showinfo("Deleted", "Partial export has been deleted.", parent=self)
            except Exception as e:
                self._log(f"❌ Failed to delete: {str(e)}")
                messagebox.showerror("Error", f"Could not delete file:\n{str(e)}", parent=self)
        
        elif keep_result is True:  # User chose "Yes" - keep and ask about opening folder
            self._ask_open_folder(zip_path)
        
        print("✅ Cancelled export handler finished")
    
    # main_app.py - REPLACE _handle_successful_export method

    def _handle_successful_export(self, total, successful, failed, elapsed_formatted, avg_speed, zip_path):
        """
        Handle UI flow when export completed successfully.
        
        IMPROVED: Ensures dialogs appear on top.
        """
        success_rate = (len(successful) / total * 100) if total > 0 else 0
        
        # Build success message
        message = f"Export completed successfully!\n\n"
        message += f"📊 Statistics:\n"
        message += f"  • Total Reports: {total}\n"
        message += f"  • Successful: {len(successful)}\n"
        message += f"  • Failed: {len(failed)}\n"
        message += f"  • Success Rate: {success_rate:.1f}%\n"
        message += f"  • Duration: {elapsed_formatted}\n"
        if avg_speed > 0:
            message += f"  • Average Speed: {avg_speed:.1f} reports/sec\n"
        message += f"\n💾 ZIP saved to:\n{zip_path}"
        
        # ✅ Ensure window focus before dialog
        self._ensure_window_focus()
        
        # Show success dialog
        messagebox.showinfo("Export Complete", message, parent=self)
        
        # Ask about opening folder
        self._ask_open_folder(zip_path)
        
        print("✅ Successful export handler finished")

    
    # main_app.py - REPLACE _ask_open_folder method

    def _ask_open_folder(self, zip_path):
        """
        Ask user if they want to open the folder containing the export.
        
        IMPROVED: Better error handling and focus management.
        """
        import subprocess
        import platform
        import os
        
        print(f"📂 Asking to open folder: {zip_path}")
        
        try:
            # Ensure focus
            self.lift()
            self.focus_force()
            
            result = messagebox.askyesno(
                "Open Folder?", 
                "Would you like to open the folder containing the exported file?",
                parent=self
            )
            
            print(f"   User choice: {result}")
            
            if result:
                folder = os.path.dirname(zip_path)
                
                try:
                    if platform.system() == "Windows":
                        os.startfile(folder)
                    elif platform.system() == "Darwin":  # macOS
                        subprocess.Popen(["open", folder])
                    else:  # Linux
                        subprocess.Popen(["xdg-open", folder])
                    
                    self._log(f"📂 Opened folder: {folder}")
                    print(f"✅ Folder opened: {folder}")
                    
                except Exception as e:
                    self._log(f"❌ Could not open folder: {str(e)}")
                    messagebox.showerror("Error", f"Could not open folder:\n{str(e)}", parent=self)
            
        except Exception as e:
            print(f"❌ Error in _ask_open_folder: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_export_error(self, error_msg: str):
        """
        Handle export error with proper state cleanup.
        
        ✅ UPDATED: Better handling for Excel dependency errors
        
        IMPROVED: Ensures state is reset even on errors.
        """
        print(f"❌ Export error handler called: {error_msg}")
        
        # ✅ CRITICAL: Reset state immediately
        self._reset_export_state()
        
        # Update UI
        self._set_export_ui_state(True)
        self._refresh_button_visibility()
        self.update_idletasks()
        
        self.progress_bar.set(0)
        
        # Get elapsed time
        elapsed = self.progress_tracker.get_elapsed_seconds()
        elapsed_formatted = self.progress_tracker.format_time(elapsed) if elapsed > 0 else "0s"
        
        self.progress_label.configure(
            text=f"❌ Export failed after {elapsed_formatted}",
            text_color=self.theme_colors["error"]  # ✅ Theme-aware red
        )
        
        self._log("=" * 50)
        self._log(f"❌ EXPORT FAILED")
        self._log(f"⏱️  Failed after: {elapsed_formatted}")
        self._log(f"📊 Error: {error_msg}")
        self._log("=" * 50)
        
        # ✅ NEW: Check if it's an Excel dependency error
        # Get helpful error message
        helpful_msg = self._get_helpful_error_message(error_msg)
        
        # ✅ GUARD: Check if already showing dialog
        with self.state_lock:
            if self._showing_dialog:
                print("⚠️ Error dialog already showing")
                return
            self._showing_dialog = True
        
        try:
            messagebox.showerror(
                "Export Failed",
                f"Export failed:\n\n{error_msg}\n\n{helpful_msg}"
            )
        finally:
            # ✅ CRITICAL: Clear dialog flag
            with self.state_lock:
                self._showing_dialog = False
        
        print("✅ Error handler finished")
        
        
    def _get_unique_filename(self, directory: str, base_filename: str) -> str:
        """
        Generate a unique filename by appending counter if file exists.
        
        Examples:
            salesforce_reports_20251201.zip
            salesforce_reports_20251201_1.zip
            salesforce_reports_20251201_2.zip
        
        """
        import os
        
        # Build full path
        full_path = os.path.join(directory, base_filename)
        
        # If file doesn't exist, use base filename as-is
        if not os.path.exists(full_path):
            return base_filename
        
        # Extract name and extension
        if '.' in base_filename:
            name_part, ext_part = base_filename.rsplit('.', 1)
            # Handle .xls.zip or .xlsx.zip case
            if ext_part == 'zip' and name_part.endswith('.xls'):
                name_part = name_part[:-4]  # Remove .xls
                ext_part = 'xls.zip'
            elif ext_part == 'zip' and name_part.endswith('.xlsx'):
                name_part = name_part[:-5]  # Remove .xlsx
                ext_part = 'xls.zip'  # Standardize to .xls.zip
        else:
            name_part = base_filename
            ext_part = ''
        
        # Try appending _1, _2, _3... until we find an available name
        counter = 1
        max_attempts = 1000  # Safety limit
        
        while counter < max_attempts:
            # Generate new filename with counter
            if ext_part:
                new_filename = f"{name_part}_{counter}.{ext_part}"
            else:
                new_filename = f"{name_part}_{counter}"
            
            new_full_path = os.path.join(directory, new_filename)
            
            # Check if this filename is available
            if not os.path.exists(new_full_path):
                return new_filename
            
            counter += 1
        
        # Fallback: append timestamp if somehow we hit the limit
        import time
        timestamp = int(time.time())
        if ext_part:
            return f"{name_part}_{timestamp}.{ext_part}"
        else:
            return f"{name_part}_{timestamp}"     


    
    def _get_helpful_error_message(self, error_msg: str) -> str:
        """Get helpful suggestion based on error message"""
        error_lower = error_msg.lower()
        
        if "session" in error_lower or "authentication" in error_lower:
            return "💡 Suggestion: Your session may have expired. Try logging out and back in."
        
        elif "network" in error_lower or "connection" in error_lower or "timeout" in error_lower:
            return "💡 Suggestion: Check your internet connection and try again."
        
        elif "permission" in error_lower or "access" in error_lower:
            return "💡 Suggestion: You may not have permission to access these reports. Check with your Salesforce admin."
        
        elif "limit" in error_lower or "exceeded" in error_lower:
            return "💡 Suggestion: Salesforce API limits may have been reached. Try exporting fewer reports at once or wait a few minutes."
        
        elif "cancelled" in error_lower:
            return "ℹ️ Export was cancelled by user."
        
        else:
            return "💡 Suggestion: Try exporting fewer reports at once, or check the activity log for more details."
    
    def _set_export_ui_state(self, enabled: bool):
        """
        Enable/disable UI during export.
        
        ✅ FIXED: Removed logout_button (doesn't exist in this window)
        
        IMPROVED: Uses atomic state management and better button handling.
        """
        state = "normal" if enabled else "disabled"
        
        try:
            # ✅ REMOVED: self.logout_button.configure(state=state)
            # This button doesn't exist in SalesforceExporterApp
            
            # Back button (this exists)
            if hasattr(self, 'back_button'):
                self.back_button.configure(state=state)
            
            # Browse button
            if hasattr(self, 'browse_button'):
                self.browse_button.configure(state=state)
            
            # Filename entry
            if hasattr(self, 'filename_entry'):
                self.filename_entry.configure(state=state)
            
            # Refresh button logic
            if hasattr(self, 'refresh_button'):
                if enabled:
                    # Re-enable only if user has searched before
                    if self.last_search_keyword:
                        self.refresh_button.configure(state="normal")
                    else:
                        self.refresh_button.configure(state="disabled")
                else:
                    # Export starting, disable refresh
                    self.refresh_button.configure(state="disabled")
            
            # Search UI
            if hasattr(self, 'search_button'):
                self.search_button.configure(state=state)
            
            if hasattr(self, 'left_search_entry'):
                self.left_search_entry.configure(state=state)
            
            if enabled:
                # ✅ Export finished - restore normal UI
                if hasattr(self, 'filename_entry'):
                    self.filename_entry.configure(state="normal")
                
                # ✅ CRITICAL: Use centralized button refresh
                self._refresh_button_visibility()
                
            else:
                # ✅ Export starting - disable everything
                if hasattr(self, 'filename_entry'):
                    self.filename_entry.configure(state="disabled")
                
                # Buttons handled by _refresh_button_visibility()
            
            # Force UI update
            self.update_idletasks()
            
        except Exception as e:
            print(f"⚠️ UI state update error: {e}")
            import traceback
            traceback.print_exc()
    
    # ===== QUEUE PROCESSING =====
    def destroy(self):
        """
        Clean up resources before window destruction.
        ✅ IMPROVED: Comprehensive cleanup
        """
        # ✅ Set destruction flag to prevent new operations
        self._is_being_destroyed = True
        
        # ✅ Cancel any ongoing operations
        try:
            self.export_cancel_event.set()
        except:
            pass
        
        # ✅ Clean up virtual tree
        try:
            if self.virtual_tree:
                self.virtual_tree.clear()
                self.virtual_tree = None
        except:
            pass
        
        # ✅ Clean up tree items
        try:
            self.tree_items.clear()
        except:
            pass
        
        # ✅ Cancel any pending timers
        try:
            if self._configure_timer:
                self.after_cancel(self._configure_timer)
        except:
            pass
        
        try:
            if self.search_timer:
                self.after_cancel(self.search_timer)
        except:
            pass
        
        # ✅ Clear search cache
        try:
            self.search_cache.clear()
        except:
            pass
        
        # ✅ Clear selection
        try:
            self.selected_items.clear()
        except:
            pass
        
        # ✅ Clear queue
        try:
            while not self.update_queue.empty():
                self.update_queue.get_nowait()
        except:
            pass
        
        # Call parent destroy
        try:
            super().destroy()
        except:
            pass

    def _is_window_alive(self) -> bool:
        """
        Check if window still exists and is usable.
        
        ✅ NEW: Prevents operations on destroyed windows
        
        Returns:
            True if window is alive, False otherwise
        """
        if self._is_being_destroyed:
            return False
        
        try:
            # Try to access a basic window property
            _ = self.winfo_exists()
            return True
        except:
            return False        
    
    def _recover_from_search_error(self):
        """
        Recover UI state after a search error.
        
        ✅ NEW: Ensures UI is always usable even after errors
        """
        # Reset all search-related state
        with self.state_lock:
            self.is_loading = False
            self._set_ui_state("idle")
        
        # Clear cancel event
        self.export_cancel_event.clear()
        
        # Reset search UI
        self._reset_search_ui()
        
        # Show empty search state
        try:
            self._show_empty_search_state()
        except:
            pass
        
        self._log("🔄 Search state recovered - ready for new search")

    def _debug_print_state(self):
        """
        Print current state for debugging.
        
        ✅ NEW: Helpful for troubleshooting
        """
        print("\n" + "="*60)
        print("DEBUG: Current Application State")
        print("="*60)
        
        try:
            with self.state_lock:
                print(f"  is_loading: {self.is_loading}")
                print(f"  is_exporting: {self.is_exporting}")
                print(f"  _export_state: {self._export_state}")
                print(f"  _showing_dialog: {self._showing_dialog}")
        except Exception as e:
            print(f"  Error reading state: {e}")
        
        try:
            with self.ui_lock:
                print(f"  ui_state: {self.ui_state}")
        except:
            pass
        
        try:
            print(f"  cancel_event.is_set(): {self.export_cancel_event.is_set()}")
        except:
            pass
        
        try:
            print(f"  selected_items count: {len(self.selected_items)}")
        except:
            pass
        
        try:
            print(f"  search_cache size: {len(self.search_cache)}")
        except:
            pass
        
        try:
            print(f"  queue size: {self.update_queue.qsize()}")
        except:
            pass
        
        print("="*60 + "\n")

    def _enable_debug_mode(self):
        """
        Enable debug mode with verbose logging.
        
        ✅ NEW: Call this if you need to debug issues
        """
        # Bind Ctrl+D to print debug state
        self.bind('<Control-d>', lambda e: self._debug_print_state())
        
        self._log("🐛 Debug mode enabled - Press Ctrl+D to print state")


    def _process_queue(self):
        """
        Process updates from background threads.
        
        ✅ FIXED: Better error handling for each event type
        """
        # ✅ SAFETY: Check if window still exists
        if not self._is_window_alive():
            return
        
        try:
            # Process all queued items (up to 10 per cycle to prevent blocking)
            processed = 0
            max_per_cycle = 10
            
            while processed < max_per_cycle:
                try:
                    item = self.update_queue.get_nowait()
                except queue.Empty:
                    break
                
                processed += 1
                
                # ✅ SAFETY: Validate item structure
                if not isinstance(item, tuple) or len(item) < 1:
                    print(f"⚠️ Invalid queue item: {item}")
                    continue
                
                event_type = item[0]
                data = item[1] if len(item) > 1 else None
                
                # ✅ ADD DEBUG LOGGING HERE:
                print(f"🎬 Processing queue event: {event_type}")
                
                # ✅ Handle each event type with error handling
                try:
                    if event_type == "search_complete":
                        self._on_search_complete(data)
                        
                    elif event_type == "search_error":
                        self._on_search_error(data)
                        
                    elif event_type == "search_cancelled":
                        self._on_search_cancelled()
                        
                    elif event_type == "progress_with_name":
                        self._on_export_progress_with_name(data)
                        
                    elif event_type == "progress":
                        self._on_export_progress(data)
                        
                    elif event_type == "export_complete":
                        # ✅ ADD EXTRA DEBUG HERE:
                        print("=" * 60)
                        print("🎯 EXPORT_COMPLETE EVENT RECEIVED!")
                        print(f"   Data type: {type(data)}")
                        print(f"   Data: {data}")
                        print("   Calling _on_export_complete()...")
                        print("=" * 60)   
                             
                        self._on_export_complete(data)
                        
                        print("✅ _on_export_complete() returned")
                        
                    elif event_type == "export_error":
                        self._on_export_error(data)
                        
                    elif event_type == "log":
                        self._log(data)
                        
                    elif event_type == "ui_update":
                        # ✅ NEW: Handle generic UI updates
                        callback, args, kwargs = data
                        callback(*args, **kwargs)
                        
                    else:
                        print(f"⚠️ Unknown event type: {event_type}")
                        
                except Exception as e:
                    print(f"❌ Error processing event '{event_type}': {e}")
                    import traceback
                    traceback.print_exc()
        
        except Exception as e:
            print(f"❌ Queue processor error: {e}")
            import traceback
            traceback.print_exc()
        
        # Schedule next check (100ms interval)
        try:
            if self._is_window_alive():
                self.after(100, self._process_queue)
        except Exception as e:
            print(f"❌ Cannot schedule queue processor: {e}")

    def _is_window_alive(self) -> bool:
        """
        Check if window still exists and is usable.
        
        ✅ NEW: Prevents operations on destroyed windows
        
        Returns:
            True if window is alive, False otherwise
        """
        if hasattr(self, '_is_being_destroyed') and self._is_being_destroyed:
            return False
        
        try:
            # Try to access a basic window property
            return self.winfo_exists()
        except:
            return False
            
    
    def _on_back_clicked(self):
        """
        Handle back button click.
        Returns to parent application (gui.py).
        """
        # Check if busy
        if self._is_ui_busy():
            if self.is_loading:
                message = "Search is in progress. Cancel and return?"
            elif self._is_export_busy():
                message = "Export is in progress. Cancel and return?"
            else:
                message = "An operation is in progress. Cancel and return?"
            
            result = messagebox.askyesno(
                "Operation in Progress",
                message,
                icon='warning'
            )
            
            if not result:
                return
            
            # Cancel operations
            self._log("🛑 Cancelling operations to return...")
            self.export_cancel_event.set()
            
            # Give threads time to cleanup
            self.after(500, self._force_back)
            return
        
        # No operations running - safe to return
        self._force_back()
    
    def _force_back(self):
        """Force return to parent application"""
        # Reset states
        self._reset_export_state()
        self.is_loading = False
        
        # Clear search state
        self.last_search_keyword = None
        self.search_cache.clear()
        
        try:
            self.grab_release()
        except:
            pass
        
        # Call parent's logout handler (which shows export frame)
        if self.on_logout_callback:
            try:
                self.on_logout_callback()
            except Exception as e:
                print(f"⚠️ Error in back callback: {e}")
    
    

# ===== NO STANDALONE ENTRY POINT =====
# This app is now launched via main.py's AppLauncher
# Do not run this file directly

if __name__ == "__main__":
    print("⚠️  ERROR: This module cannot run standalone!")
    print("✅ This is integrated into the main application.")
    print("✅ Run main.py from the parent project instead.")
    import sys
    sys.exit(1)