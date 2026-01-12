import sqlite3
import os
import time
import pdfplumber
from typing import List, Dict

class SearchIndexer:
    def __init__(self, db_path="dashboard/search_index.db"):
        self.db_path = db_path
        self.initialize_db()

    def initialize_db(self):
        conn = sqlite3.connect(self.db_path)
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
        # Standard table to track modification times for incremental updates
        c.execute("""
            CREATE TABLE IF NOT EXISTS file_meta (
                path TEXT PRIMARY KEY,
                mtime REAL
            )
        """)
        conn.commit()
        conn.close()

    def index_file(self, full_path: str, relative_path: str):
        if not os.path.exists(full_path):
            return

        current_mtime = os.stat(full_path).st_mtime
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Check if needs update
        c.execute("SELECT mtime FROM file_meta WHERE path = ?", (relative_path,))
        row = c.fetchone()
        
        if row and row[0] == current_mtime:
            # Already indexed and unchanged
            conn.close()
            return
        
        # Parse PDF using pdfplumber
        try:
            full_text = ""
            with pdfplumber.open(full_path) as pdf:
                text_content = []
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text_content.append(extracted)
                full_text = "\n".join(text_content)
            
            filename = os.path.basename(full_path)

            if row:
                # Update existing
                c.execute("DELETE FROM pdf_fts WHERE path = ?", (relative_path,))
            
            # Simple content cleaning for better searching
            # Collapse multiple spaces
            full_text = " ".join(full_text.split())

            c.execute("INSERT INTO pdf_fts (filename, content, path, mtime) VALUES (?, ?, ?, ?)", 
                      (filename, full_text, relative_path, current_mtime))
            
            c.execute("INSERT OR REPLACE INTO file_meta (path, mtime) VALUES (?, ?)", 
                      (relative_path, current_mtime))
            
            conn.commit()
            print(f"Indexed: {filename}")
            
        except Exception as e:
            print(f"Failed to index {full_path}: {e}")
        finally:
            conn.close()

    def search(self, query: str, scope: str = "all") -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Scope mapping
        scope_map = {
            "import": "%/Import_Policy/%",
            "export": "%/Export_Policy/%",
            "import_extra": "%/Import_Policy_Extra/%",
            "export_extra": "%/Export_Policy_Extra/%"
        }

        try:
            sql = """
                SELECT path, filename, snippet(pdf_fts, 1, '<b>', '</b>', '...', 20) 
                FROM pdf_fts 
                WHERE pdf_fts MATCH ?
            """
            params = [query]

            if scope in scope_map:
                sql += " AND path LIKE ?"
                params.append(scope_map[scope])
            
            sql += " ORDER BY rank"
            # No LIMIT as requested by user

            c.execute(sql, tuple(params))
            
            results = []
            for row in c.fetchall():
                results.append({
                    "path": row[0],
                    "name": row[1],
                    "matches": [{
                        "snippet": row[2]
                    }]
                })
            return results
        except Exception as e:
            print(f"Search error: {e}")
            return []
        finally:
            conn.close()

    def reindex_all(self, base_path: str):
        print("Starting full re-indexing...")
        count = 0
        for root, dirs, files in os.walk(base_path):
            for file in files:
                if file.endswith(".pdf"):
                    full_path = os.path.join(root, file)
                    rel_dir = os.path.relpath(root, base_path)
                     # Match the path format used in server.py: /files/{folder}/{file}
                    # But server.py uses 'downloads' as base.
                    # If base_path is 'downloads', rel_dir is just the subfolder or '.'
                    
                    if rel_dir == ".":
                         web_path = f"/files/{file}"
                    else:
                         web_path = f"/files/{rel_dir}/{file}"
                    
                    self.index_file(full_path, web_path)
                    count += 1
        print(f"Indexing complete. Processed {count} files.")
