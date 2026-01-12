# HSN DGFT Viewer — Issue Tracker

A comprehensive list of bugs, design issues, and code quality problems identified in the codebase.

---

## 🔴 Critical Bugs

### 1. Duplicate Imports in `server.py`
**File:** [`server.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/server.py)  
**Lines:** 10-11, 12 & 34

```python
from pydantic import BaseModel
from pydantic import BaseModel  # Duplicate
from pypdf import PdfReader
...
from pypdf import PdfReader  # Duplicate on line 34
```

**Impact:** Code clutter, pypdf is imported but never used (indexer uses pdfplumber).

---

### 2. Deprecated `@app.on_event("startup")` Usage
**File:** [`server.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/server.py#L56-L59)

```python
@app.on_event("startup")
async def startup_event():
```

**Impact:** FastAPI has deprecated `on_event` in favor of lifespan context managers. This will cause warnings and eventually break in future versions.

**Fix:** Use `lifespan` async context manager pattern.

---

### 3. Global Mutable State for `current_process`
**File:** [`server.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/server.py#L80)

```python
current_process = None
```

**Impact:** Race conditions in concurrent environments. Multiple requests could interfere with the process state.

---

### 4. Silent Exception Swallowing
**Files:** [`server.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/server.py#L99-L100), [`extract_dgft_pdfs.py`](file:///home/quantavil/Documents/Project/HSN/extract_dgft_pdfs.py#L103-L104)

```python
except:
    pass  # Silent failure
```

**Impact:** Errors are silently ignored, making debugging extremely difficult.

---

### 5. XSS Vulnerability in Search Results
**File:** [`index.html`](file:///home/quantavil/Documents/Project/HSN/dashboard/index.html#L200)

```html
<p class="font-mono text-xs opacity-80" x-text="match.snippet"></p>
```

The search API returns HTML with `<b>` tags for highlighting:
```python
snippet(pdf_fts, 1, '<b>', '</b>', '...', 20)
```

But `x-text` escapes HTML. This means `<b>` tags appear as literal text.

**Fix:** Use `x-html` but sanitize input, or use CSS-based highlighting.

---

### 6. Missing Page Number in Search Results
**File:** [`index.html`](file:///home/quantavil/Documents/Project/HSN/dashboard/index.html#L198-L199)

```html
<span x-text="'Page ' + match.page"></span>
```

The indexer doesn't return page numbers — `match.page` is always undefined.

**Impact:** UI displays "Page undefined" for all search results.

---

## 🟠 Design Issues

### 7. Hardcoded Port Assumptions
**File:** [`index.html`](file:///home/quantavil/Documents/Project/HSN/dashboard/index.html#L396-L398)

```javascript
if (window.location.port !== '8000') {
    url = 'http://localhost:8000/api/search';
}
```

**Impact:** Fragile cross-port development handling. Won't work with non-localhost environments or custom ports.

**Recommendation:** Use environment configuration or relative URLs with proper server setup.

---

### 8. Synchronous Database Calls Block Event Loop
**File:** [`indexer.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/indexer.py#L87-L130)

```python
def search(self, query: str, scope: str = "all") -> List[Dict]:
    conn = sqlite3.connect(self.db_path)  # Blocking I/O
```

**Impact:** Search requests block the async event loop. Under load, server becomes unresponsive.

**Fix:** Use `asyncio.to_thread()` for DB calls, or use an async SQLite library.

---

### 9. No Pagination/Limit on Search Results  
**File:** [`indexer.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/indexer.py#L111-L112)

```python
sql += " ORDER BY rank"
# No LIMIT as requested by user
```

**Impact:** A generic search term could return thousands of results, causing memory issues and UI lag.

---

### 10. WebSocket Connection Not Resilient
**File:** [`index.html`](file:///home/quantavil/Documents/Project/HSN/dashboard/index.html#L467-L492)

No reconnection logic if WebSocket disconnects.

**Impact:** Users lose real-time updates if connection drops. Must refresh page.

---

### 11. Static File Mounting Overlaps
**File:** [`server.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/server.py#L31-L32)

```python
app.mount("/static", StaticFiles(directory="dashboard"), name="static")
app.mount("/files", StaticFiles(directory="downloads"), name="files")
```

The `dashboard` directory includes `server.py`, `indexer.py`, and `.pyc` files — all served publicly.

**Security Issue:** Source code and database are exposed at `/static/server.py`, `/static/search_index.db`.

---

### 12. Unused `RunConfig.action` 'single' Type
**File:** [`server.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/server.py#L37)

```python
action: str = 'all' # 'all', 'import', 'export', 'single'
```

`'single'` is documented but frontend sends `'all'` instead (line 635 in index.html).

---

## 🟡 Code Quality Issues

### 13. Vestigial Comments
**File:** [`server.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/server.py#L44)

```python
# ... (existing code)
```

Copy-paste artifact left in code.

---

### 14. Redundant Font Import
**Files:** [`index.html`](file:///home/quantavil/Documents/Project/HSN/dashboard/index.html#L12-L14), [`styles.css`](file:///home/quantavil/Documents/Project/HSN/dashboard/styles.css#L1-L2)

Fonts are imported twice — both in HTML and CSS.

---

### 15. Inconsistent Error Handling
Mixed patterns across codebase:
- Some use `try/except` with alerts
- Some use `try/except: pass`
- Some catch generic `Exception`
- Some don't catch at all

---

### 16. `connected_websockets` List Never Used
**File:** [`server.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/server.py#L81)

```python
connected_websockets: List[WebSocket] = []
```

This variable is declared but never used. `ConnectionManager` manages its own list.

---

### 17. Playwright Pages Resource Leak (Partial Fix)
**File:** [`extract_dgft_pdfs.py`](file:///home/quantavil/Documents/Project/HSN/extract_dgft_pdfs.py#L97-L104)

The `cleanup_extra_pages` function exists but has a bare `except: pass` that could mask cleanup failures.

---

### 18. Magic Strings for Scope Mapping
**File:** [`indexer.py`](file:///home/quantavil/Documents/Project/HSN/dashboard/indexer.py#L91-L97)

```python
scope_map = {
    "import": "%/Import_Policy/%",
    ...
}
```

Hard-coded path patterns coupled to directory structure. Changes require updates in multiple files.

---

## 🔵 Enhancement Opportunities

### 19. No Loading States for File List
When files are loading initially, no skeleton/spinner is shown in the main grid.

---

### 20. No Error Boundary for API Failures
API errors show browser `alert()` dialogs — poor UX.

---

### 21. Search Scope Doesn't Update Results
Changing category doesn't re-trigger content search. User must press Enter again.

---

### 22. Double Font Loading Slows Initial Render
Google Fonts loaded in both HTML preconnect and CSS @import.

---

## Summary Table

| Severity | Count | Categories |
|----------|-------|------------|
| 🔴 Critical | 6 | Duplicate imports, deprecated API, XSS, undefined data |
| 🟠 Design | 6 | Hardcoded ports, blocking I/O, security exposure |
| 🟡 Quality | 6 | Dead code, inconsistent patterns |
| 🔵 Enhancement | 4 | UX improvements |

---

*Generated: 2026-01-12*
