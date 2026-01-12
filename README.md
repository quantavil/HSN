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

## Prerequisites
-   Python 3.7+
-   [Playwright](https://playwright.dev/python/)

## Installation

1.  **Install dependencies**:
    ```bash
    pip install playwright
    ```

2.  **Install browser binaries**:
    ```bash
    playwright install chromium
    ```

## Usage

Run the script from the command line:

```bash
python3 extract_dgft_pdfs.py [OPTIONS]
```

### Common Commands

**1. Download Everything (Import + Export + All Extras)**
```bash
python3 extract_dgft_pdfs.py --policy all
```

**2. Download Only Import Policy**
```bash
python3 extract_dgft_pdfs.py --policy import
```

**3. Download Only "Extras" (Notifications, Appendices, Pets, etc.)**
Skips the main policy chapters and only updates the supplementary documents.
```bash
python3 extract_dgft_pdfs.py --only-extras
```

**4. Download a Specific Chapter**
Downloads only Chapter 01 (Live Animals).
```bash
python3 extract_dgft_pdfs.py --chapter "01"
```

**5. Filter by Section Name**
Downloads only sections containing "Notification" in their title.
```bash
python3 extract_dgft_pdfs.py --section "Notification"
```

**6. Force Overwrite**
Re-downloads files even if they already exist.
```bash
python3 extract_dgft_pdfs.py --force
```

## Options Reference

| Flag | Description |
| :--- | :--- |
| `-p`, `--policy` | Policy type to download: `import`, `export`, or `all` (default: `all`). |
| `-c`, `--chapter` | Filter by specific Chapter ID (e.g., "01", "85"). |
| `-s`, `--section` | Filter by section title (substring match, case-insensitive). |
| `-f`, `--force` | Force overwrite existing files. |
| `--only-extras` | Download **only** supplementary items (Notifications, Appendices, etc.), skipping main chapters. |
| `--skip-extras` | Skip downloading supplementary items. |

## Output Structure

Files are saved in the `downloads/` directory, organized by policy type:

```
downloads/
├── Import_Policy/          # Main Import Policy Chapters (01-98)
├── Import_Policy_Extra/    # Import Notifications, Appendices, etc.
├── Export_Policy/          # Main Export Policy Chapters (01-98)
└── Export_Policy_Extra/    # Export Notifications, Appendices, etc.
```

## How It Works

1.  **Headless Browser**: Uses Playwright (Chromium) to render the dynamic DGFT website.
2.  **Scoped Interaction**: Identifies the "Import" and "Export" DOM containers specifically to ensure clicks are sent to the correct section.
3.  **Dynamic Detection**:
    -   When a card is clicked, the script waits for a data table (`#itcdetails`) to load.
    -   If a table loads, it iterates through rows and downloads the PDF linked in each row.
    -   If no table loads, it checks if the page redirected to a PDF or triggered a download event (common for "Notification" and "Appendix").
4.  **Blob Extraction**: For table-based links which use sophisticated `javascript:` actions, the script intercepts `window.open` or fetches the `blob:` URL directly to save the file.
