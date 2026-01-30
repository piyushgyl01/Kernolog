import queue
import time
import threading
import signal
import sys
from sentence_transformers import SentenceTransformer
from collector.core import LogWatcher
from normalizer.core import LogNormalizer
from storage import RelationalLogDB

MODEL_NAME = "all-MiniLM-L6-v2"

class Engine:
    def __init__(self):
        self.running = True
        print("⏳ Engine: Loading AI Model...")
        self.model = SentenceTransformer(MODEL_NAME)
        self.dbs = {
            'error': RelationalLogDB('error'),
            'warning': RelationalLogDB('warning'),
            'debug': RelationalLogDB('debug')
        }
        self.buffers = {k: [] for k in self.dbs}
        self.last_flush = time.time()

    def _get_cat(self, p):
        return 'error' if p <= 3 else 'warning' if p == 4 else 'debug'

    def process(self, input_queue):
        while self.running:
            try:
                data = input_queue.get(timeout=1.0)
                if data is None: break
                
                cat = self._get_cat(data.get('priority', 6))
                self.buffers[cat].append(data)
                
                if len(self.buffers[cat]) >= 16: self._flush(cat)
            except queue.Empty: pass
            
            if time.time() - self.last_flush > 5.0:
                for c in self.buffers: self._flush(c)
                self.last_flush = time.time()

    def _flush(self, cat):
        if self.buffers[cat]:
            self.dbs[cat].add_batch(self.model, self.buffers[cat])
            self.buffers[cat] = []

    def stop(self):
        self.running = False
        for db in self.dbs.values(): db.close()

def main():
    raw_q, clean_q = queue.Queue(), queue.Queue()
    
    collector = LogWatcher(callback=raw_q.put)
    normalizer = LogNormalizer(input_queue=raw_q, output_queue=clean_q)
    engine = Engine()
    
    threads = [
        threading.Thread(target=collector.start),
        threading.Thread(target=normalizer.start),
        threading.Thread(target=engine.process, args=(clean_q,))
    ]
    for t in threads: t.start()

    print("\n🚀 Kernolog Engine Active. (Writes to ./gen_data)")
    
    def shutdown(signum, frame):
        print("\nStopping Engine...")
        collector.stop()
        normalizer.stop()
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    while True: time.sleep(1)

if __name__ == "__main__":
    main()