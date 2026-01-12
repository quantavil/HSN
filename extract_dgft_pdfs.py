import asyncio
import os
import re
import base64
from playwright.async_api import async_playwright
import argparse

# Configuration
BASE_URL = "https://www.dgft.gov.in/CP/?opt=itchs-import-export"
DOWNLOAD_DIR = "downloads"
CHROME_PATH = os.path.expanduser("~/.cache/ms-playwright/chromium-1200/chrome-linux/chrome")

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
    "FAQs on Restricted Items",
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

async def process_card(page, context, card_title, output_folder, force_update=False, target_chapter=None, link_selector=None, container_selector=None):
    """
    Process a specific card (Policy section, Appendix, etc.) from the dashboard.
    """
    print(f"\n--- Starting {card_title} ({output_folder}) ---")
    folder_path = os.path.join(DOWNLOAD_DIR, output_folder)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    print(f"Navigating to {BASE_URL}...")
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")

    # 1. Click 'View' button for the specific card
    try:
        # Use a more flexible xpath to find the View button associated with the card title
        # We look for h5 with text, then find the closest anchor tag (ancestor)
        # Scoped selector if container provided
        if container_selector:
            # Look for h5/card within the specific container
            view_button_selector = f"xpath={container_selector}//h5[contains(text(), '{card_title}')]/ancestor::a"
        else:
            view_button_selector = f"xpath=//h5[contains(text(), '{card_title}')]/ancestor::a"
        
        # Check if element exists before waiting too long
        if not await page.query_selector(view_button_selector):
            print(f"Card '{card_title}' not found on page. Skipping.")
            return

        # Capture downloads
        downloads = []
        page.on("download", lambda d: downloads.append(d))

        await page.click(view_button_selector)
        # Wait for some indication of loading?
        await page.wait_for_timeout(2000) 
    except Exception as e:
        print(f"Could not find or click view button for {card_title}: {e}")
        return

    # Wait for either table or PDF load
    try:
        # We wait for either the table to appear OR the URL to change to a PDF
        # But wait_for_selector is simplest; if it fails, we check URL.
        await page.wait_for_selector("#itcdetails", timeout=5000)
    except Exception as e:
        print(f"Table (#itcdetails) did not load for {card_title}. Checking for download, direct PDF, or new tab...")
        
        # 0. Check for Downloads
        if downloads:
            print(f"Detected {len(downloads)} download event(s).")
            for download in downloads:
                filename = f"{card_title.replace(' ', '_')}.pdf"
                if len(filename) > 240: filename = filename[:240] + ".pdf"
                filepath = os.path.join(folder_path, filename)
                
                print(f"Saving download to {filepath}...")
                await download.save_as(filepath)
                print(f"Saved {filename}")
            return

        # DEBUG: Print current state
        print(f"Current Page URL: {page.url}")
        print(f"Total pages: {len(context.pages)}")
        for i, p in enumerate(context.pages):
            try:
                print(f"Page {i} URL: {p.url}")
            except:
                print(f"Page {i} (closed/error)")

        # 1. Check if CURRENT page is a PDF
        if page.url.lower().endswith(".pdf") or "pdf" in page.url.lower() or "/website/" in page.url.lower():
             print(f"Detected direct PDF on current page: {page.url}")
             filename = f"{card_title.replace(' ', '_')}.pdf"
             if len(filename) > 240: filename = filename[:240] + ".pdf"
             filepath = os.path.join(folder_path, filename)

             if os.path.exists(filepath) and not force_update:
                 print(f"Skipping {filename} (already exists)")
                 return

             try:
                 pdf_url = page.url
                 print(f"Downloading {pdf_url} to {filename}...")
                 # Fetch blob
                 data_url = await page.evaluate(f"""
                     async () => {{
                         const response = await fetch('{pdf_url}');
                         const blob = await response.blob();
                         const reader = new FileReader();
                         return new Promise((resolve) => {{
                             reader.onloadend = () => resolve(reader.result);
                             reader.readAsDataURL(blob);
                         }});
                     }}
                 """)
                 header, encoded = data_url.split(",", 1)
                 data = base64.b64decode(encoded)
                 with open(filepath, "wb") as f:
                     f.write(data)
                 print(f"Saved {filename}")
                 
                 # Go back to main page for next iteration if needed, though usually we process one card per call
                 # But we must ensure state is clean if we were reusing page (which we are)
                 # Wait, process_card is called iteratively. We need to go back? 
                 # The caller 'process_card' starts with 'goto(BASE_URL)', so next call will reset.
                 return 
             except Exception as ex:
                 print(f"Failed to download PDF from current page: {ex}")
                 return

        # 2. Check for NEW tab
        pages = context.pages
        # Filter for pages created after our main page (assuming main page is pages[0])
        # But easier just to check count or check for other pages
        for subpage in pages:
            if subpage == page: continue
            
            try:
                await subpage.wait_for_load_state("domcontentloaded", timeout=5000)
            except:
                pass
                
            print(f"Checking new tab: {subpage.url}")
            if subpage.url.lower().endswith(".pdf") or "pdf" in subpage.url.lower() or "/website/" in subpage.url.lower():
                print("Detected PDF in new tab.")
                filename = f"{card_title.replace(' ', '_')}.pdf"
                if len(filename) > 240: filename = filename[:240] + ".pdf"
                filepath = os.path.join(folder_path, filename)
                
                if os.path.exists(filepath) and not force_update:
                    print(f"Skipping {filename} (already exists)")
                    await subpage.close()
                    return

                try:
                    pdf_url = subpage.url
                    print(f"Downloading {pdf_url} to {filename}...")
                    
                    data_url = await subpage.evaluate(f"""
                        async () => {{
                            const response = await fetch('{pdf_url}');
                            const blob = await response.blob();
                            const reader = new FileReader();
                            return new Promise((resolve) => {{
                                reader.onloadend = () => resolve(reader.result);
                                reader.readAsDataURL(blob);
                            }});
                        }}
                    """)
                    header, encoded = data_url.split(",", 1)
                    data = base64.b64decode(encoded)

                    with open(filepath, "wb") as f:
                        f.write(data)
                    print(f"Saved {filename}")
                    await subpage.close()
                    return
                except Exception as ex:
                    print(f"Failed to download PDF from new tab: {ex}")
                    await subpage.close()
                    return
            
            # Close non-relevant tabs
            # await subpage.close() 

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
        await page.wait_for_timeout(1500) # Small breath for row render

        rows = await page.query_selector_all("#itcdetails tbody tr")
        if not rows:
            print("No rows found in table.")
            break

        row_count = len(rows)
        for i in range(row_count):
            # Refetch rows to avoid stale element handle errors
            rows = await page.query_selector_all("#itcdetails tbody tr")
            if i >= len(rows): break
            row = rows[i]

            cols = await row.query_selector_all("td")
            if len(cols) < 2:
                continue

            # Generic column extraction
            # Assume Col 0 = ID/S.No/Date, Col 1 = Description/Title
            col0_text = await cols[0].inner_text()
            col0_text = col0_text.strip()
            
            col1_text = await cols[1].inner_text()
            col1_text = col1_text.strip()

            # Filter by chapter/ID if requested (primitive check)
            if target_chapter and col0_text != target_chapter:
                continue

            # Sanitize filename components
            safe_col0 = re.sub(r'[^\w\s-]', '', col0_text).strip().replace(' ', '_')
            safe_col1 = re.sub(r'[^\w\s-]', '', col1_text).strip().replace(' ', '_')
            
            # Truncate
            if len(safe_col1) > 80:
                safe_col1 = safe_col1[:80]
            
            # Construct filename: {cleaned_card_title}_{col0}_{col1}.pdf
            # Remove redundant "Details" or spaces from card title for filename prefix
            prefix = card_title.replace(' ', '_').replace('ITC(HS)_based_', '').replace('Details', '').strip('_')
            filename = f"{prefix}_{safe_col0}_{safe_col1}.pdf"
            
            # Additional safety: ensure filename length is managed
            if len(filename) > 240:
                filename = filename[:240] + ".pdf"

            filepath = os.path.join(folder_path, filename)

            if os.path.exists(filepath) and not force_update:
                print(f"Skipping {filename} (already exists)")
                continue

            # Find PDF link
            pdf_link = None
            if link_selector:
                pdf_link = await row.query_selector(link_selector)
            else:
                # Fallback: try to find an anchor with a PDF icon or just the last column's anchor
                pdf_link = await row.query_selector("a i.fa-file-pdf")
                if not pdf_link:
                    # Try finding any anchor in the last column
                    try:
                        last_col = cols[-1]
                        pdf_link = await last_col.query_selector("a")
                    except:
                        pass

            # Sometimes the 'pdf_link' found via 'i.fa...' needs the parent 'a'
            if pdf_link:
                try:
                    tag_name = await pdf_link.evaluate("el => el.tagName")
                    if tag_name == "I":
                        parent = await pdf_link.evaluate_handle("el => el.closest('a')")
                        if parent:
                            pdf_link = parent
                except:
                    pass

            if pdf_link:
                print(f"Downloading {filename}...")

                # Clear previous captured urls
                await page.evaluate("window._opened_urls = []")
                
                try:
                    await pdf_link.click()
                except Exception as e:
                    print(f"Failed to click PDF link for {filename}: {e}")
                    continue

                blob_url = None
                # Wait for window.open to be called
                for _ in range(20): 
                    await page.wait_for_timeout(200)
                    captured = await page.evaluate("window._opened_urls")
                    blobs = [u for u in captured if u and u.startswith("blob:")]
                    if blobs:
                        blob_url = blobs[0]
                        break
                
                if blob_url:
                    try:
                        # Fetch blob content
                        data_url = await page.evaluate(f"""
                            async () => {{
                                const response = await fetch('{blob_url}');
                                const blob = await response.blob();
                                const reader = new FileReader();
                                return new Promise((resolve) => {{
                                    reader.onloadend = () => resolve(reader.result);
                                    reader.readAsDataURL(blob);
                                }});
                            }}
                        """)
                        header, encoded = data_url.split(",", 1)
                        data = base64.b64decode(encoded)

                        with open(filepath, "wb") as f:
                            f.write(data)
                        print(f"Saved {filename}")
                        processed_count += 1
                    except Exception as e:
                        print(f"Failed to fetch/save blob for {filename}: {e}")
                else:
                    print(f"No blob URL captured for {filename}")

                # Cleanup extra pages if any opened (though we intercepted window.open, sometimes a tab might still spawn or browser logic varies)
                for pg in context.pages:
                    if pg != page:
                        await pg.close()
            else:
                print(f"No PDF link found for row: {col0_text}")
            
            # Check early exit
            if target_chapter and col0_text == target_chapter:
                print(f"Target '{target_chapter}' processed.")
                return 

        # Pagination
        next_button = await page.query_selector("li.next a")
        should_continue = False
        if next_button:
            # Check if disabled
            try:
                is_disabled = await page.evaluate("(el) => el.parentElement.classList.contains('disabled')", next_button)
                if not is_disabled:
                    print("Moving to next page...")
                    await next_button.click()
                    page_num += 1
                    should_continue = True
            except:
                pass
        
        if not should_continue:
            print("Reached last page.")
            break
            
    print(f"Finished {card_title}. Processed: {processed_count}")


