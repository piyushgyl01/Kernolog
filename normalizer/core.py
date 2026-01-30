import threading
import queue
import logging
import subprocess
import re
from colorama import Fore, Style, init
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

init(autoreset=True)
logger = logging.getLogger("LogNormalizer")

class LogNormalizer:
    def __init__(self, input_queue, output_queue=None):
        self.input_queue = input_queue
        self.output_queue = output_queue  # <--- NEW: Connection to DB System
        self.running = False
        self.thread = None
        
        config = TemplateMinerConfig()
        self.miner = TemplateMiner(persistence_handler=None, config=config)
        self.printed_clusters = set()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._worker, name="NormalizerThread", daemon=True)
        self.thread.start()
        logger.info("Normalizer component started.")

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join()
        logger.info("Normalizer stopped.")

    def _worker(self):
        while self.running:
            try:
                # Get the Dict from the queue
                log_data = self.input_queue.get(timeout=1)
                self.process_log(log_data)
                self.input_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing log: {e}")

    def _extract_params(self, template, raw_msg):
        """
        Simple heuristic to extract parameters.
        Drain3 templates look like: "Connection from <*>"
        We split both and find the mismatches.
        """
        params = []
        # This is a basic extraction. 
        # For production, you might want more robust regex matching based on the template.
        try:
            # simple regex to extract data where <*> is
            # converting template "User <*> logged in" to regex "User (.*?) logged in"
            regex = re.escape(template).replace(re.escape('<*>'), '(.*?)')
            # Drain3 sometimes uses different markers, ensuring we catch them
            regex = regex.replace(re.escape('<NUM>'), '(.*?)') 
            
            match = re.search(f"^{regex}$", raw_msg)
            if match:
                params = list(match.groups())
            else:
                # Fallback: simple string split difference
                t_parts = template.split()
                r_parts = raw_msg.split()
                if len(t_parts) == len(r_parts):
                    params = [r for t, r in zip(t_parts, r_parts) if t != r]
        except Exception:
            pass
        return params

    def process_log(self, log_data):
        if not log_data or "message" not in log_data: return
        
        raw_msg = str(log_data["message"]).strip()
        priority = log_data.get("priority", 6)
        unit = log_data.get("unit", "sys")

        if not raw_msg: return

        # 1. Structure (Drain3)
        result = self.miner.add_log_message(raw_msg)
        cluster_id = result["cluster_id"]
        template = result["template_mined"]

        # 2. Extract Parameters (The variables)
        params = self._extract_params(template, raw_msg)

        # 3. Determine Style (Visuals)
        if priority <= 3:
            label = "ERROR"
            color = Fore.RED + Style.BRIGHT
            icon = "🔥"
        elif priority == 4:
            label = "WARN"
            color = Fore.YELLOW
            icon = "⚠️"
        else:
            label = "INFO"
            color = Fore.GREEN
            icon = "✅"

        # 4. Output to Screen (Visual Feedback)
        is_new_template = cluster_id not in self.printed_clusters
        
        if is_new_template or priority <= 4:
            self.printed_clusters.add(cluster_id)
            if is_new_template:
                print(f"{Style.DIM}🆕 [NEW TEMPLATE #{cluster_id}] {template}{Style.RESET_ALL}")
            print(f"{color}{icon} [{label:<5}] {unit}: {raw_msg[:100]}{Style.RESET_ALL}")
            
            # Desktop Alert
            if priority <= 3:
                self.trigger_alert(f"{unit}: {raw_msg}")

        # 5. PUSH TO PIPELINE (Critical Step)
        if self.output_queue:
            processed_data = {
                'message': template,   # The generalized pattern ("User <*> logged in")
                'params': params,      # The extracted variables (['Bob'])
                'priority': priority,
                'original': raw_msg,
                'unit': unit
            }
            self.output_queue.put(processed_data)

    def trigger_alert(self, message):
        try:
            subprocess.run(['notify-send', '-u', 'critical', '🔥 SYSTEM ERROR', message])
        except Exception:
            pass