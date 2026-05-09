"""
Threading helper for running long operations without blocking UI
"""
import threading
from typing import Callable, Any
import customtkinter as ctk


class ThreadHelper:
    """Helper class to run operations in background threads"""
    
    @staticmethod
    def run_in_thread(target_func: Callable, on_complete: Callable = None, 
                     on_error: Callable = None, *args, **kwargs):
        """
        Run a function in a background thread
        
        Args:
            target_func: The function to run in background
            on_complete: Callback function when complete (receives result)
            on_error: Callback function on error (receives exception)
            *args, **kwargs: Arguments to pass to target_func
        """
        def wrapper():
            try:
                result = target_func(*args, **kwargs)
                if on_complete:
                    # Schedule callback on main thread
                    on_complete(result)
            except Exception as e:
                if on_error:
                    on_error(e)
                else:
                    # Default error handling
                    print(f"Thread error: {str(e)}")
        
        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()
        return thread


class ThreadSafeButton(ctk.CTkButton):
    """
    A button that automatically disables during operation and re-enables when done
    """
    
    def __init__(self, master, command=None, loading_text="Processing...", **kwargs):
        self.original_command = command
        self.original_text = kwargs.get('text', 'Button')
        self.loading_text = loading_text
        self.is_processing = False
        
        # Override command with our wrapper
        kwargs['command'] = self._handle_click
        super().__init__(master, **kwargs)
    
    def _handle_click(self):
        """Handle button click with threading"""
        if self.is_processing:
            return
        
        if not self.original_command:
            return
        
        # Disable button and show loading state
        self._set_loading_state(True)
        
        def on_complete(result):
            # Re-enable button on main thread
            self.after(0, lambda: self._set_loading_state(False))
        
        def on_error(error):
            # Re-enable button and show error
            self.after(0, lambda: self._set_loading_state(False))
            print(f"Error: {str(error)}")
        
        # Run command in background thread
        ThreadHelper.run_in_thread(
            self.original_command,
            on_complete=on_complete,
            on_error=on_error
        )
    
    def _set_loading_state(self, is_loading: bool):
        """Set button loading state"""
        self.is_processing = is_loading
        if is_loading:
            self.configure(state="disabled", text=self.loading_text)
        else:
            self.configure(state="normal", text=self.original_text)


# Example usage wrapper functions for your app
def make_button_threadsafe(button_widget, command_func, loading_text="Processing..."):
    """
    Make an existing button thread-safe
    
    Args:
        button_widget: The CTkButton widget
        command_func: The function to run in background
        loading_text: Text to show while processing
    """
    original_text = button_widget.cget("text")
    
    def wrapper():
        # Disable button
        button_widget.configure(state="disabled", text=loading_text)
        
        def on_complete(result):
            # Re-enable on main thread
            button_widget.after(0, lambda: button_widget.configure(
                state="normal", 
                text=original_text
            ))
        
        def on_error(error):
            button_widget.after(0, lambda: button_widget.configure(
                state="normal", 
                text=original_text
            ))
            # You can show error dialog here
            print(f"Error: {str(error)}")
        
        ThreadHelper.run_in_thread(
            command_func,
            on_complete=on_complete,
            on_error=on_error
        )
    
    button_widget.configure(command=wrapper)


def run_with_progress(target_func, progress_callback=None, complete_callback=None, 
                     error_callback=None, *args, **kwargs):
    """
    Run a function with progress updates
    
    Args:
        target_func: Function to run (should accept progress_callback as kwarg)
        progress_callback: Called with progress updates (executed on main thread)
        complete_callback: Called when complete (executed on main thread)
        error_callback: Called on error (executed on main thread)
    """
    def wrapper():
        try:
            # Pass a thread-safe progress callback
            if progress_callback:
                kwargs['progress_callback'] = lambda msg: progress_callback(msg)
            
            result = target_func(*args, **kwargs)
            
            if complete_callback:
                complete_callback(result)
        except Exception as e:
            if error_callback:
                error_callback(e)
            else:
                print(f"Error: {str(e)}")
    
    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    return thread
