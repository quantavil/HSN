import sqlite3
import os
import pdfplumber
from typing import List, Dict

class SearchIndexer:
    def __init__(self, db_path="dashboard/search_index.db"):
        self.db_path = db_path
        self.initialize_db()

    def initialize_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                # Enable FTS5 extension if possible (usually built-in)
                c.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS pdf_fts USING fts5(
                        filename, 
                        content, 
                        path UNINDEXED, 
                        mtime UNINDEXED
                    )
                """)
                # Vocabulary table for fast term lookup (requires FTS5)
                c.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS pdf_terms USING fts5vocab(pdf_fts, row)
                """)
                # Standard table to track modification times for incremental updates
                c.execute("""
                    CREATE TABLE IF NOT EXISTS file_meta (
                        path TEXT PRIMARY KEY,
                        mtime REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"Index DB Init Error: {e}")

    def index_file(self, full_path: str, relative_path: str):
        if not os.path.exists(full_path):
            return

        try:
            current_mtime = os.stat(full_path).st_mtime
            
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()

                # Check if needs update
                c.execute("SELECT mtime FROM file_meta WHERE path = ?", (relative_path,))
                row = c.fetchone()
                
                if row and row[0] == current_mtime:
                    return
                
                # Parse PDF using pdfplumber
                # Note: This part is CPU intensive and blocking, but we run it in thread threadpool in server.py
                full_text = ""
                try:
                    with pdfplumber.open(full_path) as pdf:
                        text_content = []
                        for page in pdf.pages:
                            extracted = page.extract_text()
                            if extracted:
                                text_content.append(extracted)
                        full_text = "\n".join(text_content)
                except Exception as e:
                    print(f"PDF content extraction failed for {full_path}: {e}")
                    return

                filename = os.path.basename(full_path)

                if row:
                    # Update existing
                    c.execute("DELETE FROM pdf_fts WHERE path = ?", (relative_path,))
                
                # Simple content cleaning for better searching
                full_text = " ".join(full_text.split())

                c.execute("INSERT INTO pdf_fts (filename, content, path, mtime) VALUES (?, ?, ?, ?)", 
                          (filename, full_text, relative_path, current_mtime))
                
                c.execute("INSERT OR REPLACE INTO file_meta (path, mtime) VALUES (?, ?)", 
                          (relative_path, current_mtime))
                
                conn.commit()
                print(f"Indexed: {filename}")
                
        except Exception as e:
            print(f"Failed to index {full_path}: {e}")

    def search(self, query: str, scope: str = "all", fuzzy_threshold: float = 0.85) -> List[Dict]:
        """
        Search for text content within PDFs.
        fuzzy_threshold: 0.0-1.0, minimum similarity score for matches (default 85%)
        """
        from rapidfuzz import process, fuzz
        
        # Scope mapping
        scope_map = {
            "import": "%/Import_Policy/%",
            "export": "%/Export_Policy/%",
            "import_extra": "%/Import_Policy_Extra/%",
            "export_extra": "%/Export_Policy_Extra/%"
        }

        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                
                # For fuzzy matching, we do a broader search first
                # Then filter results by similarity score
                
                # Create FTS5 query with wildcards for broader matching
                search_terms = query.strip().split()
                
                # Enhanced Fuzzy Matching using Vocabulary
                # 1. Fetch all terms from index to find corrections
                c.execute("SELECT term FROM pdf_terms")
                vocab_list = [r[0] for r in c.fetchall()]
                
                expanded_terms = []
                effective_query_terms = set(search_terms)
                
                # Convert threshold to 0-100 scale for rapidfuzz
                score_cutoff = fuzzy_threshold * 100
                
                for term in search_terms:
                    # Always include the original term
                    term_alternatives = [f'"{term}"*']
                    
                    # Only look for fuzzy matches if threshold allows it (strictly less than 1.0)
                    if fuzzy_threshold < 1.0:
                        # Find closest match in vocabulary
                        match = process.extractOne(term, vocab_list, scorer=fuzz.ratio, score_cutoff=score_cutoff)
                        if match:
                            corrected_term, score, _ = match
                            if corrected_term != term:
                                term_alternatives.append(f'"{corrected_term}"*')
                                effective_query_terms.add(corrected_term)
                    
                    expanded_terms.append(" OR ".join(term_alternatives))

                # Combine all term groups with OR (matching original logic, though AND might be better for multi-word)
                # Original was: " OR ".join([f'"{term}"*'...]) implies any word match is enough.
                # Here we group corrections: (term OR correction) OR (term2 OR correction2)
                # But to maintain original structure which flatly specificied ORs:
                
                fts_query = " OR ".join(expanded_terms)
                
                sql = """
                    SELECT path, filename, content
                    FROM pdf_fts 
                    WHERE pdf_fts MATCH ?
                """
                params = [fts_query]

                if scope in scope_map:
                    sql += " AND path LIKE ?"
                    params.append(scope_map[scope])
                
                sql += " LIMIT 200"  # Get more results for fuzzy filtering

                c.execute(sql, tuple(params))
                
                results = []
                query_lower = query.lower()
                
                for row in c.fetchall():
                    path, filename, content = row
                    content_lower = content.lower() if content else ""
                    
                    # Find best matching snippet
                    best_score = 0
                    best_snippet = ""
                    
                    # Search for query in content and score similarity
                    words = content_lower.split()
                    query_words = query_lower.split()
                    
                    # Slide a window over content to find best matching region
                    window_size = max(20, len(query_words) * 3)
                    
                    for i in range(0, len(words) - len(query_words) + 1, 5):
                        window = " ".join(words[i:i + window_size])
                        
                        # Calculate similarity
                        # Calculate similarity using RapidFuzz which is faster
                        # fuzz.ratio returns 0-100, so divide by 100.0
                        score = fuzz.ratio(query_lower, window[:len(query_lower) * 2]) / 100.0
                        
                        # Also check if query terms appear in window
                        term_matches = sum(1 for term in query_words if term in window) / len(query_words)
                        combined_score = (score + term_matches) / 2
                        
                        if combined_score > best_score:
                            best_score = combined_score
                            # Get the actual snippet from original content
                            original_words = content.split()
                            start = max(0, i - 5)
                            end = min(len(original_words), i + window_size + 5)
                            snippet = " ".join(original_words[start:end])
                            
                            # Highlight query terms
                            for term in effective_query_terms:
                                import re
                                snippet = re.sub(
                                    f'({re.escape(term)})',
                                    r'<b>\1</b>',
                                    snippet,
                                    flags=re.IGNORECASE
                                )
                            best_snippet = "..." + snippet + "..."
                    
                    # Apply fuzzy threshold filter
                    if best_score >= fuzzy_threshold or any(term.lower() in content_lower for term in effective_query_terms):
                        results.append({
                            "path": path,
                            "name": filename,
                            "score": best_score,
                            "matches": [{
                                "snippet": best_snippet if best_snippet else f"Match found in {filename}"
                            }]
                        })
                
                # Sort by score descending
                results.sort(key=lambda x: x.get("score", 0), reverse=True)
                
                return results[:50]  # Return top 50
                
        except Exception as e:
            print(f"Search error: {e}")
            return []

    def reindex_all(self, base_path: str):
        print("Starting full re-indexing...")
        count = 0
        try:
            for root, dirs, files in os.walk(base_path):
                for file in files:
                    if file.endswith(".pdf"):
                        full_path = os.path.join(root, file)
                        rel_dir = os.path.relpath(root, base_path)
                        
                        if rel_dir == ".":
                             web_path = f"/files/{file}"
                        else:
                             web_path = f"/files/{rel_dir}/{file}"
                        
                        self.index_file(full_path, web_path)
                        count += 1
        except Exception as e:
             print(f"Re-indexing error: {e}")
        
        print(f"Indexing complete. Processed {count} files.")
