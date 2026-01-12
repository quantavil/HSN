import asyncio
import os
import base64
from playwright.async_api import async_playwright

BASE_URL = "https://www.dgft.gov.in/CP/?opt=itchs-import-export"

async def test_download():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
        print(f"Navigating to {BASE_URL}...")
        await page.goto(BASE_URL)
        
        # Click View
        view_button_selector = "xpath=//h5[contains(text(), 'ITC(HS) based Import Policy')]/ancestor::a"
        await page.wait_for_selector(view_button_selector)
        await page.click(view_button_selector)
        
        await page.wait_for_selector("#itcdetails", timeout=15000)
        await page.wait_for_timeout(2000) # Settle
        
        # Setup window.open interception
        await page.evaluate("""
            window._opened_urls = [];
            const originalOpen = window.open;
            window.open = (url, target, features) => {
                window._opened_urls.push(url);
                return originalOpen(url, target, features);
            }
        """)
        
        # Click first PDF link
        rows = await page.query_selector_all("#itcdetails tbody tr")
        row = rows[0]
        pdf_link = await row.query_selector("a.itchsimport")
        
        if pdf_link:
            print("Clicking PDF link...")
            # We don't need to actually handle the popup if we just want the URL
            # But the click triggers it.
            await pdf_link.click()
            
            # Wait a bit for the JS to run and window.open to be called
            await page.wait_for_timeout(2000)
            
            # Get the intercepted URL
            blob_urls = await page.evaluate("window._opened_urls")
            print(f"Intercepted URLs: {blob_urls}")
            
            valid_urls = [u for u in blob_urls if u and u.startswith("blob:")]
            
            if valid_urls:
                blob_url = valid_urls[0]
                print(f"Found Blob URL: {blob_url}")
                    
                # Fetch content
                try:
                    data_url = await page.evaluate(f"""
                        async () => {{
                            const response = await fetch('{blob_url}');
                            const blob = await response.blob();
                            const reader = new FileReader();
                            return new Promise((resolve, reject) => {{
                                reader.onloadend = () => resolve(reader.result);
                                reader.onerror = reject;
                                reader.readAsDataURL(blob);
                            }});
                        }}
                    """)
                    
                    header, encoded = data_url.split(",", 1)
                    data = base64.b64decode(encoded)
                    
                    with open("test_download.pdf", "wb") as f:
                        f.write(data)
                    print(f"Downloaded {len(data)} bytes to test_download.pdf")
                except Exception as e:
                    print(f"Error downloading blob: {e}")
            else:
                print("No blob URL intercepted.")
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_download())
