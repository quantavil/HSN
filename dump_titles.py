
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.dgft.gov.in/CP/?opt=itchs-import-export")
        await page.wait_for_load_state("networkidle")
        
        # Get all h5 titles
        titles = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('h5')).map(el => el.innerText.trim());
        }""")
        
        print("--- TITLES FOUND ---")
        for t in titles:
            print(f"'{t}'")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
