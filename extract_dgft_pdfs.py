import asyncio
import os
import re
import base64
from playwright.async_api import async_playwright
import argparse
from dataclasses import dataclass
from typing import Optional, List

# ============ CONFIGURATION ============
@dataclass
class Config:
    BASE_URL: str = "https://www.dgft.gov.in/CP/?opt=itchs-import-export"
    DOWNLOAD_DIR: str = "downloads"
    MAX_FILENAME_LENGTH: int = 240
    TIMEOUTS = {
        "page_load": 10000,
        "row_render": 2000,
        "post_click": 3000,
        "poll_interval": 200,
    }
    BLOB_POLL_ATTEMPTS: int = 20

CONFIG = Config()

# Extra/Auxiliary items to download
IMPORT_EXTRA_ITEMS = [
    "Notification",
    "How to Read Import Policy",
    "General Notes to Import Policy",
    "Appendix-1",
    "Appendix-2", 
    "Appendix-3",
    "Appendix-4",
    "Appendix-5",
    "Restricted Item Details",
    "Prohibited Item Details",
    "Import of Pets",
    "STE Item Details"
]

EXPORT_EXTRA_ITEMS = [
    "Notification",
    "How to Read Export Policy",
    "General Notes to Export Policy", 
    "Appendix-1",
    "Appendix-2", 
    "Appendix-3",
    "Appendix-4",
    "Restricted Item Details",
    "Prohibited Item Details",
    "STE Item Details",
    "Previous Export Policy"
]

# ============ HELPER FUNCTIONS ============
def sanitize_filename(text: str, max_length: int = 80) -> str:
    """Sanitize text for use in filename."""
    if not text: return "unnamed"
    safe = re.sub(r'[^\w\s-]', '', text)
    safe = re.sub(r'[\s_]+', '_', safe)  # Collapse multiple spaces/underscores
    safe = safe.strip('_')
    return safe[:max_length] if safe else "unnamed"

async def download_pdf_from_url(page_or_context, url: str, filepath: str) -> bool:
    """Download PDF from URL (handles both regular and blob URLs)."""
    try:
        if not url:
            return False
            
        data_url = await page_or_context.evaluate("""
            async (url) => {
                const response = await fetch(url);
                const blob = await response.blob();
                const reader = new FileReader();
                return new Promise((resolve, reject) => {
                    reader.onerror = reject;
                    reader.onloadend = () => resolve(reader.result);
                    reader.readAsDataURL(blob);
                });
            }
        """, url)
        
        if "," not in data_url:
            raise ValueError("Invalid data URL format")
            
        _, encoded = data_url.split(",", 1)
        data = base64.b64decode(encoded)
        
        with open(filepath, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"Failed to download PDF from {url}: {e}")
        return False

async def cleanup_extra_pages(context, main_page):
    """Close all pages except the main one."""
    for pg in context.pages:
        if pg != main_page:
            try:
                await pg.close()
            except Exception as e:
                print(f"Error closing page: {e}")

