import os
import time
import sqlite3
import numpy as np

# Configuration
DB_PATH = "gen_data"
EMBED_DIM = 384

class RelationalLogDB:
    def __init__(self, name, mode='writer'):
        self.name = name
        self.dim = EMBED_DIM
        os.makedirs(DB_PATH, exist_ok=True)
        
        self.vec_file = os.path.join(DB_PATH, f"{name}.bin")
        self.sql_file = os.path.join(DB_PATH, f"{name}.sqlite")
        
        self.conn = sqlite3.connect(self.sql_file, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;") 
        self.conn.commit()
        
        if mode == 'writer':
            self._init_schema()
            self.template_cache = {}
            self._load_cache()

        self.vec_count = 0
        if os.path.exists(self.vec_file):
            self.vec_count = os.path.getsize(self.vec_file) // (self.dim * 4)

    def _init_schema(self):
        with self.conn:
            self.conn.execute('CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY, text TEXT UNIQUE, vector_idx INTEGER, first_seen REAL, last_seen REAL, count INTEGER DEFAULT 1)')
            self.conn.execute('CREATE TABLE IF NOT EXISTS occurrences (id INTEGER PRIMARY KEY, template_id INTEGER, timestamp REAL, priority INT, FOREIGN KEY(template_id) REFERENCES templates(id))')
            self.conn.execute('CREATE TABLE IF NOT EXISTS parameters (id INTEGER PRIMARY KEY, occurrence_id INTEGER, position INTEGER, value TEXT, FOREIGN KEY(occurrence_id) REFERENCES occurrences(id))')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_template_text ON templates(text)')

    def _load_cache(self):
        cursor = self.conn.execute("SELECT id, text, vector_idx FROM templates")
        self.template_cache = {row[1]: (row[0], row[2]) for row in cursor}

    def add_batch(self, model, batch_data):
        base_time = time.time()
        unique_texts, updates, occ_insert, param_insert, batch_map = [], [], [], [], []
        
        for i, item in enumerate(batch_data):
            # 1ms offset to prevent sort collisions
            item_ts = base_time + (i * 0.001)
            
            text = item['message']
            if text in self.template_cache:
                tid, _ = self.template_cache[text]
                updates.append((item_ts, tid))
                self._prepare_occ(tid, item, occ_insert, param_insert, timestamp=item_ts)
            else:
                if text not in unique_texts: unique_texts.append(text)
                batch_map.append((i, text))

        if unique_texts:
            vecs = model.encode(unique_texts, convert_to_numpy=True)
            with open(self.vec_file, "ab") as f: f.write(vecs.tobytes())
            
            start_idx = self.vec_count
            for idx, txt in enumerate(unique_texts):
                v_idx = start_idx + idx
                cur = self.conn.execute("INSERT INTO templates (text, vector_idx, first_seen, last_seen) VALUES (?, ?, ?, ?)", (txt, v_idx, base_time, base_time))
                tid = cur.lastrowid
                self.template_cache[txt] = (tid, v_idx)
                for b_i, b_txt in batch_map:
                    if b_txt == txt:
                        correct_ts = base_time + (b_i * 0.001)
                        self._prepare_occ(tid, batch_data[b_i], occ_insert, param_insert, timestamp=correct_ts)
            self.vec_count += len(vecs)

        with self.conn:
            if updates: self.conn.executemany("UPDATE templates SET last_seen=?, count=count+1 WHERE id=?", updates)
            if occ_insert: self.conn.executemany("INSERT INTO occurrences (id, template_id, timestamp, priority) VALUES (?,?,?,?)", occ_insert)
            if param_insert: self.conn.executemany("INSERT INTO parameters (occurrence_id, position, value) VALUES (?,?,?)", param_insert)

    def _prepare_occ(self, tid, item, occ_list, param_list, timestamp):
        oid = int(timestamp*1000000) 
        occ_list.append((oid, tid, timestamp, item.get('priority',6)))
        for i, p in enumerate(item.get('params',[])): param_list.append((oid, i, str(p)))

    def search(self, query_vector, model, k=5, recency_bias=False):
        """
        Updated Search with Live Re-Ranking.
        Requires passing the `model` instance to encode full sentences on the fly.
        """
        if os.path.exists(self.vec_file): self.vec_count = os.path.getsize(self.vec_file) // (self.dim * 4)
        if self.vec_count == 0: return ["No logs indexed yet."]
        
        # 1. Broad Phase: Get top 20 candidates based on Template Structure
        search_k = min(20, self.vec_count)
        
        mm = np.memmap(self.vec_file, dtype='float32', mode='r', shape=(self.vec_count, self.dim))
        scores = np.dot(mm, query_vector.T).flatten()
        top_indices = np.argpartition(scores, -search_k)[-search_k:]
        
        raw_candidates = []
        for idx in top_indices:
            row = self.conn.execute("SELECT id, text, count, last_seen FROM templates WHERE vector_idx=?", (int(idx),)).fetchone()
            if row:
                # Fetch the LATEST occurrence with its parameters
                occ_row = self.conn.execute("SELECT id, timestamp FROM occurrences WHERE template_id=? ORDER BY timestamp DESC LIMIT 1", (row[0],)).fetchone()
                
                full_text = row[1]
                ts = row[3]
                
                if occ_row:
                    ts = occ_row[1]
                    params = [r[0] for r in self.conn.execute("SELECT value FROM parameters WHERE occurrence_id=? ORDER BY position", (occ_row[0],))]
                    
                    # Construct the REAL sentence (Hydrate)
                    # We use this for re-ranking so the model sees "SanDisk"
                    temp_text = full_text
                    for p in params:
                        if "<*>" in temp_text: temp_text = temp_text.replace("<*>", str(p), 1)
                        else: temp_text += f" {p}"
                    full_text = temp_text
                
                raw_candidates.append({
                    'template_score': float(scores[idx]),
                    'ts': ts,
                    'full_text': full_text, # This now contains "SanDisk" or "Skullcandy"
                    'display_text': self._highlight_params(row[1], params if occ_row else [])
                })
        
        # 2. Narrow Phase: Live Re-Ranking
        # We encode the FULL texts (with params) and check against the query again
        if raw_candidates:
            texts_to_rank = [c['full_text'] for c in raw_candidates]
            
            # This is fast because we only encode ~20 sentences
            new_vecs = model.encode(texts_to_rank, convert_to_numpy=True, show_progress_bar=False)
            new_scores = np.dot(new_vecs, query_vector.T).flatten()
            
            for i, c in enumerate(raw_candidates):
                c['final_score'] = float(new_scores[i])

            # 3. Sort
            if recency_bias:
                # If user wants "Latest", sort by time, but filter out low relevance (< 0.2)
                raw_candidates = [c for c in raw_candidates if c['final_score'] > 0.15]
                raw_candidates.sort(key=lambda x: x['ts'], reverse=True)
            else:
                # Otherwise sort by the new Smart Score
                raw_candidates.sort(key=lambda x: x['final_score'], reverse=True)

        output = []
        for item in raw_candidates[:k]:
            dt = time.localtime(item['ts'])
            millis = int((item['ts'] % 1) * 1000)
            t_str = f"{time.strftime('%H:%M:%S', dt)}.{millis:03d}"
            output.append(f"[Score:{item['final_score']:.2f}] {t_str} | {item['display_text']}")
        
        del mm
        return output

    def _highlight_params(self, text, params):
        for p in params:
            p_str = f"\033[1;33m{p}\033[0m"
            if "<*>" in text: text = text.replace("<*>", p_str, 1)
            else: text += f" {p_str}"
        return text

    def close(self): self.conn.close()