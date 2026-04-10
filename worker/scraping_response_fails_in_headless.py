import asyncio
import os
import random
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional
from playwright.async_api import Page, async_playwright, BrowserContext

# ==================== DATA MODELS ====================

@dataclass
class SourceLink:
    text: str
    url: str
    raw_url: str = ""
    title: Optional[str] = None
    description: Optional[str] = None
    extraction_order: int = 0

@dataclass
class ScrapingResult:
    query: str
    response_text: str
    source_links: List[SourceLink]
    total_sources: int
    success: bool
    timestamp: str
    error_message: Optional[str] = None

# ==================== SELECTORS (From main5.py) ====================

class ChatGPTSelectors:
    CHATGPT_URL = "https://chatgpt.com/"
    PROMPT_TEXTAREA = '#prompt-textarea'
    SEND_BUTTON = '[data-testid="send-button"]'
    RESPONSE_CONTAINER = 'div[data-message-author-role="assistant"]'
    RESPONSE_MARKDOWN = 'div.markdown'
    SOURCES_SIDEBAR = '[data-testid="screen-threadFlyOut"]'
    
    OVERLAY_SELECTORS = [
        'div[role="dialog"] button[aria-label="Close"]', 
        'button:has-text("Stay logged out")',             
        'button:has-text("Dismiss")',
        'button:has-text("Maybe later")',
        'div[id^="radix-"] button[aria-label="Close"]'    
    ]

# ==================== SCRAPER CLASS (Ported from main5.py) ====================

class ChatGPTScraper:
    def __init__(self):
        self.selectors = ChatGPTSelectors()

    async def scrape(self, page: Page, query: str) -> ScrapingResult:
        timestamp = datetime.now().isoformat()
        
        try:
            print(f"Navigating to {self.selectors.CHATGPT_URL}...")
            # Increase timeout for Cloudflare delays
            await page.goto(self.selectors.CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            
            # --- CLOUDFLARE CHECK ---
            # If we are stuck on "Just a moment...", wait it out.
            try:
                title = await page.title()
                if "Just a moment" in title:
                    print("⚠️ Cloudflare detected. Waiting...")
                    await asyncio.sleep(10)
            except: pass

            print("🛡️ Clearing overlays...")
            await self._kill_overlays(page)
            
            await self._submit_query(page, query)
            
            print("⏳ Waiting for response generation...")
            await self._wait_for_response(page)
            
            # Check for Soft Block
            try:
                error_toast = page.locator("div:has-text('Something went wrong')").last
                if await error_toast.is_visible(timeout=2000):
                    raise Exception("Soft Block: 'Something went wrong' toast detected.")
            except Exception as e:
                if "Soft Block" in str(e): raise e

            print("📝 Extracting content...")
            await self._wait_for_sources_button(page)
            
            response_text = await self._extract_text(page)
            source_links = await self._extract_sources(page)
            
            return ScrapingResult(
                query=query,
                response_text=response_text,
                source_links=source_links,
                total_sources=len(source_links),
                success=bool(response_text),
                timestamp=timestamp
            )

        except Exception as e:
            print(f"❌ Scraping error: {e}")
            # Save screenshot if it fails (Helps debug headless issues)
            try: await page.screenshot(path="debug_failed.png")
            except: pass
            raise e

    async def _kill_overlays(self, page: Page):
        await asyncio.sleep(2)
        for selector in self.selectors.OVERLAY_SELECTORS:
            try:
                elements = page.locator(selector)
                if await elements.count() > 0:
                    if await elements.first.is_visible():
                        print(f"   -> Clicking overlay button: {selector}")
                        await elements.first.click(force=True)
                        await asyncio.sleep(0.5)
            except:
                pass
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

    async def _submit_query(self, page: Page, query: str):
        print("⌨️ Inputting query...")
        textarea = page.locator(self.selectors.PROMPT_TEXTAREA)
        
        # Increased wait time for Headless/Cloudflare
        try:
            await textarea.wait_for(state="visible", timeout=20000)
            await textarea.click(force=True)
        except:
            # Retry overlay kill if input is blocked
            await self._kill_overlays(page)
            if await textarea.count() > 0:
                await textarea.click(force=True)
            else:
                raise Exception("Input textarea not found (Likely blocked by Cloudflare)")

        await textarea.fill("") 
        await textarea.type(query, delay=random.randint(15, 40))
        await asyncio.sleep(0.5)
        
        send_btn = page.locator(self.selectors.SEND_BUTTON)
        if await send_btn.is_visible():
            await send_btn.click(force=True)
        else:
            await page.keyboard.press("Enter")
        print("✓ Query Sent")

    async def _wait_for_response(self, page: Page):
        # Added check for Sign-up wall
        try:
            if await page.locator("div:has-text('Sign up')").first.is_visible(timeout=2000):
                raise Exception("Sign-up/Login wall detected.")
        except: pass

        try:
            await page.locator(self.selectors.RESPONSE_CONTAINER).first.wait_for(state="visible", timeout=15000)
        except:
            raise Exception("Response container never appeared. Input likely blocked.")

        await asyncio.sleep(2)
        max_retries = 60
        for _ in range(max_retries):
            if await page.locator('.result-streaming').count() == 0:
                break
            await asyncio.sleep(1)
        await asyncio.sleep(1)

    async def _wait_for_sources_button(self, page: Page):
        print("🔍 Scanning for Sources button...")
        try:
            sources_selector = 'button[aria-label="Sources"]'
            await page.locator(sources_selector).last.wait_for(state="attached", timeout=15000)
            print("✓ Sources button detected in DOM.")
        except:
            print("⚠️ Sources button not found after waiting.")

    async def _extract_text(self, page: Page) -> str:
        try:
            msgs = page.locator(self.selectors.RESPONSE_CONTAINER)
            count = await msgs.count()
            if count == 0: return ""
            
            last_msg = msgs.nth(count - 1)
            markdown_div = last_msg.locator(self.selectors.RESPONSE_MARKDOWN)
            
            clean_text = await markdown_div.evaluate('''(element) => {
                const clone = element.cloneNode(true);
                const citations = clone.querySelectorAll('[data-testid="webpage-citation-pill"]');
                citations.forEach(citation => citation.remove());
                const citationSpans = clone.querySelectorAll('span[data-state="closed"]');
                citationSpans.forEach(span => {
                    if (span.querySelector('[data-testid="webpage-citation-pill"]') !== null || 
                        span.textContent.match(/^[+]\\d+$/)) {
                        span.remove();
                    }
                });
                return clone.innerText;
            }''')
            return clean_text.strip()
        except Exception as e:
            print(f"Text extraction error: {e}")
            return ""

    async def _extract_sources(self, page: Page) -> List[SourceLink]:
        sources = []
        try:
            sources_btn = page.locator('button[aria-label="Sources"]').last
            if await sources_btn.count() == 0:
                print("⚠️ Sources button count is 0. Skipping.")
                return []

            print("📚 Attempting to open Sources sidebar...")
            
            await sources_btn.evaluate("""(btn) => {
                const makeVisible = (el) => {
                    el.style.visibility = 'visible';
                    el.style.opacity = '1';
                    el.style.pointerEvents = 'auto';
                };
                makeVisible(btn);
                if (btn.parentElement) makeVisible(btn.parentElement);
                if (btn.parentElement && btn.parentElement.parentElement) makeVisible(btn.parentElement.parentElement);
                btn.click();
            }""")
            
            sidebar_selector = self.selectors.SOURCES_SIDEBAR
            try:
                await page.locator(sidebar_selector).wait_for(state="visible", timeout=5000)
            except:
                print("⚠️ Sidebar ID not found. Trying fallback...")
                try:
                    sidebar_selector = 'section[class*="_screen"]'
                    await page.locator(sidebar_selector).first.wait_for(state="visible", timeout=3000)
                except:
                    print("❌ Failed to open sidebar.")
                    await page.keyboard.press("Escape")
                    return []

            source_items = page.locator(f'{sidebar_selector} a[target="_blank"]')
            try:
                await source_items.first.wait_for(state="visible", timeout=3000)
            except:
                print("⚠️ Sidebar opened, but no links found inside.")
                await page.keyboard.press("Escape")
                return []
            
            count_links = await source_items.count()
            print(f"✓ Found {count_links} sources")
            
            for i in range(count_links):
                try:
                    link_el = source_items.nth(i)
                    url = await link_el.get_attribute("href")
                    if not url: continue
                    
                    title_el = link_el.locator('div.font-semibold')
                    title = "Citation"
                    if await title_el.count() > 0:
                        title_text = await title_el.first.inner_text()
                        if title_text.strip(): title = title_text.strip()
                    
                    desc_el = link_el.locator('div.text-token-text-secondary')
                    description = None
                    if await desc_el.count() > 0:
                        desc_text = await desc_el.first.inner_text()
                        if desc_text.strip(): description = desc_text.strip()
                    
                    sources.append(SourceLink(
                        text=title, url=url, raw_url=url, title=title, 
                        description=description, extraction_order=i + 1
                    ))
                except Exception as e:
                    print(f"Error extracting source {i}: {e}")
                    continue
            
            print("Closing sources sidebar...")
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"❌ Source extraction error: {e}")
            try: await page.keyboard.press("Escape")
            except: pass
            
        return sources

