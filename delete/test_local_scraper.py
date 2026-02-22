import asyncio
import os
import sys
import shutil

# Ensure we can import from the worker directory
sys.path.append(os.path.join(os.getcwd(), 'worker'))

try:
    from scraper import BrowserManager, ChatGPTScraper
except ImportError:
    print("❌ Error: Could not import 'scraper'. Make sure 'worker/scraper.py' exists.")
    sys.exit(1)

async def test_scraper():
    print("🚀 Starting Local Scraper Test...")
    
    # 1. Define a local test profile (Mimics the Docker volume)
    # We use a specific folder so cookies are saved/loaded (Persistent Context)
    test_profile_path = os.path.join(os.getcwd(), "test_debug_profile")
    
    if not os.path.exists(test_profile_path):
        os.makedirs(test_profile_path)
        print(f"📁 Created new profile at: {test_profile_path}")
    else:
        print(f"📂 Using existing profile at: {test_profile_path}")

    # 2. Initialize Manager WITH the required user_data_dir argument
    # This fixes the TypeError you were seeing
    browser_manager = BrowserManager(user_data_dir=test_profile_path)
    
    scraper = ChatGPTScraper()
    
    try:
        # 3. Launch Browser
        print("🌐 Launching Browser (Persistent Context)...")
        page = await browser_manager.get_page()
        
        # 4. Run the Scrape
        query = "Which is the best MMP platform?"
        print(f"⌨️  Querying: '{query}'")
        
        result = await scraper.scrape(page, query)
        
        # 5. Output Results
        print("\n" + "="*50)
        if result.success:
            print("✅ SCRAPE SUCCESSFUL")
            print(f"📝 Response Length: {len(result.response_text)} chars")
            print(f"💬 Preview: {result.response_text[:150]}...")
            print(f"📚 Sources Found: {result.total_sources}")
            for link in result.source_links:
                print(f"   - {link.title}: {link.url}")
        else:
            print("❌ SCRAPE FAILED")
            print(f"⚠️  Error Message: {result.error_message}")
            
            # If it failed due to Cloudflare/Block, the real worker would delete the profile here.
            # We can simulate that log:
            if "soft block" in str(result.error_message).lower():
                print("🚨 Soft Block detected during test.")

        print("="*50 + "\n")

    except Exception as e:
        print(f"🔥 CRITICAL TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print("🛑 Closing Browser...")
        await browser_manager.close()

if __name__ == "__main__":
    # Force Headless=False for testing visibility, regardless of .env
    os.environ["HEADLESS"] = "True"
    asyncio.run(test_scraper())