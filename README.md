# DGFT ITC(HS) Policy PDF Extractor

A robust Python utility to automate the extraction of Import and Export policy documents (Chapters, Notifications, Appendices) from the [DGFT Website](https://www.dgft.gov.in/CP/?opt=itchs-import-export).

## Features
-   **Comprehensive Extraction**: Downloads both "Schedule 1 - Import Policy" and "Schedule 2 - Export Policy".
-   **Smart PDF Handling**:
    -   Extracts chapter PDFs from dynamic data tables.
    -   Automatically detects and downloads direct PDF links for "Extras" (Notifications, Appendices).
    -   Handles browser download events and blob URLs seamlessly.
-   **Scoped Processing**: accurately distinguishes between Import and Export sections to avoid duplicate or incorrect downloads for identically named items (e.g., "Notification").
-   **Granular Control**: Filter by policy type, chapter, specific section name, or download only "extras".
-   **Instant Content Search**: Full-text search across all downloaded PDFs using a local SQLite index.

## Prerequisites
-   Python 3.7+
-   [Playwright](https://playwright.dev/python/)

## Installation

1.  **Install dependencies**:
    ```bash
    pip install playwright fastapi uvicorn pypdf pdfplumber aiofiles
    ```

2.  **Install browser binaries**:
    ```bash
    playwright install chromium
    ```

## Usage

### 1. Extractor Script (Data Collection)
Run the script from the command line:

```bash
python3 extract_dgft_pdfs.py [OPTIONS]
```

**Options:**
-   `--policy all` (Import + Export + Extras)
-   `--policy import`, `--policy export`
-   `--chapter "01"` (Specific Chapter)
-   `--force` (Overwrite existing files)

### 2. Dashboard & Search (Viewer)
Start the dashboard server to browse and search files:

```bash
uvicorn dashboard.server:app --reload
```

Open your browser to `http://localhost:8000`.

## Content Search Architecture

The dashboard includes a high-performance content search engine that allows you to instantly find text across hundreds of PDF files.

**How it works:**
1.  **Indexing**: On startup, the server runs a background task using `dashboard/indexer.py`.
    -   It iterates through all PDFs in the `downloads/` directory.
    -   It extracts text content using **pdfplumber**, which provides reliable extraction even for complex layouts.
    -   Text is stored in a local SQLite database (`dashboard/search_index.db`) using the **FTS5** (Full-Text Search) extension.
    -   The indexer checks file modification times to avoid re-indexing unchanged files, making restarts fast.

2.  **Searching**:
    -   When you perform a search in the UI, the query is sent to the `/api/search` endpoint.
    -   The server queries the SQLite FTS index instead of opening PDF files.
    -   This reduces search time from minutes (brute-force parsing) to milliseconds.

3.  **Updates**:
    -   The index is automatically updated when the server starts.
    -   You can verify indexing progress in the dashboard console output.

## Output Structure

Files are saved in the `downloads/` directory, organized by policy type:

```
downloads/
├── Import_Policy/          # Main Import Policy Chapters (01-98)
├── Import_Policy_Extra/    # Import Notifications, Appendices, etc.
├── Export_Policy/          # Main Export Policy Chapters (01-98)
└── Export_Policy_Extra/    # Export Notifications, Appendices, etc.
```

## How It Works (Extractor)

1.  **Headless Browser**: Uses Playwright (Chromium) to render the dynamic DGFT website.
2.  **Scoped Interaction**: Identifies the "Import" and "Export" DOM containers specifically to ensure clicks are sent to the correct section.
3.  **Dynamic Detection**:
    -   When a card is clicked, the script waits for a data table (`#itcdetails`) to load.
    -   If a table loads, it iterates through rows and downloads the PDF linked in each row.
    -   If no table loads, it checks if the page redirected to a PDF or triggered a download event (common for "Notification" and "Appendix").
4.  **Blob Extraction**: For table-based links which use sophisticated `javascript:` actions, the script intercepts `window.open` or fetches the `blob:` URL directly to save the file.