async def main():
    parser = argparse.ArgumentParser(description="Extract DGFT ITC(HS) Policy & Appendix PDFs.")
    parser.add_argument("-f", "--force", action="store_true", help="Force overwrite existing files")
    parser.add_argument("-c", "--chapter", help="Specific ID/S.No to download")
    parser.add_argument("-p", "--policy", choices=['import', 'export', 'all'], default='all', help="Policy type to download")
    parser.add_argument("--skip-extras", action="store_true", help="Skip downloading extra Appendices/Notifications")
    parser.add_argument("--only-extras", action="store_true", help="Download ONLY extra Appendices/Notifications (skips main policy)")
    parser.add_argument("-s", "--section", help="Filter by specific section name (substring match, case-insensitive). E.g., 'Pets', 'Appendix', 'Notification'")
    args = parser.parse_args()

    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        # Helper to check if we should process a card based on --section
        def should_process(title):
            if not args.section:
                return True
            return args.section.lower() in title.lower()

        # Check conflicting flags
        if args.skip_extras and args.only_extras:
            print("Error: Cannot use --skip-extras and --only-extras together.")
            return

        # Import Policy
        if args.policy in ['import', 'all']:
            import_container = '//h4[contains(., "Schedule 1 - Import Policy")]/ancestor::div[contains(@class, "bg-dark-gray")][1]'
            
            # Main Policy
            if not args.only_extras and should_process("ITC(HS) based Import Policy"):
                await process_card(page, context, "ITC(HS) based Import Policy", "Import_Policy", args.force, args.chapter, link_selector="a.itchsimport", container_selector=import_container)
            
            # Extras
            if not args.skip_extras:
                for item in IMPORT_EXTRA_ITEMS:
                    if should_process(item):
                        await process_card(page, context, item, "Import_Policy_Extra", args.force, args.chapter, container_selector=import_container)
        
        # Export Policy
        if args.policy in ['export', 'all']:
            export_container = '//h4[contains(., "Schedule 2 - Export Policy")]/ancestor::div[contains(@class, "bg-dark-gray")][1]'

            # Main Policy
            if not args.only_extras and should_process("ITC(HS) based Export Policy"):
                await process_card(page, context, "ITC(HS) based Export Policy", "Export_Policy", args.force, args.chapter, link_selector="a.itchsexport", container_selector=export_container)
            
            # Extras
            if not args.skip_extras:
                for item in EXPORT_EXTRA_ITEMS:
                    if should_process(item):
                        await process_card(page, context, item, "Export_Policy_Extra", args.force, args.chapter, container_selector=export_container)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
