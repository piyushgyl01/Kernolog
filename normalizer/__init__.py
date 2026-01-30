import sys
import queue
import logging
import threading
from .core import LogNormalizer
from collector.core import LogWatcher

__all__ = ["LogNormalizer", "run_live", "process_stream"]

# Basic logging config
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class _FunctionalNormalizer(LogNormalizer):
    """
    Internal helper class.
    It overrides process_log() to call a user-provided function.
    This allows using functions instead of creating classes.
    """
    def __init__(self, input_queue, callback):
        super().__init__(input_queue)
        self.callback = callback

    def process_log(self, raw_line):
        # Delegate the logic to the user's function
        self.callback(raw_line)

def _default_printer(line):
    """Default callback: simply prints to stdout with a tag."""
    sys.stdout.write(f"[NORMALIZED] {line}\n")
    sys.stdout.flush()

def run_live():
    """
    Starts the full pipeline (Collector -> Queue -> Normalizer)
    and prints logs to the console using the default format.
    Blocks until stopped.
    """
    process_stream(_default_printer)

def process_stream(custom_callback):
    """
    Starts the full pipeline using a custom processing function.
    
    Args:
        custom_callback (func): A function that takes a log line (str) as input.
    """
    # 1. Create the Shared Queue
    q = queue.Queue()

    # 2. Initialize Collector (Producer)
    # It simply pushes raw logs into the queue
    collector = LogWatcher(callback=q.put)

    # 3. Initialize Normalizer (Consumer)
    # We use the helper class to wrap the user's function
    normalizer = _FunctionalNormalizer(input_queue=q, callback=custom_callback)

    try:
        # Start Normalizer in background
        normalizer.start()

        # Start Collector (This blocks the main thread)
        # We run this here so the script stays alive
        collector.start()

    except KeyboardInterrupt:
        # Handle clean shutdown if user presses Ctrl+C
        collector.stop()
        normalizer.stop()