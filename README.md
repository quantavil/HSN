# DGFT ITC(HS) Policy PDF Extractor

A robust Python utility to automate the extraction of Import and Export policy documents (Chapters, Notifications, Appendices) from the [DGFT Website](https://www.dgft.gov.in/CP/?opt=itchs-import-export).

## Features
-   **Comprehensive Extraction**: Downloads both "Schedule 1 - Import Policy" and "Schedule 2 - Export Policy".
-   **Smart PDF Handling**:
    -   Extracts chapter PDFs from dynamic data tables.
    -   Automatically detects and downloads direct PDF links for "Extras" (Notifications, Appendices).
    -   Handles browser download events and blob URLs seamlessly.
-   **Scoped Processing**: Accurately distinguishes between Import and Export sections (e.g., handles "Notification" in both categories separately).
-   **Granular Control**: Filter by policy type, chapter, specific section name, or download only "extras".
-   **Advanced Search**:
    -   **Content Search**: Full-text search across all downloaded PDFs using a local SQLite FTS5 index, enhanced with **RapidFuzz** for semantic term expansion.
    -   **Smart Filtering**: Real-time fuzzy filtering of filenames using a custom subsequence matching algorithm, allowing you to find files even with partial or spaced-out matches.
    -   **Adjustable Sensitivity**: Control fuzzy match strictness via the UI settings (Strict inclusion vs. Loose subsequence matching).

## Prerequisites
-   Python 3.7+
-   [Playwright](https://playwright.dev/python/)

## Installation

1.  **Install dependencies**:
    ```bash
    pip install playwright fastapi uvicorn pypdf pdfplumber aiofiles rapidfuzz
    ```

2.  **Install browser binaries**:
    ```bash
    playwright install chromium
    ```

## Docker / Podman Support

You can run the application in a container without manually installing Python dependencies.

### 1. Install Docker or Podman

**Linux (Ubuntu/Debian):**
```bash
# Docker
sudo apt-get update
sudo apt-get install -y docker.io

# Podman
sudo apt-get update
sudo apt-get install -y podman
```

**Windows:**
- **Docker:** Download [Docker Desktop](https://www.docker.com/products/docker-desktop/) or run `winget install Docker.DockerDesktop`
- **Podman:** Run `winget install RedHat.Podman-Desktop`

**macOS:**
- **Docker:** Download [Docker Desktop](https://www.docker.com/products/docker-desktop/) or run `brew install --cask docker`
- **Podman:** Run `brew install podman`

### 2. Run with Docker

Build and run the container:

```bash
# Build the image
docker build -t dgft-extractor .

# Run the container (maps port 8000 and the downloads directory)
docker run -p 8000:8000 -v $(pwd)/downloads:/app/downloads dgft-extractor
```

(Replace `docker` with `podman` if using Podman)

### 3. Stop and Remove

To stop the container and remove the image:

```bash
# Stop the running container (find the ID/name first with `docker ps`)
docker stop <container_id>

# Remove the container
docker rm <container_id>

# Remove the image
docker rmi dgft-extractor
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

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


## Architecture

### Content Search (Backend)
The dashboard uses a high-performance content search engine:
1.  **Indexing**: `dashboard/indexer.py` extracts text from PDFs using `pdfplumber` and stores it in a SQLite FTS5 database.
2.  **Searching**: Queries are executed against the FTS index.
3.  **Fuzzy Logic**: The backend uses **RapidFuzz** to find corrections for search terms in the index vocabulary, expanding the query to find relevant sections even with slight mismatches.

### File Filtering (Frontend)
The dashboard UI includes a custom fuzzy filter:
-   **Strict Mode**: Uses standard substring matching (`.includes()`).
-   **Loose Mode**: Uses subsequence matching (characters must appear in order, but can be spaced out), enabled when "Fuzzy Sensitivity" is < 90%.
-   **No Dependencies**: Lightweight implementation without external libraries.

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
