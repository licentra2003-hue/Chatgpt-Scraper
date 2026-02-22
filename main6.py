import asyncio
import json
import os
import random
import shutil
import re
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import BrowserContext, Page, async_playwright
from pydantic import BaseModel, Field

load_dotenv()

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

class ScrapeRequest(BaseModel):
    query: str = Field(..., description="Query to ask ChatGPT")
    save_files: bool = False

class SourceLinkResponse(BaseModel):
    text: str
    url: str
    raw_url: str
    title: Optional[str] = None
    description: Optional[str] = None
    extraction_order: int

class ScrapeResponse(BaseModel):
    query: str
    response_text: str
    source_links: List[SourceLinkResponse]
    total_sources: int
    success: bool
    timestamp: str
    error_message: Optional[str] = None

# ==================== SELECTORS ====================

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

# ==================== SCRAPER CLASS ====================

class ChatGPTScraper:
    def __init__(self):
        self.selectors = ChatGPTSelectors()

    async def scrape(self, page: Page, query: str, save_files: bool = False) -> ScrapingResult:
        timestamp = datetime.now().isoformat()
        
        try:
            print(f"Navigating to {self.selectors.CHATGPT_URL}...")
            await page.goto(self.selectors.CHATGPT_URL, wait_until="domcontentloaded", timeout=30000)
            
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
            
            result = ScrapingResult(
                query=query,
                response_text=response_text,
                source_links=source_links,
                total_sources=len(source_links),
                success=bool(response_text),
                timestamp=timestamp
            )
            
            if save_files:
                self._save_file(result)
                
            return result

        except Exception as e:
            print(f"❌ Scraping error: {e}")
            return ScrapingResult(
                query=query, 
                response_text="", 
                source_links=[], 
                total_sources=0, 
                success=False, 
                timestamp=timestamp, 
                error_message=str(e)
            )

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
        await textarea.wait_for(state="visible", timeout=10000)
        await textarea.click(force=True) 
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
        try:
            await page.locator(self.selectors.RESPONSE_CONTAINER).first.wait_for(state="visible", timeout=10000)
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
            # FIX: Use wait_for(state="attached") instead of polling count()
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
                
                clone.style.position = 'absolute';
                clone.style.left = '-9999px';
                clone.style.top = '0';
                clone.style.opacity = '0'; 
                clone.style.pointerEvents = 'none';
                
                document.body.appendChild(clone);
                let text = clone.innerText;
                
                // Fallback for detached/weird nodes
                if (!text) text = clone.textContent;
                
                document.body.removeChild(clone);
                return text;
            }''')
            return clean_text.strip()
        except Exception as e:
            print(f"Text extraction error: {e}")
            return ""

    async def _extract_sources(self, page: Page) -> List[SourceLink]:
        sources = []
        try:
            # 1. Locate the button
            sources_btn = page.locator('button[aria-label="Sources"]').last
            
            if await sources_btn.count() == 0:
                print("⚠️ Sources button count is 0. Skipping.")
                return []

            print("📚 Attempting to open Sources sidebar...")
            
            # 2. THE PRO FIX: Force visibility on the BUTTON AND PARENTS
            await sources_btn.evaluate("""(btn) => {
                const makeVisible = (el) => {
                    el.style.visibility = 'visible';
                    el.style.opacity = '1';
                    el.style.pointerEvents = 'auto';
                };

                makeVisible(btn);
                if (btn.parentElement) makeVisible(btn.parentElement);
                if (btn.parentElement && btn.parentElement.parentElement) makeVisible(btn.parentElement.parentElement);

                // Native click dispatch
                btn.click();
            }""")
            
            # 3. Wait for Sidebar
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

            # 4. Extract Links
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

    def _save_file(self, result: ScrapingResult):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(f"chatgpt_{ts}.json", "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, indent=2)

# ==================== BROWSER MANAGER (BOT DETECTION FIXES) ====================

# ==================== BROWSER MANAGER (ROBUST HEADLESS SETUP) ====================

class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        # Valid User-Agent is crucial for Headless mode
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        
        self.stealth_js = r"""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                // Spoof renderer to look like a real GPU (NVIDIA GTX 1050)
                if (parameter === 37445) return 'Google Inc. (NVIDIA)';
                if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)';
                return getParameter(parameter);
            };
            
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
        """

    async def start(self):
        if self.playwright is None:
            self.playwright = await async_playwright().start()
            
            # Allow ENV override, but default to True for server deployments
            headless_env = os.environ.get("HEADLESS", "true").lower() == "true"
            
            proxy = None
            if os.environ.get("PROXY_SERVER"):
                proxy = {
                    "server": os.environ.get("PROXY_SERVER"),
                    "username": os.environ.get("PROXY_USERNAME"),
                    "password": os.environ.get("PROXY_PASSWORD")
                }

            print(f"🚀 Launching Shared Browser Instance (Headless: {headless_env})")
            
            # CRITICAL: These args prevent the browser from looking like a bot
            self.browser = await self.playwright.chromium.launch(
                headless=headless_env,
                proxy=proxy,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--disable-gpu",
                    "--window-size=1920,1080",
                    "--ignore-certificate-errors"
                ],
                ignore_default_args=["--enable-automation"] # Crucial for Cloudflare
            )

    async def get_isolated_page(self) -> tuple[BrowserContext, Page]:
        """Creates a fresh, isolated context and page for a single request."""
        if not self.browser:
            await self.start()
            
        # Randomize viewport slightly
        w = 1920 + random.randint(-10, 10)
        h = 1080 + random.randint(-10, 10)
        
        context = await self.browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": w, "height": h},
            locale="en-US",
            timezone_id="America/New_York",
            device_scale_factor=1,
            has_touch=False,
            is_mobile=False,
            java_script_enabled=True
        )
        
        # Apply stealth scripts
        await context.add_init_script(self.stealth_js)
        
        page = await context.new_page()
        
        # INCREASE TIMEOUT: Default 30s is often too short for Cloudflare/ChatGPT
        page.set_default_timeout(60000) 
        
        return context, page

    async def stop(self):
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()

# ==================== API ====================

browser_manager = BrowserManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await browser_manager.start()
    yield
    await browser_manager.stop()

app = FastAPI(title="ChatGPT Scraper", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_chatgpt(request: ScrapeRequest):
    scraper = ChatGPTScraper()
    context = None
    page = None
    try:
        context, page = await browser_manager.get_isolated_page()
        result = await scraper.scrape(page, request.query, request.save_files)
        
        api_sources = [SourceLinkResponse(
            text=l.text, url=l.url, raw_url=l.raw_url, 
            title=l.title, description=l.description, 
            extraction_order=l.extraction_order
        ) for l in result.source_links]
        
        return ScrapeResponse(
            query=result.query, 
            response_text=result.response_text, 
            source_links=api_sources, 
            total_sources=result.total_sources, 
            success=result.success, 
            timestamp=result.timestamp, 
            error_message=result.error_message
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # IMPORTANT: Close context to prevent session linking
        if page: await page.close()
        if context: await context.close()

if __name__ == "__main__":
    import uvicorn
    # Clean up old profile if present
    if os.path.exists("chatgpt_guest_profile"):
        try: shutil.rmtree("chatgpt_guest_profile")
        except: pass
        
    uvicorn.run(app, host="0.0.0.0", port=8000)