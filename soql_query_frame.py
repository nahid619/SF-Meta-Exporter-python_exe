"""
SOQL Query Frame - GUI for running SOQL queries (Smart Auto-Filter)
"""
import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from typing import Optional, List, Dict
import customtkinter as ctk

from soql_runner import SOQLRunner
from threading_helper import ThreadHelper


class SOQLQueryFrame(ctk.CTkFrame):
    """Frame for SOQL query execution"""

    def __init__(self, parent, soql_runner: SOQLRunner, status_callback=None):
        super().__init__(parent)

        self.soql_runner = soql_runner
        self.status_callback = status_callback
        self.current_results: List[Dict] = []
        self.current_record_count = 0
        self.current_object_name = None

        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI components"""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)  # Results section

        # Header with back button
        self._setup_header()

        # Query editor section
        self._setup_query_editor()

        # Field suggestions section (Ctrl+Space activated)
        self._setup_suggestions_section()

        # Results section
        self._setup_results_section()

        # Status bar
        self._setup_status_bar()

    def _setup_header(self):
        """Setup header with title and back button"""
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, pady=(10, 5), sticky="ew", padx=20)
        header_frame.columnconfigure(1, weight=1)

        # Back button
        self.back_button = ctk.CTkButton(
            header_frame,
            text="← Back",
            command=self._on_back,
            width=100,
            fg_color="#666666"
        )
        self.back_button.grid(row=0, column=0, sticky="w", padx=(0, 10))

        # Title
        ctk.CTkLabel(
            header_frame,
            text="SOQL Query Runner",
            font=ctk.CTkFont(size=30, weight="bold")
        ).grid(row=0, column=1, sticky="w")

    def _setup_query_editor(self):
        """Setup query editor section"""
        editor_frame = ctk.CTkFrame(self)
        editor_frame.grid(row=1, column=0, pady=10, sticky="ew", padx=20)
        editor_frame.grid_columnconfigure(0, weight=1)

        # Label
        ctk.CTkLabel(
            editor_frame,
            text="Enter SOQL Query (Ctrl+Space for field suggestions):",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 5))

        # Query text editor with scrollbar
        query_container = ctk.CTkFrame(editor_frame)
        query_container.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        query_container.grid_columnconfigure(0, weight=1)

        self.query_text = tk.Text(
            query_container,
            height=8,
            font=("Consolas", 11),
            wrap="word",
            bg="#2b2b2b",
            fg="white",
            insertbackground="white",
            selectbackground="#1F538D"
        )
        self.query_text.grid(row=0, column=0, sticky="ew")

        # Scrollbar for query text
        query_scrollbar = ttk.Scrollbar(query_container, command=self.query_text.yview)
        query_scrollbar.grid(row=0, column=1, sticky="ns")
        self.query_text.configure(yscrollcommand=query_scrollbar.set)

        # Sample query
        sample_query = "SELECT Id, Name, CreatedDate\nFROM Account\nLIMIT 10"
        self.query_text.insert("1.0", sample_query)

        # Bind Ctrl+Enter to execute (no new line)
        def execute_on_ctrl_enter(event):
            self.execute_query()
            return "break"

        self.query_text.bind("<Control-Return>", execute_on_ctrl_enter)

        # Bind Ctrl+Space for field suggestions
        def show_suggestions_on_ctrl_space(event):
            self._trigger_field_suggestions()
            return "break"

        self.query_text.bind("<Control-space>", show_suggestions_on_ctrl_space)

        # Buttons frame (REMOVED Show Fields button)
        buttons_frame = ctk.CTkFrame(editor_frame, fg_color="transparent")
        buttons_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        buttons_frame.grid_columnconfigure(3, weight=1)

        # Execute button
        self.execute_button = ctk.CTkButton(
            buttons_frame,
            text="▶ Execute Query (Ctrl+Enter)",
            command=self.execute_query,
            height=40,
            fg_color="green",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.execute_button.grid(row=0, column=0, sticky="w", padx=(0, 10))

        # Clear button
        self.clear_button = ctk.CTkButton(
            buttons_frame,
            text="Clear",
            command=self._clear_query,
            height=40,
            width=100,
            fg_color="#666666"
        )
        self.clear_button.grid(row=0, column=1, sticky="w", padx=(0, 10))

        # Format button
        self.format_button = ctk.CTkButton(
            buttons_frame,
            text="Format",
            command=self._format_query,
            height=40,
            width=100,
            fg_color="#666666"
        )
        self.format_button.grid(row=0, column=2, sticky="w", padx=(0, 10))

        # Show Objects button
        self.objects_button = ctk.CTkButton(
            buttons_frame,
            text="📋 Show Objects",
            command=self._show_object_list,
            height=40,
            width=140,
            fg_color="#E67E22"
        )
        self.objects_button.grid(row=0, column=3, sticky="e")

    def _setup_suggestions_section(self):
        """Setup field suggestions section (Ctrl+Space activated)"""
        suggestions_frame = ctk.CTkFrame(self)
        suggestions_frame.grid(row=2, column=0, pady=(0, 10), sticky="ew", padx=20)
        suggestions_frame.grid_columnconfigure(0, weight=1)

        # Header with label
        header = ctk.CTkFrame(suggestions_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header.grid_columnconfigure(0, weight=1)

        self.suggestions_label = ctk.CTkLabel(
            header,
            text="Field Suggestions (Press Ctrl+Space to show fields)",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        )
        self.suggestions_label.grid(row=0, column=0, sticky="w")

        # Filter box with clear button
        filter_frame = ctk.CTkFrame(header, fg_color="transparent")
        filter_frame.grid(row=0, column=1, sticky="e")

        self.suggestion_search = ctk.CTkEntry(
            filter_frame,
            placeholder_text="Filter fields...",
            width=180,
            height=28
        )
        self.suggestion_search.grid(row=0, column=0, padx=(0, 5))
        self.suggestion_search.bind("<KeyRelease>", lambda e: self._filter_suggestions())

        # Clear filter button (NEW)
        self.clear_filter_button = ctk.CTkButton(
            filter_frame,
            text="✕",
            command=self._clear_filter,
            width=28,
            height=28,
            fg_color="#666666",
            hover_color="#888888"
        )
        self.clear_filter_button.grid(row=0, column=1)

        # Scrollable frame for suggestions
        suggestions_container = ctk.CTkFrame(suggestions_frame, height=100)
        suggestions_container.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        suggestions_container.grid_columnconfigure(0, weight=1)
        suggestions_container.grid_propagate(False)

        # Canvas and scrollbar for horizontal scrolling
        canvas = tk.Canvas(
            suggestions_container,
            height=80,
            bg="#2b2b2b",
            highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(suggestions_container, orient="horizontal", command=canvas.xview)

        self.suggestions_inner = ctk.CTkFrame(canvas, fg_color="#2b2b2b")

        canvas.create_window((0, 0), window=self.suggestions_inner, anchor="nw")
        canvas.configure(xscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="ew")
        scrollbar.grid(row=1, column=0, sticky="ew")

        # Update scroll region when suggestions change
        self.suggestions_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self.suggestions_canvas = canvas
        self.all_suggestion_buttons = []  # Store all buttons for filtering

    def _clear_filter(self):
        """Clear the filter input (NEW)"""
        self.suggestion_search.delete(0, tk.END)
        self._filter_suggestions()

    def _trigger_field_suggestions(self):
        """Trigger field suggestions when Ctrl+Space is pressed"""
        query = self.query_text.get("1.0", "end-1c").strip()
        object_name = self.soql_runner.get_object_from_query(query)

        if not object_name:
            self.suggestions_label.configure(text="Field Suggestions (add FROM ObjectName to see fields)")
            self._clear_suggestions()
            return

        # Update suggestions for current object
        self.current_object_name = object_name

        # Get smart filter from current cursor position (NEW)
        smart_filter = self._get_smart_filter_from_cursor()

        # Update suggestions
        self._update_live_suggestions(object_name)

        # Apply smart filter if found (NEW)
        if smart_filter:
            self.suggestion_search.delete(0, tk.END)
            self.suggestion_search.insert(0, smart_filter)
            self._filter_suggestions()

    def _get_smart_filter_from_cursor(self) -> str:
        """
        Get smart filter based on text near cursor (NEW)
        If user is typing a field name, extract it for filtering

        Example: "SELECT Id, Na|" → returns "Na"
        """
        try:
            # Get cursor position
            cursor_pos = self.query_text.index(tk.INSERT)
            line_num, col_num = map(int, cursor_pos.split('.'))

            # Get current line
            line_start = f"{line_num}.0"
            line_end = f"{line_num}.end"
            current_line = self.query_text.get(line_start, line_end)

            # Get text before cursor on current line
            text_before_cursor = current_line[:col_num]

            # Look for partial field name after last comma, SELECT, or whitespace
            # Pattern: find word characters after last separator
            match = re.search(r'[,\s]\s*([A-Za-z_][A-Za-z0-9_]*)$', text_before_cursor)

            if match:
                partial_field = match.group(1)
                # Only return if it's at least 2 characters (avoid single letter filters)
                if len(partial_field) >= 2:
                    return partial_field

            # Also check if cursor is right after SELECT
            if re.search(r'SELECT\s+([A-Za-z_][A-Za-z0-9_]*)$', text_before_cursor, re.IGNORECASE):
                match = re.search(r'SELECT\s+([A-Za-z_][A-Za-z0-9_]*)$', text_before_cursor, re.IGNORECASE)
                if match:
                    return match.group(1)

        except Exception:
            pass

        return ""

    def _clear_suggestions(self):
        """Clear all suggestion buttons"""
        for widget in self.suggestions_inner.winfo_children():
            widget.destroy()
        self.all_suggestion_buttons = []

    def _update_live_suggestions(self, object_name: Optional[str]):
        """Update field suggestions based on current object"""
        # Clear existing suggestions
        self._clear_suggestions()

        if not object_name:
            self.suggestions_label.configure(text="Field Suggestions (Press Ctrl+Space to show fields)")
            return

        # Get fields for object
        fields = self.soql_runner.get_field_suggestions(object_name)

        if not fields:
            self.suggestions_label.configure(text=f"Field Suggestions (no fields found for {object_name})")
            return

        self.suggestions_label.configure(text=f"Field Suggestions for {object_name} (click to insert)")

        # Create buttons for each field
        for idx, field in enumerate(sorted(fields, key=lambda x: x['name'])):
            field_name = field['name']
            field_type = field['type']

            # Calculate button width based on text length
            text_length = len(f"{field_name} ({field_type})")
            button_width = max(text_length * 8, 100)  # Minimum 100 pixels

            btn = ctk.CTkButton(
                self.suggestions_inner,
                text=f"{field_name} ({field_type})",
                command=lambda fn=field_name: self._insert_field(fn),
                height=28,
                width=button_width,
                fg_color="#1F538D",
                hover_color="#2E6FB5"
            )
            btn.grid(row=0, column=idx, padx=5, pady=5, sticky="w")

            # Double-click to insert
            btn.bind("<Double-Button-1>", lambda e, fn=field_name: self._insert_field(fn))

            self.all_suggestion_buttons.append((btn, field_name.lower(), field_type.lower()))

    def _filter_suggestions(self):
        """Filter displayed suggestions based on search"""
        search_term = self.suggestion_search.get().lower()

        visible_count = 0
        for btn, field_name, field_type in self.all_suggestion_buttons:
            if search_term in field_name or search_term in field_type:
                btn.grid()
                visible_count += 1
            else:
                btn.grid_remove()

        # Update label with count (NEW)
        if self.current_object_name:
            if search_term:
                self.suggestions_label.configure(
                    text=f"Field Suggestions for {self.current_object_name} ({visible_count} matching)"
                )
            else:
                self.suggestions_label.configure(
                    text=f"Field Suggestions for {self.current_object_name} (click to insert)"
                )

    def _insert_field(self, field_name: str):
        """Insert field name at cursor position"""
        # Get smart filter to see if we should replace partial text (NEW)
        smart_filter = self._get_smart_filter_from_cursor()

        if smart_filter:
            # Delete the partial field name before inserting complete name
            cursor_pos = self.query_text.index(tk.INSERT)
            line_num, col_num = map(int, cursor_pos.split('.'))

            # Calculate where partial field starts
            start_pos = f"{line_num}.{col_num - len(smart_filter)}"

            # Delete partial field
            self.query_text.delete(start_pos, cursor_pos)

        # Insert complete field name
        self.query_text.insert(tk.INSERT, field_name)
        self.query_text.focus_set()

        # Clear filter after insertion
        self._clear_filter()

    def _show_object_list(self):
        """Show dialog with list of all objects"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Select Object")
        dialog.geometry("600x500")
        dialog.transient(self)
        dialog.grab_set()

        # Header
        ctk.CTkLabel(
            dialog,
            text="Select a Salesforce Object",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=10, padx=20)

        # Search box
        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            dialog,
            placeholder_text="Search objects...",
            textvariable=search_var,
            height=35
        )
        search_entry.pack(pady=5, padx=20, fill="x")

        # Objects list with scrollbar
        list_frame = ctk.CTkFrame(dialog)
        list_frame.pack(pady=10, padx=20, fill="both", expand=True)

        objects_listbox = tk.Listbox(
            list_frame,
            font=("Consolas", 11),
            bg="#2b2b2b",
            fg="white",
            selectbackground="#1F538D",
            height=20
        )
        objects_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, command=objects_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        objects_listbox.configure(yscrollcommand=scrollbar.set)

        # Get all objects
        all_objects = self.soql_runner.get_all_objects()

        # Populate objects
        def populate_objects(search_term=""):
            objects_listbox.delete(0, tk.END)
            for obj in all_objects:
                if search_term.lower() in obj.lower():
                    objects_listbox.insert(tk.END, obj)

        populate_objects()

        # Search functionality
        def on_search(*args):
            populate_objects(search_var.get())

        search_var.trace("w", on_search)

        # Double-click to insert object
        def on_double_click(event):
            selection = objects_listbox.curselection()
            if selection:
                object_name = objects_listbox.get(selection[0])
                # Insert at cursor position
                self.query_text.insert(tk.INSERT, object_name)
                dialog.destroy()
                self.query_text.focus_set()

        objects_listbox.bind("<Double-Button-1>", on_double_click)

        # Insert button
        def insert_selected():
            selection = objects_listbox.curselection()
            if selection:
                object_name = objects_listbox.get(selection[0])
                self.query_text.insert(tk.INSERT, object_name)
                dialog.destroy()
                self.query_text.focus_set()

        button_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        button_frame.pack(pady=10, fill="x", padx=20)

        ctk.CTkButton(
            button_frame,
            text="Insert Selected",
            command=insert_selected,
            width=150,
            fg_color="green"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            button_frame,
            text="Close",
            command=dialog.destroy,
            width=100,
            fg_color="#666666"
        ).pack(side="right", padx=5)

    def execute_query(self):
        """Execute the SOQL query"""
        query = self.query_text.get("1.0", "end-1c").strip()

        if not query:
            messagebox.showwarning("Empty Query", "Please enter a SOQL query.")
            return

        # Validate query
        is_valid, error = self.soql_runner.validate_query(query)
        if not is_valid:
            messagebox.showerror("Invalid Query", f"Query validation failed:\n{error}")
            return

        # Disable execute button
        self.execute_button.configure(state="disabled", text="⏳ Executing...")
        self._update_status("Executing query...")

        # Execute in background
        def do_execute():
            records, count, error = self.soql_runner.execute_query(query)

            # Update UI on main thread
            self.after(0, lambda: self._on_query_complete(records, count, error))

        ThreadHelper.run_in_thread(do_execute)

    def _on_query_complete(self, records: List[Dict], count: int, error: Optional[str]):
        """Called when query execution completes"""
        # Re-enable execute button
        self.execute_button.configure(state="normal", text="▶ Execute Query (Ctrl+Enter)")

        if error:
            messagebox.showerror("Query Error", f"Query execution failed:\n{error}")
            self._update_status(f"Error: {error}")
            return

        # Store results
        self.current_results = records
        self.current_record_count = count

        # Display results
        self._display_results(records, count)

        # Enable export button if we have results
        if records:
            self.export_button.configure(state="normal")
        else:
            self.export_button.configure(state="disabled")

        self._update_status(f"Query executed successfully. {count} record(s) returned.")

    def _display_results(self, records: List[Dict], count: int):
        """Display query results in the treeview"""
        # Clear existing data
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)

        # Update label
        self.results_label.configure(text=f"Query Results ({count} records)")

        if not records:
            self._update_status("Query returned 0 records.")
            return

        # Get all column names
        columns = list(records[0].keys())

        # Configure columns
        self.results_tree["columns"] = columns
        self.results_tree["show"] = "headings"

        # Setup column headings
        for col in columns:
            self.results_tree.heading(col, text=col, anchor="w")
            # Set column width based on content
            max_width = len(col) * 10
            self.results_tree.column(col, width=max_width, minwidth=100, anchor="w")

        # Insert data
        for record in records:
            values = [record.get(col, "") for col in columns]
            self.results_tree.insert("", "end", values=values)

    def _export_to_csv(self):
        """Export results to CSV"""
        if not self.current_results:
            messagebox.showwarning("No Data", "No query results to export.")
            return

        # Ask for save location
        default_filename = f"SOQL_Export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        output_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=default_filename,
            filetypes=[("CSV files", "*.csv")]
        )

        if not output_path:
            return

        try:
            self.soql_runner.export_to_csv(self.current_results, output_path)
            messagebox.showinfo(
                "Export Successful",
                f"Query results exported to:\n{output_path}"
            )
            self._update_status(f"Exported {self.current_record_count} records to CSV.")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export:\n{str(e)}")

    def _setup_results_section(self):
        """Setup results table section"""
        results_frame = ctk.CTkFrame(self)
        results_frame.grid(row=3, column=0, pady=10, sticky="nsew", padx=20)
        results_frame.grid_columnconfigure(0, weight=1)
        results_frame.grid_rowconfigure(1, weight=1)

        # Results header
        results_header = ctk.CTkFrame(results_frame, fg_color="transparent")
        results_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        results_header.grid_columnconfigure(0, weight=1)

        self.results_label = ctk.CTkLabel(
            results_header,
            text="Query Results (0 records)",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w"
        )
        self.results_label.grid(row=0, column=0, sticky="w")

        # Export CSV button
        self.export_button = ctk.CTkButton(
            results_header,
            text="📥 Export to CSV",
            command=self._export_to_csv,
            height=35,
            width=150,
            fg_color="#FF6B35",
            state="disabled"
        )
        self.export_button.grid(row=0, column=1, sticky="e", padx=(10, 0))

        # Treeview container with scrollbars
        tree_container = ctk.CTkFrame(results_frame)
        tree_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tree_container.grid_columnconfigure(0, weight=1)
        tree_container.grid_rowconfigure(0, weight=1)

        # Create Treeview
        self.results_tree = ttk.Treeview(tree_container, show="tree headings")
        self.results_tree.grid(row=0, column=0, sticky="nsew")

        # Vertical scrollbar
        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.results_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.results_tree.configure(yscrollcommand=vsb.set)

        # Horizontal scrollbar
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.results_tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        self.results_tree.configure(xscrollcommand=hsb.set)

        # Style for treeview
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview",
                       background="#2b2b2b",
                       foreground="white",
                       fieldbackground="#2b2b2b",
                       borderwidth=0)
        style.configure("Treeview.Heading",
                       background="#1F538D",
                       foreground="white",
                       borderwidth=0)
        style.map("Treeview",
                 background=[("selected", "#1F538D")])

    def _setup_status_bar(self):
        """Setup status bar"""
        status_frame = ctk.CTkFrame(self, height=30)
        status_frame.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 10))
        status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="Ready",
            anchor="w",
            font=ctk.CTkFont(size=11)
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=10, pady=5)

    def _clear_query(self):
        """Clear the query editor"""
        self.query_text.delete("1.0", "end")
        self._clear_suggestions()
        self._clear_filter()

    def _format_query(self):
        """Format the current query"""
        query = self.query_text.get("1.0", "end-1c").strip()

        if not query:
            return

        formatted = self.soql_runner.format_query(query)

        self.query_text.delete("1.0", "end")
        self.query_text.insert("1.0", formatted)

    def _update_status(self, message: str):
        """Update status label"""
        self.status_label.configure(text=message)
        if self.status_callback:
            self.status_callback(message, verbose=True)

    def _on_back(self):
        """Handle back button click"""
        # This will be connected by the main GUI
        pass