async def process_card(page, context, card_title, output_folder, force_update=False, target_chapter=None, link_selector=None, container_selector=None):
    """
    Process a specific card (Policy section, Appendix, etc.) from the dashboard.
    """
    print(f"\n--- Starting {card_title} ({output_folder}) ---")
    folder_path = os.path.join(CONFIG.DOWNLOAD_DIR, output_folder)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)

    print(f"Navigating to {CONFIG.BASE_URL}...")
    try:
        await page.goto(CONFIG.BASE_URL)
        await page.wait_for_load_state("networkidle")
    except Exception as e:
        print(f"Navigation failed: {e}")
        return

    # Capture downloads
    downloads = []
    def handle_download(d):
        downloads.append(d)
    page.on("download", handle_download)

    try:
        # 1. Click 'View' button
        try:
            if container_selector:
                view_button_selector = f"xpath={container_selector}//h5[contains(normalize-space(text()), '{card_title}')]/ancestor::a"
            else:
                view_button_selector = f"xpath=//h5[contains(normalize-space(text()), '{card_title}')]/ancestor::a"
            
            if not await page.query_selector(view_button_selector):
                print(f"Card '{card_title}' not found on page. Skipping.")
                return

            await page.click(view_button_selector)
            await page.wait_for_timeout(CONFIG.TIMEOUTS["post_click"]) 
        except Exception as e:
            print(f"Could not find or click view button for {card_title}: {e}")
            return

        # Wait for either table or PDF load
        try:
            await page.wait_for_selector("#itcdetails", timeout=CONFIG.TIMEOUTS["page_load"])
        except Exception as e:
            print(f"Table (#itcdetails) did not load for {card_title}. Checking for download, direct PDF, or new tab...")
            
            # 0. Check for Downloads
            if downloads:
                print(f"Detected {len(downloads)} download event(s).")
                for download in downloads:
                    try:
                        filename = sanitize_filename(card_title) + ".pdf"
                        if len(filename) > CONFIG.MAX_FILENAME_LENGTH: 
                             filename = filename[:CONFIG.MAX_FILENAME_LENGTH] + ".pdf"
                        filepath = os.path.join(folder_path, filename)
                        
                        if os.path.exists(filepath) and not force_update:
                             print(f"Skipping {filename} (already exists)")
                             continue
                        
                        print(f"Saving download to {filepath}...")
                        await download.save_as(filepath)
                        print(f"Saved {filename}")
                    except Exception as e:
                        print(f"Download save failed: {e}")
                return

            # 1. Check if CURRENT page is a PDF
            if page.url.lower().endswith(".pdf") or "pdf" in page.url.lower() or "/website/" in page.url.lower():
                 print(f"Detected direct PDF on current page: {page.url}")
                 filename = sanitize_filename(card_title) + ".pdf"
                 filepath = os.path.join(folder_path, filename)

                 if os.path.exists(filepath) and not force_update:
                     print(f"Skipping {filename} (already exists)")
                     return

                 if await download_pdf_from_url(page, page.url, filepath):
                     print(f"Saved {filename}")
                 return

            # 2. Check for NEW tab
            found_in_tab = False
            for subpage in context.pages:
                if subpage == page: continue
                
                try:
                    await subpage.wait_for_load_state("domcontentloaded", timeout=CONFIG.TIMEOUTS["page_load"])
                except Exception:
                    pass
                    
                print(f"Checking new tab: {subpage.url}")
                if subpage.url.lower().endswith(".pdf") or "pdf" in subpage.url.lower() or "/website/" in subpage.url.lower():
                    print("Detected PDF in new tab.")
                    filename = sanitize_filename(card_title) + ".pdf"
                    filepath = os.path.join(folder_path, filename)
                    
                    if os.path.exists(filepath) and not force_update:
                        print(f"Skipping {filename} (already exists)")
                        found_in_tab = True
                        break

                    print(f"Downloading {subpage.url} to {filename}...")
                    if await download_pdf_from_url(subpage, subpage.url, filepath):
                        print(f"Saved {filename}")
                        found_in_tab = True
                        break
            
            if found_in_tab:
                return

            print(f"Could not find table or PDF for {card_title}")
            return

        # Setup window.open interception for blob downloads
        await page.evaluate("""
            window._opened_urls = [];
            const originalOpen = window.open;
            window.open = (url, target, features) => {
                window._opened_urls.push(url);
                return originalOpen(url, target, features);
            }
        """)

        page_num = 1
        processed_count = 0
        
        while True:
            print(f"Processing page {page_num}...")
            await page.wait_for_timeout(CONFIG.TIMEOUTS["row_render"])

            rows = await page.query_selector_all("#itcdetails tbody tr")
            if not rows:
                print("No rows found in table.")
                break

            row_count = len(rows)
            for i in range(row_count):
                # Re-query rows to avoid stale element reference
                rows = await page.query_selector_all("#itcdetails tbody tr")
                if i >= len(rows): break
                row = rows[i]

                cols = await row.query_selector_all("td")
                if len(cols) < 2:
                    continue

                col0_text = (await cols[0].inner_text()).strip()
                col1_text = (await cols[1].inner_text()).strip()

                if target_chapter and col0_text != target_chapter:
                    continue

                safe_col0 = sanitize_filename(col0_text)
                safe_col1 = sanitize_filename(col1_text)
                
                # Construct filename
                prefix = card_title.replace(' ', '_').replace('ITC(HS)_based_', '').replace('Details', '').strip('_')
                filename = f"{prefix}_{safe_col0}_{safe_col1}.pdf"
                
                if len(filename) > CONFIG.MAX_FILENAME_LENGTH:
                     filename = filename[:CONFIG.MAX_FILENAME_LENGTH] + ".pdf"

                filepath = os.path.join(folder_path, filename)

                if os.path.exists(filepath) and not force_update:
                    print(f"Skipping {filename} (already exists)")
                    continue

                # Find PDF link
                pdf_link = None
                if link_selector:
                    pdf_link = await row.query_selector(link_selector)
                else:
                    pdf_link = await row.query_selector("a i.fa-file-pdf")
                    if not pdf_link:
                        try:
                            last_col = cols[-1]
                            pdf_link = await last_col.query_selector("a")
                        except Exception:
                            pass

                if pdf_link:
                    try:
                        tag_name = await pdf_link.evaluate("el => el.tagName")
                        if tag_name == "I":
                            parent_handle = await pdf_link.evaluate_handle("el => el.closest('a')")
                            if parent_handle:
                                pdf_link = parent_handle.as_element() 
                    except Exception as e:
                        pass
                
                if pdf_link:
                    print(f"Downloading {filename}...")
                    await page.evaluate("window._opened_urls = []")
                    
                    try:
                        await pdf_link.click()
                    except Exception as e:
                        print(f"Failed to click PDF link for {filename}: {e}")
                        continue

                    # Poll for window.open / blob
                    blob_url = None
                    for _ in range(CONFIG.BLOB_POLL_ATTEMPTS): 
                        await page.wait_for_timeout(CONFIG.TIMEOUTS["poll_interval"])
                        captured = await page.evaluate("window._opened_urls")
                        blobs = [u for u in captured if u and u.startswith("blob:")]
                        if blobs:
                            blob_url = blobs[0]
                            break
                    
                    if blob_url:
                        if await download_pdf_from_url(page, blob_url, filepath):
                             print(f"Saved {filename}")
                             processed_count += 1
                    else:
                        print(f"No blob URL captured for {filename}")

                    # Cleanup any extra tabs that might have opened
                    await cleanup_extra_pages(context, page)
                else:
                    print(f"No PDF link found for row: {col0_text}")
                
                if target_chapter and col0_text == target_chapter:
                    print(f"Target '{target_chapter}' processed.")
                    return 

            # Pagination
            next_button = await page.query_selector("li.next a")
            should_continue = False
            if next_button:
                try:
                    is_disabled = await page.evaluate("(el) => el.parentElement.classList.contains('disabled')", next_button)
                    if not is_disabled:
                        print("Moving to next page...")
                        await next_button.click()
                        page_num += 1
                        should_continue = True
                except Exception:
                    pass
            
            if not should_continue:
                print("Reached last page.")
                break
                
        print(f"Finished {card_title}. Processed: {processed_count}")

    finally:
        # Removal of event listener
        try:
            page.remove_listener("download", handle_download)
        except Exception:
            pass
        # Final cleanup of pages
        await cleanup_extra_pages(context, page)

