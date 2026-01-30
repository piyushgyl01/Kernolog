import sys
import logging
from .core import LogWatcher

# Basic logging config so users see output immediately
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def _simple_printer(line):
    """Default callback: simply prints to stdout."""
    # We use sys.stdout directly to ensure immediate flushing to terminal
    sys.stdout.write(f"[LIVE LOG] {line}\n")
    sys.stdout.flush()

def print_logs():
    """
    Starts the collector and prints all logs to the console.
    This function blocks until the script is stopped.
    """
    watcher = LogWatcher(callback=_simple_printer)
    watcher.start()

def watch(custom_callback):
    """
    Starts the collector using a custom function provided by the user.
    
    Args:
        custom_callback (func): A function that takes a single string argument.
    """
    watcher = LogWatcher(callback=custom_callback)
    watcher.start()