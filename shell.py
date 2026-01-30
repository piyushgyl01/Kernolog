import sys
from sentence_transformers import SentenceTransformer
from storage import RelationalLogDB

def main():
    print("⏳ Loading Search Shell...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    dbs = {k: RelationalLogDB(k, mode='reader') for k in ['error', 'warning', 'debug']}
    
    # Words that trigger Time-Sorting
    TIME_KEYWORDS = ['now', 'latest', 'recent', 'current', 'last', 'today']

    print("\n" + "="*60)
    print("   KERNOLOG SEARCH SHELL")
    print("   Type: search <category> <query>")
    print("   Tip: Use 'now' or 'latest' to see what just happened.")
    print("="*60 + "\n")

    try:
        while True:
            try: line = input(f"\033[1;36mKernolog\033[0m> ").strip()
            except EOFError: break
            if not line: continue
            
            parts = line.split(" ", 2)
            cmd = parts[0].lower()
            
            if cmd in ["exit", "quit"]: break
            if cmd == "search":
                if len(parts) < 3:
                    # Allow "search debug latest" shorthand if needed, but stick to strict for now
                    if len(parts) == 2 and any(w in parts[1] for w in TIME_KEYWORDS):
                         pass 
                    else:
                        print("Usage: search <category> <query>")
                        continue
                
                cat, query = parts[1].lower(), parts[2]
                
                if cat in dbs:
                    recency = any(w in query.lower() for w in TIME_KEYWORDS)
                    
                    # 1. Clean Query
                    search_text = query
                    if recency:
                        for w in TIME_KEYWORDS:
                            search_text = search_text.replace(w, "").strip()
                    
                    # 2. Handle "Pure Recency" (User typed only "latest" or "now")
                    if recency and not search_text:
                        print(f"\n\033[1;33m--- {cat.upper()} LATEST LOGS ---\033[0m")
                        vec = model.encode(["system device error warning"], convert_to_numpy=True, show_progress_bar=False)
                        # Pass model here too!
                        res = dbs[cat].search(vec, model=model, k=10, recency_bias=True)
                        if not res: print("No logs found.")
                        for r in res: print(r)
                        print("-" * 50)
                        continue

                    # 3. Standard Semantic Search
                    vec = model.encode([search_text], convert_to_numpy=True, show_progress_bar=False)
                    
                    # --- FIX IS HERE: Pass 'model=model' ---
                    res = dbs[cat].search(vec, model=model, k=5, recency_bias=recency)
                    
                    header = f"--- {cat.upper()} Results"
                    if recency: header += " (Time Prioritized)"
                    header += " ---"
                    
                    print(f"\n\033[1;33m{header}\033[0m")
                    if not res: print("No matches found.")
                    for r in res: print(r)
                    print("-" * 50)
                else: print(f"Unknown category '{cat}'.")
            elif cmd == "clear": print("\033c", end="")
            else: print("Unknown command.")
            
    except KeyboardInterrupt: pass
    finally:
        for db in dbs.values(): db.close()

if __name__ == "__main__":
    main()