async def main():
    parser = argparse.ArgumentParser(description="Extract DGFT ITC(HS) Policy & Appendix PDFs.")
    parser.add_argument("-f", "--force", action="store_true", help="Force overwrite existing files")
    parser.add_argument("-c", "--chapter", help="Specific ID/S.No to download")
    parser.add_argument("-p", "--policy", choices=['import', 'export', 'all'], default='all', help="Policy type to download")
    parser.add_argument("--skip-extras", action="store_true", help="Skip downloading extra Appendices/Notifications")
    parser.add_argument("--only-extras", action="store_true", help="Download ONLY extra Appendices/Notifications (skips main policy)")
    parser.add_argument("-s", "--section", help="Filter by specific section name")
    args = parser.parse_args()

    if not os.path.exists(CONFIG.DOWNLOAD_DIR):
        os.makedirs(CONFIG.DOWNLOAD_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        def should_process(title):
            if not args.section:
                return True
            return args.section.lower() in title.lower()

        if args.skip_extras and args.only_extras:
            print("Error: Cannot use --skip-extras and --only-extras together.")
            return

        # Import Policy
        if args.policy in ['import', 'all']:
            import_container = '//h4[contains(normalize-space(.), "Schedule 1 - Import Policy")]/ancestor::div[contains(@class, "bg-dark-gray")][1]'
            
            if not args.only_extras and should_process("ITC(HS) based Import Policy"):
                await process_card(page, context, "ITC(HS) based Import Policy", "Import_Policy", args.force, args.chapter, link_selector="a.itchsimport", container_selector=import_container)
            
            if not args.skip_extras:
                for item in IMPORT_EXTRA_ITEMS:
                    if should_process(item):
                        await process_card(page, context, item, "Import_Policy_Extra", args.force, args.chapter, container_selector=import_container)
        
        # Export Policy
        if args.policy in ['export', 'all']:
            export_container = '//h4[contains(normalize-space(.), "Schedule 2 - Export Policy")]/ancestor::div[contains(@class, "bg-dark-gray")][1]'

            if not args.only_extras and should_process("ITC(HS) based Export Policy"):
                await process_card(page, context, "ITC(HS) based Export Policy", "Export_Policy", args.force, args.chapter, link_selector="a.itchsexport", container_selector=export_container)
            
            if not args.skip_extras:
                for item in EXPORT_EXTRA_ITEMS:
                    if should_process(item):
                        await process_card(page, context, item, "Export_Policy_Extra", args.force, args.chapter, container_selector=export_container)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
