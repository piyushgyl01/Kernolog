import subprocess
import select
import logging
import time
import signal
import json

logger = logging.getLogger("LogCollector")

class LogWatcher:
    def __init__(self, callback, command=None):
        self.callback = callback
        self.running = True
        self.proc = None
        # FORCE json output to get the PRIORITY field
        self.command = command or ["journalctl", "-f", "-o", "json", "-n", "0"]
    
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def stop(self, signum=None, frame=None):
        logger.info("Stopping collector...")
        self.running = False

    def start(self):
        logger.info(f"Collector started. Watching: {' '.join(self.command)}")
        while self.running:
            try:
                self._run_subprocess()
            except Exception as e:
                logger.error(f"Collector main loop error: {e}")
                time.sleep(2)
        self._cleanup()

    def _run_subprocess(self):
        try:
            self.proc = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,  # Text mode for easier JSON parsing
                bufsize=1 
            )
        except FileNotFoundError:
            logger.critical(f"Command not found: {self.command[0]}")
            self.running = False
            return

        poller = select.poll()
        poller.register(self.proc.stdout, select.POLLIN)

        while self.running:
            if self.proc.poll() is not None:
                logger.warning("Subprocess ended unexpectedly. Restarting in 1s...")
                time.sleep(1)
                break

            events = poller.poll(500) 
            for fd, event in events:
                if fd == self.proc.stdout.fileno():
                    line = self.proc.stdout.readline()
                    if line:
                        try:
                            # 1. Parse JSON from Journalctl
                            entry = json.loads(line)
                            
                            # 2. Extract standard fields
                            # Priority defaults to 6 (Info) if missing
                            structured_log = {
                                "message": entry.get("MESSAGE", ""),
                                "priority": int(entry.get("PRIORITY", 6)), 
                                "unit": entry.get("_SYSTEMD_UNIT", "system")
                            }
                            
                            # 3. Send Dict to Callback
                            self.callback(structured_log)

                        except json.JSONDecodeError:
                            continue # Skip broken lines
                        except Exception as e:
                            logger.error(f"Parsing error: {e}")

    def _cleanup(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        logger.info("Collector shutdown complete.")