# ==================== BROWSER MANAGER (CONFIGURED FOR HEADLESS SUCCESS) ====================

class BrowserManager:
    def __init__(self, user_data_dir: str):
        self.context = None
        self.playwright = None
        self.user_data_dir = user_data_dir 
        
        self.stealth_js = r"""
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Google Inc. (NVIDIA)';
                if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)';
                return getParameter(parameter);
            };
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        """

    async def start(self):
        if self.context is None:
            self.playwright = await async_playwright().start()
            
            headless = os.environ.get("HEADLESS", "true").lower() == "false"
            
            proxy = None
            if os.environ.get("PROXY_SERVER"):
                proxy = {
                    "server": os.environ.get("PROXY_SERVER"),
                    "username": os.environ.get("PROXY_USERNAME"),
                    "password": os.environ.get("PROXY_PASSWORD")
                }

            print(f"🚀 Launching Browser (Headless: {headless})")
            
            # --- CRITICAL FIX FOR HEADLESS MODE ---
            # 1. We removed '--start-maximized' because it doesn't work in Headless.
            # 2. We added '--window-size=1920,1080' explicitly.
            # 3. We set viewport to a fixed size to match window size.
            # 4. We added 'ignore_default_args=["--enable-automation"]' to hide the automation bar.
            
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=headless,
                proxy=proxy,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}, # Set Viewport explicitly
                args=[
                    "--disable-blink-features=AutomationControlled", 
                    "--no-sandbox", 
                    "--disable-infobars",
                    "--window-size=1920,1080", # Set Window Size explicitly
                    "--disable-dev-shm-usage",
                    "--disable-gpu"
                ],
                # This is the "Magic Switch" that hides the "Headless" banner
                ignore_default_args=["--enable-automation"] 
            )

    async def get_page(self) -> Page:
        if not self.context: 
            await self.start()
            
        if len(self.context.pages) > 0: 
            page = self.context.pages[0]
        else: 
            page = await self.context.new_page()
            
        await page.add_init_script(self.stealth_js)
        return page

    async def close(self):
        if self.context: 
            await self.context.close()
            self.context = None
        if self.playwright: 
            await self.playwright.stop()
            self.playwright = None